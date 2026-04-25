"""TableCleaner — turn pandoc's HTML-table fallback into readable markdown.

Strategy (highest iteration priority — this is the cleaner we'll keep
improving):

1. Find every ``<table>...</table>`` block in pandoc's output.
2. Parse into a rectangular grid of cell HTML strings using ``html.parser``.
3. For each cell, inspect complexity:
   - a single paragraph, possibly with inline formatting (``<strong>`` /
     ``<em>`` / ``<a>``) or a single image → SIMPLE
   - multiple paragraphs, or a short nested list → MULTILINE (can still be
     rendered in a pipe table with ``<br>`` joins)
   - more than one of: long list, multiple images, nested table → COMPLEX
4. If every cell is SIMPLE or MULTILINE ⇒ emit a GFM pipe table. Otherwise
   emit a cleaned HTML table with only ``<table> <tr> <td>``, stripped of
   ``class="odd|even"`` / ``tbody`` / style attributes.
5. First row is treated as header unless every header cell is empty (rare).

Important: we never drop content. In the worst case we fall back to a
cleaned HTML table with minimal changes, which Obsidian still renders.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import List, Optional, Tuple

from ..pipeline import CleanerContext


TABLE_BLOCK_RE = re.compile(r"<table\b.*?</table>", re.DOTALL | re.IGNORECASE)

# T-18: phantom pipe table — consecutive pipe-rows where every cell contains
# only dashes, spaces or colons (no real text). Pandoc emits these when a
# docx table has a full-colspan "title row" followed by the actual data rows
# (which become a separate table).  We match any pipe-table-like block and
# test whether ALL cells are empty/dash-only before removing it.
_PHANTOM_PIPE_BLOCK_RE = re.compile(r"^(?:\|[^\n]*\|\n)+", re.MULTILINE)
_CELL_CONTENT_RE = re.compile(r"[^|:\- \t\n]")  # any char that isn't filler


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


@dataclass
class _Cell:
    inner_html: str = ""
    rowspan: int = 1
    colspan: int = 1


@dataclass
class _TableTree:
    rows: List[List[_Cell]] = field(default_factory=list)

    def max_cols(self) -> int:
        return max((len(r) for r in self.rows), default=0)


class _TableParser(HTMLParser):
    """Minimal HTML table parser that captures raw inner HTML per cell.

    We don't try to decode the cell content — other cleaners (image rewriter,
    hyperlink cleaner) already ran on the outer markdown, so the HTML we get
    here already has proper image wiki-links etc.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.tree = _TableTree()
        self._current_row: Optional[List[_Cell]] = None
        self._current_cell: Optional[_Cell] = None
        self._cell_stack_depth = 0  # for nested tables
        self._buffer: List[str] = []

    # ---- state helpers ----
    def _append_to_cell(self, text: str) -> None:
        if self._current_cell is not None:
            self._buffer.append(text)

    def _flush_cell(self) -> None:
        if self._current_cell is not None:
            self._current_cell.inner_html = "".join(self._buffer).strip()
            self._buffer = []

    # ---- tag handlers ----
    def handle_starttag(self, tag: str, attrs: list[Tuple[str, Optional[str]]]) -> None:
        tag_lower = tag.lower()
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}

        if tag_lower == "table" and self._current_cell is not None:
            # Nested table: treat its full HTML as part of the outer cell.
            self._cell_stack_depth += 1
            self._append_to_cell(self.get_starttag_text() or f"<{tag}>")
            return
        if self._cell_stack_depth > 0:
            self._append_to_cell(self.get_starttag_text() or f"<{tag}>")
            return

        if tag_lower == "tr":
            self._current_row = []
        elif tag_lower in ("td", "th"):
            cell = _Cell()
            try:
                cell.rowspan = int(attrs_dict.get("rowspan", "1") or "1")
            except ValueError:
                cell.rowspan = 1
            try:
                cell.colspan = int(attrs_dict.get("colspan", "1") or "1")
            except ValueError:
                cell.colspan = 1
            self._current_cell = cell
            self._buffer = []
        elif tag_lower in ("table", "tbody", "thead", "tfoot"):
            return
        else:
            # Normal content tag inside cell.
            self._append_to_cell(self.get_starttag_text() or f"<{tag}>")

    def handle_startendtag(self, tag: str, attrs: list[Tuple[str, Optional[str]]]) -> None:
        if self._cell_stack_depth > 0 or self._current_cell is not None:
            self._append_to_cell(self.get_starttag_text() or f"<{tag}/>")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()

        if self._cell_stack_depth > 0:
            self._append_to_cell(f"</{tag}>")
            if tag_lower == "table":
                self._cell_stack_depth -= 1
            return

        if tag_lower == "tr":
            if self._current_row is not None:
                self.tree.rows.append(self._current_row)
            self._current_row = None
        elif tag_lower in ("td", "th"):
            self._flush_cell()
            if self._current_row is not None and self._current_cell is not None:
                self._current_row.append(self._current_cell)
            self._current_cell = None
        elif tag_lower in ("table", "tbody", "thead", "tfoot"):
            return
        else:
            self._append_to_cell(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self._append_to_cell(data)

    def handle_entityref(self, name: str) -> None:
        self._append_to_cell(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._append_to_cell(f"&#{name};")


def _parse_table(html_text: str) -> _TableTree:
    p = _TableParser()
    try:
        p.feed(html_text)
        p.close()
    except Exception:
        # Parser failure: return an empty tree so caller falls back.
        return _TableTree()
    return p.tree


# --------------------------------------------------------------------------- #
# Pipe-table detection
# --------------------------------------------------------------------------- #

_NESTED_LIST_TAG = re.compile(r"<(ol|ul)\b", re.IGNORECASE)
_PARAGRAPH_TAG = re.compile(r"<p\b", re.IGNORECASE)
_IMAGE_REF_RE = re.compile(r"!\[\[[^\]]+\]\]")
_BLOCKQUOTE_TAG = re.compile(r"<blockquote\b", re.IGNORECASE)
_NESTED_TABLE_TAG = re.compile(r"<table\b", re.IGNORECASE)


def _cell_is_simple(cell_html: str) -> bool:
    """A cell is 'simple enough' for a pipe table."""
    if _NESTED_TABLE_TAG.search(cell_html):
        return False
    if _NESTED_LIST_TAG.search(cell_html):
        return False
    if _BLOCKQUOTE_TAG.search(cell_html):
        return False
    # Multiple paragraphs are OK iff they're short — cap at 6.
    if len(_PARAGRAPH_TAG.findall(cell_html)) > 6:
        return False
    # Multiple images inside a single cell is technically OK for pipe (they
    # just appear side-by-side). Don't reject on image count.
    return True


def _header_looks_merged(tree: _TableTree) -> bool:
    """Detect tables where pandoc expanded colspan into empty header cells.

    When a source table has a merged header spanning N columns, pandoc renders
    it as 1 filled cell + (N-1) empty cells.  A real header row would have
    *most* cells filled.  Heuristic: if more than half the header cells are
    empty while the body rows are mostly filled, the header was probably merged
    and the table should stay as HTML.
    """
    if len(tree.rows) < 2:
        return False
    header = tree.rows[0]
    ncols = len(header)
    if ncols < 2:
        return False
    empty_h = sum(1 for c in header if not c.inner_html.strip())
    if empty_h == 0:
        return False
    # More than half the header cells are empty ⇒ likely expanded colspan.
    if empty_h > ncols // 2:
        return True
    # Also flag: header has adjacent empty cells (suggests a single merged span
    # that was split).
    for i in range(len(header) - 1):
        if not header[i].inner_html.strip() and not header[i + 1].inner_html.strip():
            return True
    return False


def _can_pipe(tree: _TableTree) -> bool:
    if not tree.rows:
        return False
    # Must be rectangular (every row has the same # of cells).
    widths = {len(r) for r in tree.rows}
    if len(widths) > 1:
        return False
    # Reject any row/col merge that would require rowspan/colspan.
    for row in tree.rows:
        for cell in row:
            if cell.rowspan > 1 or cell.colspan > 1:
                return False
            if not _cell_is_simple(cell.inner_html):
                return False
    # UAT Issue #5: Detect tables where pandoc expanded merged header cells
    # into empty cells — pipe tables can't express this, keep as HTML.
    if _header_looks_merged(tree):
        return False
    return True


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _flatten_cell_for_pipe(cell_html: str) -> str:
    """Convert cell inner HTML to a single line of markdown."""
    s = cell_html

    # Strip <p> wrappers — replace opening/closing with nothing but join
    # separate paragraphs with <br>.
    s = re.sub(r"\s*<p\b[^>]*>\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*</p>\s*", "<br>", s, flags=re.IGNORECASE)
    s = re.sub(r"(<br>)+$", "", s, flags=re.IGNORECASE)

    # Inline formatting HTML -> md
    s = re.sub(r"<strong\b[^>]*>(.*?)</strong>", r"**\1**", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<b\b[^>]*>(.*?)</b>", r"**\1**", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<em\b[^>]*>(.*?)</em>", r"*\1*", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<i\b[^>]*>(.*?)</i>", r"*\1*", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(
        r'<span\s+class="underline"[^>]*>(.*?)</span>',
        r"<u>\1</u>",
        s,
        flags=re.DOTALL | re.IGNORECASE,
    )
    s = re.sub(r"<span\b[^>]*>(.*?)</span>", r"\1", s, flags=re.DOTALL | re.IGNORECASE)

    # <a href="...">text</a> → [text](url)
    def _a_repl(m: re.Match) -> str:
        href = m.group(1)
        text = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        return f"[{text}]({href})"

    s = re.sub(
        r'<a\b[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
        _a_repl,
        s,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Unescape html entities we might have inside the pandoc output.
    s = html.unescape(s)

    # Normalize whitespace and remove pipe characters that would break
    # the pipe table.
    s = s.replace("|", "\\|")
    s = re.sub(r"[ \t]+", " ", s).strip()
    s = re.sub(r"(<br>\s*)+", "<br>", s)
    s = re.sub(r"^<br>|<br>$", "", s)
    return s or " "


def _grid_to_pipe(tree: _TableTree) -> str:
    if not tree.rows:
        return ""
    rendered = [[_flatten_cell_for_pipe(c.inner_html) for c in row] for row in tree.rows]
    width = len(rendered[0])

    header = rendered[0]
    body = rendered[1:]

    # UAT Issue #1: If the first row is entirely empty / whitespace, it was a
    # phantom header row injected by pandoc.  Drop it and promote the next row.
    if all(c.strip() == "" for c in header) and body:
        header = body[0]
        body = body[1:]

    separator = ["---"] * width

    lines = []
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(separator) + " |")
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# Strip class/style only from TABLE STRUCTURE elements (table, tr, td, th).
# Do NOT use a global match — that would also strip background-color from
# <span style="background-color: ..."> tags added by inline_formatter.
_TABLE_ELEM_RE = re.compile(
    r'(<(?:table|tr|td|th)\b[^>]*?)\s+class="[^"]*"',
    re.IGNORECASE | re.DOTALL,
)
_TABLE_STYLE_RE = re.compile(
    r'(<(?:table|tr|td|th)\b[^>]*?)\s+style="[^"]*"',
    re.IGNORECASE | re.DOTALL,
)

# T-21: add max-width/max-height to <img> tags inside table cells.
# Applied to every <img> in the HTML table output so wide images don't
# squeeze text columns.  We skip tags that already carry a style attribute.
_IMG_TAG_RE = re.compile(r"<img\b([^>]*)>", re.IGNORECASE)
_IMG_STYLE_ATTR = 'style="max-width:300px;max-height:150px;width:auto;height:auto"'


def _constrain_img(m: re.Match) -> str:
    attrs = m.group(1)
    # Already has a style attribute — leave it alone.
    if re.search(r'\bstyle\s*=', attrs, re.IGNORECASE):
        return m.group(0)
    return f"<img {attrs.strip()} {_IMG_STYLE_ATTR}>"


_WIKILINK_IMG_RE = re.compile(r"!\[\[([^\]|]+?)(?:\|([^\]]*))?\]\]")


def _wikilink_to_img(wikilink_match: re.Match) -> str:
    """Convert ``![[path]]`` or ``![[path|alt]]`` to ``<img>`` for HTML context.

    T-21: always includes inline size-constraint style so wide images don't
    crush adjacent text columns.
    """
    path = wikilink_match.group(1)
    alt = wikilink_match.group(2) or ""
    alt_attr = f' alt="{alt}"' if alt else ""
    return f'<img src="{path}"{alt_attr} {_IMG_STYLE_ATTR}>'


def _docx_widths_to_pct(twips: List[int]) -> List[str]:
    """Convert docx tblGrid widths (twips) to percentage strings.

    Strictly preserves the original ratio — no minimum floor. The last
    column absorbs rounding error so the set sums to exactly 100.00%.
    Returns ``[]`` if the input is unusable (empty, all-zero, negatives).
    """
    clean = [w for w in twips if w > 0]
    if not clean or len(clean) != len(twips):
        return []
    total = sum(clean)
    if total <= 0:
        return []
    raw = [w / total * 100 for w in clean]
    rounded = [round(v, 2) for v in raw[:-1]]
    rounded.append(round(100 - sum(rounded), 2))
    return [f"{p}%" for p in rounded]


def _compute_col_widths(tree: _TableTree) -> list[str]:
    """T-22b: Return percentage width strings for each column.

    Analyses content type per column and assigns proportional widths so that
    short label columns don't steal space from rich content columns:

      narrow  (avg text < 20 chars, no images)  → 10 %
      image   (any cell contains <img>)          → 25 %
      wide    (default)                          → remaining / wide_count

    Returns an empty list if all columns are the same type (equal split is
    already handled by ``table-layout:fixed``).
    """
    ncols = tree.max_cols()
    if ncols < 2:
        return []

    col_has_img = [False] * ncols
    col_text_totals: list[list[int]] = [[] for _ in range(ncols)]

    # Use body rows only for text-length sampling (skip header heuristics).
    rows_sample = tree.rows[1:] if len(tree.rows) > 1 else tree.rows
    for row in rows_sample:
        for j, cell in enumerate(row[:ncols]):
            plain = re.sub(r"<[^>]+>", "", cell.inner_html).strip()
            col_text_totals[j].append(len(plain))
            # Detect image columns: either raw <img> (before image_rewriter)
            # or ![[wiki-link]] syntax (after image_rewriter has already run).
            if re.search(r"<img\b|!\[\[", cell.inner_html, re.IGNORECASE):
                col_has_img[j] = True

    types: list[str] = []
    for j in range(ncols):
        if col_has_img[j]:
            types.append("image")
        elif col_text_totals[j]:
            avg = sum(col_text_totals[j]) / len(col_text_totals[j])
            types.append("narrow" if avg < 20 else "wide")
        else:
            types.append("wide")

    # If all columns are the same type, table-layout:fixed alone handles it.
    if len(set(types)) == 1:
        return []

    NARROW_PCT = 10
    IMAGE_PCT  = 25
    n_wide = types.count("wide")
    reserved = types.count("narrow") * NARROW_PCT + types.count("image") * IMAGE_PCT
    wide_each = max(10, (100 - reserved) // n_wide) if n_wide else 0

    raw: list[int] = []
    for t in types:
        if t == "narrow":
            raw.append(NARROW_PCT)
        elif t == "image":
            raw.append(IMAGE_PCT)
        else:
            raw.append(wide_each)

    # Adjust last 'wide' column so percentages sum exactly to 100.
    diff = 100 - sum(raw)
    if diff != 0:
        for i in range(len(raw) - 1, -1, -1):
            if types[i] == "wide":
                raw[i] += diff
                break

    return [f"{p}%" for p in raw]


def _clean_html_table(
    html_text: str,
    tree: Optional["_TableTree"] = None,
    docx_widths: Optional[List[int]] = None,
) -> str:
    """Strip junk attributes from the original HTML table."""
    s = html_text
    # Strip class/style from table structure elements only (not from <span> etc.)
    s = _TABLE_ELEM_RE.sub(r'\1', s)
    s = _TABLE_STYLE_RE.sub(r'\1', s)
    # Remove tbody/thead/tfoot wrappers (pandoc emits tbody even for simple tables).
    s = re.sub(r"</?(tbody|thead|tfoot)\s*>", "", s, flags=re.IGNORECASE)
    # T-22c: Remove pandoc's native <colgroup>...</colgroup> block so we don't
    # end up with two colgroups after our own injection below. Pandoc emits
    # <col style="width:..." /> inside this block based on grid units relative
    # to --columns=72 — neither accurate nor what we want; we replace it with
    # either docx tblGrid widths or the content-aware heuristic.
    s = re.sub(
        r"<colgroup\b[^>]*>.*?</colgroup>",
        "",
        s,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Remove <p> inside <td> with single paragraph — more compact source.
    # IMPORTANT: do NOT use re.DOTALL — it would cross cell/row boundaries
    # and corrupt multi-cell content. Without DOTALL, only single-line cells match.
    s = re.sub(
        r"<td>\s*<p>(.*?)</p>\s*</td>",
        r"<td>\1</td>",
        s,
    )
    # T-07: Strip the <p> wrapper immediately following each <li> open tag.
    # pandoc emits "loose" lists as <li><p>text</p>...</li>, which causes
    # huge line-height in Obsidian's HTML renderer inside <table> cells.
    # We only strip the FIRST <p>...</p> directly after <li>; any nested
    # <ol>/<ul> children and multi-paragraph items are left intact.
    s = re.sub(
        r"<li>\s*<p>((?:(?!</p>).)*)</p>",
        r"<li>\1",
        s,
        flags=re.DOTALL,
    )
    # T-07b: Strip <li><blockquote><p>text</p></blockquote> → <li>text
    # Tencent Docs sometimes puts indented/quoted list items in a blockquote
    # wrapper, which adds substantial vertical margin in Obsidian.
    s = re.sub(
        r"<li>\s*<blockquote>\s*<p>((?:(?!</p>).)*)</p>\s*</blockquote>",
        r"<li>\1",
        s,
        flags=re.DOTALL,
    )

    # T-23: Compact vertical spacing inside table cells. Sources of excess
    # whitespace when rendered in Obsidian/browsers:
    #   A. <p> margin-block (1em top+bottom)
    #   B. <ul>/<ol> margin-block (1em top+bottom)
    #   C. <li> margin-block (0.25-0.5em)
    #   D. <blockquote> margin + padding (1em + 10px)
    # Strategy: preserve paragraph breaks as <br>, strip <p> wrappers entirely,
    # inject compact inline margins on list/quote elements so Obsidian's
    # default CSS can't expand them. Scope is limited to this table block.
    # 1. Preserve visual line-break between paragraphs before stripping tags.
    s = re.sub(r"</p>\s*<p\b[^>]*>", "<br>", s, flags=re.IGNORECASE)
    # 2. Strip remaining <p>/</p> open/close tags (T-05, T-07, T-07b above
    # become subsumed by this but are kept for clarity).
    s = re.sub(r"</?p\b[^>]*>", "", s, flags=re.IGNORECASE)
    # 3. Compact <ul>/<ol> margins. Negative lookahead skips tags that
    # already carry an inline style (e.g. tags inside nested-table content
    # previously stylized by an outer pass).
    s = re.sub(
        r'<(ul|ol)\b(?![^>]*style=)',
        r'<\1 style="margin:0.2em 0;padding-left:1.4em"',
        s, flags=re.IGNORECASE,
    )
    # 4. <li> zero margin/padding.
    s = re.sub(
        r'<li\b(?![^>]*style=)',
        '<li style="margin:0;padding:0"',
        s, flags=re.IGNORECASE,
    )
    # 5. <blockquote> compact margin + thin left rule (keeps quote semantic
    # visible without Obsidian's default 1em margin blow-up).
    s = re.sub(
        r'<blockquote\b(?![^>]*style=)',
        '<blockquote style="margin:0.2em 0;padding-left:0.8em;border-left:2px solid #ddd"',
        s, flags=re.IGNORECASE,
    )

    # T-21: Apply size constraints to all <img> tags inside this table so they
    # don't overwhelm adjacent text columns.
    s = _IMG_TAG_RE.sub(_constrain_img, s)

    # Convert wiki-link images back to <img> tags inside HTML tables,
    # because Obsidian does NOT render ![[...]] wiki-links inside HTML blocks.
    # _wikilink_to_img already adds the size-constraint style (T-21).
    s = _WIKILINK_IMG_RE.sub(_wikilink_to_img, s)

    # T-22: Force text wrapping in Obsidian's HTML table renderer.
    # Without table-layout:fixed, Obsidian uses 'auto' layout where column
    # widths are driven by the widest unbreakable content (e.g. a deeply
    # nested list item), making the table wider than the viewport.
    # Strategy:
    #   <table>  → add style="table-layout:fixed;width:100%"
    #   <td>/<th> → add style="word-break:break-word;overflow-wrap:break-word"
    # All style/class attrs on these elements were stripped above, so we're
    # adding fresh attributes — no risk of doubling.
    s = re.sub(
        r'<table\b(?=[^>]*>)',
        '<table style="table-layout:fixed;width:100%"',
        s, count=1, flags=re.IGNORECASE,
    )
    # T-22b: Inject <colgroup> with column widths immediately after the
    # opening <table> tag so each column gets proportional space.
    # Priority:
    #   1. docx <w:tblGrid> widths — strict original ratio
    #   2. content-aware heuristic (_compute_col_widths) as fallback
    if tree is not None:
        col_widths: list[str] = []
        if docx_widths and len(docx_widths) == tree.max_cols():
            col_widths = _docx_widths_to_pct(docx_widths)
        if not col_widths:
            col_widths = _compute_col_widths(tree)
        if col_widths:
            colgroup = "<colgroup>" + "".join(
                f'<col style="width:{w}">' for w in col_widths
            ) + "</colgroup>"
            s = re.sub(
                r'(<table\b[^>]*>)',
                r'\1\n' + colgroup,
                s, count=1, flags=re.IGNORECASE,
            )
    # T-23: Append padding/line-height/vertical-align to td/th so that:
    #   - rows have consistent compact height
    #   - narrow cells with little content don't float to vertical center
    #     when neighboring wide cell wraps (vertical-align:top)
    s = re.sub(
        r'<(td|th)\b(?=[^>]*>)',
        r'<\1 style="word-break:break-word;overflow-wrap:break-word;'
        r'padding:4px 8px;line-height:1.5;vertical-align:top"',
        s, flags=re.IGNORECASE,
    )

    # Collapse blank lines
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# Match a GFM pipe table: one or more pipe-rows, then a separator row (|---|...|),
# then zero or more pipe-rows.  Must be preceded by a blank line or start-of-string
# so we don't accidentally match a single-line fragment inside a paragraph.
_GFM_TABLE_RE = re.compile(
    r'(?:(?<=\n\n)|(?<=\A))'           # blank-line or start before table
    r'((?:\|[^\n]*\|\n)+)'            # header + optional rows before separator
    r'(\|[ :|-]+\|[ :|-|\n]*\n)'     # separator row
    r'((?:\|[^\n]*\|\n)*)',           # body rows
    re.MULTILINE,
)


def _fix_gfm_empty_header(m: re.Match) -> str:
    """If the first row of a GFM pipe table has all-empty cells, drop it and
    use the next row as the header instead (UAT Issue #1)."""
    pre_sep = m.group(1)    # rows before separator (normally just the header)
    sep = m.group(2)        # separator row
    body = m.group(3)       # body rows

    pre_lines = pre_sep.splitlines(keepends=True)
    if not pre_lines:
        return m.group(0)

    header_line = pre_lines[0]
    cells = [c.strip() for c in header_line.split("|")[1:-1]]
    if not all(c == "" for c in cells):
        return m.group(0)  # header already has content — nothing to do

    # Drop the empty header; the first body row becomes the new header.
    remaining_pre = pre_lines[1:]      # any rows between original header and sep
    body_lines = body.splitlines(keepends=True)

    if remaining_pre:
        # There were extra rows between the empty header and the separator.
        new_header = remaining_pre[0]
        extra_pre = remaining_pre[1:]
        new_body = extra_pre + body_lines
    elif body_lines:
        new_header = body_lines[0]
        new_body = body_lines[1:]
    else:
        return m.group(0)  # nothing to promote

    return new_header + sep + "".join(new_body)


def _remove_phantom_pipe_tables(md: str) -> str:
    """T-18: Remove all-dash/all-empty pipe table blocks with no real content.

    Pandoc emits these phantom tables when a docx table has a full-colspan
    title/header row (e.g. "文档变更记录") that spans all columns — pandoc
    expands it into N empty/dash cells and outputs it as a standalone table
    block, separate from the actual data rows.

    Detection: a block of consecutive | lines where, after stripping pipes
    and separator characters (-, :, space), no cell contains any real text.
    """
    def _check_block(m: re.Match) -> str:
        block = m.group(0)
        # Strip each row into cell values
        for row in block.strip().splitlines():
            cells = row.split("|")
            for cell in cells:
                stripped = cell.strip()
                # If any cell has content beyond dash/colon/space, keep the block.
                if stripped and not re.match(r'^[-: ]*$', stripped):
                    return block
        # All cells are empty or separator-like — remove the block.
        return ""

    return _PHANTOM_PIPE_BLOCK_RE.sub(_check_block, md)


def clean_tables(md: str, ctx: CleanerContext) -> str:
    total = 0
    to_pipe = 0
    kept_html = 0
    widths_from_docx = 0
    widths_from_heuristic = 0

    table_grids = list(getattr(ctx.probe, "table_grids", []) or [])
    # Global table index requires counting BOTH HTML blocks (TABLE_BLOCK_RE)
    # AND pandoc's native GFM pipe tables (_GFM_TABLE_RE) in document order —
    # pandoc preserves docx table order across both output forms, so the
    # N-th table overall (whatever form) ↔ N-th tblGrid. We precompute the
    # start positions of native pipe tables so each HTML block substitution
    # can look up how many pipe tables preceded it.
    pipe_starts = [pm.start() for pm in _GFM_TABLE_RE.finditer(md)]

    def _global_idx_for_html(html_start: int, html_block_ord: int) -> int:
        n_pipe_before = sum(1 for p in pipe_starts if p < html_start)
        return n_pipe_before + html_block_ord

    html_block_ord = [0]  # mutable counter for HTML-block substitution order

    def _repl(m: re.Match) -> str:
        nonlocal total, to_pipe, kept_html, widths_from_docx, widths_from_heuristic
        total += 1
        raw = m.group(0)
        tree = _parse_table(raw)
        ncols = tree.max_cols()
        gi = _global_idx_for_html(m.start(), html_block_ord[0])
        html_block_ord[0] += 1
        docx_widths = None
        if 0 <= gi < len(table_grids):
            grid = table_grids[gi]
            if grid and len(grid) == ncols:
                docx_widths = grid
        if _can_pipe(tree):
            to_pipe += 1
            # Pipe tables can't encode column widths in GFM syntax; the
            # grid index was still consumed above to stay aligned with
            # docx table order for subsequent HTML tables.
            return _grid_to_pipe(tree)
        kept_html += 1
        if docx_widths:
            widths_from_docx += 1
        elif ncols >= 2:
            # A heuristic will run inside _clean_html_table as long as
            # tree has 2+ columns; count the intent here.
            widths_from_heuristic += 1
        return _clean_html_table(raw, tree, docx_widths=docx_widths)

    md = TABLE_BLOCK_RE.sub(_repl, md)

    # Fix empty header rows in GFM pipe tables that pandoc already emitted
    # (these bypass the HTML→pipe path above).
    md = _GFM_TABLE_RE.sub(_fix_gfm_empty_header, md)

    # T-18: Remove phantom all-empty/all-dash pipe table blocks.
    md = _remove_phantom_pipe_tables(md)

    # T-24: 检测复杂嵌套表泄漏（developer-feedback §4.1）。
    # 复杂表（含嵌套表 + 合并单元格）pandoc 输出时偶尔会在 GFM pipe 表后面留下
    # 残余 `</td></tr><tr><td>...` 序列，混在正文里。这里只统计/告警，不强行
    # 修复——后续若需修复，可对每个 leak 区段尝试 wrap 成 <table> 兜底。
    leaks = _detect_table_tag_leaks(md)

    table_report = {
        "total_html_tables": total,
        "degraded_to_pipe": to_pipe,
        "kept_as_html": kept_html,
        "widths_from_docx": widths_from_docx,
        "widths_from_heuristic": widths_from_heuristic,
        "tag_leaks": leaks["count"],
    }
    if leaks["count"]:
        ctx.warn(
            f"table_cleaner: 检测到 {leaks['count']} 处疑似泄漏 HTML 表格标签（"
            f"{', '.join(leaks['samples'][:3])}）；建议人工核查复杂嵌套表区域。"
        )
        table_report["tag_leak_samples"] = leaks["samples"][:5]

    ctx.set_report("table_cleaner", table_report)
    return md


# 仅匹配「行首/独立成行」的孤立块级表格收尾标签 —— 这些是泄漏的强信号。
# 行内出现的 `</td>`（例如已正确包裹在 <table> 内）会被下面的 _strip_tables
# 一并移除后再扫描，避免误报。
_ORPHAN_TAG_RE = re.compile(
    r"^\s*(</?(?:tr|td|th|tbody|thead|tfoot)\b[^>]*>)\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_FULL_TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.DOTALL | re.IGNORECASE)


def _detect_table_tag_leaks(md: str) -> dict:
    """统计 markdown 中"游离在 <table> 之外"的表格标签数量与样本。"""
    # 把所有完整的 <table>...</table> 抠掉，只看残余正文
    residual = _FULL_TABLE_RE.sub("", md)
    samples = []
    count = 0
    for m in _ORPHAN_TAG_RE.finditer(residual):
        count += 1
        if len(samples) < 5:
            samples.append(m.group(1))
    return {"count": count, "samples": samples}
