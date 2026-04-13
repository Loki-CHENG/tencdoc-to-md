# Backlog & 已知问题 — tencdoc-to-md

> 按优先级由高到低排列。P1 为下轮迭代目标。

---

## P1 — 严重问题（影响可读性）

### T-09：摩点"发布形态"表格第三列不显示

**文档**：众筹一期-摩点竞品调研（摩点模式分析）  
**现象**：`发布形态 / 创意 / 众筹项目` 三列表格，第三列内容完全不显示；image4-7 无法预览  
**根因假设**：`<td>` 结构中存在孤立 `</p>` 标签，或 `<td>` 未正确闭合  
**复现**：`tests/output/摩点模式分析.md`  
**方向**：重新审视 `_TableParser` 对大型嵌套结构（多层列表 + colspan + 大量图片）的解析边界

### T-11：店铺带货功能表第 4 行起结构崩溃

**文档**：众筹一期-店铺&带货PRD  
**现象**：`功能模块 / 功能描述 / 交互示例` 表格，第 4 行后内容脱出表格  
**根因假设**：单元格内容量过大（多级嵌套列表），触发 HTML parser 边界问题  
**复现**：`tests/output/小店众筹-店铺、带货.md`  
**方向**：检查 `_TableParser` 的 `handle_data` / `handle_starttag` 是否在大内容下丢失状态

---

## P2 — 功能缺口

### T-08：体行 colspan 导致列位移

**现象**：原表中某行有 `colspan=2` 的图片单元格，pandoc 展开后，后续列（如"邀约入驻"）错位  
**已处理**：header 行 colspan 展开（`_header_looks_merged()`）已覆盖  
**待处理**：body row 中行列数不一致时，`_can_pipe()` 应拒绝，保留为 HTML

---

## P3 — 体验优化

### T-14：Callout / 高亮块丢失

**文档**：众筹2.0（自营众筹融合小店众筹）  
**现象**：腾讯文档"💡 想法"等高亮块（style ID `ablt93` 等随机值）输出为正文  
**期望**：转为 Obsidian callout 语法
```markdown
> [!note] 想法
> 众筹应该是一个类目玩法为壳…
```
**难点**：腾讯文档每篇文档的 callout style ID 不同，需通过段落的 `<w:pBdr>`（边框）或背景填充特征来识别  
**参考**：众筹2.0 中 style `ablt93` 的段落含 `<w:pBdr>` 和底部边框分隔

### T-16：图片尺寸过大

**文档**：众筹一期-导购PRD  
**现象**：docx 内嵌超大分辨率图片，直接提取后文件巨大，影响 Obsidian 加载  
**方案**：在 `_copy_images()` 阶段，若检测到图片宽度超过 `--max-image-width N`（默认 1920px），使用 Pillow 等比缩放  
**依赖**：需 `pip install pillow`，设为可选依赖

---

## P4 — 架构设施

### T-17：Checkpoint-Resume

**现状**：每次执行 `convert.py` 均为全量重跑，无中间状态持久化  
**影响场景**：批量转换中途中断；大型文档 pandoc 阶段失败后无法从 pipeline 接续  
**设计方案**：
- 在 `--batch 目录/` 模式下引入 `.tencdoc_checkpoint.json`
- 记录每个文件的 `status`（pending / done / failed）、`sha256`、`output_path`
- 重跑时跳过 `status=done` 且 hash 未变的条目
- 单文件通常 < 5 秒，正式化批量模式后再实现

---

## 已知限制（不计划修复）

| 特性 | 现状 | 说明 |
|---|---|---|
| vMerge 垂直合并 | 保留为 HTML | pipe 表无法表达 rowspan |
| 公式 OMML | pandoc 原生处理 | 样本中未出现，暂不专门处理 |
| 文本框 `<v:textbox>` | pandoc 原生处理 | 占比极低 |
| 批注 `<w:comment>` | 默认丢弃 | 未来可转 Obsidian callout |
| 腾讯文档 @人 `MENTION_WXWORK` | 输出为 `@name(id)` 明文 | 暂不做额外处理 |
