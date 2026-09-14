#!/usr/bin/env python3
"""在不读取正文的前提下盘点算子材料。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKIP_DIRS = {".git", ".svn", "node_modules", "__pycache__", ".pytest_cache"}
MODES = {"clean-room-generation", "engineering", "full-analysis"}


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


def add_role(roles: list[str], role: str) -> None:
    if role not in roles:
        roles.append(role)


def classify(path: Path) -> list[str]:
    name = path.name.lower()
    stem = path.stem.lower()
    suffix = path.suffix.lower()
    roles: list[str] = []

    if name == "manifest.json":
        add_role(roles, "package_manifest")
    if "no_leak" in name or "sources_allowed" in name or "source-policy" in name:
        add_role(roles, "source_policy")
    if re.search(r"(^|[_-])task([_-]|\.|$)", name):
        add_role(roles, "task_scope")
    if "acceptance" in name or "验收" in name:
        add_role(roles, "acceptance")
    if name == "definition.json" or "interface" in name or "接口" in name:
        add_role(roles, "interface_definition")
    if "reference_extraction" in name or "reference-boundary" in name:
        add_role(roles, "reference_boundary")
    if (
        name == "reference.py"
        or "golden" in name
        or "reference_impl" in name
        or "参考实现" in name
    ):
        add_role(roles, "executable_reference")
    if "workload" in name or "work_load" in name:
        add_role(roles, "workload")
    if "performance_case" in name or "perf_case" in name:
        add_role(roles, "performance_cases")
    if "kernelbench" in name and "config" in name:
        add_role(roles, "evaluation_config")
    if re.search(r"profil|msprof|timeline|op_summary|kernel_details|trace", name):
        add_role(roles, "profiling")
    if "baseline" in name or "基线" in name:
        add_role(roles, "baseline")
    if suffix in {".safetensors", ".ckpt", ".pth", ".pt", ".onnx"}:
        add_role(roles, "model_weights")
    if suffix in {".zip", ".tar", ".gz", ".tgz", ".7z"}:
        add_role(roles, "archive")
    if suffix in {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".tiling"}:
        add_role(roles, "implementation_source")
    if not roles and (stem == "readme" or "design" in name or "设计" in name):
        add_role(roles, "supporting_documentation")
    if not roles:
        add_role(roles, "other")
    return roles


def priority_for(roles: list[str]) -> str:
    required = {
        "task_scope",
        "acceptance",
        "interface_definition",
        "executable_reference",
        "workload",
        "source_policy",
    }
    recommended = {
        "package_manifest",
        "reference_boundary",
        "performance_cases",
        "evaluation_config",
    }
    if required.intersection(roles):
        return "required"
    if recommended.intersection(roles):
        return "recommended"
    return "optional"


def visibility_for(mode: str, roles: list[str]) -> str:
    if mode == "clean-room-generation":
        if "profiling" in roles:
            return "evaluator_only"
        if {"baseline", "implementation_source"}.intersection(roles):
            return "human_review"
    return "generator"


def stable_id(root_index: int, relative_path: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", Path(relative_path).stem.lower()).strip("-")
    slug = (slug or "file")[:40]
    digest = hashlib.sha1(
        f"{root_index}:{relative_path}".encode("utf-8")
    ).hexdigest()[:8]
    return f"material-{slug}-{digest}"


def sha256_file(path: Path, max_bytes: int) -> tuple[str | None, str]:
    size = path.stat().st_size
    if size > max_bytes:
        return None, "skipped_size_limit"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest(), "complete"


def load_existing(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(item.get("path")): item for item in data.get("items", [])}


def iter_files(root: Path, include_hidden: bool):
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [
            directory
            for directory in dirs
            if directory not in SKIP_DIRS
            and (include_hidden or not directory.startswith("."))
        ]
        for name in sorted(files):
            if not include_hidden and name.startswith("."):
                continue
            path = Path(current) / name
            if path.is_symlink() or not path.is_file():
                continue
            yield path


def write_report(path: Path, manifest: dict[str, Any]) -> None:
    counts = Counter()
    for item in manifest["items"]:
        counts.update(item["roles"])
    lines = [
        "# 材料清单",
        "",
        f"模式：`{manifest['mode']}`  ",
        f"文件数：{len(manifest['items'])}",
        "",
        "## 角色统计",
        "",
    ]
    for role, count in sorted(counts.items()):
        lines.append(f"- `{role}`: {count}")
    lines.extend(["", "## 材料", ""])
    for item in manifest["items"]:
        selection = "已选择" if item["selected"] else "未选择"
        lines.append(
            f"- `{item['id']}` — `{item['relative_path']}` — "
            f"{', '.join(item['roles'])}; {item['visibility']}; {selection}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def parse_args() -> argparse.Namespace:
    parser = ChineseArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        action="append",
        required=True,
        type=Path,
        help="待盘点的材料根目录；可重复指定",
    )
    parser.add_argument(
        "--mode",
        choices=sorted(MODES),
        default="clean-room-generation",
        help="材料使用模式",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="materials.json 输出路径",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="可选的 Markdown 材料报告路径",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="包含隐藏文件和隐藏目录",
    )
    parser.add_argument(
        "--hash-max-mib",
        type=int,
        default=64,
        help="计算 SHA-256 的单文件大小上限（MiB）",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    roots = [root.expanduser().resolve() for root in args.root]
    missing = [root for root in roots if not root.is_dir()]
    if missing:
        for root in missing:
            print(f"错误：材料根路径不是目录：{root}", file=sys.stderr)
        return 2

    output = args.output.expanduser().resolve()
    existing = load_existing(output)
    max_bytes = args.hash_max_mib * 1024 * 1024
    items: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    for root_index, root in enumerate(roots):
        for path in iter_files(root, args.include_hidden):
            resolved = str(path.resolve())
            if resolved == str(output) or resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            relative = path.relative_to(root).as_posix()
            roles = classify(path)
            priority = priority_for(roles)
            visibility = visibility_for(args.mode, roles)
            digest, hash_status = sha256_file(path, max_bytes)
            stat = path.stat()
            prior = existing.get(resolved, {})
            item = {
                "id": prior.get("id", stable_id(root_index, relative)),
                "root_index": root_index,
                "path": resolved,
                "source_kind": "local",
                "relative_path": relative,
                "bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
                "sha256": digest,
                "hash_status": hash_status,
                "roles": roles,
                "priority": priority,
                "selected": prior.get(
                    "selected",
                    priority in {"required", "recommended"}
                    and visibility == "generator",
                ),
                "visibility": prior.get("visibility", visibility),
                "source_of_truth": prior.get("source_of_truth", False),
                "user_notes": prior.get("user_notes", ""),
            }
            items.append(item)

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "roots": [str(root) for root in roots],
        "items": sorted(
            items, key=lambda item: (item["root_index"], item["relative_path"])
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if args.report:
        write_report(args.report.expanduser().resolve(), manifest)

    print(f"输出文件={output}")
    print(f"文件数={len(items)}")
    print(f"已选择={sum(1 for item in items if item['selected'])}")
    print(
        "需人工审阅="
        f"{sum(1 for item in items if item['visibility'] == 'human_review')}"
    )
    print(
        "仅评测方可见="
        f"{sum(1 for item in items if item['visibility'] == 'evaluator_only')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
