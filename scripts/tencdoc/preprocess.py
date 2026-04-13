"""Docx preprocessor — fix XML quirks before handing to pandoc.

Tencent Docs applies ``<w:numPr>`` (numbered/bulleted list) to heading
paragraphs. Pandoc >= 2.9 usually preserves the heading semantics but when
the heading level is deep (5/6) **and** the paragraph has ``<w:numPr>`` with
certain indent combinations, pandoc renders the paragraph as a plain bold
list item instead of a heading — losing all structure.

Fix: before invoking pandoc, we rewrite ``document.xml`` to strip
``<w:numPr>`` (and any ``<w:ind>`` introduced by the list) from any
paragraph whose ``<w:pStyle>`` maps to a heading in ``styles.xml``.

Additionally, pandoc silently drops several common inline formats:
- ``<w:u w:val="single">``       — underline
- ``<w:shd w:fill="RRGGBB">``   — background colour (highlight)
- ``<w:color w:val="RRGGBB">``  — text colour

We inject Unicode PUA sentinels around the affected run text *before*
pandoc processes the XML.  Pandoc passes these opaque characters through
unchanged, and the ``inline_formatter`` cleaner later converts them to HTML
``<u>`` / ``<span style="background-color:...">`` / ``<span style="color:...">``
tags.

Sentinel characters (Private Use Area — extremely unlikely to appear in
real Chinese/English document text):
  \\uE100  = open underline
  \\uE101  = close underline
  \\uE102  = open highlight  (immediately followed by 6-char hex colour)
  \\uE104  = close highlight
  \\uE105  = open text colour (immediately followed by 6-char hex colour)
  \\uE106  = close text colour

The preprocessed docx is written to a temp file; the original is never
modified.
"""

from __future__ import annotations

import re
import shutil
import zipfile
import tempfile
from pathlib import Path
from typing import Set

from .probe import DocxProbe


# ---------------------------------------------------------------------------
# Sentinel characters for inline-format injection
# ---------------------------------------------------------------------------
_SEN_U_OPEN   = "\uE100"   # open underline
_SEN_U_CLOSE  = "\uE101"   # close underline
_SEN_H_OPEN   = "\uE102"   # open highlight  (followed by 6-char hex)
_SEN_H_CLOSE  = "\uE104"   # close highlight
_SEN_C_OPEN   = "\uE105"   # open text colour (followed by 6-char hex)
_SEN_C_CLOSE  = "\uE106"   # close text colour

# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------
_PSTYLE_VAL = re.compile(r'<w:pStyle\s+w:val="([^"]+)"')

# We'll strip <w:numPr>...</w:numPr> (which can contain ilvl + numId)
# from paragraphs whose pStyle is in the heading set.
_NUMPR_BLOCK = re.compile(r'<w:numPr>.*?</w:numPr>', re.DOTALL)
# Also strip empty <w:numPr/> self-closing tags.
_NUMPR_SELF = re.compile(r'<w:numPr\s*/>')

# Match a single paragraph block.
_PARAGRAPH = re.compile(r'<w:p\b[^>]*>.*?</w:p>', re.DOTALL)
# Match pPr block inside paragraph.
_PPR_BLOCK = re.compile(r'<w:pPr>(.*?)</w:pPr>', re.DOTALL)


def _heading_style_ids(probe: DocxProbe) -> Set[str]:
    """Return the set of pStyle IDs that correspond to headings."""
    ids = set()
    for sid, name in probe.paragraph_style_map.items():
        lower = name.lower().strip()
        if lower.startswith("heading ") or lower == "title":
            ids.add(sid)
    return ids


def _strip_numpr_from_headings(doc_xml: str, heading_ids: Set[str]) -> tuple[str, int]:
    """Remove <w:numPr> from heading paragraphs. Return (new_xml, count)."""
    fixed = 0

    def _fix_paragraph(m: re.Match) -> str:
        nonlocal fixed
        para = m.group(0)
        # Does this paragraph have a heading pStyle?
        pstyle_m = _PSTYLE_VAL.search(para)
        if not pstyle_m or pstyle_m.group(1) not in heading_ids:
            return para
        # Only strip if it actually has numPr.
        if '<w:numPr>' not in para and '<w:numPr/>' not in para:
            return para
        fixed += 1
        # Strip the numPr block inside pPr.
        def _fix_ppr(ppr_m: re.Match) -> str:
            inner = ppr_m.group(1)
            inner = _NUMPR_BLOCK.sub('', inner)
            inner = _NUMPR_SELF.sub('', inner)
            return f'<w:pPr>{inner}</w:pPr>'
        return _PPR_BLOCK.sub(_fix_ppr, para)

    result = _PARAGRAPH.sub(_fix_paragraph, doc_xml)
    return result, fixed


# ---------------------------------------------------------------------------
# Inline-format sentinel injection
# ---------------------------------------------------------------------------

