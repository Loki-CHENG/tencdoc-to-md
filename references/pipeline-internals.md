# Pipeline Internals — tencdoc-to-md

> Level 3 参考文档。需要调试或扩展 cleaner 时加载。

---

## 整体架构

```
convert.py
  │
  ├─ probe_docx()          → DocxProbe（元信息）
  ├─ preprocess_docx()     → 修改后的临时 docx
  ├─ pandoc（子进程）       → 原始 GFM markdown
  └─ run_pipeline()        → 逐步应用 CLEANERS 列表
```

`CleanerContext` 在所有 cleaner 间共享状态（stem、image_files、报告数据），每个 cleaner 签名为 `(md: str, ctx: CleanerContext) -> str`。

---

## preprocess.py — pandoc 前处理

### 1. Heading numPr 剥离

**问题**：腾讯文档对标题段落也附加 `<w:numPr>`（列表缩进），pandoc 有时将深层标题（H5/H6）误渲染为加粗列表项。

**修复**：遍历 `<w:p>`，若 `<w:pStyle>` 映射到标题样式，则删除其 `<w:numPr>` 块。

### 2. Inline Sentinel 注入

**问题**：pandoc 直接丢弃 `<w:u val="single">`（下划线）和 `<w:shd w:fill="RRGGBB">`（背景高亮）。

**方案**：在 `<w:t>` 内容前后注入 Unicode PUA 字符，pandoc 视其为普通文本透传：

| Sentinel | 值 | 含义 |
|---|---|---|
| `_SEN_U_OPEN` | `\uE100` | 下划线开始 |
| `_SEN_U_CLOSE` | `\uE101` | 下划线结束 |
| `_SEN_H_OPEN` | `\uE102` | 高亮开始（后跟 6 位 hex 颜色） |
| `_SEN_H_CLOSE` | `\uE104` | 高亮结束 |

示例注入后的 XML：
```xml
<w:t>\uE102FFFF00众筹商品屏蔽进选品广场\uE104</w:t>
```

**跳过颜色**：`FFFFFF`、`AUTO`、`NONE` 视为无高亮，不注入。

---

## inline_formatter.py

接收带 sentinel 的 markdown，还原为 HTML 标签：

```
\uE100TEXT\uE101              →  <u>TEXT</u>
\uE102RRGGBBTEXT\uE104        →  <span style="background-color: #RRGGBB">TEXT</span>
```

未配对的 sentinel 用 `_STRAY_RE` 清除，不会产生残留字符。

---

## table_cleaner.py — 最高迭代优先级

### 处理路径

```
HTML table block (TABLE_BLOCK_RE)
       │
       ├─ _parse_table()       → _TableTree (grid of _Cell)
       ├─ _can_pipe()?
       │     ├─ YES → _grid_to_pipe()
       │     └─ NO  → _clean_html_table()
       │
       └─ 后处理：_GFM_TABLE_RE.sub(_fix_gfm_empty_header, md)
```

### `_can_pipe()` 拒绝条件

| 条件 | 原因 |
|---|---|
| 行列不等宽 | 无法表达为矩形 pipe 表 |
| `rowspan > 1` 或 `colspan > 1` | pipe 表不支持合并单元格 |
| 单元格含嵌套列表/引用块 | `_cell_is_simple()` 返回 False |
| `_header_looks_merged()` 为 True | 首行空列超半数，说明是展开的 colspan header |

### `_header_looks_merged()` 逻辑

pandoc 展开 `colspan=N` header 时，生成 1 个填充格 + (N-1) 个空格。  
启发式：首行空格数 > 总列数 / 2，或相邻两个空格，判定为 merged header → 保留 HTML。

### `_clean_html_table()` 处理步骤

