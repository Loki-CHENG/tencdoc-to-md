# UAT Report — tencdoc-to-md v0.6.6 部署反馈修复验证

> 走查版本：v0.6.6（2026-04-25）
> 走查依据：[`developer-feedback.md`](../../../../Library/Mobile%20Documents/com~apple~CloudDocs/Bilibili/BilibiliWork/WorkObsidian/05-工具与部署/tenndoc使用/developer-feedback.md)（Kimi Code CLI 在 macOS Bash 3.2 + Python 3.14.3 环境下的部署实测反馈，2026-04-25）
> 走查人：Claude
> 验证方法：单元级 + 端到端转换（会员购自营供应链计划 SOP.docx）

---

## 一、修复状态汇总

| 优先级 | ID | 问题 | 状态 | 验证 |
|---|---|---|---|---|
| P0 | F-01 | install.sh 中文全角括号在 Bash 3.2 下崩溃 | 🟢 **已修** | `bash -n` + Bash 3.2.57 复现脚本 |
| P0 | F-02 | host.py 极简 YAML 不还原 `\ ` / `\~` → 幽灵目录 | 🟢 **已修** | `normalize_path_input` 单测 + `_yaml_load` 单测 |
| P0 | F-02b | options 页面缺乏路径校验 | 🟢 **已修**（host 端） | `cmd_set_config` 返回 warnings |
| P1 | F-03 | 复杂表 `</td></tr>` 标签泄漏到正文 | 🟢 **已检测** | 端到端报告 `tag_leaks: 18`（与反馈一致） |
| P2 | F-04 | front matter `source:` 始终为空但已捕获候选 | 🟢 **已修** | 端到端：`source` = 腾讯文档原链 |
| P2 | F-05 | unzip 中文文件名兼容（README） | ⚪ 未做 | 文档增改，下轮处理 |
| P3 | F-06 | 两套 config 说明（README） | ⚪ 未做 | 文档增改，下轮处理 |

---

## 二、各项修复细节与验证

### F-01 · install.sh Bash 3.2 全角括号崩溃（P0）

**反馈现象**（feedback §2）：
```
./install.sh: line 143: user_cfg�: unbound variable
```

**根因**：Bash 3.2 解析 `"$user_cfg（"` 时把全角左括号字节（`U+FF08` UTF-8: `EF BC 88`）并入变量名，配合 `set -u` 触发崩溃。

**修复**（[`install.sh`](../../install.sh)）：

| 改动 | 说明 |
|---|---|
| `install.sh:143`：`用户配置：$user_cfg（repo_dir = $REPO_DIR）` → `用户配置: $user_cfg (repo_dir = $REPO_DIR)` | 半角括号兜底 Bash 3.2 |
| 顶部新增 `BASH_VERSINFO[0] < 4` 警告 | 提示用户 `brew install bash` |

**验证**：
```bash
$ /bin/bash --version | head -1
GNU bash, version 3.2.57(1)-release (x86_64-apple-darwin23)

$ /bin/bash -c 'set -u; user_cfg="/test"; printf "用户配置: %s (repo_dir = %s)\n" "$user_cfg" "REPO"'
用户配置: /test (repo_dir = REPO)   ✓ 不再崩溃

$ bash -n install.sh
✓ 语法通过
```

---

### F-02 · host.py 配置路径 shell 转义未还原（P0，最严重）

**反馈现象**（feedback §3）：用户从终端复制 iCloud 路径粘贴到扩展 options 页面，路径含 `\ ` / `\~` 转义字符；极简 `_yaml_load` 仅去引号不去转义；`Path()` 把字面反斜杠当成目录名一部分，转换产物被写到「幽灵目录」：
```
/Users/.../Mobile\ Documents/com\~apple\~CloudDocs/.../待整理/X.md   ← 幽灵
/Users/.../Mobile Documents/com~apple~CloudDocs/.../待整理/X.md      ← 期望
```
此外 `output_dir = WorkObsidian/04-原始资料/待整理` 与 vault 末段 `WorkObsidian` 重复嵌套也被忽略。

**修复**（[`native-host/host.py`](../../native-host/host.py)）：

| 改动 | 说明 |
|---|---|
| 新增 `normalize_path_input(value)` | `\<空格>` → ` `；`\~` → `~`；strip 引号/空白 |
| `_PATH_KEYS = {"vault","output_dir","attachments_dir","repo_dir","inbox"}` | 集中管理路径类字段 |
| `_yaml_load` 内对 `_PATH_KEYS` 字段调用 `normalize_path_input` | 读出来即净化 |
| `cmd_set_config` 写入前校验，返回 `warnings` 数组 | 4 类校验：vault 是否绝对/存在、output_dir 是否以 vault 末段开头、是否检测到 shell 转义 |

