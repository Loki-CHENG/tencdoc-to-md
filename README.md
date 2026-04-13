# tencdoc-to-md

将**腾讯文档 / 企业微信（WeCom）**导出的 `.docx` 文件，转换为 **Obsidian 兼容的 Markdown**。

支持：图片提取 & wiki-link 引用 · 表格智能清洗 · 下划线/高亮/文字颜色还原 · YAML front matter 注入 · 批量转换

---

## 目录

- [效果预览](#效果预览)
- [前置依赖](#前置依赖)
- [安装方式](#安装方式)
- [首次配置](#首次配置)
- [日常使用](#日常使用)
- [更新方式](#更新方式)
- [部署验证 Checklist](#部署验证-checklist)
- [常见问题](#常见问题)

---

## 效果预览

```
输入：腾讯文档导出的 某PRD.docx
输出：
  ~/ObsidianVault/TencDocs/
  ├── 某PRD.md              ← 带 YAML front matter 的 Markdown
  └── 某PRD/               ← 图片附件目录
      ├── image1.png
      └── image2.jpg
```

转换能力一览：

| 能力 | 说明 |
|------|------|
| 图片提取 | 自动提取内嵌图片，生成 `![[wiki-link]]` 引用 |
| 表格清洗 | 简单表格降级为 GFM pipe table；复杂表格保留 HTML，智能分配列宽 |
| 下划线还原 | `<u>文字</u>` |
| 高亮还原 | `<span style="background-color: ...">` |
| 文字颜色还原 | `<span style="color: ...">` |
| front matter | 自动注入 title / source / converted_at / author 等字段 |
| 批量转换 | 一条命令处理整个文件夹 |

---

## 前置依赖

### 1. Python 3.8+

```bash
python3 --version   # 确认已安装
```

如未安装，从 https://www.python.org/downloads/ 下载。

### 2. pandoc 2.9+

```bash
pandoc --version   # 确认已安装
```

安装方式：

```bash
# macOS
brew install pandoc

# Ubuntu / Debian
sudo apt install pandoc

# Windows
# 下载安装包：https://pandoc.org/installing.html
```

### 3. Python 依赖包

```bash
pip install pyyaml python-docx
```

---

## 安装方式

### 方式 A — Claude Code 用户

将本仓库克隆到项目的 `.claude/skills/` 目录：

```bash
# 进入你的项目根目录
cd /your/project

# 创建 skills 目录（如不存在）
mkdir -p .claude/skills

# 克隆
git clone git@github.com:Loki-CHENG/tencdoc-to-md.git .claude/skills/tencdoc-to-md
```

克隆后，Claude Code 会自动识别 `SKILL.md`，可以直接在对话中调用转换功能。

### 方式 B — KimiCode（Trae）用户

将本仓库克隆到 Trae 工作区下的 `.kimi/skills/` 目录：

```bash
# 进入你的 Trae 工作区根目录
cd /your/trae-workspace

# 创建 skills 目录（如不存在）
mkdir -p .kimi/skills

# 克隆
git clone git@github.com:Loki-CHENG/tencdoc-to-md.git .kimi/skills/tencdoc-to-md
```

> **注意：** 如果 Trae/KimiCode 的 skill 目录路径不同，请根据实际路径调整。

### 方式 C — 命令行直接使用（不依赖 AI 工具）

将本仓库克隆到任意目录，直接运行脚本即可：

```bash
# 克隆到本地
git clone git@github.com:Loki-CHENG/tencdoc-to-md.git
cd tencdoc-to-md

# 配置（见下方"首次配置"）
cp config.example.yaml config.yaml
# 编辑 config.yaml，填写你的路径

# 运行
python batch.py
```

---

## 首次配置

克隆完成后，**必须**执行一次配置，否则无法使用批量转换功能。

**第一步：复制配置模板**

```bash
cp config.example.yaml config.yaml
```

**第二步：用编辑器打开 `config.yaml`，修改以下三个路径**

```yaml
# 腾讯文档 docx 存放目录（批量转换时扫描此目录）
docx_dir: ~/Downloads/腾讯文档导出

# 转换后 md 文件的输出目录（填写你的 Obsidian vault 子目录）
output_dir: ~/ObsidianVault/TencDocs

# 附件目录（图片存放位置）
# 留空 = 与 md 同级的子目录（推荐新用户使用）
# 填路径 = 全局附件库（适合 Obsidian 统一附件管理）
attachments_dir: ""
```

> `config.yaml` 已在 `.gitignore` 中，不会被 git 追踪，每次 `git pull` 更新代码时不会覆盖你的配置。

**第三步：验证依赖**

```bash
python scripts/check_deps.py
```

看到 `All critical dependencies satisfied.` 说明环境正常。

---

## 日常使用

### 批量转换（推荐）

```bash
# 进入项目目录
cd tencdoc-to-md

# 转换 docx_dir 下所有 .docx 文件
python batch.py

# 覆盖已存在的输出文件
python batch.py --force

# 只转换某一个文件
python batch.py --file 某PRD.docx

# 预览模式（不写文件，仅查看会生成什么）
python batch.py --dry-run
```

### 单文件转换

```bash
# 最简用法（输出目录从 config.yaml 读取）
python convert.py ~/Downloads/某PRD.docx

# 指定输出目录
python convert.py ~/Downloads/某PRD.docx --output-dir ~/ObsidianVault/TencDocs

# 覆盖已有文件
python convert.py ~/Downloads/某PRD.docx --force

# 查看所有选项
python convert.py --help
```

### 关于附件目录的两种模式

**模式 A（默认，留空）— 同级子目录**

```
TencDocs/
├── 某PRD.md
└── 某PRD/
    ├── image1.png
    └── image2.jpg
```

**模式 B（填写路径）— 全局附件库**

```yaml
# config.yaml
attachments_dir: ~/ObsidianVault/attachments
```

```
TencDocs/
└── 某PRD.md

attachments/
└── 某PRD/
    ├── image1.png
    └── image2.jpg
```

使用模式 B 时，需要同步在 Obsidian 中设置：
`设置 → 文件与链接 → 附件文件夹路径` → 填写 `attachments`（相对 vault 根目录）

---

## 更新方式

```bash
cd tencdoc-to-md
git pull
```

`config.yaml` 在 `.gitignore` 中，更新代码不会覆盖你的配置。

---

## 部署验证 Checklist

第一次部署完成后，按以下步骤验证：

```
□ 1. git clone 成功，目录结构完整
      ls -la  （应看到 convert.py batch.py config.example.yaml 等文件）

□ 2. 复制配置模板
      cp config.example.yaml config.yaml

□ 3. 编辑 config.yaml，填写三个路径（docx_dir / output_dir / attachments_dir）

□ 4. 验证依赖
      python scripts/check_deps.py
      （看到 "All critical dependencies satisfied." 即可）

□ 5. 安装 Python 依赖
      pip install pyyaml python-docx

□ 6. 放一个腾讯文档导出的 .docx 到 docx_dir 目录

□ 7. 运行批量转换
      python batch.py
      （看到 ✅ 行即成功）

□ 8. 打开 Obsidian，确认
      - .md 文件已出现在 output_dir 对应的 vault 目录
      - 文档内图片正常显示（不是红色叹号）
      - front matter（文件顶部的 --- 块）格式正确
```

---

## 常见问题

**Q：运行时提示 `ERROR: pandoc 未找到`**

A：需要先安装 pandoc，参见[前置依赖](#前置依赖)。

**Q：提示 `输出已存在`**

A：加 `--force` 参数覆盖：`python batch.py --force`

**Q：图片在 Obsidian 中显示红色叹号（无法加载）**

A：检查 Obsidian 的附件文件夹设置。如果使用模式 B（全局附件库），需要在 Obsidian 设置中将附件路径指向 `attachments_dir` 对应目录。

**Q：表格显示异常**

A：腾讯文档的复杂表格（合并单元格、嵌套列表）会保留为 HTML 格式，需要 Obsidian 开启"渲染 HTML"功能（默认开启）。

**Q：转换后标题层级不对**

A：腾讯文档导出的 docx 标题样式不规范，工具会自动修复常见问题。如仍有问题，可手动调整 md 文件中的 `#` 层级。

---

## 项目结构

```
tencdoc-to-md/
├── convert.py              ← 单文件转换入口（根目录快捷方式）
├── batch.py                ← 批量转换入口
├── config.example.yaml     ← 配置模板（复制为 config.yaml 后填写路径）
├── config.yaml             ← 你的本地配置（不进 git）
├── requirements.txt        ← Python 依赖声明
├── LICENSE                 ← MIT 协议
├── SKILL.md                ← AI agent 调用规范（Claude Code / KimiCode）
├── scripts/
│   ├── convert.py          ← 核心转换逻辑
│   ├── check_deps.py       ← 依赖检查
│   └── tencdoc/            ← 转换流水线各模块
│       ├── probe.py
│       ├── preprocess.py
│       ├── pipeline.py
│       └── cleaners/
├── references/
│   ├── CHANGELOG.md        ← 版本历史
│   ├── pipeline-internals.md
│   └── backlog.md
└── tests/
    ├── run_tests.py        ← 回归测试脚本
    └── UAT_report/         ← 走查报告
```

---

## License

MIT © 2026 [Loki Cheng](https://github.com/Loki-CHENG)
