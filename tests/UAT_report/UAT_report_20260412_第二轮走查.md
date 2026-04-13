# UAT Report — tencdoc-to-md 技能走查（第二轮）

> 走查版本：v0.3（2026-04-12，基于 test_output_v0.3.0 全量转换结果）
> 走查人：Loki
> 验证状态图例：🔴 未修复 / 🟡 部分修复 / 🟢 已修复 / ⚪ 不适用 / ❓ 待确认 / 🗓 Backlog

---

## 汇总看板（第二轮新增 + 第一轮遗留）

| ID | 文档 | 类别 | 严重度 | 问题 | 状态 |
| --- | --- | --- | --- | --- | --- |
| T-07 | 店铺带货 / 售后PRD / 导购PRD | 表格 | 高 | 表格内多级列表行间距过大（`<li><p>` + `<li><blockquote><p>` 两种形态） | 🟡 `<li><p>` 已修 / `<li><blockquote>` 仍存 |
| T-08 | 摩点 | 表格 | 中 | 行内 colspan 导致列位移（邀约入驻行） | 🟡 |
| T-09 | 摩点 | 表格 | 严重 | 发布形态表第三列不显示 + 图片失效 | ❓ v0.3 已生成三列，需 Obsidian 目视确认 |
| T-11 | 店铺带货 | 表格 | 严重 | 功能点表第 4 行起结构崩溃 | ❓ v0.3 结构完整，需目视确认 |
| T-14 | 众筹 2.0 | 内容 | 中 | Callout 块（💡 想法）丢失 | 🗓 Backlog |
| T-18 | 店铺带货 / 订单 / 众筹2.0 | 表格 | 中 | 变更记录上方出现幽灵空白 pipe 表（全 dash 行 + 全空行） | 🔴 待修 |
| T-19 | 业务进展汇报 / 多文档 | 格式 | 低 | `<!-- end list -->` HTML 注释残留在正文 | 🔴 待修 |
| T-20 | 售后PRD | 内容 | 中 | 文字颜色（红色 `#FF0000`）丢失，显示为默认黑色 | 🔴 待修 |
| T-21 | 导购PRD / 多表格 | 图片 | 高 | 表格内图片过宽，挤压文字列可读性极差 | 🔴 待修 |
| T-16 | 全局 | 图片 | 中 | 图片文件尺寸过大影响表格展示 | 🗓 Backlog（T-21 inline style 为过渡方案） |

---

## 文档一：小店众筹-店铺、带货

**文件路径：** `test_output_v0.3.0/小店众筹-店铺、带货.md`

| ID | 类别 | 严重度 | 位置 | 问题 | 预期 | 实际 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T-18 | 表格 | 中 | 文档变更记录区域 | 正文表前出现幽灵空白 pipe 表 | 仅显示变更记录数据表 | 先出现一个全 dash + 全空格 pipe 表块，空行后再出现真实数据表 | 🔴 根因：pandoc 把 docx 合并行拆成两个独立表 |
| T-07 | 表格 | 高 | 功能点说明表第 2 列（功能描述） | 多级列表行间距正常 | 行间距紧凑 | 部分 `<li><blockquote><p>` 结构导致额外 margin | 🟡 待修 |

---

## 文档二：小店众筹-订单

**文件路径：** `test_output_v0.3.0/小店众筹-订单.md`

| ID | 类别 | 严重度 | 位置 | 问题 | 预期 | 实际 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T-18 | 表格 | 中 | 文档变更记录区域 | 同店铺带货 T-18 | 仅显示变更记录数据表 | 全 dash + 全空 pipe 表幽灵块 | 🔴 同根因 |
| T-21 | 图片 | 高 | 功能描述表第 3 列（交互示例） | 图片列宽度适中，不压缩文字列 | `max-width: 300px; max-height: 150px` | 图片原始宽度，撑满列宽，文字列极窄 | 🔴 待修 |

---

## 文档三：众筹1.0—售后PRD

**文件路径：** `test_output_v0.3.0/众筹1.0—售后PRD.md`

| ID | 类别 | 严重度 | 位置 | 问题 | 预期 | 实际 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T-20 | 内容 | 中 | "本次新增：众筹项目失败和终止砍单"等红色文字 | 文字颜色保留为红色 | `<span style="color: #FF0000">本次新增...</span>` | pandoc 丢弃 `<w:color w:val="FF0000">`，输出纯黑文字 | 🔴 待修 |
| T-07 | 表格 | 高 | 众筹失败/终止砍单接口表格第 2 列 | 列表行间距紧凑 | 正常行高 | `<li><blockquote><p>` 结构残留，Obsidian 渲染出额外 margin | 🟡 待修 |

---

## 文档四：众筹2.0

**文件路径：** `test_output_v0.3.0/众筹2.0.md`

| ID | 类别 | 严重度 | 位置 | 问题 | 预期 | 实际 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T-14 | 内容 | 中 | "众筹应该是一个类目玩法为壳…" Callout 块 | Obsidian callout `> [!note] 想法` | 腾讯文档 callout 块展示 | 腾讯文档 callout 使用随机样式 ID，pandoc 丢弃 | 🗓 Backlog |
| T-18 | 表格 | 中 | 文档内多处幽灵空表 | 仅显示数据行 | 数据完整 | 全 dash 幽灵表头出现在数据表上方 | 🔴 待修 |