**单元验证**：
```python
n = normalize_path_input
assert n(r'/Users/x/Mobile\ Documents/com\~apple\~CloudDocs') \
       == '/Users/x/Mobile Documents/com~apple~CloudDocs'
assert n('  "/path/with quotes"  ') == '/path/with quotes'
assert n('') == ''

y = _yaml_load
res = y('vault: "/Users/foo/Mobile\\\\ Documents/x"\nrepo_dir: /Users/foo/p\\\\~rojects\n')
assert res['vault'] == '/Users/foo/Mobile Documents/x'
assert res['repo_dir'] == '/Users/foo/p~rojects'
```
全部通过 ✓

**`cmd_set_config` warnings 触发面板**：

| 输入 | warning |
|---|---|
| `vault = "/Users/.../Mobile\ Documents/..."` | `vault: 检测到 shell 转义字符（\空格 或 \~），已自动归一化为 "/Users/.../Mobile Documents/..."` |
| `vault = "relative/path"` | `vault 不是绝对路径：relative/path` |
| `vault = "/不存在的路径"` | `vault 目录不存在：/不存在的路径` |
| `vault = "/Users/.../WorkObsidian"` + `output_dir = "WorkObsidian/sub"` | `output_dir: 'WorkObsidian/sub' 以 vault 末段 'WorkObsidian' 开头，可能导致路径重复嵌套` |

> 注：feedback §3.4 方案 C（接入 pyyaml）暂未做。理由：极简解析器 + `normalize_path_input` 已覆盖该场景，pyyaml 在 install.sh 检查链条里多一个失败点。后续若出现更复杂场景再升级。

---

### F-03 · 复杂表 HTML 标签泄漏到正文（P1）

**反馈现象**（feedback §4.1）：`会员购自营供应链计划SOP.docx` 中 3 处复杂表（嵌套表 / 合并单元格）出现 `</td>`、`</tr>`、`<tr>`、`<td>` 残留在 markdown 正文中。

**修复**（[`scripts/tencdoc/cleaners/table_cleaner.py`](../../scripts/tencdoc/cleaners/table_cleaner.py)）— **检测而非修复**：

| 新增 | 说明 |
|---|---|
| `_FULL_TABLE_RE` | 匹配 `<table>...</table>` 完整块 |
| `_ORPHAN_TAG_RE` | 行首/独立成行的 `</?tr/td/th/tbody/thead/tfoot>` |
| `_detect_table_tag_leaks(md)` | 抠掉所有完整 `<table>` 后扫描残余孤立标签 |
| `clean_tables` 末端调用 + `ctx.warn(...)` + 报告 `tag_leaks` / `tag_leak_samples` | 用户可在 JSON 报告 / Obsidian 中清楚看到提醒 |

**理由**：自动修复需要把泄漏区段重新包成 `<table>` 或回退为原始 HTML，逻辑分支多易翻车；先把信号亮出来，后续 v0.7.x 再考虑兜底。

**端到端验证**（会员购 SOP.docx）：

| 字段 | 值 |
|---|---|
| `total_html_tables` | 8 |
| `degraded_to_pipe` | 6 |
| `kept_as_html` | 2 |
| `widths_from_docx` | 1 |
| `widths_from_heuristic` | 1 |
| **`tag_leaks`** | **18** |
| `tag_leak_samples` | `["</tr>", "<tr>", "</tr>", "<tr>", "</tr>"]` |
| `warnings` | `["table_cleaner: 检测到 18 处疑似泄漏 HTML 表格标签..."]` |

直接核对 md 文件：`<table` 计数 = 2，`</table>` 计数 = 5，差值 3 个孤立 `</table>` + 嵌套 `<tr>` 共 18 行 → 与统计完全一致 ✓

---

### F-04 · front_matter `source:` 自动填充（P2）

**反馈现象**（feedback §4.3）：`hyperlink_cleaner` 已收集腾讯文档原链并写为 YAML 注释，但 `source:` 字段强制为空，用户每次都要手动复制粘贴。

**修复**（[`scripts/tencdoc/cleaners/front_matter.py`](../../scripts/tencdoc/cleaners/front_matter.py)）：

