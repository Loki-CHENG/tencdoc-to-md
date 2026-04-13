# Changelog — tencdoc-to-md

遵循 [语义化版本 2.0.0](https://semver.org/lang/zh-CN/) 和 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 规范。

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
