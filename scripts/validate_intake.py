#!/usr/bin/env python3
"""校验 Ascend 算子需求采集产物，并可选择冻结契约。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


VALID_MODES = {"clean-room-generation", "engineering", "full-analysis"}
VALID_VISIBILITIES = {
    "generator",
    "evaluator_only",
    "human_review",
    "forbidden",
}
VALID_STATUSES = {"draft", "reviewed", "approved", "superseded"}
VALID_SOURCE_KINDS = {"local", "remote"}
SHA256_LENGTH = 64
REQUIRED_INTERFACE_BRANCHES = {
    "registration",
    "tensor_contract",
    "state_aliasing",
    "shape_semantics",
    "numerical_behavior",
    "graph_execution",
}


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


class ChineseArgumentParser(argparse.ArgumentParser):
    """把 argparse 的固定帮助标签改为中文。"""

    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "用法：")

    def format_help(self) -> str:
        return (
            super()
            .format_help()
            .replace("usage:", "用法：")
            .replace("options:", "选项：")
            .replace("show this help message and exit", "显示帮助信息并退出")
        )

    def error(self, message: str) -> None:
        message = (
            message.replace("the following arguments are required:", "缺少必需参数：")
            .replace("argument ", "参数 ")
            .replace("invalid choice:", "无效选项：")
            .replace("expected one argument", "需要一个参数值")
            .replace("choose from", "可选值")
        )
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: 错误：{message}\n")


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"找不到文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"文件中的 JSON 无效：{path}：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层值必须是对象：{path}")
    return data


def canonical_contract_hash(contract: dict[str, Any]) -> str:
    clone = json.loads(json.dumps(contract))
    clone.setdefault("approval", {})["contract_sha256"] = None
    payload = json.dumps(
        clone,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value.lower())
    )


def material_snapshot(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """构造冻结快照；本地摘要实际复算，远端摘要只接受显式证据。"""
    errors: list[str] = []
    selected: list[dict[str, Any]] = []
    items = data.get("items")
    if not isinstance(items, list):
        return {"mode": data.get("mode"), "selected": []}, [
            "materials.items 无法构造材料快照"
        ]
    for index, item in enumerate(items):
        if not isinstance(item, dict) or item.get("selected") is not True:
            continue
        prefix = f"materials.items[{index}]"
        source_kind = item.get("source_kind", "local")
        digest: str | None = None
        if source_kind == "local":
            path_value = item.get("path")
            path = Path(path_value) if isinstance(path_value, str) else None
            if path is None or not path.is_file():
                errors.append(f"{prefix} 已选择的本地材料不存在或不是文件")
            elif item.get("hash_status") != "complete" or not valid_sha256(
                item.get("sha256")
            ):
                errors.append(f"{prefix} 已选择的本地材料缺少完整 SHA-256 摘要")
            else:
                try:
                    digest = sha256_file(path)
                except OSError as exc:
                    errors.append(f"{prefix} 无法读取本地材料以复算摘要：{exc}")
                else:
                    if digest != item["sha256"].lower():
                        errors.append(f"{prefix} 本地材料 SHA-256 与实际内容不一致")
        elif source_kind == "remote":
            evidence = item.get("digest_evidence")
            if not isinstance(evidence, dict):
                errors.append(f"{prefix} 远端材料缺少 digest_evidence")
            elif (
                evidence.get("algorithm") != "sha256"
                or not valid_sha256(evidence.get("digest"))
                or not evidence.get("collected_at")
                or not evidence.get("locator")
            ):
                errors.append(
                    f"{prefix} 远端摘要证据必须包含 sha256 digest、collected_at 和 locator"
                )
            else:
                digest = evidence["digest"].lower()
                if item.get("sha256") not in (None, digest):
                    errors.append(f"{prefix} 远端摘要证据与 sha256 字段不一致")
        else:
            errors.append(f"{prefix}.source_kind 必须是以下值之一：{sorted(VALID_SOURCE_KINDS)}")
        selected.append(
            {
                "id": item.get("id"),
                "path": item.get("path"),
                "roles": item.get("roles"),
                "sha256": digest,
                "source_kind": source_kind,
                "source_of_truth": item.get("source_of_truth"),
                "source_locator": (
                    item.get("digest_evidence", {}).get("locator")
                    if isinstance(item.get("digest_evidence"), dict)
                    else None
                ),
                "visibility": item.get("visibility"),
            }
        )
    return {
        "mode": data.get("mode"),
        "selected": sorted(selected, key=lambda item: str(item["id"])),
    }, errors


def canonical_materials_snapshot_hash(data: dict[str, Any]) -> tuple[str, list[str]]:
    snapshot, errors = material_snapshot(data)
    payload = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), errors


def validate_materials(
    data: dict[str, Any],
) -> tuple[list[str], list[str], set[str], set[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    ids: set[str] = set()
    selected_roles: set[str] = set()

    if data.get("schema_version") != 1:
        errors.append("materials.schema_version 必须为 1")
    mode = data.get("mode")
    if mode not in VALID_MODES:
        errors.append(f"materials.mode 必须是以下值之一：{sorted(VALID_MODES)}")
    items = data.get("items")
    if not isinstance(items, list):
        errors.append("materials.items 必须是数组")
        return errors, warnings, ids, selected_roles

    for index, item in enumerate(items):
        prefix = f"materials.items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} 必须是对象")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            errors.append(f"{prefix}.id 必须是非空字符串")
        elif item_id in ids:
            errors.append(f"材料 ID 重复：{item_id}")
        else:
            ids.add(item_id)
        if not isinstance(item.get("path"), str) or not item["path"]:
            errors.append(f"{prefix}.path 必须是非空字符串")
        source_kind = item.get("source_kind", "local")
        if source_kind not in VALID_SOURCE_KINDS:
            errors.append(
                f"{prefix}.source_kind 必须是以下值之一：{sorted(VALID_SOURCE_KINDS)}"
            )
        roles = item.get("roles")
        if (
            not isinstance(roles, list)
            or not roles
            or not all(isinstance(role, str) for role in roles)
        ):
            errors.append(f"{prefix}.roles 必须是非空字符串数组")
            roles = []
        visibility = item.get("visibility")
        if visibility not in VALID_VISIBILITIES:
            errors.append(f"{prefix}.visibility 无效")
        selected = item.get("selected")
        if not isinstance(selected, bool):
            errors.append(f"{prefix}.selected 必须是布尔值")
        if selected:
            if visibility == "generator":
                selected_roles.update(roles)
            if visibility == "forbidden":
                errors.append(f"{prefix} 同时被标记为已选择和禁止使用")
            unsafe_roles = {"baseline", "implementation_source", "profiling"}
            if (
                mode == "clean-room-generation"
                and visibility == "generator"
                and unsafe_roles.intersection(roles)
            ):
                errors.append(
                    f"{prefix} 把实现、基线或性能剖析材料暴露给了"
                    "洁净室生成智能体"
                )
        if item.get("hash_status") == "skipped_size_limit":
            warnings.append(
                f"{prefix} 超过大小上限，未计算哈希"
            )
    return errors, warnings, ids, selected_roles


def validate_tensor(
    tensor: Any,
    prefix: str,
    approved: bool,
    require_physical_contract: bool,
    errors: list[str],
) -> None:
    if not isinstance(tensor, dict):
        errors.append(f"{prefix} 必须是对象")
        return
    for field in ("id", "name", "kind"):
        if not isinstance(tensor.get(field), str) or not tensor[field]:
            errors.append(f"{prefix}.{field} 必须是非空字符串")
    for field in ("dtypes", "formats"):
        if not isinstance(tensor.get(field), list):
            errors.append(f"{prefix}.{field} 必须是数组")
    if approved:
        if not tensor.get("logical_shape"):
            errors.append(f"{prefix}.logical_shape 是批准契约的必填字段")
    if approved and require_physical_contract:
        for field in ("physical_layout", "stride", "mutability"):
            if not tensor.get(field):
                errors.append(f"{prefix}.{field} 是批准契约的必填字段")
        if not isinstance(tensor.get("optional"), bool):
            errors.append(f"{prefix}.optional 在批准时必须是布尔值")
        for field in ("value_constraints", "source_ids"):
            if not isinstance(tensor.get(field), list):
                errors.append(f"{prefix}.{field} 在批准时必须是数组")
        if "alias_of" not in tensor:
            errors.append(f"{prefix}.alias_of 在批准时必须显式填写（可为 null）")
    if approved:
        if tensor.get("status") not in {"confirmed", "deferred"}:
            errors.append(
                f"{prefix}.status 在批准时必须为 confirmed 或 deferred"
            )


def validate_contract(
    data: dict[str, Any],
    material_ids: set[str],
    selected_roles: set[str],
    materials_mode: Any,
    allow_pending_hash: bool = False,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("contract.schema_version 必须为 1")
    if data.get("status") not in VALID_STATUSES:
        errors.append(
            f"contract.status 必须是以下值之一：{sorted(VALID_STATUSES)}"
        )
    if data.get("mode") not in VALID_MODES:
        errors.append(f"contract.mode 必须是以下值之一：{sorted(VALID_MODES)}")
    elif data.get("mode") != materials_mode:
        errors.append("materials.mode、contract.mode 与 policies.source_mode 必须一致")
    approved = data.get("status") == "approved"

    operator = data.get("operator")
    if not isinstance(operator, dict) or not operator.get("name"):
        errors.append("contract.operator.name 为必填字段")
    elif approved:
        if not operator.get("target_soc"):
            errors.append("批准契约时必须填写 contract.operator.target_soc")
        if not operator.get("integration_target"):
            errors.append(
                "批准契约时必须填写 contract.operator.integration_target"
            )
        scope = operator.get("scope", {})
        if not isinstance(scope.get("included"), list) or not scope["included"]:
            errors.append(
                "批准契约时 contract.operator.scope.included 不得为空"
            )

    interface = data.get("interface")
    if not isinstance(interface, dict):
        errors.append("contract.interface 必须是对象")
    else:
        branches = interface.get("branch_decisions")
        tensor_contract_applicable = (
            isinstance(branches, dict)
            and isinstance(branches.get("tensor_contract"), dict)
            and branches["tensor_contract"].get("disposition") == "applicable"
        )
        state_aliasing_applicable = (
            isinstance(branches, dict)
            and isinstance(branches.get("state_aliasing"), dict)
            and branches["state_aliasing"].get("disposition") == "applicable"
        )
        require_physical_contract = (
            tensor_contract_applicable or state_aliasing_applicable
        )
        inputs = interface.get("inputs")
        outputs = interface.get("outputs")
        if not isinstance(inputs, list) or not isinstance(outputs, list):
            errors.append("contract.interface.inputs 和 outputs 必须是数组")
        else:
            for index, tensor in enumerate(inputs):
                validate_tensor(
                    tensor,
                    f"contract.interface.inputs[{index}]",
                    approved,
                    require_physical_contract,
                    errors,
                )
            for index, tensor in enumerate(outputs):
                validate_tensor(
                    tensor,
                    f"contract.interface.outputs[{index}]",
                    approved,
                    require_physical_contract,
                    errors,
                )
            if approved and (not inputs or not outputs):
                errors.append(
                    "批准契约必须至少定义一个输入和一个输出"
                )
        if approved:
            if not isinstance(branches, dict):
                errors.append("批准契约必须填写 contract.interface.branch_decisions")
            else:
                for branch in sorted(REQUIRED_INTERFACE_BRANCHES):
                    decision = branches.get(branch)
                    prefix = f"contract.interface.branch_decisions.{branch}"
                    if not isinstance(decision, dict):
                        errors.append(f"{prefix} 必须是对象")
                        continue
                    disposition = decision.get("disposition")
                    if disposition not in {"applicable", "not_applicable", "deferred"}:
                        errors.append(
                            f"{prefix}.disposition 必须为 applicable、not_applicable 或 deferred"
                        )
                    if disposition in {"applicable", "not_applicable"} and not decision.get("rationale"):
                        errors.append(f"{prefix}.rationale 不得为空")
                    if disposition == "deferred":
                        deferment = decision.get("deferment")
                        required = ("default", "risk", "owner", "validation_plan")
                        if not isinstance(deferment, dict) or any(
                            not deferment.get(field) for field in required
                        ):
                            errors.append(
                                f"{prefix}.deferment 必须填写 default、risk、owner 和 validation_plan"
                            )
                applicable_fields = {
                    "registration": interface.get("registration"),
                    "shape_semantics": interface.get("shape_relations"),
                    "numerical_behavior": data.get("correctness", {}).get("tolerances"),
                    "graph_execution": interface.get("graph_mode"),
                }
                for branch, value in applicable_fields.items():
                    decision = branches.get(branch, {})
                    if decision.get("disposition") != "applicable":
                        continue
                    if branch in {"registration", "shape_semantics"} and not value:
                        errors.append(
                            f"{branch} 标记为 applicable 时必须填写对应契约字段"
                        )
                    elif branch == "numerical_behavior" and (
                        not isinstance(value, dict)
                        or all(value.get(key) is None for key in ("atol", "rtol", "standard"))
                    ):
                        errors.append("numerical_behavior 标记为 applicable 时必须填写容差契约")
                    elif branch == "graph_execution" and (
                        not isinstance(value, dict)
                        or not isinstance(value.get("required"), bool)
                    ):
                        errors.append("graph_execution 标记为 applicable 时必须明确 required")
                    elif (
                        branch == "graph_execution"
                        and value.get("required") is True
                        and (
                            not value.get("capture_contract")
                            or not value.get("replay_contract")
                        )
                    ):
                        errors.append(
                            "graph_execution required=true 时必须填写 capture_contract 和 replay_contract"
                        )
                if state_aliasing_applicable and not isinstance(
                    interface.get("side_effects"), list
                ):
                    errors.append("state_aliasing 标记为 applicable 时 side_effects 必须是数组")

    policies = data.get("policies", {})
    if policies.get("source_mode") not in VALID_MODES:
        errors.append("contract.policies.source_mode 无效")
    elif policies.get("source_mode") != data.get("mode"):
        errors.append("materials.mode、contract.mode 与 policies.source_mode 必须一致")
    required_roles = policies.get("required_material_roles", [])
    if not isinstance(required_roles, list):
        errors.append(
            "contract.policies.required_material_roles 必须是数组"
        )
    elif approved:
        missing_roles = sorted(set(required_roles) - selected_roles)
        if missing_roles:
            errors.append(
                "已选材料缺少必需角色："
                + ", ".join(missing_roles)
            )

    references = (
        ("correctness", "reference_material_ids"),
        ("performance", "baseline_material_ids"),
    )
    for section, field in references:
        values = data.get(section, {}).get(field, [])
        if not isinstance(values, list):
            errors.append(f"contract.{section}.{field} 必须是数组")
            continue
        unknown = sorted(set(values) - material_ids)
        if unknown:
            errors.append(
                f"contract.{section}.{field} 包含未知材料 ID："
                + ", ".join(unknown)
            )

    decisions = data.get("decisions", {})
    blockers = decisions.get("unresolved_blockers", [])
    if not isinstance(blockers, list):
        errors.append("contract.decisions.unresolved_blockers 必须是数组")
    elif approved and blockers:
        errors.append("批准契约不能包含未解决的阻塞项")

    if approved:
        correctness = data.get("correctness", {})
        if not correctness.get("reference_material_ids"):
            errors.append(
                "批准契约至少需要一个正确性参考材料"
            )
        if not correctness.get("required_cases"):
            errors.append("批准契约必须包含正确性用例")
        performance = data.get("performance", {})
        if performance.get("required", False):
            required_performance = (
                "baseline_material_ids",
                "metric",
                "comparator",
                "threshold",
                "benchmark_case_ids",
                "measurement_protocol",
                "timing_boundary",
            )
            for field in required_performance:
                value = performance.get(field)
                if value is None or value == [] or value == "":
                    errors.append(
                        f"批准契约时必须填写 contract.performance.{field}"
                    )
        approval = data.get("approval", {})
        if approval.get("user_confirmed") is not True:
            errors.append("contract.approval.user_confirmed 必须为 true")
        if not approval.get("approved_by") or not approval.get("approved_at"):
            errors.append(
                "批准契约必须填写 approved_by 和 approved_at"
            )
        if not approval.get("confirmation_record"):
            errors.append("批准契约必须填写中文最终确认留痕 confirmation_record")
        stored_contract_hash = approval.get("contract_sha256")
        stored_materials_hash = approval.get("materials_snapshot_sha256")
        if not allow_pending_hash:
            if not valid_sha256(stored_contract_hash):
                errors.append("批准契约必须包含有效的 contract_sha256")
            if not valid_sha256(stored_materials_hash):
                errors.append("批准契约必须包含有效的 materials_snapshot_sha256")

    evidence = data.get("evidence", [])
    if not isinstance(evidence, list):
        errors.append("contract.evidence 必须是数组")
    else:
        if approved and not evidence:
            errors.append("批准契约必须包含字段级证据或用户决策定位")
        for index, record in enumerate(evidence):
            if not isinstance(record, dict):
                errors.append(f"contract.evidence[{index}] 必须是对象")
                continue
            if approved:
                for key in ("id", "field", "locator"):
                    if not isinstance(record.get(key), str) or not record[key].strip():
                        errors.append(f"contract.evidence[{index}].{key} 不得为空")
                if record.get("status") != "confirmed":
                    errors.append(f"contract.evidence[{index}] 批准时必须为 confirmed")
            refs = record.get("material_ids", [])
            if not isinstance(refs, list):
                errors.append(
                    f"contract.evidence[{index}].material_ids 必须是数组"
                )
            else:
                unknown = sorted(set(refs) - material_ids)
                if unknown:
                    errors.append(
                        f"contract.evidence[{index}] 包含未知材料 ID："
                        + ", ".join(unknown)
                    )
    return errors, warnings


def parse_args() -> argparse.Namespace:
    parser = ChineseArgumentParser(description=__doc__)
    parser.add_argument(
        "--materials",
        required=True,
        type=Path,
        help="materials.json 路径",
    )
    parser.add_argument(
        "--contract",
        required=True,
        type=Path,
        help="operator-task.json 路径",
    )
    parser.add_argument(
        "--write-hash",
        action="store_true",
        help="其他批准检查全部通过后，写入规范化契约哈希",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        materials = load_json(args.materials)
        contract = load_json(args.contract)
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    material_result = validate_materials(materials)
    material_errors, material_warnings, ids, roles = material_result
    approval = contract.get("approval", {})
    allow_pending_hash = (
        args.write_hash
        and not approval.get("contract_sha256")
        and not approval.get("materials_snapshot_sha256")
    )
    contract_errors, contract_warnings = validate_contract(
        contract,
        ids,
        roles,
        materials.get("mode"),
        allow_pending_hash,
    )
    errors = material_errors + contract_errors
    warnings = material_warnings + contract_warnings

    # 基线可只供评测，但提取的字段证据必须来自已选且对生成者可见的材料。
    items = materials.get("items", [])
    if isinstance(items, list):
        visible_ids = {
            item.get("id") for item in items
            if isinstance(item, dict) and isinstance(item.get("id"), str)
            and item.get("selected") is True and item.get("visibility") == "generator"
        }
        records = contract.get("evidence", [])
        if isinstance(records, list):
            for record in records:
                if not isinstance(record, dict):
                    continue
                refs = record.get("material_ids", [])
                if isinstance(refs, list) and any(
                    not isinstance(ref, str) or ref not in visible_ids for ref in refs
                ):
                    errors.append("字段证据引用了未选中或生成者不可见的材料")

    expected_materials_hash, snapshot_errors = canonical_materials_snapshot_hash(materials)
    errors.extend(snapshot_errors)
    expected_hash = canonical_contract_hash(contract)
    stored_hash = contract.get("approval", {}).get("contract_sha256")
    if stored_hash and stored_hash != expected_hash:
        errors.append(
            "已保存的契约哈希与当前契约内容不一致"
        )
    stored_materials_hash = contract.get("approval", {}).get(
        "materials_snapshot_sha256"
    )
    if stored_materials_hash and stored_materials_hash != expected_materials_hash:
        errors.append("已保存的材料快照哈希与当前选择、模式、可见性或内容不一致")

    for warning in warnings:
        print(f"警告：{warning}")
    for error in errors:
        print(f"错误：{error}", file=sys.stderr)
    if errors:
        print(
            f"校验=失败 错误数={len(errors)} 警告数={len(warnings)}"
        )
        return 1

    if args.write_hash:
        if contract.get("status") != "approved":
            print(
                "错误：--write-hash 要求 contract.status=approved",
                file=sys.stderr,
            )
            return 1
        approval = contract.setdefault("approval", {})
        if approval.get("contract_sha256") or approval.get("materials_snapshot_sha256"):
            print(
                "错误：已有部分或完整冻结摘要；旧批准合同或材料变化必须创建新修订版后重新批准",
                file=sys.stderr,
            )
            return 1
        approval["materials_snapshot_sha256"] = expected_materials_hash
        expected_hash = canonical_contract_hash(contract)
        approval["contract_sha256"] = expected_hash
        args.contract.write_text(
            json.dumps(contract, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"契约_SHA256={expected_hash}")

    print(f"校验=通过 警告数={len(warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
