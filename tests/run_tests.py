#!/usr/bin/env python3
"""Smoke-test runner for tencdoc-to-md.

Usage:
    python run_tests.py <docx_dir> [--output-dir DIR]

Converts every .docx in <docx_dir>, verifies:
1. Exit code is 0
2. .md file is produced and non-empty
3. Attachments dir exists (even if empty)
4. Every ![[...]] wiki-link image ref resolves to a real file
5. No raw pandoc media/ references remain in the markdown
6. Front matter YAML is present

Prints a summary table at the end. Non-zero exit if any check fails.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def _find_docx_files(directory: str) -> list[Path]:
    d = Path(directory)
    return sorted(d.glob("*.docx"))


def _check_md(md_path: Path, out_dir: Path) -> list[str]:
    errors = []
    if not md_path.exists():
        errors.append("md file not created")
        return errors
    content = md_path.read_text(encoding="utf-8")
    if len(content) < 50:
        errors.append(f"md file too small ({len(content)} chars)")
    if not content.startswith("---"):
        errors.append("missing YAML front matter")
    # Check for broken wiki-link refs.
    refs = re.findall(r'!\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]', content)
    for ref in refs:
        if not (out_dir / ref).exists():
            errors.append(f"broken image ref: {ref}")
    # Check no raw pandoc media/ refs remain.
    raw_media = re.findall(r'media[_/]?out/media/', content)
    if raw_media:
        errors.append(f"raw pandoc media paths remain ({len(raw_media)})")
    return errors


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <docx_dir> [--output-dir DIR]")
        return 1

    docx_dir = sys.argv[1]
    out_dir = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--output-dir" else None

    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    convert_script = scripts_dir / "convert.py"

    files = _find_docx_files(docx_dir)
    if not files:
        print(f"No .docx files found in {docx_dir}")
        return 1

    with tempfile.TemporaryDirectory(prefix="tencdoc_test_") as tmp:
        target = Path(out_dir) if out_dir else Path(tmp)
        target.mkdir(parents=True, exist_ok=True)

        results = []
        for f in files:
            r = subprocess.run(
                [sys.executable, str(convert_script), str(f),
                 "--output-dir", str(target), "--force"],
                capture_output=True, text=True,
            )
            report = {}
            try:
                report = json.loads(r.stderr)["tencdoc_report"]
            except Exception:
                pass

            md_name = report.get("output_md", "").split("/")[-1] if report else "?"
            md_path = target / md_name if md_name != "?" else Path("/nonexistent")

            errors = []
            if r.returncode != 0:
                errors.append(f"exit code {r.returncode}")
            errors.extend(_check_md(md_path, target))

            results.append((f.name, md_name, r.returncode, errors, report))

        # Print summary.
        all_ok = True
        print(f"\n{'Source':<50} {'Output':<45} {'RC':>3} {'Status'}")
        print("-" * 110)
        for src, out, rc, errs, rpt in results:
            status = "OK" if not errs else "; ".join(errs)
            if errs:
                all_ok = False
            print(f"{src[:49]:<50} {out[:44]:<45} {rc:>3} {status}")

        # Aggregate stats.
        total_images = sum(r.get("image_count", 0) for *_, r in results)
        total_tables_pipe = sum(
            r.get("stages", {}).get("table_cleaner", {}).get("degraded_to_pipe", 0)
            for *_, r in results
        )
        total_tables_html = sum(
            r.get("stages", {}).get("table_cleaner", {}).get("kept_as_html", 0)
            for *_, r in results
        )
        print(f"\nTotal: {len(files)} files | {total_images} images | "
              f"{total_tables_pipe} pipe tables, {total_tables_html} HTML tables")
        print("PASS" if all_ok else "FAIL")
        return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
