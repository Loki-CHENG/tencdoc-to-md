"""FrontMatterInjector — prepend YAML metadata block.

MVP fields: ``title`` / ``source`` / ``converted_at`` / ``source_file`` /
``tags`` / ``author`` / ``aliases``.

We reuse the Tencent Doc links collected by ``hyperlink_cleaner``'s report:
if exactly one such link occurs in the markdown and it happens to match the
document title, we put it into ``source``. Otherwise ``source`` stays empty
for the user to fill in.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from ..pipeline import CleanerContext


def _yaml_escape(value: str) -> str:
    # Minimal escaping — quote if contains ':', '#', or starts with an
    # indicator character.
    if value is None:
        return '""'
    s = str(value)
    needs_quote = any(ch in s for ch in [":", "#", "[", "]", "{", "}", "&", "*", "!", "|", ">", "'", '"']) or s.strip() != s
    if needs_quote:
        return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return s


def _yaml_list(values: Iterable[Any]) -> str:
    values = list(values)
    if not values:
        return "[]"
    return "\n" + "\n".join(f"  - {_yaml_escape(v)}" for v in values)


def inject_front_matter(md: str, ctx: CleanerContext) -> str:
    probe = ctx.probe
    title = probe.title or ctx.output_stem
    author = probe.author or ""
    converted_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    source_file = ctx.source_docx.name

    tenc_links = ctx.report.get("hyperlink_cleaner", {}).get("tencent_doc_links", [])
    # We do NOT try to auto-guess the "source" URL yet — the first Tencent
    # Doc link in the body is often an unrelated cross-reference. Leave
    # empty for now; include the candidates as a YAML comment for the user.
    source_value = ""

    lines = ["---"]
    lines.append(f"title: {_yaml_escape(title)}")
    lines.append(f"source: {_yaml_escape(source_value)}")
    lines.append(f"converted_at: {converted_at}")
    lines.append(f"source_file: {_yaml_escape(source_file)}")
    lines.append("tags: []")
    lines.append(f"author: {_yaml_escape(author)}")
    lines.append("aliases: []")
    if tenc_links:
        lines.append("# tencent_doc_link_candidates (内部链接，供参考):")
        for url in tenc_links[:10]:
            lines.append(f"#   - {url}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")

    ctx.set_report(
        "front_matter",
        {
            "title": title,
            "author": author,
            "tencent_doc_link_candidates": tenc_links[:10],
        },
    )
    return "\n".join(lines) + md.lstrip("\n")
