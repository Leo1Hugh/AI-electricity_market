#!/usr/bin/env python3
"""Rebuild the compact hourly input table from raw CAISO responses.

The builder reads every source response, keeps the newest version for each
``(opr_dt, opr_hr)`` series key, and writes a deterministic gzip CSV.  The
reference hourly file can be replaced explicitly by the R2b command after the
legacy comparison and the independent SP15 source check pass.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import re
import zipfile
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


OUTPUT_COLUMNS = [
    "opr_dt",
    "opr_hr",
    "ts_utc",
    "price",
    "load_caiso",
    "load_sce",
    "load_sdge",
    "ren_solar",
    "ren_wind",
]
LOAD_COLUMNS = {
    "CA ISO-TAC": "load_caiso",
    "SCE-TAC": "load_sce",
    "SDGE-TAC": "load_sdge",
}
RENEWABLE_COLUMNS = {"Solar": "ren_solar", "Wind": "ren_wind"}
LEGACY_COLUMNS = ("ts_utc", "price", "load_caiso", "load_sce", "load_sdge")
VERSION_RE = re.compile(r"(?<!\d)(\d{8})[_-](\d{2})[_-](\d{2})[_-](\d{2})(?:[_-](\d{2}))?")


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of *path*."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _filename_timestamp(*names: str) -> int:
    """Extract a comparable UTC nanosecond timestamp from a CAISO filename."""
    values: list[int] = []
    for name in names:
        for match in VERSION_RE.finditer(name):
            digits = match.groups(default="00")
            try:
                stamp = datetime.strptime(
                    "_".join(digits[:4]), "%Y%m%d_%H_%M_%S"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            values.append(int(stamp.timestamp() * 1_000_000_000))
    return max(values, default=0)


def _source_rank(path: Path, member: str = "") -> tuple[int, int, str, str]:
    """Return a deterministic version rank for a file/member pair.

    CAISO response names include a generation timestamp, while synthetic or
    manually archived responses often only have meaningful filesystem mtimes.
    The larger of those signals wins; names provide a stable final tie-break.
    """
    mtime = path.stat().st_mtime_ns
    stamp = _filename_timestamp(path.name, member)
    return max(mtime, stamp), stamp, path.name, member


def _csv_members(path: Path) -> Iterator[tuple[str, pd.DataFrame]]:
    """Yield decoded CSV members from a ZIP, rejecting corrupt archives."""
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise zipfile.BadZipFile(f"corrupt ZIP member: {bad_member}")
        for info in archive.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".csv"):
                continue
            payload = archive.read(info)
            frame = pd.read_csv(io.BytesIO(payload), encoding="utf-8-sig")
            yield info.filename, frame


def _column(frame: pd.DataFrame, *names: str) -> str | None:
    """Find the first case-sensitive or upper-case equivalent column name."""
    for name in names:
        if name in frame.columns:
            return name
    upper = {str(name).upper(): str(name) for name in frame.columns}
    for name in names:
        if name.upper() in upper:
            return upper[name.upper()]
    return None


def _base_fields(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize date/hour/UTC fields without filling any missing values."""
    date_col = _column(frame, "OPR_DT", "OP_DATE", "OPR_DATE")
    hour_col = _column(frame, "OPR_HR")
    if date_col is None or hour_col is None:
        return pd.DataFrame(columns=["opr_dt", "opr_hr", "ts_utc"])
    out = pd.DataFrame(index=frame.index)
    out["opr_dt"] = pd.to_datetime(frame[date_col], errors="coerce").dt.normalize()
    out["opr_hr"] = pd.to_numeric(frame[hour_col], errors="coerce")
    out["ts_utc"] = pd.NaT
    ts_col = _column(frame, "INTERVALSTARTTIME_GMT", "INTERVAL_START_GMT")
    if ts_col is not None:
        out["ts_utc"] = pd.to_datetime(frame[ts_col], errors="coerce", utc=True)
    valid = out["opr_dt"].notna() & out["opr_hr"].between(1, 24)
    return out.loc[valid].copy()


def _hourly_interval_mask(frame: pd.DataFrame, index: pd.Index) -> pd.Series:
    """Keep the hourly interval (OPR_INTERVAL=0) when a source exposes it."""
    column = _column(frame, "OPR_INTERVAL")
    if column is None:
        return pd.Series(True, index=index)
    values = pd.to_numeric(frame.loc[index, column], errors="coerce")
    return values.eq(0) | values.isna()


