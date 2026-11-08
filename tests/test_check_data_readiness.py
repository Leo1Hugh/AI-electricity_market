"""预检脚本的 mock 响应测试。"""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest

from scripts import check_data_readiness as readiness


def _payload(rows: list[dict[str, str]]) -> bytes:
    import csv

    stream = io.StringIO()
    fields = sorted({key for row in rows for key in row})
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("response.csv", stream.getvalue())
    return output.getvalue()


def _rows():
    price = [
        {
            "OPR_DT": "2026-11-08",
            "OPR_HR": str(hour),
            "NODE": "TH_SP15_GEN-APND",
            "MARKET_RUN_ID": "DAM",
            "LMP_TYPE": "LMP",
            "MW": "10",
        }
        for hour in range(1, 25)
    ]
    load = [
        {
            "OPR_DT": "2026-11-09",
            "OPR_HR": str(hour),
            "TAC_AREA_NAME": region,
            "MARKET_RUN_ID": "DAM",
            "XML_DATA_ITEM": "SYS_FCST_DA_MW",
            "MW": "10",
        }
        for region in readiness.TARGET_LOADS
        for hour in range(1, 25)
    ]
    renewable = [
        {
            "OPR_DT": "2026-11-09",
            "OPR_HR": str(hour),
            "TRADING_HUB": "SP15",
            "RENEWABLE_TYPE": kind,
            "MARKET_RUN_ID": "DAM",
            "XML_DATA_ITEM": "RENEW_FCST_DA_MW",
            "MW": "10",
        }
        for kind in readiness.TARGET_RENEWABLES
        for hour in range(1, 25)
    ]
    return price, load, renewable


def test_ready(monkeypatch: pytest.MonkeyPatch):
    price, load, renewable = _rows()

    def fake_download(url: str, timeout: int = 60):
        if "PRC_LMP" in url:
            return _payload(price)
        if "SLD_FCST" in url:
            return _payload(load)
        return _payload(renewable)

    monkeypatch.setattr(readiness, "_download", fake_download)
    result = readiness.check_once(date(2026, 11, 9))
    assert result["ready"] is True
    assert result["reports"]["SLD_FCST"]["hours"]["CA ISO-TAC"] == 24


def test_missing_load_is_not_ready(monkeypatch: pytest.MonkeyPatch):
    price, load, renewable = _rows()
    load = [row for row in load if not (row["TAC_AREA_NAME"] == "SCE-TAC" and row["OPR_HR"] == "24")]

    def fake_download(url: str, timeout: int = 60):
        return _payload(price if "PRC_LMP" in url else load if "SLD_FCST" in url else renewable)

    monkeypatch.setattr(readiness, "_download", fake_download)
    result = readiness.check_once(date(2026, 11, 9))
    assert result["ready"] is False
    assert result["reports"]["SLD_FCST"]["hours"]["SCE-TAC"] == 23


def test_missing_renewable_is_not_ready(monkeypatch: pytest.MonkeyPatch):
    price, load, renewable = _rows()
    renewable = [row for row in renewable if not (row["RENEWABLE_TYPE"] == "Wind" and row["OPR_HR"] == "24")]

    def fake_download(url: str, timeout: int = 60):
        return _payload(price if "PRC_LMP" in url else load if "SLD_FCST" in url else renewable)

    monkeypatch.setattr(readiness, "_download", fake_download)
    result = readiness.check_once(date(2026, 11, 9))
    assert result["ready"] is False
    assert result["reports"]["SLD_REN_FCST"]["hours"]["Wind"] == 23


def test_missing_d1_price_is_not_ready(monkeypatch: pytest.MonkeyPatch):
    price, load, renewable = _rows()
    price = price[:-1]

    def fake_download(url: str, timeout: int = 60):
        return _payload(price if "PRC_LMP" in url else load if "SLD_FCST" in url else renewable)

    monkeypatch.setattr(readiness, "_download", fake_download)
    result = readiness.check_once(date(2026, 11, 9))
    assert result["ready"] is False
    assert result["reports"]["PRC_LMP"]["hours"] == 23


def test_network_error_exit_code(monkeypatch: pytest.MonkeyPatch):
    def fail_download(url: str, timeout: int = 60):
        raise readiness.ReadinessError("network error: blocked")

    monkeypatch.setattr(readiness, "_download", fail_download)
    assert readiness.main(["--as-of", "2026-11-09", "--once"]) == 1