# A run element: <w:r> ... <w:rPr>...</w:rPr> ... <w:t ...>TEXT</w:t> </w:r>
# We need to detect underline / shading / colour in rPr and wrap t content.
_RUN_RE = re.compile(r'<w:r\b[^>]*>(.*?)</w:r>', re.DOTALL)
_W_T_RE = re.compile(r'(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)', re.DOTALL)
_UNDERLINE_RE = re.compile(r'<w:u\s+w:val="single"\s*/>', re.IGNORECASE)
_SHD_FILL_RE  = re.compile(
    r'<w:shd\b[^>]*\bw:fill="([0-9A-Fa-f]{6})"[^>]*/>', re.IGNORECASE
)
_COLOR_VAL_RE = re.compile(
    r'<w:color\b[^>]*\bw:val="([0-9A-Fa-f]{6})"[^>]*/>', re.IGNORECASE
)

# Colours to treat as "no highlight" (white, auto, transparent)
_SKIP_FILLS = {'FFFFFF', 'AUTO', 'NONE', ''}


def _is_near_black(hex6: str) -> bool:
    """Return True for near-black default text colours (all channels < 0x30).

    Tencent Docs often stores default text colour as 000000 or 0D0D0D.
    We don't want to wrap these in a colour span — only meaningful colours
    like red (#FF0000) or blue (#0000FF) should get sentinel treatment.
    """
    try:
        r = int(hex6[0:2], 16)
        g = int(hex6[2:4], 16)
        b = int(hex6[4:6], 16)
        return r < 0x30 and g < 0x30 and b < 0x30
    except ValueError:
        return True  # malformed — treat as default


def _inject_run_sentinels(doc_xml: str) -> tuple[str, int, int, int]:
    """Wrap underline, highlight, and coloured runs with PUA sentinels.

    Returns (modified_xml, underline_count, highlight_count, colour_count).
    """
    ul_count = 0
    hl_count = 0
    cl_count = 0

    def _rewrite_run(m: re.Match) -> str:
        nonlocal ul_count, hl_count, cl_count
        run = m.group(1)

        # Locate rPr block
        rpr_end = run.find('</w:rPr>')
        if rpr_end == -1:
            return m.group(0)
        rpr = run[:rpr_end + len('</w:rPr>')]

        # Check for underline
        has_ul = bool(_UNDERLINE_RE.search(rpr))

        # Check for highlight shading
        shd_m = _SHD_FILL_RE.search(rpr)
        fill = shd_m.group(1).upper() if shd_m else None
        if fill and fill in _SKIP_FILLS:
            fill = None

        # Check for text colour (T-20); skip near-black defaults
        col_m = _COLOR_VAL_RE.search(rpr)
        colour = col_m.group(1).upper() if col_m else None
        if colour and _is_near_black(colour):
            colour = None

        if not has_ul and not fill and not colour:
            return m.group(0)

        # Wrap the <w:t> content with sentinels
        def _wrap_t(tm: re.Match) -> str:
            nonlocal ul_count, hl_count, cl_count
            open_tag, text, close_tag = tm.group(1), tm.group(2), tm.group(3)
            if has_ul:
                ul_count += 1
                text = _SEN_U_OPEN + text + _SEN_U_CLOSE
            if fill:
                hl_count += 1
                text = _SEN_H_OPEN + fill + text + _SEN_H_CLOSE
            if colour:
                cl_count += 1
                text = _SEN_C_OPEN + colour + text + _SEN_C_CLOSE
            return open_tag + text + close_tag

        new_run = _W_T_RE.sub(_wrap_t, run)
        return '<w:r>' + new_run + '</w:r>'

    result = _RUN_RE.sub(_rewrite_run, doc_xml)
    return result, ul_count, hl_count, cl_count


def preprocess_docx(docx_path: Path, probe: DocxProbe) -> tuple[Path, int, int, int, int]:
    """Create a temp copy of the docx with heading numPr stripped and inline
    format sentinels injected.

    Returns ``(temp_docx_path, paragraphs_fixed, underline_runs, highlight_runs,
    colour_runs)``.

    The caller is responsible for cleaning up the temp file/dir.
    """
    heading_ids = _heading_style_ids(probe)

    tmp_dir = Path(tempfile.mkdtemp(prefix="tencdoc_pre_"))
    tmp_docx = tmp_dir / docx_path.name

    fixed = ul_count = hl_count = cl_count = 0
    with zipfile.ZipFile(docx_path, 'r') as zin:
        with zipfile.ZipFile(tmp_docx, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "word/document.xml":
                    xml = data.decode("utf-8", errors="replace")
                    if heading_ids:
                        xml, fixed = _strip_numpr_from_headings(xml, heading_ids)
                    xml, ul_count, hl_count, cl_count = _inject_run_sentinels(xml)
                    zout.writestr(item, xml.encode("utf-8"))
                else:
                    zout.writestr(item, data)

    return tmp_docx, fixed, ul_count, hl_count, cl_count