---

## 文档五：众筹一期-导购PRD

**文件路径：** `test_output_v0.3.0/众筹一期-导购PRD-产品-正式稿-25Y11M.md`

| ID | 类别 | 严重度 | 位置 | 问题 | 预期 | 实际 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T-21 | 图片 | 高 | 表格图片列（交互示例等） | 图片有最大宽高约束，不压缩文字列 | `max-width: 300px; max-height: 150px` | 图片撑满列宽，文字列可见宽度极小 | 🔴 待修 |
| T-07 | 表格 | 高 | 功能模块表第 2 列（多级列表） | 行间距紧凑 | 正常行高 | `<li><blockquote>` 结构或 `<li><p>` 变体导致过高行距 | 🟡 待修 |

---

## 文档六：众筹-运营-业务进展汇报

**文件路径：** `test_output_v0.3.0/众筹业务进展汇报_26年02月 V5.md`

| ID | 类别 | 严重度 | 位置 | 问题 | 预期 | 实际 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T-19 | 格式 | 低 | 正文各处列表中断点（第 270、281、297、407 行等） | 无多余注释 | 纯净 markdown 输出 | `<!-- end list -->` HTML 注释出现在列表断点处 | 🔴 待修 |

---

## 新 Issue 技术分析

### T-18 — 幽灵 Pipe 表（Ghost All-Dash/Empty Table）

**根因**：Tencent Docs 变更记录模板在 docx 中存在一行"合并标题行"（colspan 全覆盖），后接数据行。pandoc 将合并行单独解析为一个 pipe 表（因所有 cell 内容为 dash 或 empty），数据行成为第二个独立 pipe 表。

**现象输出**：
```markdown
| -------- | -------- | -------- | ------- | ------ |
|          |          |          |         |        |

| **变更日期** | **变更模块** | ...
```

**修复策略**：`table_cleaner.py` 新增 `_remove_phantom_pipe_tables()` — 检测所有连续 `|` 开头行构成的 pipe 块，若全部 cell 内容仅含 `-`/` `/`:（无任何实质文字），则删除该块。

---

### T-19 — `<!-- end list -->` 注释残留

**根因**：pandoc 在列表被非列表内容（blockquote/图片）打断后，在续接列表前插入 `<!-- end list -->` 注释以标记语义边界。

**修复策略**：`list_squeezer.py` 新增一行 `re.sub(r'<!--\s*end list\s*-->\s*\n?', '', md)`。

---

### T-20 — 文字颜色（`<w:color>`）丢失

**根因**：pandoc 2.9.2 忽略 `<w:color w:val="RRGGBB">` 属性，与 T-12/T-13 属同族问题。

**修复策略**：扩展 sentinel 机制：
- Sentinel `\uE105` = 开色（后接 6 字符 hex）/ `\uE106` = 关色
- Skip 接近黑色的默认颜色（三通道均 < `0x30` 的深色，涵盖 `000000`、`0D0D0D`）
- `preprocess.py` 检测 `<w:color>` 注入 sentinel
- `inline_formatter.py` 恢复为 `<span style="color: #RRGGBB">text</span>`

---

### T-21 — 表格内图片宽度过大

**根因**：pandoc 提取图片时不加尺寸限制；HTML table 内的 `<img>` 无 `max-width`，撑满列宽。

**修复策略**：`table_cleaner.py` 在 `_clean_html_table()` 内为所有 `<img>` 添加 inline style：
```html
style="max-width:300px;max-height:150px;width:auto;height:auto"
```
表格外的独立图片（`![[...]]` wiki-link）不作处理；用户可按需添加 Obsidian CSS snippet 控制全局高度。

---

### T-07b — `<li><blockquote><p>` 行间距问题

**根因**：已有 `<li><p>` strip 未覆盖 `<li><blockquote><p>text</p></blockquote></li>` 结构。Obsidian 对 blockquote 有额外 margin-top/bottom。

**修复策略**：`table_cleaner.py` `_clean_html_table()` 补充 strip：将 `<li>` 内的 `<blockquote><p>text</p></blockquote>` 展开为纯文本 `text`。

---

## 修复路线图（v0.4.0）

| 优先级 | Issue | 实现位置 | 预估工作量 |
| --- | --- | --- | --- |
| 🔴 P1 | T-18 幽灵空表 | `table_cleaner.py` | 小 |
| 🔴 P1 | T-19 end list 注释 | `list_squeezer.py` | 极小 |
| 🔴 P1 | T-20 文字颜色 | `preprocess.py` + `inline_formatter.py` | 小 |
| 🔴 P1 | T-21 图片宽度 | `table_cleaner.py` | 小 |
| 🟡 P2 | T-07b blockquote 行距 | `table_cleaner.py` | 小 |
| 🗓 P3 | T-14 Callout 块 | 独立模块 | 大 |
| 🗓 P3 | T-16 图片压缩 | `convert.py` + Pillow | 中 |

---

*第二轮走查完成于 2026-04-12，第三轮待 v0.4.0 重新生成后进行*