def _put_latest(
    records: dict[tuple[pd.Timestamp, int, str], tuple[tuple[int, int, str, str], object, object]],
    key: tuple[pd.Timestamp, int, str],
    rank: tuple[int, int, str, str],
    value: object,
    ts_utc: object,
) -> None:
    """Keep the value from the newest source rank for one series key."""
    previous = records.get(key)
    if previous is None or rank >= previous[0]:
        records[key] = (rank, value, ts_utc)


def _read_prices(price_root: Path) -> tuple[dict[tuple[pd.Timestamp, int, str], tuple], int]:
    """Read filtered PRC_LMP CSVs into a latest-version record map."""
    records: dict[tuple[pd.Timestamp, int, str], tuple] = {}
    files = sorted(price_root.rglob("*.csv"))
    for path in files:
        frame = pd.read_csv(path)
        market = _column(frame, "MARKET_RUN_ID")
        lmp_type = _column(frame, "LMP_TYPE")
        node = _column(frame, "NODE", "NODE_ID", "NODE_ID_XML")
        value_col = _column(frame, "MW", "VALUE")
        base = _base_fields(frame)
        if market is None or lmp_type is None or node is None or value_col is None or base.empty:
            continue
        keep = (
            frame.loc[base.index, market].astype(str).str.strip().eq("DAM")
            & frame.loc[base.index, lmp_type].astype(str).str.strip().eq("LMP")
            & frame.loc[base.index, node].astype(str).str.strip().eq("TH_SP15_GEN-APND")
        )
        keep &= _hourly_interval_mask(frame, base.index)
        for index in base.index[keep]:
            value = pd.to_numeric(pd.Series([frame.at[index, value_col]]), errors="coerce").iloc[0]
            if pd.isna(value):
                continue
            key = (base.at[index, "opr_dt"], int(base.at[index, "opr_hr"]), "price")
            rank = _source_rank(path)
            _put_latest(records, key, rank, float(value), base.at[index, "ts_utc"])
    return records, len(files)


def _read_loads(raw_root: Path) -> tuple[dict[tuple[pd.Timestamp, int, str], tuple], int]:
    """Read target TAC load forecasts from monthly ZIP responses."""
    records: dict[tuple[pd.Timestamp, int, str], tuple] = {}
    files = sorted((raw_root / "sld_fcst").glob("*.zip"))
    for path in files:
        for member, frame in _csv_members(path):
            region_col = _column(frame, "TAC_AREA_NAME", "TAC_AREA", "REGION", "RESOURCE_NAME")
            market = _column(frame, "MARKET_RUN_ID", "MARKET_TYPE")
            item = _column(frame, "XML_DATA_ITEM", "DATA_ITEM")
            value_col = _column(frame, "MW", "VALUE", "LOAD_FORECAST")
            base = _base_fields(frame)
            if region_col is None or market is None or value_col is None or base.empty:
                continue
            keep = frame.loc[base.index, region_col].astype(str).str.strip().isin(LOAD_COLUMNS)
            keep &= frame.loc[base.index, market].astype(str).str.strip().eq("DAM")
            keep &= _hourly_interval_mask(frame, base.index)
            if item is not None:
                keep &= frame.loc[base.index, item].astype(str).str.strip().eq("SYS_FCST_DA_MW")
            rank = _source_rank(path, member)
            for index in base.index[keep]:
                value = pd.to_numeric(pd.Series([frame.at[index, value_col]]), errors="coerce").iloc[0]
                if pd.isna(value):
                    continue
                column = LOAD_COLUMNS[str(frame.at[index, region_col]).strip()]
                key = (base.at[index, "opr_dt"], int(base.at[index, "opr_hr"]), column)
                _put_latest(records, key, rank, float(value), base.at[index, "ts_utc"])
    return records, len(files)


