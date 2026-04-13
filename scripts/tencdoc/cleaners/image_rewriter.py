"""ImageRewriter — normalize all image references to Obsidian wiki-links.

Handles both:

1. Standard markdown images produced by pandoc::

    ![alt text](media/image1.png){width="1.2in" height="3.4in"}

2. HTML ``<img>`` tags pandoc emits inside complex tables::

    <img src="media/image1.png" style="width:1.27in;height:2.76in" alt="descript" />

Both are rewritten to Obsidian embed wiki-links::

    ![[stem/image1.png]]

Dropping width/height and the meaningless ``alt="descript"`` that Tencent Docs
injects on every image. If the original alt is meaningful (i.e. not empty,
not ``descript``, not ``图像``, etc.) we preserve it as::

    ![[stem/image1.png|人工补的 alt 描述]]
"""

from __future__ import annotations

import re
from pathlib import Path

from ..pipeline import CleanerContext


# alt values that Tencent Docs / pandoc emit as placeholders — drop them.
_ALT_STOPWORDS = {
    "",
    "descript",
    "图像",
    "图片",
    "picture",
    "image",
    "screenshot",
    "pasted image",
}


# Common image basename pattern: "imageN.ext"
_IMAGE_BASENAME = re.compile(r"(image\d+\.[a-zA-Z0-9]+)")


def _clean_alt(alt: str) -> str:
    alt = (alt or "").strip()
    if alt.lower() in _ALT_STOPWORDS:
        return ""
    # Strip trailing " 描述已自动生成" that Word / Tencent Doc add.
    alt = re.sub(r"\s*描述已自动生成\s*$", "", alt)
    alt = re.sub(r"\s*自动生成的.*$", "", alt)
    return alt.strip()


def _to_wikilink(basename: str, stem: str, alt: str) -> str:
    alt = _clean_alt(alt)
    inner = f"{stem}/{basename}"
    if alt:
        return f"![[{inner}|{alt}]]"
    return f"![[{inner}]]"


def rewrite_images(md: str, ctx: CleanerContext) -> str:
    stem = ctx.output_stem
    replaced_md = 0
    replaced_html = 0

    # --- 1. pandoc markdown image syntax ---
    # matches ![alt](path){attrs}  OR  ![alt](path)
    md_img_pattern = re.compile(
        r"!\[([^\]]*)\]\(([^)]+)\)(\{[^}]*\})?"
    )

    def _md_repl(m: re.Match) -> str:
        nonlocal replaced_md
        alt = m.group(1)
        path = m.group(2)
        base_m = _IMAGE_BASENAME.search(path)
        if not base_m:
            # Not an image we extracted (could be external URL). Leave alone.
            return m.group(0)
        basename = base_m.group(1)
        replaced_md += 1
        return _to_wikilink(basename, stem, alt)

    md = md_img_pattern.sub(_md_repl, md)

    # --- 2. HTML <img ...> tags (inside HTML tables etc.) ---
    img_tag_pattern = re.compile(
        r'<img\b([^>]*?)/?>',
        re.IGNORECASE | re.DOTALL,
    )
    src_pattern = re.compile(r'src\s*=\s*"([^"]+)"', re.IGNORECASE)
    alt_pattern = re.compile(r'alt\s*=\s*"([^"]*)"', re.IGNORECASE)

    def _html_repl(m: re.Match) -> str:
        nonlocal replaced_html
        body = m.group(1)
        src_m = src_pattern.search(body)
        alt_m = alt_pattern.search(body)
        if not src_m:
            return m.group(0)
        base_m = _IMAGE_BASENAME.search(src_m.group(1))
        if not base_m:
            return m.group(0)
        basename = base_m.group(1)
        alt = alt_m.group(1) if alt_m else ""
        replaced_html += 1
        return _to_wikilink(basename, stem, alt)

    md = img_tag_pattern.sub(_html_repl, md)

    ctx.set_report(
        "image_rewriter",
        {
            "markdown_images_rewritten": replaced_md,
            "html_images_rewritten": replaced_html,
        },
    )
    return md
