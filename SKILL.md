---
name: tencdoc-to-md
description: >
  将腾讯文档（企业微信/WeCom 导出）的 .docx 转换为 Obsidian 兼容 Markdown。
  图片抽取到同名附件目录并以 ![[wiki-link]] 引用；自动注入 YAML front matter；
  表格智能降级为 pipe 或保留清洗后的 HTML；还原被 pandoc 丢弃的下划线与背景高亮。
  触发条件：用户提到"腾讯文档 / WeCom / 企业微信导出的 docx 转 markdown"，
  或文件名含 PRD / 需求等业务词且来源为 doc.weixin.qq.com；通用 docx 请用 docx-to-md。
  v0.4.x 新增：文字颜色恢复（<span style="color">）、幽灵空表清除、图片宽度约束。
  v0.5.0 新增：config.yaml 路径配置、全局附件库模式、batch.py 批量入口、根目录快捷脚本。
  v0.6.4 新增：HTML 表格 <colgroup> 按 docx w:tblGrid 原始比例注入列宽（内容启发式降为 fallback）。
license: MIT
compatibility: >
  Python 3.8+，pandoc 2.9+（brew install pandoc / apt install pandoc），pyyaml>=5.1
metadata:
  author: loki
  version: "0.5.0"
  category: knowledge-management
  tags: ["tencent-docs", "wecom", "obsidian", "markdown", "docx"]
  updated: "2026-04-13"
  changelog: "references/CHANGELOG.md"
argument-hint: "<docx-path> [--output-dir <dir>] [--attachments-dir <dir>] [--dry-run]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

# tencdoc-to-md — 腾讯文档 → Obsidian Markdown

## 何时使用

满足以下任一条件时使用本 skill，否则用 `docx-to-md`：

- 来源是 **腾讯文档 / WeCom / 企业微信 / doc.weixin.qq.com**
- `word/styles.xml` 内标题的 `w:styleId` 为 6 位随机字符（`probe.py` 自动识别）
- 文件名含 PRD / 需求 / 腾讯 / wework 等业务关键词
- 目标是 Obsidian vault，需要 `![[...]]` wiki-link 图片引用

## 工作流程

### Step 0 — 检查依赖

```bash
python <skill>/scripts/check_deps.py
```

缺少 `pandoc` 或 `python3` 时会打印安装建议并以非零码退出。

### Step 1 — 转换

```bash
python <skill>/scripts/convert.py "<docx路径>" \
    [--output-dir <目录>]   # 默认与输入同级
    [--force]               # 覆盖已存在的输出
    [--dry-run]             # 只预览，不落盘
```

**产物：**
```
<output-dir>/
├── <stem>.md               # 转换后的 markdown
└── <stem>/                 # 附件目录
    ├── image1.png
    └── image2.jpg
```

**stderr 输出一份 JSON 报告**，包含各 cleaner 处理统计和 warnings。

### Step 2 — 读取报告 & 语义补充

转换完成后检查 JSON 报告并按需补充：

```
关注字段：
  stages.preprocess.heading_numpr_stripped   # 修复的标题数
  stages.table_cleaner.kept_as_html          # 保留为 HTML 的复杂表
  stages.inline_formatter.highlights_restored # 恢复的高亮数
  warnings                                   # 需人工处理的警告
```

语义补充：
- 图片无 alt 的，根据上下文段落就地补写描述
- front matter 里 `source` 为空但正文有 `doc.weixin.qq.com/...`，手动填入
- 核对标题层级，调整明显错位的段落

## 输入输出规范

**文件名归一化**（保留中文，只清理文件系统敏感字符）：

| 原字符 | 替换为 |
|---|---|
| `: / \ ? * " < > \|` | `-` |
| 连续空白（含全角） | 单个半角空格 |
| 前后空白 / 点号 | 去掉 |

**Front matter 字段**：`title / source / converted_at / source_file / tags / author / aliases`

## Cleaner Pipeline

按以下顺序执行，每步职责独立：

| # | Cleaner | 职责 |
|---|---|---|
| 1 | `image_rewriter` | `![](media/x)` → `![[stem/imageN.ext]]` |
| 2 | `heading_normalizer` | 解包 list-wrapped heading；H2 为最高级 |
| 3 | `inline_formatter` | PUA sentinel → `<u>` / `<span style="background-color">` / `<span style="color">` |
| 4 | `table_cleaner` | HTML→pipe 或清洗 HTML；修复空首行、`<li><p>`/`<li><blockquote>` 间距；图片宽度约束；幽灵空表清除 |
| 5 | `hyperlink_cleaner` | 清空链接 / 多余空格 |
| 6 | `list_squeezer` | 压缩松散列表空行；清除 `<!-- end list -->` 注释 |
| 7 | `front_matter` | 注入 YAML + H1 title |

详细实现说明见 `references/pipeline-internals.md`。

## 目录结构

```
tencdoc-to-md/
├── convert.py                      ← 根目录单文件转换快捷入口
├── batch.py                        ← 根目录批量转换入口（读 config.yaml）
├── config.example.yaml             ← 路径配置模板（复制为 config.yaml 后填写）
├── SKILL.md                        ← 本文件（Level 1+2，AI agent 调用规范）
├── README.md                       ← 人类可读安装文档
├── LICENSE                         ← MIT 协议
├── requirements.txt                ← Python 依赖声明
├── references/                     ← Level 3，按需加载
│   ├── pipeline-internals.md       ← cleaner 详细机制
│   ├── backlog.md                  ← 已知问题与路线图
│   └── CHANGELOG.md                ← 版本历史
├── scripts/
│   ├── convert.py                  ← 核心转换逻辑（含 convert_one() 供 batch.py 调用）
│   ├── check_deps.py
│   └── tencdoc/
│       ├── probe.py                ← 解析 docx 元信息
│       ├── preprocess.py           ← heading numPr 修复 + inline sentinel 注入
│       ├── pipeline.py             ← CleanerContext + run_pipeline()
│       ├── utils.py
│       └── cleaners/
│           ├── image_rewriter.py
│           ├── heading_normalizer.py
│           ├── inline_formatter.py ← v0.3 新增
│           ├── table_cleaner.py    ← 持续优化重点
│           ├── hyperlink_cleaner.py
│           ├── list_squeezer.py
│           └── front_matter.py
└── tests/
    ├── fixtures/
    ├── run_tests.py
    └── UAT_report/
        └── UAT_report_20260412.md
```

## 持续迭代指南

发现新问题时的三步流程：

1. **最小 fixture**：把触发 case 的 docx 片段放入 `tests/fixtures/`，命名说明问题
2. **单文件改动**：优先只改一个 cleaner，不跨文件杂糅逻辑
3. **回归验证**：`python tests/run_tests.py` 确保未破坏已有 case

当前 P1 问题（下轮优先）：见 `references/backlog.md`
