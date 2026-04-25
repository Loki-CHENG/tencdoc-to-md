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
# 视为「路径」的配置 key：保存/读取时都要做归一化（去 shell 转义）
_PATH_KEYS = {"vault", "output_dir", "attachments_dir", "repo_dir", "inbox"}


def normalize_path_input(value: str) -> str:
    """处理用户从终端复制来的带 shell 转义的路径。

    场景：用户在终端 `cd` 到 iCloud 目录，shell 把空格/`~` 转义成 `\\ ` / `\\~`，
    复制粘贴到扩展 options 页面后，原样进入 config.yaml。极简 YAML 解析器
    不会还原这些转义，导致后续 `os.path.expanduser` 把 `\\` 当作字面字符，
    创建出"幽灵目录"。

    本函数把：
        \\<space>  →  <space>
        \\~        →  ~
    并去掉首尾空白与残留引号。
    """
    if not value:
        return value
    s = str(value)
    # 处理常见 shell 转义。注意先处理 `\~` 再处理 `\ `，避免顺序敏感。
    s = s.replace("\\~", "~").replace("\\ ", " ")
    return s.strip().strip('"').strip("'")


def _yaml_load(text: str) -> dict:
    """极简 YAML 读取（只支持 key: value，避免强依赖 pyyaml）。

    对路径类字段额外做 shell 转义归一化，防止 `\\ ` / `\\~` 进入 Path()。
    """
    result = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line or ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k in _PATH_KEYS:
            v = normalize_path_input(v)
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
#  macOS TCC workaround
# ───────────────────────────────────────────────────────────────────────────
def _is_tcc_protected(path: str) -> bool:
    """是否落在 macOS TCC 保护目录（Downloads/Documents/Desktop）。

    这些目录下，Native host 继承 Chrome 的 TCC 上下文后无法直接读取。
    """
    real = os.path.realpath(os.path.expanduser(path))
    home = os.path.expanduser("~")
    for sub in ("Downloads", "Documents", "Desktop"):
        guarded = os.path.join(home, sub)
        if real == guarded or real.startswith(guarded + os.sep):
            return True
    return False


