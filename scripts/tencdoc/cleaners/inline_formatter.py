"""inline_formatter — restore inline formatting lost by pandoc.

pandoc silently drops three OOXML run properties:
  - ``<w:u w:val="single">``         underline
  - ``<w:shd w:fill="RRGGBB">``      background-colour highlight
  - ``<w:color w:val="RRGGBB">``     text colour

``preprocess.py`` injects Unicode PUA sentinels around the affected runs
*before* pandoc processes the docx.  This cleaner converts those sentinels
back to Obsidian-compatible HTML tags:

  \\uE100TEXT\\uE101           →  <u>TEXT</u>
  \\uE102RRGGBBTEXT\\uE104    →  <span style="background-color: #RRGGBB">TEXT</span>
  \\uE105RRGGBBTEXT\\uE106    →  <span style="color: #RRGGBB">TEXT</span>

The sentinel characters are chosen from Unicode's Private Use Area
(U+E100–U+E106) and should never appear in ordinary document text.
"""

from __future__ import annotations

import re

from ..pipeline import CleanerContext

# ---------------------------------------------------------------------------
# Sentinel definitions (must match preprocess.py)
# ---------------------------------------------------------------------------
_SEN_U_OPEN   = "\uE100"
_SEN_U_CLOSE  = "\uE101"
_SEN_H_OPEN   = "\uE102"
_SEN_H_CLOSE  = "\uE104"
_SEN_C_OPEN   = "\uE105"   # text colour
_SEN_C_CLOSE  = "\uE106"

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------
# Underline: \uE100 ... \uE101
_UNDERLINE_RE = re.compile(
    _SEN_U_OPEN + r"(.*?)" + _SEN_U_CLOSE,
    re.DOTALL,
)

# Highlight: \uE102 RRGGBB ... \uE104
_HIGHLIGHT_RE = re.compile(
    _SEN_H_OPEN + r"([0-9A-Fa-f]{6})(.*?)" + _SEN_H_CLOSE,
    re.DOTALL,
)

# Text colour: \uE105 RRGGBB ... \uE106
_COLOUR_RE = re.compile(
    _SEN_C_OPEN + r"([0-9A-Fa-f]{6})(.*?)" + _SEN_C_CLOSE,
    re.DOTALL,
)

# Stray sentinels that were not properly paired (safety clean-up)
_STRAY_RE = re.compile(
    r"[\uE100\uE101\uE102\uE104\uE105\uE106]",
)

# Adjacent same-style span merger — Tencent Docs often exports each character
# (or small phrase) as a separate <w:r> run, resulting in many consecutive
# identical <span> tags.  We merge them iteratively until stable.
# NOTE: content inside spans must not cross line boundaries (no re.DOTALL) so
# that multi-line documents don't cause catastrophic backtracking.
_ADJ_SPAN_RE = re.compile(
    r'<span\s+style="([^"]+)">([^<]*(?:<(?!/span)[^<]*)*)</span>'
    r'([ \t]*)'
    r'<span\s+style="([^"]+)">([^<]*(?:<(?!/span)[^<]*)*)</span>',
)


def _merge_adjacent_spans(md: str) -> str:
    """Collapse runs of adjacent <span> elements with identical style into one.

    Iterates until no more merges are possible.  Only merges spans on the same
    logical line (no newlines between them) to avoid runaway matches.
    """
    def _try_merge(m: re.Match) -> str:
        style1, content1, gap, style2, content2 = (
            m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        )
        if style1 != style2:
            return m.group(0)
        return f'<span style="{style1}">{content1}{gap}{content2}</span>'

    prev = None
    while prev != md:
        prev = md
        md = _ADJ_SPAN_RE.sub(_try_merge, md)
    return md


def clean_inline_formats(md: str, ctx: CleanerContext) -> str:
    """Convert PUA sentinels back to HTML inline tags."""
    ul_count = 0
    hl_count = 0
    cl_count = 0

    def _repl_ul(m: re.Match) -> str:
        nonlocal ul_count
        ul_count += 1
        return f"<u>{m.group(1)}</u>"

    def _repl_hl(m: re.Match) -> str:
        nonlocal hl_count
        hl_count += 1
        color = m.group(1).upper()
        text  = m.group(2)
        return f'<span style="background-color: #{color}">{text}</span>'

    def _repl_cl(m: re.Match) -> str:
        nonlocal cl_count
        cl_count += 1
        color = m.group(1).upper()
        text  = m.group(2)
        return f'<span style="color: #{color}">{text}</span>'

    md = _UNDERLINE_RE.sub(_repl_ul, md)
    md = _HIGHLIGHT_RE.sub(_repl_hl, md)
    md = _COLOUR_RE.sub(_repl_cl, md)
    # Remove any stray / unpaired sentinels
    md = _STRAY_RE.sub("", md)
    # Merge adjacent same-style spans (character-level run splitting in Tencent Docs)
    md = _merge_adjacent_spans(md)

    ctx.set_report(
        "inline_formatter",
        {
            "underlines_restored": ul_count,
            "highlights_restored": hl_count,
            "colours_restored": cl_count,
        },
    )
    return md
