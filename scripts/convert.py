#!/usr/bin/env python3
"""tencdoc-to-md: convert a Tencent Docs (WeCom) docx export into an
Obsidian-friendly markdown file with a sibling attachments folder.

Usage::

    python convert.py <docx_path> [--output-dir DIR] [--attachments-dir DIR]
                                  [--dry-run] [--keep-pandoc-media] [--force]

配置文件（可选）：
    在脚本同目录或项目根目录放置 config.yaml，可预设 output_dir / attachments_dir。
    命令行参数优先级 > config.yaml > 默认值。

Exit codes:
    0  — success
    1  — user-facing error (missing input, pandoc not installed, etc.)
    2  — internal error
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Make the ``tencdoc`` package importable when this script is run directly.
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent  # 项目根目录（tencdoc-to-md/）
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from tencdoc.pipeline import CleanerContext, run_pipeline  # noqa: E402
from tencdoc.probe import probe_docx  # noqa: E402
from tencdoc.preprocess import preprocess_docx  # noqa: E402
from tencdoc.utils import ensure_dir, normalize_filename, write_text  # noqa: E402
from tencdoc.cleaners.image_rewriter import rewrite_images  # noqa: E402
from tencdoc.cleaners.heading_normalizer import normalize_headings  # noqa: E402
from tencdoc.cleaners.table_cleaner import clean_tables  # noqa: E402
from tencdoc.cleaners.hyperlink_cleaner import clean_hyperlinks  # noqa: E402
from tencdoc.cleaners.list_squeezer import squeeze_lists  # noqa: E402
from tencdoc.cleaners.front_matter import inject_front_matter  # noqa: E402
from tencdoc.cleaners.inline_formatter import clean_inline_formats  # noqa: E402


CLEANERS = [
    rewrite_images,
    normalize_headings,
    clean_inline_formats,   # underline / highlight sentinels → HTML tags
    clean_tables,
    clean_hyperlinks,
    squeeze_lists,
    inject_front_matter,
]


# --------------------------------------------------------------------------- #
# 配置文件读取
# --------------------------------------------------------------------------- #

def _load_config() -> dict:
    """读取项目根目录的 config.yaml，找不到或格式错误时静默返回空字典。"""
    try:
        import yaml  # pyyaml
    except ImportError:
        return {}

    for candidate in [_ROOT / "config.yaml", _HERE / "config.yaml"]:
        if candidate.exists():
            try:
                with open(candidate, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                return data
            except Exception:
                pass
    return {}


def _resolve_path(value: str | None) -> Path | None:
    """将字符串路径（含 ~）解析为绝对 Path，空字符串或 None 返回 None。"""
    if not value:
        return None
    return Path(value).expanduser().resolve()


# --------------------------------------------------------------------------- #
# 核心转换函数（供 batch.py 调用）
# --------------------------------------------------------------------------- #

def convert_one(
    docx: Path,
    output_dir: Path,
    attachments_dir: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
    keep_pandoc_media: bool = False,
) -> dict:
    """转换单个 docx 文件，返回 report 字典。

    Args:
        docx:             输入 .docx 路径（已解析为绝对路径）
        output_dir:       .md 文件写入目录
        attachments_dir:  全局附件根目录；None 表示使用 output_dir/stem/ 同级模式
        force:            覆盖已存在的输出
        dry_run:          只跑流水线，不落盘
        keep_pandoc_media: 保留 pandoc 原始 media 目录（调试用）
    """
    ensure_dir(output_dir)

    probe = probe_docx(docx)
    stem = normalize_filename(probe.title or docx.stem)

    md_path = output_dir / f"{stem}.md"

    # 决定附件目录：全局模式 or 同级子目录模式
    if attachments_dir:
        # 全局附件库：attachments_dir/<stem>/
        attachments_abs = attachments_dir / stem
        # wiki-link 中用相对 Obsidian 路径：<stem>/imageN.ext
        attachments_dir_name = stem
    else:
        # 同级模式：output_dir/<stem>/
        attachments_abs = output_dir / stem
        attachments_dir_name = stem

    if md_path.exists() and not force and not dry_run:
        raise FileExistsError(
            f"输出已存在：{md_path}\n使用 --force 覆盖，或 batch.py 中设置 force=True"
        )

    preprocessed_docx, preprocess_fixed, pre_ul, pre_hl, pre_cl = preprocess_docx(docx, probe)
    _preprocessed_tmp = preprocessed_docx.parent if preprocessed_docx != docx else None

    with tempfile.TemporaryDirectory(prefix="tencdoc_") as tmp:
        tmp_path = Path(tmp)
        media_out = tmp_path / "media_out"
        raw_md = _run_pandoc(preprocessed_docx, media_out)

        ctx = CleanerContext(
            probe=probe,
            output_md_path=md_path,
            output_stem=stem,
            attachments_dir_name=attachments_dir_name,
            attachments_abs_dir=attachments_abs,
            source_docx=docx,
            pandoc_media_dir=media_out,
        )

        md = run_pipeline(raw_md, ctx, CLEANERS)

        if not dry_run:
            ensure_dir(attachments_abs)
            ctx.image_files = _copy_images(media_out, attachments_abs)
            write_text(md_path, md)

        if keep_pandoc_media and not dry_run:
            debug_copy = output_dir / f"{stem}.pandoc-media-debug"
            if debug_copy.exists():
                shutil.rmtree(debug_copy)
            shutil.copytree(media_out, debug_copy)

    if _preprocessed_tmp and _preprocessed_tmp.exists():
        shutil.rmtree(_preprocessed_tmp, ignore_errors=True)

    report = _build_report(ctx)
    report["tencdoc_report"]["stages"]["preprocess"] = {
        "heading_numpr_stripped": preprocess_fixed,
        "underline_runs_injected": pre_ul,
        "highlight_runs_injected": pre_hl,
        "colour_runs_injected": pre_cl,
    }
    return report


# --------------------------------------------------------------------------- #
# 内部工具函数
# --------------------------------------------------------------------------- #

def _run_pandoc(docx: Path, media_out: Path) -> str:
    cmd = [
        "pandoc",
        str(docx),
        "-f", "docx",
        "-t", "gfm",
        "--wrap=none",
        f"--extract-media={media_out}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        raise SystemExit(
            "ERROR: pandoc 未找到。请先安装 pandoc：\n"
            "  macOS:  brew install pandoc\n"
            "  Ubuntu: sudo apt install pandoc\n"
            "  详见：https://pandoc.org/installing.html"
        )
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"ERROR: pandoc 执行失败（{e.returncode}）:\n{e.stderr}")
    return result.stdout


def _copy_images(media_out: Path, dest: Path) -> list[Path]:
    """Copy all pandoc-extracted media files into the attachments dir."""
    if not media_out.exists():
        return []
    copied: list[Path] = []
    for item in sorted(media_out.rglob("*")):
        if not item.is_file():
            continue
        target = dest / item.name
        shutil.copy2(item, target)
        copied.append(target)
    return copied


def _build_report(ctx: CleanerContext) -> dict:
    return {
        "tencdoc_report": {
            "version": "0.1.0",
            "source_docx": str(ctx.source_docx),
            "output_md": str(ctx.output_md_path),
            "attachments_dir": str(ctx.attachments_abs_dir),
            "probe": ctx.probe.summary(),
            "stages": ctx.report,
            "warnings": ctx.warnings,
            "image_count": len(ctx.image_files),
        }
    }


# --------------------------------------------------------------------------- #
# CLI 入口
# --------------------------------------------------------------------------- #

def main() -> int:
    cfg = _load_config()

    ap = argparse.ArgumentParser(
        description="将腾讯文档 (WeCom) 的 .docx 转换为 Obsidian Markdown",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("docx_path", help="输入的 .docx 文件路径")
    ap.add_argument(
        "--output-dir", "-o",
        default=None,
        help="Markdown 文件输出目录（默认：config.yaml 中的 output_dir，或 docx 所在目录）",
    )
    ap.add_argument(
        "--attachments-dir",
        default=None,
        help="全局附件根目录（默认：config.yaml 中的 attachments_dir，或 output_dir/<stem>/）",
    )
    ap.add_argument("--dry-run", action="store_true", help="预览模式，不写入文件")
    ap.add_argument("--keep-pandoc-media", action="store_true", help="保留 pandoc 原始 media 目录（调试用）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的输出文件")
    args = ap.parse_args()

    docx = Path(args.docx_path).expanduser().resolve()
    if not docx.exists() or docx.suffix.lower() != ".docx":
        print(f"ERROR: 不是有效的 .docx 文件：{docx}", file=sys.stderr)
        return 1

    # 路径优先级：CLI 参数 > config.yaml > 默认值
    output_dir = (
        _resolve_path(args.output_dir)
        or _resolve_path(cfg.get("output_dir"))
        or docx.parent
    )
    attachments_dir = (
        _resolve_path(args.attachments_dir)
        or _resolve_path(cfg.get("attachments_dir"))
    )

    try:
        report = convert_one(
            docx=docx,
            output_dir=output_dir,
            attachments_dir=attachments_dir,
            force=args.force,
            dry_run=args.dry_run,
            keep_pandoc_media=args.keep_pandoc_media,
        )
    except FileExistsError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    md_path = report["tencdoc_report"]["output_md"]
    if args.dry_run:
        print("[dry-run] 预览完成，未写入文件")
    else:
        print(f"已生成：{md_path}")

    print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
