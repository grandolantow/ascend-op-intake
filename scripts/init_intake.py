#!/usr/bin/env python3
"""初始化可恢复的 Ascend 算子需求采集工作区。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


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


def operator_slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    if not slug:
        raise ValueError("算子名称必须至少包含一个字母或数字")
    return slug


def render(template: Path, replacements: dict[str, str]) -> str:
    text = template.read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace("{{" + key + "}}", value)
    if re.search(r"\{\{[A-Z0-9_]+\}\}", text):
        raise ValueError(f"模板中存在未替换的占位符：{template}")
    return text


def parse_args() -> argparse.Namespace:
    parser = ChineseArgumentParser(description=__doc__)
    parser.add_argument(
        "--operator",
        required=True,
        help="面向用户展示的算子名称",
    )
    parser.add_argument(
        "--task-root",
        required=True,
        type=Path,
        help="任务根目录",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="需求采集产物目录；默认位于任务根目录的 dev_docs 下",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="保留已有产物，只创建缺失文件",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    task_root = args.task_root.expanduser().resolve()
    if not task_root.is_dir():
        print(f"错误：任务根路径不是目录：{task_root}", file=sys.stderr)
        return 2

    slug = operator_slug(args.operator)
    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir
        else task_root / "dev_docs" / slug / "intake"
    )
    skill_root = Path(__file__).resolve().parents[1]
    assets = skill_root / "assets"
    materials_path = output_dir / "materials.json"

    replacements = {
        "OPERATOR_NAME": args.operator,
        "OPERATOR_SLUG": slug,
        "TASK_ROOT": task_root.as_posix(),
        "MATERIALS_PATH": materials_path.as_posix(),
    }
    files = {
        "operator-task.json": assets / "operator-task.template.json",
        "interface-contract.md": assets / "interface-contract.template.md",
        "decision-log.md": assets / "decision-log.template.md",
    }

    existing = [output_dir / name for name in files if (output_dir / name).exists()]
    if existing and not args.resume:
        print(
            "错误：需求采集产物已经存在；如需保留，请使用 --resume",
            file=sys.stderr,
        )
        for path in existing:
            print(f"  {path}", file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    kept: list[Path] = []
    for name, template in files.items():
        destination = output_dir / name
        if destination.exists():
            kept.append(destination)
            continue
        content = render(template, replacements)
        if destination.suffix == ".json":
            json.loads(content)
        destination.write_text(content, encoding="utf-8", newline="\n")
        created.append(destination)

    print(f"需求采集目录={output_dir}")
    for path in created:
        print(f"已创建={path}")
    for path in kept:
        print(f"已保留={path}")
    print(
        "下一步=运行 collect_materials.py，提供一个或多个 --root，"
        f"并指定 --output {materials_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