def _move_via_finder(src: str, dst_dir: Path) -> str | None:
    """通过 osascript 让 Finder 把文件移到非 TCC 目录，返回新路径。

    Finder 进程自己就有 Downloads 读权限，不会继承 Chrome 的 TCC。
    """
    src = os.path.realpath(src)
    dst_dir = Path(os.path.realpath(str(dst_dir)))
    dst_dir.mkdir(parents=True, exist_ok=True)
    target = dst_dir / Path(src).name

    # 若同名，加时间戳防冲突
    if target.exists():
        stem = target.stem
        suffix = target.suffix
        ts = int(time.time())
        target = dst_dir / f"{stem}.{ts}{suffix}"

    # AppleScript：tell Finder to move POSIX file X to POSIX file Y
    # 注意：Finder 的 "move" 如果 X 原位置就在 Y 的父目录，会拒绝；这里不会
    script = f'''
    tell application "Finder"
        set srcFile to POSIX file "{src}" as alias
        set dstFolder to POSIX file "{str(dst_dir)}" as alias
        move srcFile to dstFolder with replacing
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            # Finder 移动失败（可能因重名），降级尝试 ditto 工具 —— ditto 也走用户空间
            return _move_via_ditto(src, str(target))
        # Finder 移动成功时，目标文件名 = 源文件名（放到 dst_dir 下）
        moved_path = dst_dir / Path(src).name
        if moved_path.exists():
            return str(moved_path)
        # 如果被 Finder 自动重命名了，找最新的 docx
        cands = sorted(dst_dir.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
        return str(cands[0]) if cands else None
    except Exception:
        return _move_via_ditto(src, str(target))


def _move_via_ditto(src: str, dst: str) -> str | None:
    """ditto 是 macOS 系统拷贝工具，偶尔能绕过 TCC（特别是对同一 volume 内的 move）。

    作为 Finder 失败时的兜底。
    """
    try:
        proc = subprocess.run(
            ["ditto", src, dst],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0 and os.path.exists(dst):
            # ditto 是拷贝不是移动，拷贝成功后删掉源
            try:
                os.remove(src)
            except Exception:
                pass  # 删不掉也无所谓，有副本了
            return dst
    except Exception:
        pass
    return None


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
    warnings: list[str] = []
    for key in ("vault", "inbox", "output_dir", "attachments_dir"):
        if key not in msg:
            continue
        raw = msg[key]
        cleaned = normalize_path_input(raw) if key in _PATH_KEYS else raw
        # 提示用户：检测到了 shell 转义，已自动剥除
        if isinstance(raw, str) and ("\\ " in raw or "\\~" in raw):
            warnings.append(
                f"{key}: 检测到 shell 转义字符（\\空格 或 \\~），已自动归一化为 “{cleaned}”"
            )
        # vault 必须是绝对路径且实际存在；否则给个清晰提示而不是默默写入
        if key == "vault" and cleaned:
            expanded = os.path.expanduser(cleaned)
            if not os.path.isabs(expanded):
                warnings.append(f"vault 不是绝对路径：{cleaned}")
            elif not os.path.isdir(expanded):
                warnings.append(f"vault 目录不存在：{expanded}")
        # output_dir / attachments_dir 一般是相对 vault 的子路径；
        # 若以 vault 末段开头，提示重复嵌套（feedback §3.2 第四层）
        if key in ("output_dir", "attachments_dir") and cleaned:
            vault_val = normalize_path_input(msg.get("vault", cfg.get("vault", "")))
            if vault_val:
                vault_basename = os.path.basename(os.path.normpath(os.path.expanduser(vault_val)))
                if vault_basename and cleaned.split("/", 1)[0] == vault_basename:
                    warnings.append(
                        f"{key}: '{cleaned}' 以 vault 末段 '{vault_basename}' 开头，"
                        f"可能导致路径重复嵌套；{key} 应该是相对 vault 的子路径。"
                    )
        cfg[key] = cleaned
    path = save_config(cfg)
    resp: dict = {"ok": True, "cmd": "set_config", "path": str(path)}
    if warnings:
        resp["warnings"] = warnings
    return resp


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

    # macOS TCC 兼容：若直接读被拒（PermissionError），改走 Finder 把文件
    # 搬到非 TCC 目录再处理。如果用户已给 Chrome "完全磁盘访问"，这里直接
    # 读成功就跳过整个 workaround。
    if sys.platform == "darwin" and _is_tcc_protected(docx_path):
        try:
            # 探测一下：能不能读头几个字节？
            with open(docx_path, "rb") as _f:
                _f.read(4)
        except PermissionError:
            # 确实被 TCC 拒了，启用 Finder workaround
            tmp_dir = Path(repo_dir) / "tmp-downloads"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            moved = _move_via_finder(docx_path, tmp_dir)
            if moved and os.path.exists(moved):
                docx_path = moved
            # 如果搬不动，下面 convert.py 启动时会再次暴露错误

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

    # macOS/Linux GUI 启动的子进程 PATH 很窄（通常只有 /usr/bin:/bin:/usr/sbin:/sbin），
    # 看不到 Homebrew (/usr/local/bin、/opt/homebrew/bin) 里的 pandoc 等工具。
    # 这里把常见路径并入 PATH。
    extra_paths = [
        "/usr/local/bin",      # Intel Mac Homebrew
        "/opt/homebrew/bin",   # Apple Silicon Homebrew
        "/opt/homebrew/sbin",
        "/usr/local/sbin",
    ]
    cur_path = env.get("PATH", "")
    path_parts = cur_path.split(os.pathsep) if cur_path else []
    for p in extra_paths:
        if p not in path_parts and os.path.isdir(p):
            path_parts.insert(0, p)
    env["PATH"] = os.pathsep.join(path_parts)

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


def cmd_doctor(_msg: dict) -> dict:
    """健康检查：一次返回所有关键环境信息，方便 UI 侧排障。

    检查项：
      - host 版本、Python 版本、平台
      - 配置是否存在、关键字段是否填了
      - repo_dir 和 convert.py 是否存在
      - pandoc 是否能在增强 PATH 下找到
      - macOS 下 Chrome 是否对 ~/Downloads 有 Full Disk Access（通过尝试读探测）
    """
    report: dict = {
        "ok": True,
        "cmd": "doctor",
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "checks": [],
    }

    def add(name: str, passed: bool, detail: str = "") -> None:
        report["checks"].append({"name": name, "ok": passed, "detail": detail})
        if not passed:
            report["ok"] = False

    # 1. config
    cfg = load_config()
    add("config.yaml 存在", CONFIG_FILE.exists(), str(CONFIG_FILE))
    add("repo_dir 已设置", bool(cfg.get("repo_dir")), cfg.get("repo_dir", "(空)"))
    add("vault 已设置", bool(cfg.get("vault")), cfg.get("vault", "(空)"))

    # 2. repo & convert.py
    repo_dir = cfg.get("repo_dir", "")
    if repo_dir:
        add("repo_dir 目录存在", Path(repo_dir).exists(), repo_dir)
        cp = Path(repo_dir) / "convert.py"
        add("convert.py 存在", cp.exists(), str(cp))

    # 3. pandoc
    env_path_parts = (os.environ.get("PATH", "") or "").split(os.pathsep)
    for p in ("/usr/local/bin", "/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/sbin"):
        if p not in env_path_parts and os.path.isdir(p):
            env_path_parts.insert(0, p)
    pandoc_path = ""
    for p in env_path_parts:
        cand = os.path.join(p, "pandoc")
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            pandoc_path = cand
            break
    add("pandoc 可执行", bool(pandoc_path), pandoc_path or "(未找到)")

    # 4. macOS Full Disk Access —— 试读 ~/Downloads 下任意文件
    if sys.platform == "darwin":
        dl = Path(os.path.expanduser("~/Downloads"))
        if dl.exists():
            try:
                items = list(dl.iterdir())
                # 只要能列目录就说明有权限（TCC 拦的不是 stat 是 open）；进一步 open 任意一个
                can_read = True
                sample = ""
                for it in items:
                    if it.is_file():
                        try:
                            with open(it, "rb") as f:
                                f.read(4)
                            sample = str(it)
                            break
                        except PermissionError:
                            can_read = False
                            sample = str(it)
                            break
                        except Exception:
                            continue
                add(
                    "Chrome 对 ~/Downloads 有读权限",
                    can_read,
                    sample or "(目录为空，无法确认)",
                )
            except PermissionError:
                add("Chrome 对 ~/Downloads 有读权限", False, "列目录失败")

    return report


HANDLERS = {
    "ping": cmd_ping,
    "get_config": cmd_get_config,
    "set_config": cmd_set_config,
    "convert": cmd_convert,
    "doctor": cmd_doctor,
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
