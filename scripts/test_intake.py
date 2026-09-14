#!/usr/bin/env python3
"""无需第三方依赖的需求采集辅助脚本回归测试。"""

from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent


class IntakeScriptsTest(unittest.TestCase):
    def run_script(
        self,
        name: str,
        *args: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPTS / name), *args],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

    def write_approved_fixture(self, root: Path) -> tuple[Path, Path]:
        materials = root / "materials.json"
        roles = [
            "task_scope",
            "executable_reference",
            "workload",
            "acceptance",
            "source_policy",
            "baseline",
        ]
        items = []
        for role in roles:
            path = root / f"{role}.txt"
            path.write_text(role, encoding="utf-8")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            items.append(
                {
                    "id": f"material-{role}",
                    "path": str(path),
                    "source_kind": "local",
                    "sha256": digest,
                    "hash_status": "complete",
                    "roles": [role],
                    "selected": True,
                    "visibility": "generator",
                }
            )
        materials.write_text(
            json.dumps(
                {"schema_version": 1, "mode": "engineering", "items": items}
            ),
            encoding="utf-8",
        )
        tensor = {
            "id": "I-01",
            "name": "x",
            "kind": "input",
            "dtypes": ["bfloat16"],
            "formats": ["ND"],
            "logical_shape": "[T, D]",
            "physical_layout": "最后一维连续",
            "stride": "[S0, 1]",
            "optional": False,
            "mutability": "read-only",
            "alias_of": None,
            "value_constraints": [],
            "source_ids": ["material-task_scope"],
            "status": "confirmed",
        }
        output = {**tensor, "id": "O-01", "name": "y", "kind": "output"}
        branches = {
            name: {
                "disposition": "applicable",
                "rationale": f"已确认 {name}",
                "deferment": None,
            }
            for name in (
                "registration",
                "tensor_contract",
                "state_aliasing",
                "shape_semantics",
                "numerical_behavior",
                "graph_execution",
            )
        }
        contract = root / "operator-task.json"
        contract.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "approved",
                    "mode": "engineering",
                    "operator": {
                        "name": "Example",
                        "target_soc": "ascend910_93",
                        "integration_target": "standalone",
                        "scope": {"included": ["向量阶段"]},
                    },
                    "interface": {
                        "registration": "example_op(Tensor x) -> Tensor",
                        "inputs": [tensor],
                        "outputs": [output],
                        "side_effects": [],
                        "shape_relations": ["y.shape == x.shape"],
                        "graph_mode": {
                            "required": True,
                            "capture_contract": ["形状在捕获时确定"],
                            "replay_contract": ["地址可变"],
                        },
                        "branch_decisions": branches,
                    },
                    "correctness": {
                        "reference_material_ids": [
                            "material-executable_reference"
                        ],
                        "required_cases": ["case-1"],
                        "tolerances": {"atol": 0.001, "rtol": 0.001, "standard": None},
                    },
                    "performance": {
                        "required": True,
                        "baseline_material_ids": ["material-baseline"],
                        "metric": "latency_us",
                        "comparator": "<=",
                        "threshold": 10,
                        "benchmark_case_ids": ["case-1"],
                        "measurement_protocol": "设备事件",
                        "timing_boundary": "候选实现端到端",
                    },
                    "policies": {
                        "source_mode": "engineering",
                        "required_material_roles": roles[:-1],
                    },
                    "decisions": {"unresolved_blockers": []},
                    "evidence": [{
                        "id": "E-interface", "field": "interface",
                        "locator": "task_scope.txt 与用户最终确认",
                        "material_ids": ["material-task_scope"],
                        "status": "confirmed",
                    }],
                    "approval": {
                        "user_confirmed": True,
                        "approved_by": "用户",
                        "approved_at": "2026-09-01T00:00:00Z",
                        "confirmation_record": "用户确认：批准本修订全部契约与材料选择。",
                        "materials_snapshot_sha256": None,
                        "contract_sha256": None,
                    },
                }
            ),
            encoding="utf-8",
        )
        return materials, contract

    def test_approved_evidence_must_be_present_and_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            materials, contract = self.write_approved_fixture(Path(temp))
            original = json.loads(contract.read_text(encoding="utf-8"))
            for evidence in ([], [{
                "id": "E-interface", "field": "interface", "locator": "测试材料",
                "material_ids": ["material-task_scope"], "status": "proposed",
            }]):
                current = {**original, "evidence": evidence}
                contract.write_text(json.dumps(current), encoding="utf-8")
                result = self.run_script("validate_intake.py", "--materials", str(materials),
                                         "--contract", str(contract), "--write-hash")
                self.assertEqual(result.returncode, 1)
            contract.write_text(json.dumps(original), encoding="utf-8")
            manifest = json.loads(materials.read_text(encoding="utf-8"))
            manifest["items"][0]["visibility"] = "evaluator_only"
            materials.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_script("validate_intake.py", "--materials", str(materials),
                                     "--contract", str(contract), "--write-hash")
            self.assertEqual(result.returncode, 1)
            self.assertIn("生成者不可见", result.stderr)

    def test_initialize_collect_and_validate_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / "package"
            package.mkdir()
            (package / "TASK_AND_ACCEPTANCE.md").write_text(
                "任务",
                encoding="utf-8",
            )
            (package / "reference.py").write_text(
                "def run(): pass",
                encoding="utf-8",
            )
            (package / "workload.jsonl").write_text("{}\n", encoding="utf-8")
            (package / "NO_LEAK_POLICY.md").write_text(
                "策略",
                encoding="utf-8",
            )

            intake = root / "intake"
            result = self.run_script(
                "init_intake.py",
                "--operator",
                "ExampleOp",
                "--task-root",
                str(root),
                "--output-dir",
                str(intake),
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            result = self.run_script(
                "collect_materials.py",
                "--root",
                str(package),
                "--output",
                str(intake / "materials.json"),
                "--report",
                str(intake / "material-report.md"),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(
                (intake / "materials.json").read_text(encoding="utf-8")
            )
            roles = {
                role for item in manifest["items"] for role in item["roles"]
            }
            expected_roles = {
                "task_scope",
                "acceptance",
                "executable_reference",
                "workload",
                "source_policy",
            }
            self.assertTrue(expected_roles.issubset(roles))

            result = self.run_script(
                "validate_intake.py",
                "--materials",
                str(intake / "materials.json"),
                "--contract",
                str(intake / "operator-task.json"),
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_clean_room_rejects_generator_visible_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / "package"
            package.mkdir()
            (package / "fused_baseline.cpp").write_text(
                "// 实现",
                encoding="utf-8",
            )
            output = root / "materials.json"
            result = self.run_script(
                "collect_materials.py",
                "--root",
                str(package),
                "--output",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(output.read_text(encoding="utf-8"))
            manifest["items"][0]["selected"] = True
            manifest["items"][0]["visibility"] = "generator"
            output.write_text(json.dumps(manifest), encoding="utf-8")
            contract = root / "operator-task.json"
            contract.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "draft",
                        "mode": "clean-room-generation",
                        "operator": {"name": "Example"},
                        "interface": {"inputs": [], "outputs": []},
                        "correctness": {"reference_material_ids": []},
                        "performance": {"baseline_material_ids": []},
                        "policies": {"required_material_roles": []},
                        "decisions": {"unresolved_blockers": []},
                        "evidence": [],
                        "approval": {"contract_sha256": None},
                    }
                ),
                encoding="utf-8",
            )
            result = self.run_script(
                "validate_intake.py",
                "--materials",
                str(output),
                "--contract",
                str(contract),
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("洁净室生成智能体", result.stderr)

    def test_approved_contract_can_be_frozen_and_revalidated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            materials, contract = self.write_approved_fixture(root)
            result = self.run_script(
                "validate_intake.py",
                "--materials",
                str(materials),
                "--contract",
                str(contract),
                "--write-hash",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            frozen = json.loads(contract.read_text(encoding="utf-8"))
            self.assertRegex(
                frozen["approval"]["contract_sha256"],
                r"^[0-9a-f]{64}$",
            )
            self.assertRegex(
                frozen["approval"]["materials_snapshot_sha256"],
                r"^[0-9a-f]{64}$",
            )
            result = self.run_script(
                "validate_intake.py",
                "--materials",
                str(materials),
                "--contract",
                str(contract),
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            (root / "workload.txt").write_text("changed", encoding="utf-8")
            result = self.run_script(
                "validate_intake.py",
                "--materials",
                str(materials),
                "--contract",
                str(contract),
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("实际内容不一致", result.stderr)

            (root / "workload.txt").write_text("workload", encoding="utf-8")
            manifest = json.loads(materials.read_text(encoding="utf-8"))
            manifest["items"][0]["visibility"] = "evaluator_only"
            materials.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_script(
                "validate_intake.py",
                "--materials",
                str(materials),
                "--contract",
                str(contract),
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("材料快照哈希", result.stderr)

    def test_approved_without_hash_is_rejected_without_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            materials, contract = self.write_approved_fixture(Path(temp))
            result = self.run_script(
                "validate_intake.py",
                "--materials",
                str(materials),
                "--contract",
                str(contract),
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("contract_sha256", result.stderr)

            data = json.loads(contract.read_text(encoding="utf-8"))
            data["approval"]["confirmation_record"] = None
            contract.write_text(json.dumps(data), encoding="utf-8")
            result = self.run_script(
                "validate_intake.py",
                "--materials",
                str(materials),
                "--contract",
                str(contract),
                "--write-hash",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("confirmation_record", result.stderr)

    def test_mode_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            materials, contract = self.write_approved_fixture(Path(temp))
            data = json.loads(contract.read_text(encoding="utf-8"))
            data["policies"]["source_mode"] = "full-analysis"
            contract.write_text(json.dumps(data), encoding="utf-8")
            result = self.run_script(
                "validate_intake.py",
                "--materials",
                str(materials),
                "--contract",
                str(contract),
                "--write-hash",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("必须一致", result.stderr)

    def test_selected_missing_local_material_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            materials, contract = self.write_approved_fixture(root)
            (root / "workload.txt").unlink()
            result = self.run_script(
                "validate_intake.py",
                "--materials",
                str(materials),
                "--contract",
                str(contract),
                "--write-hash",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("不存在或不是文件", result.stderr)

    def test_incomplete_interface_branch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            materials, contract = self.write_approved_fixture(Path(temp))
            data = json.loads(contract.read_text(encoding="utf-8"))
            data["interface"]["branch_decisions"]["graph_execution"] = {
                "disposition": "pending",
                "rationale": None,
            }
            contract.write_text(json.dumps(data), encoding="utf-8")
            result = self.run_script(
                "validate_intake.py",
                "--materials",
                str(materials),
                "--contract",
                str(contract),
                "--write-hash",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("graph_execution.disposition", result.stderr)

    def test_applicable_branch_requires_its_contract_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            materials, contract = self.write_approved_fixture(Path(temp))
            data = json.loads(contract.read_text(encoding="utf-8"))
            data["interface"]["registration"] = None
            contract.write_text(json.dumps(data), encoding="utf-8")
            result = self.run_script(
                "validate_intake.py",
                "--materials",
                str(materials),
                "--contract",
                str(contract),
                "--write-hash",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("registration 标记为 applicable", result.stderr)

            data = json.loads(contract.read_text(encoding="utf-8"))
            data["interface"]["registration"] = "example_op(Tensor x) -> Tensor"
            data["interface"]["graph_mode"]["capture_contract"] = []
            contract.write_text(json.dumps(data), encoding="utf-8")
            result = self.run_script(
                "validate_intake.py",
                "--materials",
                str(materials),
                "--contract",
                str(contract),
                "--write-hash",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("capture_contract 和 replay_contract", result.stderr)

    def test_remote_material_requires_digest_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            materials, contract = self.write_approved_fixture(Path(temp))
            manifest = json.loads(materials.read_text(encoding="utf-8"))
            item = manifest["items"][0]
            item["source_kind"] = "remote"
            item["path"] = "/remote/task.txt"
            item["sha256"] = None
            item.pop("digest_evidence", None)
            materials.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_script(
                "validate_intake.py",
                "--materials",
                str(materials),
                "--contract",
                str(contract),
                "--write-hash",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("远端材料缺少 digest_evidence", result.stderr)

    def test_old_partial_hash_cannot_be_silently_completed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            materials, contract = self.write_approved_fixture(Path(temp))
            data = json.loads(contract.read_text(encoding="utf-8"))
            data["approval"]["contract_sha256"] = "0" * 64
            contract.write_text(json.dumps(data), encoding="utf-8")
            result = self.run_script(
                "validate_intake.py",
                "--materials",
                str(materials),
                "--contract",
                str(contract),
                "--write-hash",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("materials_snapshot_sha256", result.stderr)

    def test_invalid_items_shape_reports_error_instead_of_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            materials = root / "materials.json"
            materials.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "mode": "engineering",
                        "items": None,
                    }
                ),
                encoding="utf-8",
            )
            contract = root / "operator-task.json"
            contract.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "draft",
                        "mode": "engineering",
                        "operator": {"name": "Example"},
                        "interface": {"inputs": [], "outputs": []},
                        "correctness": {"reference_material_ids": []},
                        "performance": {"baseline_material_ids": []},
                        "policies": {
                            "source_mode": "engineering",
                            "required_material_roles": [],
                        },
                        "decisions": {"unresolved_blockers": []},
                        "evidence": [],
                    }
                ),
                encoding="utf-8",
            )
            result = self.run_script(
                "validate_intake.py",
                "--materials",
                str(materials),
                "--contract",
                str(contract),
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("materials.items 必须是数组", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