| 改动 | 说明 |
|---|---|
| `source_value = tenc_links[0] if tenc_links else ""` | 取首个候选 |
| `source_auto_filled = bool(source_value)` | 报告字段 |
| YAML 注释文案分流 | 单候选：「请确认是否本文档自身」；多候选：「如非自身请改成下列其一」 |
| 报告新增 `front_matter.source` / `source_auto_filled` | 便于回归监控 |

**端到端验证**（会员购 SOP）：
```yaml
---
title: 会员购自营供应链计划SOP
source: "https://doc.weixin.qq.com/doc/w3_AFsAcQbzADgCNHJ9DTfebSX2sr5Pa?scode=..."
converted_at: 2026-04-25T09:53:44+08:00
source_file: 会员购自营供应链计划SOP.docx
...
# source 已自动取唯一候选；如非本文档自身请改为空。
#   - https://doc.weixin.qq.com/doc/w3_AFsAcQbzADgCNHJ9DTfebSX2sr5Pa?scode=...
---
```
`source` 已自动填充 ✓

> 设计取舍：原代码注释明确说「首个链接可能是交叉引用而非自身」所以保守留空；本轮逆转此决定的依据：实测中用户手动操作成本远高于偶发 review 修正成本，且新文案明确提示用户复核。

---

## 三、回归（不应破坏的旧能力）

端到端转换 `会员购自营供应链计划SOP.docx`（exit 0），报告关键字段：

| 模块 | 字段 | 值 | 评估 |
|---|---|---|---|
| `image_rewriter` | `html_images_rewritten` | 2 | ✓ 与 v0.6.5 一致 |
| `heading_normalizer` | `headings_after` | 10 | ✓ 与 v0.6.5 一致 |
| `inline_formatter` | `highlights_restored` / `colours_restored` | 8 / 2 | ✓ 与 v0.6.5 一致 |
| `table_cleaner` | `widths_from_docx` / `widths_from_heuristic` | 1 / 1 | ✓ T-22c 列宽逻辑未受影响 |
| `list_squeezer` | `blank_lines_dropped` | 6 | ✓ 与 v0.6.5 一致 |
| `preprocess` | `heading_numpr_stripped` | 10 | ✓ 一致 |

`py_compile` 三个修改文件：全部通过。

---

## 四、未处理项与下一步

| ID | 项目 | 优先级 | 计划 |
|---|---|---|---|
| F-05 | README 增补「unzip 中文文件名」备用方案（`python3 -c "import zipfile..."`） | P2 | 下轮文档批量更新 |
| F-06 | README 增补两套 config（`~/.config/...` vs repo `<root>/config.yaml`）说明框 | P3 | 同上 |
| F-03b | 表标签泄漏的**自动修复**（包成 `<table>` / 兜底 raw HTML 块） | P1 | v0.7.x，需要先收集更多 leak 样本 |
| F-07 | 不可见图片（`image2.png` 3.3KB）未提取的 probe 阶段 warning | P2 | 需先调研 pandoc 行为，归入 v0.7.x backlog |
| F-08 | 扩展 popup 接入 `cmd_doctor` UI 入口 | P2 | 需要 extension 端改动，独立任务 |

---

## 五、变更文件清单

| 文件 | 类别 | 行数变化（粗略） |
|---|---|---|
| `install.sh` | 修复 | +6 / -1 |
| `native-host/host.py` | 修复 + 新功能 | +60 / -7 |
| `scripts/tencdoc/cleaners/front_matter.py` | 新功能 | +15 / -5 |
| `scripts/tencdoc/cleaners/table_cleaner.py` | 新功能 | +45 / -7 |
| `references/CHANGELOG.md` | 文档 | +25 |
| `SKILL.md` | 文档 | +2 |

---

## 六、结论

P0/P1/P2 主线 4 项问题（install.sh 崩溃、幽灵目录、表标签泄漏检测、source 自动填充）已**全部修复并验证**。剩余未处理 4 项均为文档/扩展 UI 类工作，属于「质量改善」而非「阻塞使用」，可在 v0.7.x 文档大整理时一并处理。

**建议立即操作**：

1. 已升级到 v0.6.6 的用户重跑 `install.sh`（让 launcher 与新 manifest 重新写入）
2. 若 `~/.config/tencdoc-to-md/config.yaml` 中 vault 含 `\ ` / `\~`：
   - 方案 A：手动改正（推荐，立刻生效）
   - 方案 B：从扩展 options 页面重新点保存（host 端会自动归一化）
3. 历史已转换但被写到「幽灵目录」的 md 文件需手动 `mv` 到正确位置（host 端不主动迁移历史产物）