def _read_renewables(raw_root: Path) -> tuple[dict[tuple[pd.Timestamp, int, str], tuple], int]:
    """Read SP15 Solar/Wind forecasts from monthly ZIP responses."""
    records: dict[tuple[pd.Timestamp, int, str], tuple] = {}
    files = sorted((raw_root / "sld_ren_fcst").glob("*.zip"))
    for path in files:
        for member, frame in _csv_members(path):
            hub = _column(frame, "TRADING_HUB")
            renewable = _column(frame, "RENEWABLE_TYPE", "RENEWABLE_FUEL_TYPE")
            market = _column(frame, "MARKET_RUN_ID", "MARKET_TYPE")
            item = _column(frame, "XML_DATA_ITEM", "DATA_ITEM")
            value_col = _column(frame, "MW", "VALUE", "RENEWABLE_FORECAST", "FORECAST")
            base = _base_fields(frame)
            if hub is None or renewable is None or market is None or value_col is None or base.empty:
                continue
            keep = frame.loc[base.index, hub].astype(str).str.strip().eq("SP15")
            keep &= frame.loc[base.index, renewable].astype(str).str.strip().isin(RENEWABLE_COLUMNS)
            keep &= frame.loc[base.index, market].astype(str).str.strip().eq("DAM")
            keep &= _hourly_interval_mask(frame, base.index)
            if item is not None:
                keep &= frame.loc[base.index, item].astype(str).str.strip().eq("RENEW_FCST_DA_MW")
            rank = _source_rank(path, member)
            for index in base.index[keep]:
                value = pd.to_numeric(pd.Series([frame.at[index, value_col]]), errors="coerce").iloc[0]
                if pd.isna(value):
                    continue
                column = RENEWABLE_COLUMNS[str(frame.at[index, renewable]).strip()]
                key = (base.at[index, "opr_dt"], int(base.at[index, "opr_hr"]), column)
                _put_latest(records, key, rank, float(value), base.at[index, "ts_utc"])
    return records, len(files)


def _records_to_frame(
    price: dict[tuple[pd.Timestamp, int, str], tuple],
    loads: dict[tuple[pd.Timestamp, int, str], tuple],
    renewables: dict[tuple[pd.Timestamp, int, str], tuple],
) -> pd.DataFrame:
    """Merge source maps into the fixed nine-column hourly schema."""
    keys = {(key[0], key[1]) for key in (*price, *loads, *renewables)}
    rows: list[dict[str, object]] = []
    for day, hour in sorted(keys):
        row: dict[str, object] = {column: np.nan for column in OUTPUT_COLUMNS}
        row["opr_dt"] = day
        row["opr_hr"] = hour
        price_record = price.get((day, hour, "price"))
        if price_record is not None:
            row["price"] = price_record[1]
            row["ts_utc"] = price_record[2]
        for column in (*LOAD_COLUMNS.values(), *RENEWABLE_COLUMNS.values()):
            record = loads.get((day, hour, column)) or renewables.get((day, hour, column))
            if record is not None:
                row[column] = record[1]
                if pd.isna(row["ts_utc"]):
                    row["ts_utc"] = record[2]
        rows.append(row)
    output = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if output.empty:
        return output
    output["opr_dt"] = pd.to_datetime(output["opr_dt"]).dt.strftime("%Y-%m-%d")
    output["opr_hr"] = output["opr_hr"].astype("int64")
    output["ts_utc"] = pd.to_datetime(output["ts_utc"], utc=True, errors="coerce")
    output = output.sort_values(["opr_dt", "opr_hr"], kind="mergesort").reset_index(drop=True)
    return output


def rebuild(raw_root: Path, price_root: Path) -> tuple[pd.DataFrame, dict[str, int]]:
    """Read all raw inputs and return the rebuilt table plus input counts."""
    price, n_price = _read_prices(price_root)
    loads, n_load = _read_loads(raw_root)
    renewables, n_renew = _read_renewables(raw_root)
    frame = _records_to_frame(price, loads, renewables)
    return frame, {"price_csv": n_price, "load_zip": n_load, "renewable_zip": n_renew}


def _write_deterministic(frame: pd.DataFrame, output: Path) -> None:
    """Write a deterministic gzip CSV with a zero gzip timestamp."""
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = frame.to_csv(index=False).encode("utf-8")
    with output.open("wb") as stream:
        with gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0) as archive:
            archive.write(payload)


