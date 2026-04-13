"""ListSqueezer — compact pandoc's overly-loose markdown output.

Pandoc often wraps list items in blank lines even when the source was a
tight list. For Obsidian reading, we prefer compact lists. We also collapse
any run of 3+ blank lines to a single blank line.
"""

from __future__ import annotations

import re

from ..pipeline import CleanerContext


_BLANK_RUN_RE = re.compile(r"\n{3,}")
# A blank line between two consecutive list items with the same marker and
# indent is noise we can remove.
_LIST_ITEM_RE = re.compile(r"^([ \t]*)(?:[-*+]|\d+\.)\s")


def squeeze_lists(md: str, ctx: CleanerContext) -> str:
    # T-19: Remove "<!-- end list -->" HTML comments that pandoc inserts as
    # list-continuation markers.  They are semantically meaningless in the
    # output and appear as raw text in Obsidian.
    md = re.sub(r"<!--\s*end list\s*-->\s*\n?", "", md)

    md = _BLANK_RUN_RE.sub("\n\n", md)

    # Drop blank lines between adjacent list items of the same type.
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    blanks_dropped = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        # peek: current is list item, next is blank, next-next is list item
        if (
            _LIST_ITEM_RE.match(line)
            and i + 2 < len(lines)
            and lines[i + 1].strip() == ""
            and _LIST_ITEM_RE.match(lines[i + 2])
        ):
            # skip the blank
            i += 2
            blanks_dropped += 1
            continue
        i += 1

    md = "\n".join(out)
    if not md.endswith("\n"):
        md += "\n"

    ctx.set_report("list_squeezer", {"blank_lines_dropped": blanks_dropped})
    return md
