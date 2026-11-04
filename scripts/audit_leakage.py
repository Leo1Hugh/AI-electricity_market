#!/usr/bin/env python3
"""Audit truncation invariants and obvious future-information patterns."""

from __future__ import annotations

import argparse
import ast
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DAYS = ("2024-03-09", "2025-11-23", "2026-10-31")
FEATURE_COUNT = 85
FORBIDDEN = (
    (re.compile(r"interpolate\s*\([^)]*limit_direction\s*=\s*['\"]both", re.I | re.S),
     "双向 interpolate(limit_direction='both')"),
    (re.compile(r"\.bfill\s*\(", re.I), "bfill"),
    (re.compile(r"\.shift\s*\(\s*-", re.I), "shift(-"),
    (re.compile(r"\bcenter\s*=\s*True\b", re.I), "center=True"),
)


@dataclass(frozen=True)
class Check:
    """One audit result."""

    name: str
    passed: bool
    detail: str


def _static_scan(root: Path = ROOT) -> list[Check]:
    """Scan panel/data and daily rebuild sources for prohibited patterns."""
    paths = sorted((root / "src/em/data").rglob("*.py"))
    paths.extend([root / "scripts/fetch_daily.py", root / "scripts/rebuild_hourly.py"])
    checks: list[Check] = []
    found = 0
    for path in paths:
        if not path.exists():
            checks.append(Check(f"存在 {path.relative_to(root)}", False, "文件不存在"))
            continue
        text = path.read_text(encoding="utf-8")
        for pattern, label in FORBIDDEN:
            match = pattern.search(text)
            if match:
                found += 1
                line = text.count("\n", 0, match.start()) + 1
                checks.append(Check(f"静态扫描 {path.relative_to(root)}", False, f"第 {line} 行命中 {label}"))
    if not found:
        checks.append(Check("静态扫描未来信息模式", True, f"扫描 {len(paths)} 个源文件，未命中禁用模式"))
    return checks


def _panel_input_check(root: Path = ROOT) -> Check:
    """Check that build_panel remains a pure feature transformation."""
    path = root / "src/em/data/panel.py"
    if not path.exists():
        return Check("build_panel 输入审计", False, "src/em/data/panel.py 不存在")
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return Check("build_panel 输入审计", False, f"语法错误: {exc}")
    function = next((node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "build_panel"), None)
    if function is None:
        return Check("build_panel 输入审计", False, "找不到 build_panel")
    source = ast.get_source_segment(text, function) or ""
    forbidden = ("read_csv", "read_parquet", "load_hourly", "actual", "future")
    hits = [token for token in forbidden if token in source.lower()]
    if hits:
        return Check("build_panel 输入审计", False, f"函数体包含不允许的输入/未来标记: {hits}")
    needed = ("price", "load_caiso", "solar", "wind", "calendar_features")
    missing = [token for token in needed if token not in source]
    if missing:
        return Check("build_panel 输入审计", False, f"函数体缺少预期输入或日历路径: {missing}")
    return Check("build_panel 输入审计", True, "只从 price/load/ren 矩阵和 calendar_features 构造特征")


def _truncation_checks(hourly_path: Path, root: Path = ROOT) -> list[Check]:
    """Rebuild sample days from truncated raw input and compare 85 features."""
    try:
        import sys

        src = root / "src"
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
        from em.data.panel import build_panel
        from em.io import load_hourly
    except Exception as exc:
        return [Check("截断重算导入", False, str(exc))]

    try:
        hourly = load_hourly(hourly_path)
        full = build_panel(hourly)
    except Exception as exc:
        return [Check("全量面板重算", False, str(exc))]

    checks: list[Check] = []
    try:
        from em.contracts import FEATURES

        features = list(FEATURES)
    except Exception:
        features = []
    if len(features) != FEATURE_COUNT:
        checks.append(Check("特征数量", False, f"契约特征数为 {len(features)}，期望 {FEATURE_COUNT}"))
    for sample in SAMPLE_DAYS:
        day = pd.Timestamp(sample)
        try:
            truncated = hourly[pd.to_datetime(hourly["opr_dt"]).dt.normalize() <= day]
            rebuilt = build_panel(truncated)
            expected = full[full["day"] == day].sort_values("hour").reset_index(drop=True)
            actual = rebuilt[rebuilt["day"] == day].sort_values("hour").reset_index(drop=True)
            if expected.shape[0] != actual.shape[0]:
                raise AssertionError(f"行数不一致 full={len(expected)} truncated={len(actual)}")
            if features:
                np.testing.assert_allclose(
                    expected[features].to_numpy(dtype=float),
                    actual[features].to_numpy(dtype=float),
                    rtol=0.0,
                    atol=1e-9,
                    equal_nan=True,
                )
            checks.append(Check(f"截断重算 {sample}", True, f"{len(features)} 个特征逐元素一致"))
        except Exception as exc:
            checks.append(Check(f"截断重算 {sample}", False, str(exc)))
    return checks


def _render(checks: list[Check], hourly: Path) -> str:
    """Render the audit markdown, including the accepted historical limitation."""
    lines = [
        "# 泄漏审计报告",
        "",
        f"- 输入：`{hourly}`",
        "- 样本日：2024-03-09、2025-11-23、2026-10-31",
        "",
        "| 检查项 | 结果 | 说明 |",
        "|---|---|---|",
    ]
    for check in checks:
        lines.append(f"| {check.name} | {'通过' if check.passed else '失败'} | {check.detail.replace('|', '/') } |")
    lines += [
        "",
        "## 已知限制",
        "",
        "OASIS 历史文件没有可证明的版本发布时间；回测使用事后修订值。该偏差已接受，审计不能据此声称完全消除未来信息。",
        "",
        "## 结论",
        "",
        f"- {'通过：未发现审计项失败。' if all(item.passed for item in checks) else '失败：至少一项审计未通过。'}",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Run the leakage audit and always write a report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hourly", type=Path, default=Path("work/hourly.csv.gz"))
    parser.add_argument("--output", type=Path, default=Path("reports/leakage_audit.md"))
    args = parser.parse_args(argv)
    checks = _static_scan(ROOT)
    checks.append(_panel_input_check(ROOT))
    checks.extend(_truncation_checks(args.hourly, ROOT))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(_render(checks, args.hourly), encoding="utf-8")
    failed = [item for item in checks if not item.passed]
    print(f"audit checks={len(checks)} failures={len(failed)} report={args.output}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
