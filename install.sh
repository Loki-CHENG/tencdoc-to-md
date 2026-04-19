#!/usr/bin/env bash
# tencdoc-to-md Chrome 扩展一键安装脚本
#
# 做三件事：
#   1. 注册 Native Messaging host manifest 到 Chrome / Edge / Brave / Arc
#   2. 把 ~/.config/tencdoc-to-md/config.yaml 里的 repo_dir 指向本仓库
#   3. 打印扩展加载步骤
#
# 用法：
#   ./install.sh                        # 交互式：提示填扩展 ID
#   ./install.sh <extension-id>         # 直接安装指定扩展 ID
#   ./install.sh --uninstall            # 卸载 host manifest
#
# 支持：macOS / Linux

set -euo pipefail

HOST_NAME="com.loki.tencdoc_to_md"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_SCRIPT="${REPO_DIR}/native-host/host.py"
LAUNCHER="${REPO_DIR}/native-host/host-launcher.sh"

# ─────────────────────────────────────────────────────────────────────────────
# 颜色
# ─────────────────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  CYAN='\033[36m'; GREEN='\033[32m'; YELLOW='\033[33m'; RED='\033[31m'; RESET='\033[0m'; BOLD='\033[1m'
else
  CYAN=''; GREEN=''; YELLOW=''; RED=''; RESET=''; BOLD=''
fi

log()   { printf "${CYAN}▸${RESET} %s\n" "$*"; }
ok()    { printf "${GREEN}✓${RESET} %s\n" "$*"; }
warn()  { printf "${YELLOW}!${RESET} %s\n" "$*"; }
fail()  { printf "${RED}✗${RESET} %s\n" "$*" >&2; exit 1; }

# ─────────────────────────────────────────────────────────────────────────────
# 定位各浏览器的 Native Messaging hosts 目录
# ─────────────────────────────────────────────────────────────────────────────
detect_host_dirs() {
  local os="$(uname -s)"
  local dirs=()
  case "$os" in
    Darwin)
      dirs+=("$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts")
      dirs+=("$HOME/Library/Application Support/Google/Chrome Canary/NativeMessagingHosts")
      dirs+=("$HOME/Library/Application Support/Chromium/NativeMessagingHosts")
      dirs+=("$HOME/Library/Application Support/Microsoft Edge/NativeMessagingHosts")
      dirs+=("$HOME/Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts")
      dirs+=("$HOME/Library/Application Support/Arc/User Data/NativeMessagingHosts")
      ;;
    Linux)
      dirs+=("$HOME/.config/google-chrome/NativeMessagingHosts")
      dirs+=("$HOME/.config/chromium/NativeMessagingHosts")
      dirs+=("$HOME/.config/microsoft-edge/NativeMessagingHosts")
      dirs+=("$HOME/.config/BraveSoftware/Brave-Browser/NativeMessagingHosts")
      ;;
    *)
      fail "不支持的操作系统：$os"
      ;;
  esac
  printf '%s\n' "${dirs[@]}"
}

# ─────────────────────────────────────────────────────────────────────────────
# 创建 launcher（因为 manifest 的 path 必须可执行，我们不直接指 .py，用一个 shell 包一层来锁定 python3）
# ─────────────────────────────────────────────────────────────────────────────
create_launcher() {
  cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
exec /usr/bin/env python3 "$HOST_SCRIPT" "\$@"
EOF
  chmod +x "$LAUNCHER"
  chmod +x "$HOST_SCRIPT"
  ok "launcher 已生成：$LAUNCHER"
}

# ─────────────────────────────────────────────────────────────────────────────
# 写 host manifest
# ─────────────────────────────────────────────────────────────────────────────
write_manifest() {
  local ext_id="$1"
  local manifest_json
  manifest_json=$(cat <<EOF
{
  "name": "$HOST_NAME",
  "description": "tencdoc-to-md native helper",
  "path": "$LAUNCHER",
  "type": "stdio",
  "allowed_origins": [
    "chrome-extension://$ext_id/"
  ]
}
EOF
)
  local any_written=0
  while IFS= read -r dir; do
    # 只写入实际浏览器装过的位置（父目录存在）
    local parent
    parent="$(dirname "$dir")"
    if [ ! -d "$parent" ]; then
      continue
    fi
    mkdir -p "$dir"
    printf '%s\n' "$manifest_json" > "$dir/${HOST_NAME}.json"
    ok "已写入：$dir/${HOST_NAME}.json"
    any_written=1
  done < <(detect_host_dirs)
  if [ "$any_written" -eq 0 ]; then
    warn "未发现任何 Chromium 系浏览器的目录；如果你用的是其他浏览器，请手动把上面 manifest 写到对应路径"
  fi
}