def _normal_for_compare(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize a frame for key-aligned comparison with the old hourly table."""
    missing = [column for column in OUTPUT_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"comparison table missing columns: {missing}")
    out = frame[OUTPUT_COLUMNS].copy()
    out["opr_dt"] = pd.to_datetime(out["opr_dt"], errors="coerce").dt.strftime("%Y-%m-%d")
    out["opr_hr"] = pd.to_numeric(out["opr_hr"], errors="coerce")
    out = out[out["opr_hr"].between(1, 24)].copy()
    out["opr_hr"] = out["opr_hr"].astype("int64")
    return out.sort_values(["opr_dt", "opr_hr"], kind="mergesort").reset_index(drop=True)


def _column_differences(old: pd.DataFrame, new: pd.DataFrame, columns: Iterable[str]) -> dict[str, int]:
    """Count cell differences for key-aligned columns."""
    differences: dict[str, int] = {}
    for column in columns:
        if column == "ts_utc":
            a = pd.to_datetime(old[column], errors="coerce", utc=True).astype("int64").to_numpy()
            b = pd.to_datetime(new[column], errors="coerce", utc=True).astype("int64").to_numpy()
            equal = a == b
        else:
            a = pd.to_numeric(old[column], errors="coerce").to_numpy(dtype=float)
            b = pd.to_numeric(new[column], errors="coerce").to_numpy(dtype=float)
            equal = np.isclose(a, b, rtol=0.0, atol=1e-9, equal_nan=True)
        differences[column] = int((~equal).sum())
    return differences


def compare_with_old(frame: pd.DataFrame, old_path: Path) -> dict[str, object]:
    """Compare legacy-compatible columns and report renewable differences.

    The old table is known to contain NP15 renewable values.  Its renewable
    columns are therefore diagnostic only; the comparison gate covers the
    five shared legacy columns and leaves the SP15 gate to ``compare_raw_sp15``.
    """
    if not old_path.exists():
        return {
            "available": False,
            "equal": True,
            "legacy_differences": {},
            "renewable_differences": {},
            "message": "old table absent",
        }
    old = _normal_for_compare(pd.read_csv(old_path))
    new = _normal_for_compare(frame)
    if len(old) != len(new) or not old[["opr_dt", "opr_hr"]].equals(new[["opr_dt", "opr_hr"]]):
        return {
            "available": True,
            "equal": False,
            "legacy_differences": {},
            "renewable_differences": {},
            "message": f"key grid differs: old={len(old)} new={len(new)}",
        }
    legacy = _column_differences(old, new, LEGACY_COLUMNS)
    renewable = _column_differences(old, new, tuple(RENEWABLE_COLUMNS.values()))
    total = sum(legacy.values())
    return {
        "available": True,
        "equal": total == 0,
        "legacy_differences": legacy,
        "renewable_differences": renewable,
        "message": "legacy columns match" if total == 0 else f"{total} legacy differing cells",
    }


def compare_raw_sp15(frame: pd.DataFrame, raw_root: Path) -> dict[str, object]:
    """Compare output renewable values with the newest raw SP15 records."""
    expected, _ = _read_renewables(raw_root)
    actual_frame = frame.copy()
    actual_frame["opr_dt"] = pd.to_datetime(actual_frame["opr_dt"], errors="coerce").dt.normalize()
    results: dict[str, dict[str, int]] = {}
    all_equal = True
    for column in RENEWABLE_COLUMNS.values():
        expected_values = {
            (key[0], key[1]): float(record[1])
            for key, record in expected.items()
            if key[2] == column
        }
        actual_values = {
            (row.opr_dt, int(row.opr_hr)): float(getattr(row, column))
            for row in actual_frame.loc[actual_frame[column].notna(), ["opr_dt", "opr_hr", column]].itertuples(index=False)
        }
        matched = sum(
            1
            for key, value in expected_values.items()
            if key in actual_values and np.isclose(value, actual_values[key], rtol=0.0, atol=1e-9)
        )
        exact = matched == len(expected_values) and len(actual_values) == len(expected_values)
        all_equal &= exact
        results[column] = {
            "expected": len(expected_values),
            "actual": len(actual_values),
            "matched": matched,
        }
    return {"equal": all_equal, "columns": results}


def _report(
    *,
    frame: pd.DataFrame | None,
    counts: dict[str, int],
    output: Path,
    comparison: dict[str, object] | None,
    raw_sp15: dict[str, object] | None = None,
    error: str | None = None,
) -> str:
    """Render the rebuild report."""
    lines = [
        "# Hourly 重建报告",
        "",
        f"- 生成时间（UTC）：{datetime.now(timezone.utc).isoformat()}",
        f"- 输出：`{output}`",
        f"- 输入价格 CSV：{counts.get('price_csv', 0)}",
        f"- 输入负荷 ZIP：{counts.get('load_zip', 0)}",
        f"- 输入风光 ZIP：{counts.get('renewable_zip', 0)}",
    ]
    if error:
        lines += ["", "## 错误", "", f"- {error}"]
        return "\n".join(lines) + "\n"
    assert frame is not None
    dates = pd.to_datetime(frame["opr_dt"], errors="coerce")
    lines += [
        f"- 输出行数：{len(frame)}；列数：{len(frame.columns)}",
        f"- 日期范围：{dates.min().date() if dates.notna().any() else '无'} 至 {dates.max().date() if dates.notna().any() else '无'}",
        f"- 输出 SHA-256：`{sha256(output)}`",
        "",
        "## 缺失日期 / DST",
        "",
    ]
    if dates.notna().any():
        counts_by_day = frame.groupby("opr_dt").size()
        unusual = counts_by_day[counts_by_day != 24]
        if len(unusual):
            lines.extend(f"- `{day}`：{int(count)} 行" for day, count in unusual.items())
        else:
            lines.append("- 无非 24 小时日期")
    else:
        lines.append("- 无输出日期")
    lines += ["", "## 与旧 hourly 的比较", ""]
    if comparison is None or not comparison.get("available"):
        lines.append("- 未找到旧表，未比较。")
    else:
        lines.append(f"- {'通过' if comparison['equal'] else '失败'}：{comparison['message']}")
        lines.append("- legacy 门只比较 `ts_utc`、`price`、`load_caiso`、`load_sce`、`load_sdge`。")
        for column, count in comparison.get("legacy_differences", {}).items():
            lines.append(f"- legacy `{column}` 差异单元格：{count}")
        renewable_differences = comparison.get("renewable_differences", {})
        for column, count in renewable_differences.items():
            if count:
                lines.append(f"- WARNING: 旧表 `{column}` 与 SP15 重建差异 {count} 个单元格；旧表风光口径为 NP15。")
    lines += ["", "## 与 raw SP15 风光比较", ""]
    if raw_sp15 is None:
        lines.append("- 未比较。")
    else:
        lines.append(f"- {'通过' if raw_sp15['equal'] else '失败'}：逐列精确比较（atol=1e-9）。")
        for column, values in raw_sp15.get("columns", {}).items():
            lines.append(
                f"- `{column}`：raw={values['expected']}，输出={values['actual']}，匹配={values['matched']}"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Run the rebuild CLI and return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw/caiso"))
    parser.add_argument("--price-root", type=Path, default=Path("data/CAISO"))
    parser.add_argument("--out", type=Path, default=Path("work/hourly.rebuilt.csv.gz"))
    parser.add_argument("--report", type=Path, default=Path("reports/rebuild_report.md"))
    args = parser.parse_args(argv)
    old_path = Path("work/hourly.csv.gz")
    report_text: str
    try:
        frame, counts = rebuild(args.raw_root, args.price_root)
        if frame.empty:
            raise ValueError("no target rows found in raw inputs")
        # Compare before writing when --out points at the legacy reference.
        comparison = compare_with_old(frame, old_path)
        raw_sp15 = compare_raw_sp15(frame, args.raw_root)
        _write_deterministic(frame, args.out)
        report_text = _report(
            frame=frame,
            counts=counts,
            output=args.out,
            comparison=comparison,
            raw_sp15=raw_sp15,
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report_text, encoding="utf-8")
        print(f"rebuilt {len(frame)} rows; output={args.out}; report={args.report}")
        renewable_differences = comparison.get("renewable_differences", {})
        if any(renewable_differences.values()):
            print("WARNING: legacy hourly renewable columns are NP15; they are excluded from the failure gate.")
        if not comparison.get("equal"):
            print(f"ERROR: legacy comparison failed: {comparison['message']}")
            return 1
        if not raw_sp15.get("equal"):
            print("ERROR: raw SP15 renewable comparison failed")
            return 1
        return 0
    except Exception as exc:
        report_text = _report(
            frame=None,
            counts={},
            output=args.out,
            comparison=None,
            raw_sp15=None,
            error=str(exc),
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report_text, encoding="utf-8")
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
