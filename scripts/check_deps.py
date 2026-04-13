#!/usr/bin/env python3
"""Pre-flight dependency check for tencdoc-to-md.

Validates:
- Python >= 3.8
- pandoc >= 2.9 on PATH
- pyyaml (required for config.yaml reading)
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

    # ── Python ──────────────────────────────────────────────────────────────
    print(f"Python: {sys.version.split()[0]}")
    if not _python_version_ok():
        print("  [FAIL] 需要 Python >= 3.8")
        ok = False
    else:
        print("  [OK]")

    # ── pandoc ──────────────────────────────────────────────────────────────
    ver = _pandoc_version()
    if ver is None:
        print("pandoc: 未安装")
        print("  [FAIL] pandoc 是必需依赖，请安装：")
        print("    macOS  : brew install pandoc")
        print("    Ubuntu : sudo apt install pandoc")
        print("    Windows: https://pandoc.org/installing.html")
        ok = False
    else:
        print(f"pandoc: {ver}")
        if _parse_ver(ver) < (2, 9):
            print(f"  [WARN] 建议 pandoc >= 2.9（当前 {ver}），可能影响转换质量")
        else:
            print("  [OK]")

    # ── pyyaml（必需，用于读取 config.yaml）────────────────────────────────
    try:
        import yaml
        ver_yaml = getattr(yaml, "__version__", "unknown")
        print(f"pyyaml: {ver_yaml}")
        print("  [OK]")
    except ImportError:
        print("pyyaml: 未安装")
        print("  [FAIL] pyyaml 是必需依赖（读取 config.yaml 配置文件）")
        print("    安装命令：")
        print("    macOS/Linux : python3 -m pip install pyyaml --user --break-system-packages")
        print("    Windows     : pip install pyyaml")
        ok = False

    # ── python-docx（可选）─────────────────────────────────────────────────
    try:
        import docx  # noqa: F401
        print("python-docx: 已安装")
        print("  [OK]")
    except ImportError:
        print("python-docx: 未安装（可选）")
        print("  [INFO] 可选依赖，缺少时 probe 会自动降级")
        print("    安装命令：python3 -m pip install python-docx --user --break-system-packages")

    # ── 结论 ────────────────────────────────────────────────────────────────
    print()
    if ok:
        print("✅  所有必需依赖已满足，可以开始使用。")
        return 0
    else:
        print("❌  存在缺失的必需依赖，请按上面的提示安装后重试。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