1. `_TABLE_ELEM_RE` / `_TABLE_STYLE_RE`：只从 `table/tr/td/th` 元素上删除 `class` 和 `style`（不影响 `<span style="background-color:...">` 等内联格式）
2. `re.sub(tbody|thead|tfoot)`：移除 pandoc 产生的包装标签
3. `<td>\s*<p>(.*?)</p>\s*</td>` **不加 re.DOTALL**：仅压缩单行单段 td，避免跨 cell 截断
4. `<li>\s*<p>(...)` **非贪婪、不越过第一个 `</p>`**：去除 `<li><p>` 的段落包裹，消除 Obsidian 阅读视图的行间距问题
5. `_WIKILINK_IMG_RE.sub(_wikilink_to_img)`：`![[path]]` → `<img src="path">`（Obsidian 不在 HTML block 中渲染 wiki-link）

### 列宽处理规范（T-22c：docx 原始比例优先）

HTML fallback 表格注入 `<colgroup>` 时的优先级：

| 优先级 | 来源 | 触发条件 |
|---|---|---|
| 1 | docx `w:tblGrid/w:gridCol@w:w` → twips 按比例换算为百分比（严格保留原比例，无下限） | `probe.table_grids[i]` 存在且列数 == `tree.max_cols()` |
| 2 | 内容启发式 `_compute_col_widths`（narrow 10% / image 25% / wide 平分剩余） | 1 不满足（无 tblGrid、列数不符、嵌套表对不上等） |
| 3 | 不注入 `<colgroup>`，交给 `table-layout:fixed` 平分 | 启发式也返回空（单列 / 所有列同类型） |

**表序匹配**：`clean_tables` 按 `TABLE_BLOCK_RE` 在 pandoc 输出中遍历的顺序维护 `cursor`，与 `probe.table_grids` 的文档序一一对应。pipe 表降级路径也会消费一个 grid 下标以保持对齐。

**百分比算法**：`_docx_widths_to_pct(twips)` 过滤非正值，按 `pct[i] = w[i] / sum(w) * 100` 保留 2 位小数，末列吸收舍入差使总和严格为 100%。

**统计字段**（见 `report.table_cleaner`）：`widths_from_docx` / `widths_from_heuristic` 反映每种来源命中的 HTML 表数量，便于回归监控。

### `_fix_gfm_empty_header()` 逻辑

pandoc 对无 header 表补充全空首行。此函数检测 GFM pipe 表的首行是否全部为空白单元格，若是则丢弃首行并将下一行提升为 header。

---

## probe.py — 元信息提取

不依赖 python-docx，直接解析 ZIP 内的 XML：

| 字段 | 来源 |
|---|---|
| `title` | Title 样式的第一个段落文本 |
| `author` | `docProps/core.xml` → `dc:creator` |
| `heading_levels_used` | 遍历 document.xml 中所有 pStyle 映射到 heading N |
| `image_files` | `word/media/` 目录列表 |
| `is_tencent_doc` | `len(rand_style_ids) >= 2 AND name_has_lower_heading` |
| `has_vmerge` | `<w:vMerge>` 元素存在 |
| `table_grids` | 按文档序遍历 `<w:tblGrid>` 块抓取每个 `<w:gridCol w:w="N"/>` 的 twips；嵌套表也计入 |

**腾讯文档指纹**：styles.xml 中 `w:styleId` 为 6 位随机字符（如 `rdbvau`）但 `w:name` 保留标准名（`heading 2`）。

---

## 扩展 Cleaner 的方法

1. 在 `scripts/tencdoc/cleaners/` 新建 `my_cleaner.py`
2. 实现 `def my_cleaner(md: str, ctx: CleanerContext) -> str`
3. 在 `convert.py` 的 `CLEANERS` 列表中插入合适位置
4. 用 `ctx.set_report("my_cleaner", {...})` 写入 JSON 报告

`CleanerContext` 可用字段：
- `ctx.stem` — 文件名（不含扩展名）
- `ctx.image_files` — 已复制到附件目录的图片文件名列表
- `ctx.probe` — `DocxProbe` 实例（含所有元信息）
