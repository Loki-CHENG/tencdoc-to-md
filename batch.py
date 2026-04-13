#!/usr/bin/env python3
"""tencdoc-to-md 批量转换入口。

读取 config.yaml 中的 docx_dir / output_dir / attachments_dir，
将 docx_dir 下的所有 .docx 文件批量转换为 Obsidian Markdown。

用法：
    python batch.py                     # 读取 config.yaml，批量转换 docx_dir
    python batch.py --file 某文档.docx  # 只转换指定文件（路径相对于 docx_dir）
    python batch.py --force             # 覆盖已存在的输出
    python batch.py --dry-run           # 预览模式，不写文件

前提：
    1. 已安装 pandoc（python batch.py 会先检查）
    2. config.yaml 已配置（参考 config.example.yaml）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 把 scripts/ 加入路径，复用核心逻辑
_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT / "scripts"))

from convert import convert_one, _load_config, _resolve_path, _print_summary  # noqa: E402


def _check_pandoc() -> bool:
    import shutil
    return shutil.which("pandoc") is not None


def main() -> int:
    # ── 读取配置 ──────────────────────────────────────────────────────────────
    cfg = _load_config()

    docx_dir_raw = cfg.get("docx_dir", "")
    output_dir_raw = cfg.get("output_dir", "")
    attachments_dir_raw = cfg.get("attachments_dir", "")

    docx_dir = _resolve_path(docx_dir_raw)
    output_dir = _resolve_path(output_dir_raw)
    attachments_dir = _resolve_path(attachments_dir_raw)

    # ── CLI 参数 ───────────────────────────────────────────────────────────────
    ap = argparse.ArgumentParser(
        description="批量将腾讯文档 .docx 转换为 Obsidian Markdown",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--file", "-f",
        default=None,
        help="只转换指定文件（文件名或绝对路径）",
    )
    ap.add_argument("--force", action="store_true", help="覆盖已存在的输出")
    ap.add_argument("--dry-run", action="store_true", help="预览模式，不写入文件")
    ap.add_argument("--verbose", action="store_true", help="每个文件转换后输出完整 JSON 报告")
    args = ap.parse_args()

    # ── 前置检查 ───────────────────────────────────────────────────────────────
    if not _check_pandoc():
        print(
            "❌  未找到 pandoc，请先安装：\n"
            "    macOS:  brew install pandoc\n"
            "    Ubuntu: sudo apt install pandoc\n"
            "    详见：https://pandoc.org/installing.html",
            file=sys.stderr,
        )
        return 1

    if not docx_dir:
        print(
            "❌  未配置 docx_dir。\n"
            "    请复制 config.example.yaml → config.yaml，并填写 docx_dir 路径。",
            file=sys.stderr,
        )
        return 1

    if not docx_dir.exists():
        print(f"❌  docx_dir 目录不存在：{docx_dir}", file=sys.stderr)
        return 1

    if not output_dir:
        print(
            "❌  未配置 output_dir。\n"
            "    请在 config.yaml 中填写 output_dir 路径。",
            file=sys.stderr,
        )
        return 1

    # ── 确定要转换的文件列表 ───────────────────────────────────────────────────
    if args.file:
        target = Path(args.file)
        if not target.is_absolute():
            target = docx_dir / target
        target = target.expanduser().resolve()
        if not target.exists():
            print(f"❌  文件不存在：{target}", file=sys.stderr)
            return 1
        files = [target]
    else:
        files = sorted(docx_dir.glob("*.docx"))
        if not files:
            print(f"⚠️   {docx_dir} 下没有找到任何 .docx 文件", file=sys.stderr)
            return 0

    # ── 批量转换 ───────────────────────────────────────────────────────────────
    print(f"\n📂 来源目录：{docx_dir}")
    print(f"📁 输出目录：{output_dir}")
    if attachments_dir:
        print(f"🖼️  附件目录：{attachments_dir}  （全局附件库模式）")
    else:
        print(f"🖼️  附件目录：与 md 同级子目录  （默认模式）")
    print(f"📄 共 {len(files)} 个文件\n")

    results = []
    for docx in files:
        print(f"  转换中：{docx.name} ...", end="", flush=True)
        try:
            report = convert_one(
                docx=docx,
                output_dir=output_dir,
                attachments_dir=attachments_dir,
                force=args.force,
                dry_run=args.dry_run,
            )
            md_out = report["tencdoc_report"]["output_md"]
            img_count = report["tencdoc_report"]["image_count"]
            warns = report["tencdoc_report"]["warnings"]
            status = "✅"
            detail = f"{Path(md_out).name}  ({img_count} 张图片)"
            if warns:
                status = "⚠️ "
                detail += f"  [{len(warns)} 个警告]"
            results.append((docx.name, status, detail, None))
            print(f"\r  {status} {docx.name[:40]:<42} → {detail}")
        except FileExistsError as e:
            results.append((docx.name, "⏭️ ", "已存在，跳过（用 --force 覆盖）", None))
            print(f"\r  ⏭️  {docx.name[:40]:<42} 已存在，跳过")
        except Exception as e:
            results.append((docx.name, "❌", str(e), e))
            print(f"\r  ❌ {docx.name[:40]:<42} 失败：{e}")
            continue

        if args.verbose and results and results[-1][1] == "✅":
            import json
            print(json.dumps(report, ensure_ascii=False, indent=2))

    # ── 汇总 ───────────────────────────────────────────────────────────────────
    ok = sum(1 for *_, s, __ in results if s in ("✅", "⚠️ "))
    skipped = sum(1 for *_, s, __ in results if s == "⏭️ ")
    failed = sum(1 for *_, s, __ in results if s == "❌")

    print(f"\n{'─'*60}")
    print(f"完成 {ok} 个  跳过 {skipped} 个  失败 {failed} 个  共 {len(files)} 个")
    if args.dry_run:
        print("（dry-run 模式：未写入任何文件）")
    print(f"{'─'*60}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
