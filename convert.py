#!/usr/bin/env python3
"""单文件转换快捷入口（根目录）。

等价于：python scripts/convert.py <docx_path> [选项]

用法示例：
    python convert.py ~/Downloads/我的文档.docx
    python convert.py ~/Downloads/我的文档.docx --force
    python convert.py ~/Downloads/我的文档.docx --output-dir ~/ObsidianVault/TencDocs

完整选项说明请运行：python convert.py --help
"""

import sys
from pathlib import Path

# 将 scripts/ 加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))

from convert import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
