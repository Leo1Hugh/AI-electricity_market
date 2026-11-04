"""Synthetic ZIP tests for deterministic hourly rebuilding."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pandas as pd

from scripts import rebuild_hourly


def _write_zip(path: Path, name: str, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, frame.to_csv(index=False))


def _price_rows(value: float) -> list[dict[str, object]]:
    rows = []
    for hour in (1, 2, 3, 4, 25):
        rows.append(
            {
                "OPR_DT": "2024-11-03",
                "OPR_HR": hour,
                "INTERVALSTARTTIME_GMT": f"2024-11-03T{hour:02d}:00:00+00:00",
                "NODE": "TH_SP15_GEN-APND",
                "MARKET_RUN_ID": "DAM",
                "LMP_TYPE": "LMP",
                "MW": value + hour,
            }
        )
    return rows


def _load_rows(value: float, day: str = "2024-11-03") -> list[dict[str, object]]:
    rows = []
    for region in ("CA ISO-TAC", "SCE-TAC", "SDGE-TAC"):
        rows.append(
            {
                "OPR_DT": day,
                "OPR_HR": 1,
                "INTERVALSTARTTIME_GMT": f"{day}T07:00:00+00:00",
                "TAC_AREA_NAME": region,
                "MARKET_RUN_ID": "DAM",
                "XML_DATA_ITEM": "SYS_FCST_DA_MW",
                "MW": value,
            }
        )
    return rows


def _renew_rows(value: float, day: str = "2024-11-03") -> list[dict[str, object]]:
    return [
        {
            "OPR_DT": day,
            "OPR_HR": 1,
            "INTERVALSTARTTIME_GMT": f"{day}T07:00:00+00:00",
            "TRADING_HUB": "SP15",
            "RENEWABLE_TYPE": kind,
            "MARKET_RUN_ID": "DAM",
            "XML_DATA_ITEM": "RENEW_FCST_DA_MW",
            "MW": value,
        }
        for kind in ("Solar", "Wind")
    ]


def test_latest_version_wins_and_hour25_is_dropped(tmp_path: Path):
    price_root = tmp_path / "prices"
    price_root.mkdir()
    old = price_root / "old.csv"
    new = price_root / "new.csv"
    pd.DataFrame(_price_rows(10)).to_csv(old, index=False)
    pd.DataFrame(_price_rows(100)).to_csv(new, index=False)
    os.utime(old, (1_000, 1_000))
    os.utime(new, (2_000, 2_000))

    raw = tmp_path / "raw"
    _write_zip(raw / "sld_fcst" / "load.zip", "load.csv", _load_rows(7))
    _write_zip(raw / "sld_ren_fcst" / "renew.zip", "renew.csv", _renew_rows(2))
    frame, counts = rebuild_hourly.rebuild(raw, price_root)

    assert counts == {"price_csv": 2, "load_zip": 1, "renewable_zip": 1}
    assert set(frame["opr_hr"]) == {1, 2, 3, 4}
    assert frame.loc[frame["opr_hr"] == 1, "price"].iloc[0] == 101
    assert "opr_dt" in frame and list(frame.columns) == rebuild_hourly.OUTPUT_COLUMNS

    legacy = frame.copy()
    legacy["ren_solar"] = legacy["ren_solar"].fillna(0.0) + 1000.0
    legacy_path = tmp_path / "legacy.csv.gz"
    legacy.to_csv(legacy_path, index=False, compression="gzip")
    comparison = rebuild_hourly.compare_with_old(frame, legacy_path)
    assert comparison["equal"]
    assert comparison["renewable_differences"]["ren_solar"] > 0
    assert rebuild_hourly.compare_raw_sp15(frame, raw)["equal"]


def test_spring_missing_hour_is_preserved_as_missing_key(tmp_path: Path):
    price_root = tmp_path / "prices"
    price_root.mkdir()
    rows = [
        {
            "OPR_DT": "2024-03-10",
            "OPR_HR": hour,
            "INTERVALSTARTTIME_GMT": f"2024-03-10T{hour:02d}:00:00+00:00",
            "NODE": "TH_SP15_GEN-APND",
            "MARKET_RUN_ID": "DAM",
            "LMP_TYPE": "LMP",
            "MW": 1.0,
        }
        for hour in (1, 2, 4)
    ]
    pd.DataFrame(rows).to_csv(price_root / "spring.csv", index=False)
    raw = tmp_path / "raw"
    _write_zip(raw / "sld_fcst" / "load.zip", "load.csv", _load_rows(7, "2024-03-10"))
    _write_zip(raw / "sld_ren_fcst" / "renew.zip", "renew.csv", _renew_rows(2, "2024-03-10"))
    frame, _ = rebuild_hourly.rebuild(raw, price_root)
    assert frame["opr_hr"].tolist() == [1, 2, 4]


def test_deterministic_gzip_bytes(tmp_path: Path):
    price_root = tmp_path / "prices"
    price_root.mkdir()
    pd.DataFrame(_price_rows(10)).to_csv(price_root / "one.csv", index=False)
    raw = tmp_path / "raw"
    _write_zip(raw / "sld_fcst" / "load.zip", "load.csv", _load_rows(7))
    _write_zip(raw / "sld_ren_fcst" / "renew.zip", "renew.csv", _renew_rows(2))
    frame, _ = rebuild_hourly.rebuild(raw, price_root)
    first = tmp_path / "one.csv.gz"
    second = tmp_path / "two.csv.gz"
    rebuild_hourly._write_deterministic(frame, first)
    rebuild_hourly._write_deterministic(frame, second)
    assert first.read_bytes() == second.read_bytes()
