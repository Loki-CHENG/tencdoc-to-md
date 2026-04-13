"""HeadingNormalizer — fix the two headings quirks of Tencent Docs.

Quirk 1: pandoc wraps standalone headings in a numbered list when the source
paragraph had ``<w:numPr>`` applied::

    2.  #### 需求目标
    5.  #### 需求详细描述

        1.  ##### 功能点说明

We unwrap these: strip the leading "N." / bullet and any indentation, so the
heading starts a fresh line.

Quirk 2: Tencent Docs authors often start the document at heading-4 or
heading-5 because they treat the heading menu as a font-size picker. After
pandoc conversion we end up with a md file whose top-level section is
``#####``. We shift so the minimum *used* level becomes H2 (H1 is reserved
for the front matter title).
"""

from __future__ import annotations

import re

from ..pipeline import CleanerContext


# Line patterns we care about.
# - Indented leading marker: "    2.  ####" or "- ####" or "* ####"
_LIST_WRAPPED_HEADING = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>(?:\d+\.)|[-*+])[ \t]+(?P<hashes>#{1,6})[ \t]+(?P<text>.*\S)\s*$"
)
# Plain heading line (no wrapping).
_PLAIN_HEADING = re.compile(r"^(?P<hashes>#{1,6})[ \t]+(?P<text>.*\S)\s*$")


def _unwrap_list_headings(md: str) -> tuple[str, int]:
    lines = md.splitlines()
    unwrapped = 0
    new_lines = []
    for line in lines:
        m = _LIST_WRAPPED_HEADING.match(line)
        if m:
            unwrapped += 1
            new_lines.append(f"{m.group('hashes')} {m.group('text')}")
        else:
            new_lines.append(line)
    return "\n".join(new_lines) + ("\n" if md.endswith("\n") else ""), unwrapped


def _collect_heading_levels(md: str) -> list[int]:
    levels = []
    # Skip content inside fenced code blocks.
    in_fence = False
    for line in md.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _PLAIN_HEADING.match(line)
        if m:
            levels.append(len(m.group("hashes")))
    return levels


def _shift_headings(md: str, offset: int) -> tuple[str, int]:
    """Subtract ``offset`` from every heading's level; clamp to [1, 6]."""
    if offset == 0:
        return md, 0

    touched = 0
    in_fence = False
    new_lines = []
    for line in md.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            new_lines.append(line)
            continue
        if in_fence:
            new_lines.append(line)
            continue
        m = _PLAIN_HEADING.match(line)
        if not m:
            new_lines.append(line)
            continue
        old_level = len(m.group("hashes"))
        new_level = max(1, min(6, old_level - offset))
        new_lines.append("#" * new_level + " " + m.group("text"))
        touched += 1

    suffix = "\n" if md.endswith("\n") else ""
    return "\n".join(new_lines) + suffix, touched


def _remove_empty_headings(md: str) -> tuple[str, int]:
    """Remove heading lines that have no text content (e.g. ``### `` or ``####``)."""
    removed = 0
    new_lines = []
    in_fence = False
    for line in md.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        if not in_fence and re.match(r"^#{1,6}\s*$", line):
            removed += 1
            continue
        new_lines.append(line)
    suffix = "\n" if md.endswith("\n") else ""
    return "\n".join(new_lines) + suffix, removed


def normalize_headings(md: str, ctx: CleanerContext) -> str:
    md, unwrapped = _unwrap_list_headings(md)
    md, empty_removed = _remove_empty_headings(md)

    levels = _collect_heading_levels(md)
    if not levels:
        ctx.set_report(
            "heading_normalizer",
            {
                "list_wrapped_unwrapped": unwrapped,
                "empty_headings_removed": empty_removed,
                "heading_levels_before": [],
                "offset_applied": 0,
                "headings_after": 0,
            },
        )
        return md

    min_level = min(levels)
    # Target: min used level becomes H2 (H1 is reserved for front-matter title).
    target = 2
    offset = min_level - target
    md, touched = _shift_headings(md, offset)

    ctx.set_report(
        "heading_normalizer",
        {
            "list_wrapped_unwrapped": unwrapped,
            "empty_headings_removed": empty_removed,
            "heading_levels_before": sorted(set(levels)),
            "min_level_before": min_level,
            "offset_applied": offset,
            "headings_after": touched,
        },
    )
    return md
