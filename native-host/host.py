#!/usr/bin/env python3
"""tencdoc-to-md Native Messaging host.

协议：
    stdin  ← Chrome：4 字节小端长度 + JSON
    stdout → Chrome：4 字节小端长度 + JSON

支持命令：
    {"cmd": "ping"}                                    → {"ok": true, "version": "..."}
    {"cmd": "get_config"}                              → {"ok": true, "vault": "...", "inbox": "...",
                                                           "output_dir": "...", "attachments_dir": "..."}
    {"cmd": "set_config", "vault": "...", ...}         → {"ok": true, "path": "~/.config/..."}
    {"cmd": "convert", "docx_path": "...",
       "source_url": "...", "doc_title": "..."}        → {"ok": true, "md_path": "...", "duration_ms": N}

配置文件位置：~/.config/tencdoc-to-md/config.yaml
转换逻辑：复用项目根目录下的 convert.py（由 install.sh 把仓库路径记录到 config.yaml 的 repo_dir 字段）
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import time
import traceback
from pathlib import Path

__version__ = "0.6.0"

CONFIG_DIR = Path(os.path.expanduser("~/.config/tencdoc-to-md"))
CONFIG_FILE = CONFIG_DIR / "config.yaml"


# ───────────────────────────────────────────────────────────────────────────
#  Native Messaging I/O
# ───────────────────────────────────────────────────────────────────────────
def read_message():
    raw_len = sys.stdin.buffer.read(4)
    if len(raw_len) != 4:
        return None
    msg_len = struct.unpack("<I", raw_len)[0]
    raw = sys.stdin.buffer.read(msg_len)
    if len(raw) != msg_len:
        return None
    return json.loads(raw.decode("utf-8"))


def send_message(msg: dict) -> None:
    data = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


# ───────────────────────────────────────────────────────────────────────────
#  Config
# ───────────────────────────────────────────────────────────────────────────
def _yaml_load(text: str) -> dict:
    """极简 YAML 读取（只支持 key: value，避免强依赖 pyyaml）。"""
    result = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line or ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        result[k] = v
    return result


def _yaml_dump(cfg: dict) -> str:
    lines = ["# tencdoc-to-md config — 由扩展 options 页面或 install.sh 写入"]
    for k, v in cfg.items():
        if v is None:
            v = ""
        # 值里有空格或冒号就加引号
        sv = str(v)
        if any(c in sv for c in ' :#"\'\\'):
            sv = '"' + sv.replace('"', '\\"') + '"'
        lines.append(f"{k}: {sv}")
    return "\n".join(lines) + "\n"


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return _yaml_load(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(_yaml_dump(cfg), encoding="utf-8")
    return CONFIG_FILE


def resolve_path(p: str, base: str | None = None) -> str:
    """把 ~ 展开；相对路径相对 base 解析。"""
    if not p:
        return ""
    p = os.path.expanduser(p)
    if not os.path.isabs(p) and base:
        p = os.path.join(os.path.expanduser(base), p)
    return p


# ───────────────────────────────────────────────────────────────────────────
#  命令实现
# ───────────────────────────────────────────────────────────────────────────
def cmd_ping(_msg: dict) -> dict:
    return {"ok": True, "cmd": "ping", "version": __version__}


def cmd_get_config(_msg: dict) -> dict:
    cfg = load_config()
    return {
        "ok": True,
        "cmd": "get_config",
        "vault": cfg.get("vault", ""),
        "inbox": cfg.get("inbox", "_tencdoc-inbox"),
        "output_dir": cfg.get("output_dir", "TencDocs"),
        "attachments_dir": cfg.get("attachments_dir", ""),
        "repo_dir": cfg.get("repo_dir", ""),
    }


def cmd_set_config(msg: dict) -> dict:
    cfg = load_config()
    for key in ("vault", "inbox", "output_dir", "attachments_dir"):
        if key in msg:
            cfg[key] = msg[key]
    path = save_config(cfg)
    return {"ok": True, "cmd": "set_config", "path": str(path)}


def cmd_convert(msg: dict) -> dict:
    start = time.time()
    cfg = load_config()

    repo_dir = cfg.get("repo_dir", "")
    if not repo_dir or not Path(repo_dir).exists():
        raise RuntimeError(
            "配置里没有 repo_dir（指向 tencdoc-to-md 克隆的位置）。请重跑 install.sh。"
        )
    convert_py = Path(repo_dir) / "convert.py"
    if not convert_py.exists():
        raise RuntimeError(f"找不到 {convert_py}")

    vault = resolve_path(cfg.get("vault", ""))
    if not vault:
        raise RuntimeError("vault 未配置，请到扩展 options 页面填写")

    output_dir = resolve_path(cfg.get("output_dir", "TencDocs"), base=vault)
    attachments_dir = cfg.get("attachments_dir", "").strip()
    if attachments_dir:
        attachments_dir = resolve_path(attachments_dir, base=vault)

    docx_path = msg.get("docx_path")
    if not docx_path:
        raise RuntimeError("缺少 docx_path")
    docx_path = os.path.expanduser(docx_path)
    if not os.path.exists(docx_path):
        raise RuntimeError(f"docx 文件不存在：{docx_path}")

    cmd = [
        sys.executable,
        str(convert_py),
        docx_path,
        "--output-dir",
        output_dir,
        "--force",
        "--verbose",
    ]
    if attachments_dir:
        cmd += ["--attachments-dir", attachments_dir]

    env = os.environ.copy()
    # convert.py 可能会尝试读 config.yaml；我们让它看到 repo_dir 下那份
    env["TENCDOC_CONFIG"] = str(Path(repo_dir) / "config.yaml")

    proc = subprocess.run(
        cmd, capture_output=True, text=True, env=env, cwd=repo_dir
    )
    duration_ms = int((time.time() - start) * 1000)
    if proc.returncode != 0:
        raise RuntimeError(
            f"convert.py 返回 {proc.returncode}\nstderr:\n{proc.stderr[-2000:]}"
        )

    # 解析 stderr 里的 JSON 报告（--verbose 会输出到 stderr）
    md_path = None
    for line in reversed(proc.stderr.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                report = json.loads(line)
                md_path = report.get("md_path") or report.get("output_md")
                break
            except Exception:
                pass

    return {
        "ok": True,
        "cmd": "convert",
        "md_path": md_path or "",
        "duration_ms": duration_ms,
        "stdout_tail": proc.stdout[-400:],
    }


HANDLERS = {
    "ping": cmd_ping,
    "get_config": cmd_get_config,
    "set_config": cmd_set_config,
    "convert": cmd_convert,
}


# ───────────────────────────────────────────────────────────────────────────
#  主循环
# ───────────────────────────────────────────────────────────────────────────
def main() -> int:
    try:
        msg = read_message()
        if msg is None:
            return 0
        cmd = msg.get("cmd")
        handler = HANDLERS.get(cmd)
        if not handler:
            send_message({"ok": False, "cmd": cmd, "error": f"unknown cmd: {cmd}"})
            return 0
        try:
            resp = handler(msg)
        except Exception as e:
            send_message(
                {
                    "ok": False,
                    "cmd": cmd,
                    "error": str(e),
                    "detail": traceback.format_exc()[-1500:],
                }
            )
            return 0
        send_message(resp)
        return 0
    except Exception as e:
        # 尽可能把 fatal 错误也送回
        try:
            send_message({"ok": False, "error": f"fatal: {e}"})
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
