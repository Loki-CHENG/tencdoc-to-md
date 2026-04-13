"""Shared utilities for the tencdoc-to-md pipeline."""

from __future__ import annotations

import re
from pathlib import Path


# Filesystem-unfriendly characters across macOS / Windows / Linux / Obsidian.
_UNSAFE_CHARS = set(':/\\?*"<>|')


def normalize_filename(name: str) -> str:
    """Normalize a filename stem for cross-platform + Obsidian compatibility.

    Rules:
    - Replace any of ``: / \\ ? * " < > |`` with ``-``
    - Collapse any run of whitespace (incl. full-width) to a single space
    - Strip leading/trailing whitespace and dots
    - Preserve Chinese characters as-is
    """
    chars = []
    for ch in name:
        if ch in _UNSAFE_CHARS:
            chars.append("-")
        else:
            chars.append(ch)
    cleaned = "".join(chars)
    # Collapse whitespace (including Chinese full-width space \u3000)
    cleaned = re.sub(r"[\s\u3000]+", " ", cleaned)
    cleaned = cleaned.strip().strip(".").strip()
    # Collapse repeated dashes introduced by replacement
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned or "untitled"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
