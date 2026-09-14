# 需求采集契约数据结构

模板采用 JSON，使材料收集、校验、合并和哈希计算只依赖标准 Python
环境。JSON 文件是机器可读状态；与用户追问时应同时展示 Markdown
摘要。

## `materials.json`

顶层字段：

- `schema_version`：当前为 `1`；
- `mode`：`clean-room-generation`、`engineering` 或
  `full-analysis`；
- `roots`：解析为绝对路径后的材料根目录；
- `items`：材料记录数组。

每条材料记录包含稳定 ID、来源类型、路径、大小、修改时间、SHA-256、
建议角色、优先级、选择状态、可见性和用户备注。已选本地材料必须存在且
具有可复算的完整 SHA-256；远端材料必须提供带采集时间和定位信息的摘要
证据。采集器可能
误分类，最终以人工审阅后的选择为准。

## `operator-task.json`

主要区段：

- `operator`：名称、目标硬件、集成位置和包含/排除范围；
- `interface`：注册接口、张量、属性、状态、形状关系和图模式契约；
- `correctness`：真值来源、用例、容差和副作用检查；
- `performance`：基线、指标方向、阈值、用例和测量协议；
- `delivery`：输出目录、文档目录和必需交付物；
- `policies`：来源模式和必需材料角色；
- `evidence`：带材料 ID 和定位信息的字段级结论；
- `decisions`：已确认决策和未解决阻塞项；
- `approval`：批准人、时间和规范化契约哈希。

批准态 evidence 不得为空，记录须有 id、field、locator 及 confirmed
状态；材料引用必须已选择且对生成者可见。用户直接决定的字段可以不引用
材料，但 locator 要定位到该次用户决定。校验器检查记录关联，不判断
自然语言结论是否正确，也不自动发现文档正文中的所有矛盾。

`interface.branch_decisions` 对注册、张量契约、状态/别名、形状语义、数值
行为和图执行六个关键分支逐项记录 `applicable`、`not_applicable` 或
`deferred`。适用或不适用都写理由；延后必须写默认值、风险、责任人和验证
计划。这样保证覆盖关键分支，又不强迫无关字段伪造答案。

每个张量记录为：

```json
{
  "id": "I-01",
  "name": "x",
  "kind": "input",
  "dtypes": ["bfloat16"],
  "formats": ["ND"],
  "logical_shape": "[T, D]",
  "physical_layout": "最后一维连续",
  "stride": "[S0, 1]",
  "optional": false,
  "mutability": "read-only",
  "alias_of": null,
  "value_constraints": [],
  "source_ids": [],
  "status": "proposed"
}
```

字段状态使用 `confirmed`、`proposed` 或 `deferred`。获批契约中的有条件
延后写在对应分支的 `deferment`，包含默认值、风险、责任人和验证计划，
但不再保留为 `unresolved_blockers`；无法给出这些条件的事项仍是阻塞项，
契约不能批准。

## 批准与哈希

用户明确批准当前完整摘要后，才执行以下写入；请求“开始采集”或
确认某个字段不等于最终批准：

1. 如果替换已经审阅过的契约，递增 `revision`；
2. 将 `status` 设为 `approved`；
3. 填写 `approval.approved_by`、`approval.approved_at`，并将
   `approval.user_confirmed` 设为 `true`；
4. 把中文确认过程写入 `approval.confirmation_record`，运行
   `validate_intake.py --materials <清单> --contract <契约> --write-hash`。
5. 不带 `--write-hash` 普通复验通过后交付。任一步失败都保留实际状态，
   不得仅凭 `status=approved` 报告已经冻结完成。

命令写入 `materials_snapshot_sha256`，再计算规范化契约哈希。普通校验中，
批准态缺任一哈希都会失败。只有两个摘要都为空、批准元数据和中文确认留痕
完整的当前修订可以初始化哈希；已有任一摘要的旧批准合同必须创建新修订，
不能通过再次运行命令静默补签。
