# Changelog — tencdoc-to-md

遵循 [语义化版本 2.0.0](https://semver.org/lang/zh-CN/) 和 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 规范。

---

## [0.6.6] — 2026-04-25（部署/转换质量反馈修复）

### Fixed

- **install.sh：Bash 3.2 全角括号崩溃**（developer-feedback §2）。macOS 自带 Bash 3.2 解析 `"$var（"` 会把全角左括号字节并进变量名，触发 `unbound variable` 退出。第 143 行 `用户配置：$user_cfg（repo_dir = $REPO_DIR）` 改为半角括号 `用户配置: $user_cfg (repo_dir = $REPO_DIR)`；脚本顶部新增 `${BASH_VERSINFO[0]}<4` 警告，提示用户 `brew install bash`。
- **native-host/host.py：扩展配置路径转义字符导致幽灵目录**（developer-feedback §3，P0）。极简 `_yaml_load` 不还原 `\ ` / `\~`，导致 iCloud 路径含字面反斜杠时被 `Path()` 当作单独目录名，文件被写到「丢失」位置。
  - 新增 `normalize_path_input(value)`：剥 `\<space>` → 空格、`\~` → `~`、首尾引号/空白
  - `_PATH_KEYS = {"vault","output_dir","attachments_dir","repo_dir","inbox"}` 在 `_yaml_load` 与 `cmd_set_config` 双向应用归一化
  - `cmd_set_config` 新增校验 → 返回 `warnings`：vault 不是绝对路径 / 目录不存在 / output_dir 以 vault 末段开头（重复嵌套）/ 检测到 shell 转义已剥除

### Added

- **front_matter：`source` 字段自动填充**（developer-feedback §4.3）。若 `hyperlink_cleaner` 收集到至少一个腾讯文档链接，取首个填入 `source:`；候选链接仍以 YAML 注释保留并附「请人工确认是否本文档自身」提示。报告中新增 `front_matter.source` / `front_matter.source_auto_filled`。
- **table_cleaner：HTML 标签泄漏检测（T-24）**（developer-feedback §4.1）。在 `clean_tables` 末端扫描所有「未被 `<table>...</table>` 包裹」的孤立 `<tr>/<td>/</tr>/</td>/<tbody>` 等行，写入 `report.table_cleaner.tag_leaks` 数量与最多 5 个样本，并 `ctx.warn(...)` 让用户在转换报告中收到提醒。SOP 实测产生 18 处泄漏（与 feedback §4.1 描述一致），证明检测命中。

### Verification

- `python3 -m py_compile`：3 个修改的 Python 文件全部通过
- `bash -n install.sh`：通过
- `normalize_path_input` 单测：`"/Users/.../Mobile\ Documents/com\~apple\~CloudDocs"` → `"/Users/.../Mobile Documents/com~apple~CloudDocs"` ✓
- 端到端：会员购 SOP docx 转换 → `source` 已自动填充、warnings 数组报告 18 处 tag_leak、front_matter 渲染正确

---

## [0.6.5] — 2026-04-25（HTML 表格紧凑行间距）

### Changed

- **T-23：HTML fallback 表格作用域内重写垂直留白策略**，目标是让单元格内嵌套列表的视觉密度接近 Obsidian 纯 markdown 列表。在 `_clean_html_table` 内按顺序新增 6 步：
  1. `</p>\s*<p>` → `<br>` 保留段落视觉换行
  2. 剥光剩余 `<p>/</p>` 标签（消除 1em 段落 margin）
  3. `<ul>/<ol>` 注入 `style="margin:0.2em 0;padding-left:1.4em"`
  4. `<li>` 注入 `style="margin:0;padding:0"`
  5. `<blockquote>` 注入 `style="margin:0.2em 0;padding-left:0.8em;border-left:2px solid #ddd"`
  6. `<td>/<th>` 现有 word-break style 追加 `padding:4px 8px;line-height:1.5;vertical-align:top`
- 老规则 T-05/T-07/T-07b 因步骤 2 变为冗余但暂保留，待 v0.7.0 整理。
- 步骤 3-5 用 `(?![^>]*style=)` negative lookahead 避免覆盖嵌套表内联样式。

### Verification

- 4 文档回归：列宽 `widths_from_docx` 数据完全稳定（带货佣金结算 9/9、PRD 2/3、会员购 1、小店 N/A），证明本轮改动正交于 T-22c。
- PRD 那张 5-6 层嵌套 ul 表的渲染密度由「每 li 上下 ~16-32px gap」降到「~2-4px」。

---

## [0.6.4] — 2026-04-24（HTML 表格列宽保留 docx 原始比例）

### Changed

- **T-22c：HTML fallback 表格的 `<colgroup>` 优先读取 docx `w:tblGrid/w:gridCol` 原始宽度**，严格按 twips 比例换算为百分比注入，不设下限。内容启发式 `_compute_col_widths` 退化为 fallback（仅当 docx 无 tblGrid / 列数对不上时触发）。解决长期痛点：需求表"模块"窄列被启发式错判为 wide 挤占"详情"宽列可读空间。
- `_clean_html_table(html, tree, docx_widths=None)` 新增参数；`clean_tables` 主循环按 `TABLE_BLOCK_RE` 的遍历顺序维护 `cursor`，与 `probe.table_grids` 一一对应。pipe 表降级路径也会消费 grid 下标以保持表序对齐。

### Added

- **`scripts/tencdoc/probe.py`**：
  - `DocxProbe.table_grids: List[List[int]]` — 按文档序的每张表的 `<w:gridCol w:w>` twips 列表
  - `_extract_table_grids(doc_xml)` — 遍历 `<w:tblGrid>...</w:tblGrid>` 块并抽取 gridCol 宽度
- **`scripts/tencdoc/cleaners/table_cleaner.py`**：
  - `_docx_widths_to_pct(twips)` — twips → 百分比字符串（保留 2 位小数，末列吸收舍入差）
  - 报告字段 `widths_from_docx` / `widths_from_heuristic` 统计每种宽度来源命中数
- **`references/pipeline-internals.md`**：新增「列宽处理规范（T-22c）」章节

---

## [0.6.3] — 2026-04-19（浏览器扩展：端到端可用）

本次迭代聚焦把 Chrome 扩展 `TencDoc → Obsidian` 从"能装上但点不动"修到"一键触发 → 下载 → Native Host 转换 → 回写按钮状态"全链路可跑通。过程中踩了四个坑，按排查顺序记录。

### Fixed

- **E-01：`findMenuButton` 找不到"文件操作"按钮** — 腾讯文档新版 DOM 里真正的触发器是 `#main-menu-file`（`aria-haspopup="true"`，`div` 元素），`#headerbar-filemenu` 退化成外层容器。`content.js` 重写 `findMenuButton()`：优先 `#main-menu-file`，回退到 `#headerbar-filemenu`、`[class*="menu-button-file"]`、aria-label 文本匹配；`waitForMenuButton(timeout=8000)` 给慢加载页面宽限窗口。

- **E-02：content-script 不在编辑器 frame 里执行** — 腾讯文档把编辑器渲染在 `<iframe id="very_fast_inner">` 内，顶层 frame 里根本没有菜单 DOM。诊断时所有选择器都返回空／false 就是这个原因。修复：`manifest.json` 加 `"all_frames": true` 让内容脚本注入所有 frame；`content.js` 新增 `isEditorFrame()` + `waitForEditorFrame(15000)`，只在能找到编辑器 DOM 的 frame 里注入浮动按钮，顶层 frame 跳过，避免按钮重影。

- **E-03：合成事件过不了 Dui（React）组件的 isTrusted + `:hover` 检查** — `dispatchEvent` 的 `MouseEvent` 只能模拟"假鼠标"，Dui 菜单的二级子菜单（`.mainmenu-item-export-as-docx`）是 lazy-mount：必须真鼠标 hover 过"导出为"之后 React 状态才挂载子菜单 DOM。修复：`background.js` 用 `chrome.debugger` attach + CDP `Input.dispatchMouseEvent` 发真实鼠标事件（`mouseMoved` / `mousePressed` / `mouseReleased`），走浏览器原生输入管线，isTrusted=true，CSS `:hover` 也生效。`manifest.json` 加 `"debugger"` 权限。

- **E-04：keepAlive 循环重复 attach/detach 自撞（"already attached" / "无法启动 debugger"）** — 为了防止 DOM 查找空档里 Dui 收起子菜单，content.js 有个 200ms 的 keepAlive 循环持续给"导出为"发真鼠 move 维持 hover。最初每次循环都 attach+detach，导致上一次 detach 还没跑完下一次 attach 就被拒。引入 **session 协议**：`sendRealMouse(steps, session)` 的 `session` 取 `'begin'` / `'continue'` / `'end'`，整个导出会话只 attach 一次、keepAlive 循环都用 `'continue'` 复用连接、最终点 docx 用 `'end'` 统一 detach。`background.js` 用 `attachedTabs` Set 做状态机，监听 `chrome.debugger.onDetach` 清理登记（用户手动关 DevTools / tab 关闭的场景）。

- **E-05：Step 6 最后一次 CDP 调用跟 keepAlive 循环抢连接** — 之前的顺序是"先点 docx → 再停 keepAlive"，最后一次 `action='click'`（session='end' 会 detach）跟循环里飞行中的 `action='move'`（session='continue'）竞争。改为**先 `keepAlive=false; await keepAliveLoop;`，确认循环退出后再发 `'end'` 的 click**。同时 Step 5 的 catch 也改为 async，抛错前 `await keepAliveLoop` 让循环落地，外层 catch 再 `forceDetachMouse()` 清理。

### Added

- **`extension/background.js`**：
  - `attachedTabs` Set + `_attachIfNeeded` / `_detachIfAttached` 幂等 helper（`"already attached"` 归一化处理，补登记）
  - `realMouseExport(tabId, steps, session)` session 协议：`'begin'`/`'continue'`/`'end'`/`'legacy'` 四种模式
  - `chrome.debugger.onDetach` 监听器：外部原因（DevTools 关闭 / tab 关闭）detach 时同步清理 `attachedTabs`
  - `real_mouse_detach` 消息处理：content.js 失败路径调用的强制清理接口 `forceDetachTab(tabId)`
  - 下载匹配从单变量 `pendingExport` 改为 FIFO `pendingQueue`：支持用户快速连续点或多 tab 并行导出
  - `reapExpiredPending()`：30s 窗口外的 pending 过期清理

- **`extension/content.js`**：
  - `isEditorFrame()` / `waitForEditorFrame()` iframe 选择逻辑，MutationObserver + 轮询双保险
  - `sendRealMouse(steps, session)` 改签名支持 session；新增 `forceDetachMouse()` 供失败恢复
  - keepAlive 循环：每 200ms 真鼠 move 到"导出为"中心 + `hover()` 合成事件 + `classList.add('dui-menu-submenu-visible')` 三重保险
  - 按钮 `data-status` 状态机：`idle` / `working` / `waiting` / `done` / `error`；done 状态下左键 = 复制 md_path，右键任意状态 = 复制最近路径；模块级 `lastMdPath` 跨次持久
  - CDP 冲突时的诊断错误文案（提示关 DevTools 或其他扩展）

- **`extension/manifest.json`**：`"debugger"` 权限、`"all_frames": true`、`host_permissions` 加 `docs.qq.com/*`

### Changed

- `manifest.json` version → 0.6.3
- `sendRealMouse` 默认行为保持兼容：未传 session 时走 legacy 模式（每次 attach+detach），与旧调用点兼容

### Known Issues / Debt

- 如果用户在导出途中打开 DevTools，`chrome.debugger` 会被 DevTools 抢走（`Another debugger is already attached`），扩展无法恢复。目前错误文案已提示，但没有自动 fallback。
- Dui 的 `keepAlive` 循环频率（200ms）是经验值，更慢的机器可能需要调。

---

## [0.5.0] — 2026-04-13

### Added
- **config.yaml 路径配置**：新增 `config.example.yaml` 模板，用户复制为 `config.yaml` 后填写三个路径（`docx_dir` / `output_dir` / `attachments_dir`），批量转换无需每次敲参数；`config.yaml` 已加入 `.gitignore`，`git pull` 不覆盖用户配置
- **全局附件库模式**：`config.yaml` 中 `attachments_dir` 填写路径后，所有文档的图片统一存放到指定目录的 `<stem>/` 子文件夹，兼容 Obsidian 统一附件管理；留空则保持原同级子目录行为（向后兼容）
- **batch.py 批量转换入口**（根目录）：读取 `config.yaml`，扫描 `docx_dir` 下所有 `.docx` 并批量转换；支持 `--file` / `--force` / `--dry-run`；带进度输出和汇总统计
- **根目录 convert.py 快捷入口**：`python convert.py <docx>` 等价于 `python scripts/convert.py <docx>`，无需记住脚本路径
- **`convert_one()` 函数**：将 `scripts/convert.py` 的核心逻辑抽取为可复用函数，供 `batch.py` 调用
- **`--attachments-dir` CLI 参数**：`scripts/convert.py` 新增此参数，支持命令行指定全局附件目录（优先级高于 config.yaml）
- **README.md**：新增中文人类文档，包含安装说明（Claude Code / KimiCode Trae / 命令行三种方式）、首次配置步骤、日常使用示例、部署验证 checklist、常见问题
- **LICENSE**：MIT 协议文件
- **requirements.txt**：声明 `pyyaml>=5.1`（config.yaml 读取）和 `python-docx>=0.8.11`（可选，probe 备用）
- **.gitignore**：排除 `__pycache__/`、`*.pyc`、`.DS_Store`、`tests/output/`、`config.yaml`

### Changed
- `scripts/convert.py` 重构：路径解析逻辑抽取为 `_load_config()` + `_resolve_path()`；主逻辑移入 `convert_one()` 供外部调用；CLI 入口精简为 `main()`
- `SKILL.md` version → 0.5.0；目录结构说明更新；`argument-hint` 新增 `--attachments-dir`；`compatibility` 补充 `pyyaml` 依赖

---

## [0.4.1] — 2026-04-13

### Fixed
- **T-22b**：`_compute_col_widths()` 图片列检测失效 — 流水线中 `image_rewriter` 先于 `table_cleaner` 运行，将 `<img src="...">` 转换为 `![[wiki-link]]`，导致图片列被误判为 wide 列，获得 45% 宽度而非 25%。修复：在 `col_has_img` 检测条件中新增 `!\[\[` 匹配，现可正确识别 wiki-link 图片列，输出 `10% | 25% | 65%` 分配。

---

## [0.4.0] — 2026-04-12

### Fixed
- **T-18**：幽灵空白 pipe 表清除 — `table_cleaner._remove_phantom_pipe_tables()` 检测并删除全 dash/空格的 pipe 表块（由 docx 合并标题行拆分所致）
- **T-19**：`<!-- end list -->` 注释残留 — `list_squeezer` 开头新增一步 `re.sub` 清除
- **T-20**：文字颜色（`<w:color>`）丢失 — 扩展 sentinel 机制：新增 `\uE105RRGGBB...\uE106`，跳过接近黑色的默认色（三通道均 < 0x30），恢复为 `<span style="color: #RRGGBB">`
- **T-21**：表格内图片过宽 — `_clean_html_table()` 和 `_wikilink_to_img()` 统一对 `<img>` 添加 `style="max-width:300px;max-height:150px;width:auto;height:auto"`
- **T-07b**：`<li><blockquote><p>` 行间距过大 — `_clean_html_table()` 新增正则展开 blockquote 包裹

### Added
- `preprocess.py`：新增 `_is_near_black()` 颜色判断辅助函数；`_inject_run_sentinels()` 返回 4 元组（新增 `colour_count`）
- `inline_formatter.py`：新增 `_COLOUR_RE` 模式，`clean_inline_formats()` 报告新增 `colours_restored` 字段
- `convert.py`：preprocess 阶段报告新增 `colour_runs_injected`

### Changed
- `SKILL.md` version → 0.4.0；description 补充 v0.4.0 新增能力摘要
- Cleaner pipeline 说明表更新 inline_formatter / table_cleaner / list_squeezer 描述

---

## [0.3.0] — 2026-04-12

### Added
- `inline_formatter.py`：新 cleaner，通过 PUA sentinel 机制还原 pandoc 丢弃的下划线（`<u>`）和背景高亮（`<span style="background-color: ...">）
- `preprocess.py`：新增 `_inject_run_sentinels()`，在 pandoc 处理前对 `<w:u>` 和 `<w:shd fill>` 运行注入 Unicode PUA 标记
- `references/` 目录：按 Agent Skills Specification 三层渐进披露架构拆出 Level 3 内容
- `references/pipeline-internals.md`：详细 cleaner 机制文档
- `references/backlog.md`：已知问题与路线图
- `references/CHANGELOG.md`：本文件

### Fixed
- **T-01/T-10**：GFM pipe table 空首行 — 新增 `_fix_gfm_empty_header()` 后处理所有 pandoc 直接输出的 pipe 表
- **T-02/T-06**：HTML 表格内 `![[wiki-link]]` 无法预览 — `_wikilink_to_img()` 转为 `<img src="...">`
- **T-03**：`re.DOTALL` 跨 cell 截断破坏表格结构 — 移除 DOTALL flag
- **T-05**：Colspan 展开导致列位移 — `_header_looks_merged()` 检测后保留 HTML
- **T-07/T-15**：`<li><p>` 行间距过大 / Obsidian 阅读视图表格不渲染 — 在 HTML table 内去除 `<li>` 的 `<p>` 包裹
- **T-12**：文字背景高亮丢失 — preprocess sentinel + inline_formatter
- **T-13**：下划线丢失 — 同上

### Changed
- `table_cleaner._STYLE_ATTR_RE`：全局匹配改为仅清除 `table/tr/td/th` 元素的 `style` 属性，避免误删内联高亮 span 的样式
- `SKILL.md`：按 Agent Skills Specification 重构，补全 YAML frontmatter（license / compatibility / metadata / argument-hint / allowed-tools），正文拆分为 Level 2 核心指令 + Level 3 参考文档

---

## [0.2.0] — 2026-04-12（当日早期版本）

### Added
- UAT 走查流程，8 篇文档 / 17 个 issue 结构化记录（`tests/UAT_report/UAT_report_20260412.md`）

### Fixed
- **T-01**：`_grid_to_pipe()` 内检测并跳过全空首行（覆盖 HTML→pipe 转换路径）
- **T-03**：`_clean_html_table()` 移除 `re.DOTALL`
- **T-05**：`_header_looks_merged()` + `_can_pipe()` 联动

---

## [0.1.0] — 2026-04-12（MVP）

### Added
- 完整 cleaner pipeline：image_rewriter / heading_normalizer / table_cleaner / hyperlink_cleaner / list_squeezer / front_matter
- `probe.py`：无需 python-docx，直接解析 docx ZIP 提取元信息
- `preprocess.py`：heading numPr 剥离（修复深层标题被 pandoc 误渲染为列表项）
- `check_deps.py`：依赖检查（pandoc / python3）
- `tests/run_tests.py`：批量回归测试
- 12 个样本文档全部通过基础测试（exit code / front matter / wiki-link refs / 无裸 pandoc 路径）