# ─────────────────────────────────────────────────────────────────────────────
# 更新本仓库配置 + 用户 config.yaml 里的 repo_dir
# ─────────────────────────────────────────────────────────────────────────────
update_user_config() {
  local user_cfg_dir="$HOME/.config/tencdoc-to-md"
  local user_cfg="$user_cfg_dir/config.yaml"
  mkdir -p "$user_cfg_dir"
  if [ -f "$user_cfg" ]; then
    # 替换或追加 repo_dir
    if grep -q "^repo_dir:" "$user_cfg"; then
      # 用 awk 替换更稳
      awk -v r="$REPO_DIR" '
        /^repo_dir:/ {print "repo_dir: " r; next}
        {print}
      ' "$user_cfg" > "$user_cfg.tmp" && mv "$user_cfg.tmp" "$user_cfg"
    else
      printf 'repo_dir: %s\n' "$REPO_DIR" >> "$user_cfg"
    fi
  else
    cat > "$user_cfg" <<EOF
# tencdoc-to-md 用户配置
# 由 install.sh 初始化；可用扩展 options 页面或直接编辑
repo_dir: $REPO_DIR
vault: ""
inbox: _tencdoc-inbox
output_dir: TencDocs
attachments_dir: ""
EOF
  fi
  ok "用户配置：$user_cfg（repo_dir = $REPO_DIR）"
}

# ─────────────────────────────────────────────────────────────────────────────
# 卸载
# ─────────────────────────────────────────────────────────────────────────────
uninstall() {
  while IFS= read -r dir; do
    local f="$dir/${HOST_NAME}.json"
    if [ -f "$f" ]; then
      rm -f "$f"
      ok "删除 $f"
    fi
  done < <(detect_host_dirs)
  rm -f "$LAUNCHER"
  ok "卸载完成（保留用户 config.yaml 以便下次重装）"
}

# ─────────────────────────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────────────────────────
main() {
  printf "${BOLD}TencDoc → Obsidian · 扩展安装器${RESET}\n\n"

  if [ "${1:-}" = "--uninstall" ]; then
    uninstall
    exit 0
  fi

  # 1. 依赖检查
  command -v python3 >/dev/null 2>&1 || fail "找不到 python3"
  command -v pandoc  >/dev/null 2>&1 || warn "pandoc 未安装；转换时会失败（brew install pandoc / apt install pandoc）"

  # 2. 扩展 ID
  local ext_id="${1:-}"
  if [ -z "$ext_id" ]; then
    cat <<'STEP'
请先在 Chrome / Edge / Brave / Arc 里加载扩展：
  1. 浏览器地址栏打开 chrome://extensions
  2. 右上角打开「开发者模式」
  3. 点「加载已解压的扩展程序」，选中本目录的 extension/ 文件夹
  4. 扩展列表里会显示一个 ID（32 个字母），复制下来

STEP
    read -r -p "$(printf "${CYAN}?${RESET} 扩展 ID：")" ext_id
  fi
  # 去掉前后空白（粘贴时容易带上）
  ext_id="$(printf '%s' "$ext_id" | tr -d '[:space:]')"
  # 统一小写；Chrome 生成的扩展 ID 只有 a-p 32 个字符，但宽容一点避免误杀
  ext_id="$(printf '%s' "$ext_id" | tr '[:upper:]' '[:lower:]')"
  if ! [[ "$ext_id" =~ ^[a-p]{32}$ ]]; then
    fail "扩展 ID 格式错误（应为 32 个 a-p 字母，可从 chrome://extensions 复制）：$ext_id"
  fi

  # 3. 创建 launcher
  create_launcher

  # 4. 写 host manifest 到所有浏览器
  write_manifest "$ext_id"

  # 5. 初始化用户 config
  update_user_config

  # 6. 最终提示
  cat <<STEP

${GREEN}${BOLD}安装完成 🎉${RESET}

接下来：
  1. 打开扩展的「设置」页面（点扩展图标 → 打开设置）
  2. 填写 Vault 根目录（绝对路径）
  3. 访问 https://doc.weixin.qq.com/ 打开任意一个你有导出权限的文档
  4. 右下角「→ Obsidian」按钮一键转换

如要卸载：
  ./install.sh --uninstall
STEP
}

main "$@"
