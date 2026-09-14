# ascend-op-intake

用证据和用户确认，把 Ascend 算子需求、材料、接口语义、正确性门槛与性能
协议整理成可交接的需求契约。它适合在实现算子前建立边界，也适合恢复已有
采集任务或只检查现有产物。

本 skill 不实现或修改内核，不安装 CANN，不编译、运行或验证 NPU 算子，
也不采集性能。脚本不会自动理解材料正文、替用户选择材料或替用户批准契约；
分类建议只是待审阅的元数据。仓库不包含真实模型包、权重、凭据或用户材料，
请自行准备并确认可公开/可见范围。

## 环境与安装

需要 Python 3.10 或更高版本，仅使用 Python 标准库，不需要 NPU、CANN 或
第三方 Python 包。本地验证环境为 Python 3.12.10。将本仓库 clone 到自己
可读的 skill 目录，或复制到项目的 `.agents/skills/ascend-op-intake/`。
公开仓库地址：[grandolantow/ascend-op-intake](https://github.com/grandolantow/ascend-op-intake)。

```bash
git clone https://github.com/grandolantow/ascend-op-intake.git
cd ascend-op-intake
python scripts/test_intake.py -v
```

将目录放入 agent 支持的技能目录后，可这样发起任务：

```text
使用 $ascend-op-intake 澄清 ExampleAdd 的需求。材料位于我指定的 package
目录，先列出材料和可见性建议，提取允许材料中的事实，只问关键缺口。
待我批准完整契约后，完成冻结与复验。不要开始内核实现。
```

仅 clone 不代表所有 agent 都会自动加载；也可在请求中明确指定本目录的
`SKILL.md`。Codex 的技能发现方式参见[官方说明](https://learn.chatgpt.com/docs/build-skills)。

脚本路径均相对于本目录。三个 CLI 是：

- `scripts/init_intake.py`：创建或恢复采集产物模板；
- `scripts/collect_materials.py`：按材料根目录盘点文件、计算摘要并生成报告；
- `scripts/validate_intake.py`：只读检查材料清单与契约，批准后可显式写入哈希。

## 快速流程

需求采集产物默认在 `dev_docs/<operator>/intake/`，包含
`materials.json`、`material-report.md`、`operator-task.json`、
`interface-contract.md` 和 `decision-log.md`。以下示例使用相对路径；材料
根是 `./demo-project/package`，输出目录是其外部的
`./demo-project/intake-output`，因此不会把刚生成的 JSON/报告再次采集进去。
以下命令在本仓库根目录执行，`demo-project/package` 必须是你事先准备好的
任务与材料目录；示例不会自动下载或生成真实输入包。

PowerShell：

```powershell
$skill = "."
$intake = "./demo-project/intake-output"
python "$skill/scripts/init_intake.py" `
  --operator demo-op --task-root ./demo-project --output-dir $intake
python "$skill/scripts/collect_materials.py" `
  --root ./demo-project/package `
  --mode clean-room-generation `
  --output "$intake/materials.json" `
  --report "$intake/material-report.md"
python "$skill/scripts/validate_intake.py" `
  --materials "$intake/materials.json" `
  --contract "$intake/operator-task.json"
```

Bash：

```bash
skill=.
intake=./demo-project/intake-output
python "$skill/scripts/init_intake.py" \
  --operator demo-op --task-root ./demo-project --output-dir "$intake"
python "$skill/scripts/collect_materials.py" \
  --root ./demo-project/package \
  --mode clean-room-generation \
  --output "$intake/materials.json" \
  --report "$intake/material-report.md"
python "$skill/scripts/validate_intake.py" \
  --materials "$intake/materials.json" \
  --contract "$intake/operator-task.json"
```

`init_intake.py` 不接受 `--mode`；模式只在采集时选择，并须随后把
`materials.json` 的 `mode`、`operator-task.json` 的 `mode` 和
`policies.source_mode` 三处改为完全相同的值。可选模式为
`clean-room-generation`、`engineering` 和 `full-analysis`。初始化脚本发现
已有产物会拒绝覆盖；续办请加 `--resume`，它只补齐缺失文件并保留已有内容。

### 新建

1. 先运行初始化和材料盘点，人工审阅每条记录的 `selected`、`visibility`、
   `source_of_truth` 与备注；不要把分类建议当成批准。
2. 只打开已选择且 `visibility=generator` 的材料正文，按字段记录证据、推断
   和用户决定；受限材料只保留允许的元数据。
3. 补齐接口、分支决策、正确性/性能门槛和交付范围，普通校验通过后交给用户
   审阅。草稿通过不等于需求完整或已批准。

### 续办

先读取已有 `materials.json`、`operator-task.json` 和决策日志，只调查当前
缺口或变化。保留已有批准记录；材料、选择、可见性、模式、接口或门槛改变时，
递增修订号，保留旧产物并重新获得本修订的明确批准，不得静默覆盖已批准清单。

### 只验证

不读取不必要的材料正文，也不写哈希：

```bash
python scripts/validate_intake.py \
  --materials ./demo-project/intake-output/materials.json \
  --contract ./demo-project/intake-output/operator-task.json
```

## 批准、冻结与材料边界

只有用户明确批准当前完整摘要后，才将契约设为 `approved`，填写批准人、时间
和中文 `confirmation_record`，并设置 `approval.user_confirmed=true`，再运行：

```bash
python scripts/validate_intake.py \
  --materials ./demo-project/intake-output/materials.json \
  --contract ./demo-project/intake-output/operator-task.json --write-hash
python scripts/validate_intake.py \
  --materials ./demo-project/intake-output/materials.json \
  --contract ./demo-project/intake-output/operator-task.json
```

`--write-hash` 不是批准动作，只能在批准元数据和其余检查通过后执行；它会写入
材料快照哈希和规范化契约哈希。已有任一冻结摘要的旧批准契约不能补签，须新建
修订并重新批准。默认单文件 SHA-256 上限为 64 MiB；超过上限的已选本地材料
会缺少完整哈希，普通材料校验与批准/冻结检查均可能失败；可用采集器的
`--hash-max-mib <上限>` 调整，但应先确认材料大小和读取范围。

三种模式的边界如下：

- `clean-room-generation`：生成上下文只能使用任务语义、公开接口、允许的参考
  资料、工作负载和通用平台文档；已有实现、融合内部细节和实现专属 profiling
  不得进入生成上下文。`forbidden`、`human_review`、`evaluator_only` 的正文
  不得在洁净室中打开。
- `engineering`：在用户和仓库策略允许时可使用源码及 profiling，但仍要保留
  来源和许可证记录。
- `full-analysis`：可广泛追溯和对比；使用后不能再声称同一上下文是洁净室生成。

远端材料不由这些本地脚本访问或实时验证；只接受带算法、摘要、采集时间和定位
信息的摘要证据，并在材料中标记 `source_kind=remote`。因此“校验通过”只代表
结构、关联和已提供摘要证据符合规则，不代表远端文件当前存在，更不代表 NPU
正确性、服务可用性或性能结果。

## 常见问题

- 三处模式不一致：同步 `materials.mode`、`operator-task.json.mode` 和
  `policies.source_mode`，然后重新普通校验。
- 把基线/实现/性能材料设为洁净室生成可见：改为合适的 `visibility`，必要时
  重新选择模式；已污染的上下文不能靠改标签恢复洁净。
- 选中的文件不存在、远端缺少 `digest_evidence`、或已选大文件没有完整哈希：
  补齐真实材料/证据；已批准产物先保留旧快照，再在新修订中盘点，不要填造摘要。
- `--write-hash` 被拒绝：确认状态为 `approved`、证据和批准留痕完整，且不是
  带部分旧哈希的契约。内容变化应走新修订。
- 外部官方 skill validator 可能依赖 PyYAML；本仓库脚本和单元测试不依赖它，
  2026-09-14 的本地检查因缺少 PyYAML 未能执行该校验器。静态检查或脚本测试同样不等于实际算子/NPU
  验证。

## 目录导航

- `SKILL.md`：触发路由、工作边界和完成条件；
- `references/intake-workflow.md`：新建、盘点、提取、批准和生命周期；
- `references/material-policy.md`：模式、可见性和证据优先级；
- `references/contract-schema.md`：JSON 字段、分支和哈希约束；
- `references/questioning.md`：需要用户裁决时的追问方式；
- `assets/`：初始化生成的 JSON/Markdown 模板；
- `scripts/`：三个 CLI 及 `test_intake.py` 回归测试。

当前 `scripts/test_intake.py` 包含 12 个测试用例；维护方式见
[CONTRIBUTING.md](CONTRIBUTING.md)，Astra 适配依据见
[设计说明](references/design-rationale.md)。
