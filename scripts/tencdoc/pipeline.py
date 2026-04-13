"""Cleaner pipeline orchestration.

A cleaner is any callable::

    def cleaner(md: str, ctx: CleanerContext) -> str: ...

It returns the new markdown. ``ctx.report[cleaner_name]`` is a free-form dict
where each cleaner records metrics so the final report can explain what
happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List

from .probe import DocxProbe


@dataclass
class CleanerContext:
    """Shared state + config threaded through the pipeline."""

    probe: DocxProbe
    output_md_path: Path
    output_stem: str
    attachments_dir_name: str
    attachments_abs_dir: Path
    source_docx: Path
    pandoc_media_dir: Path  # temp dir where pandoc extracted media
    image_files: List[Path] = field(default_factory=list)
    report: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def set_report(self, stage: str, data: Any) -> None:
        self.report[stage] = data


Cleaner = Callable[[str, CleanerContext], str]


def run_pipeline(
    md: str, ctx: CleanerContext, cleaners: List[Cleaner]
) -> str:
    for cleaner in cleaners:
        md = cleaner(md, ctx)
    return md
