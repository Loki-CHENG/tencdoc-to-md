"""HyperlinkCleaner — cosmetic cleanup of markdown hyperlinks.

Current duties (intentionally minimal; we'll iterate as we see new cases):

- Trim whitespace around link text: ``[  foo  ](url)`` → ``[foo](url)``
- Drop empty links left by pandoc: ``[]()``
- Detect Tencent Doc self-links (``doc.weixin.qq.com``) and tag them in the
  report so the outer agent can decide whether to rewrite them to vault
  wiki-links.
"""

from __future__ import annotations

import re

from ..pipeline import CleanerContext


_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
_TENC_LINK_HOSTS = ("doc.weixin.qq.com", "docs.qq.com")


def clean_hyperlinks(md: str, ctx: CleanerContext) -> str:
    tenc_links: list[str] = []
    empty_dropped = 0
    trimmed = 0

    def _repl(m: re.Match) -> str:
        nonlocal empty_dropped, trimmed
        text = m.group(1)
        url = m.group(2).strip()
        stripped_text = text.strip()
        if not stripped_text and not url:
            empty_dropped += 1
            return ""
        if stripped_text != text:
            trimmed += 1
        if any(h in url for h in _TENC_LINK_HOSTS):
            tenc_links.append(url)
        if not stripped_text:
            # Link with empty text but real URL → show the URL itself.
            return f"<{url}>"
        return f"[{stripped_text}]({url})"

    md = _LINK_RE.sub(_repl, md)

    ctx.set_report(
        "hyperlink_cleaner",
        {
            "empty_links_dropped": empty_dropped,
            "text_trimmed": trimmed,
            "tencent_doc_links": tenc_links,
        },
    )
    return md
