#!/usr/bin/env python3
"""Pre-flight dependency check for tencdoc-to-md.

Validates:
- Python >= 3.8
- pandoc >= 2.9 on PATH
- python-docx (optional, used by probe for fallback)

Exit 0 = all good. Exit 1 = missing critical dep with install instructions.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import re
from typing import Tuple, Optional


def _python_version_ok() -> bool:
    return sys.version_info >= (3, 8)


def _pandoc_version() -> Optional[str]:
    path = shutil.which("pandoc")
    if not path:
        return None
    try:
        out = subprocess.run(
            ["pandoc", "--version"], capture_output=True, text=True, timeout=10
        )
        m = re.search(r"pandoc\s+([\d.]+)", out.stdout)
        return m.group(1) if m else "unknown"
    except Exception:
        return None


def _parse_ver(ver: str) -> Tuple[int, ...]:
    return tuple(int(x) for x in ver.split(".") if x.isdigit())


def main() -> int:
    ok = True
    print(f"Python: {sys.version}")
    if not _python_version_ok():
        print("  [FAIL] Python >= 3.8 required.")
        ok = False
    else:
        print("  [OK]")

    ver = _pandoc_version()
    if ver is None:
        print("pandoc: NOT FOUND")
        print("  [FAIL] pandoc is required. Install:")
        print("    macOS  : brew install pandoc")
        print("    Ubuntu : sudo apt install pandoc")
        print("    Windows: choco install pandoc  OR  https://pandoc.org/installing.html")
        ok = False
    else:
        print(f"pandoc: {ver}")
        if _parse_ver(ver) < (2, 9):
            print(f"  [WARN] pandoc >= 2.9 recommended (you have {ver}).")
        else:
            print("  [OK]")

    # Optional: python-docx
    try:
        import docx  # noqa: F401
        print("python-docx: installed")
        print("  [OK]")
    except ImportError:
        print("python-docx: not installed (optional)")
        print("  [INFO] pip install python-docx  — needed only for advanced probe fallback.")

    if ok:
        print("\nAll critical dependencies satisfied.")
        return 0
    else:
        print("\nSome critical dependencies are missing. Please install them before running convert.py.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
