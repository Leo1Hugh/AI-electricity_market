"""预检脚本的 mock 响应测试。"""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, timedelta, timezone
import json
from urllib.parse import parse_qs, urlparse

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


def _xml_payload() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("response.xml", "<error><ERR_CODE>1000</ERR_CODE><ERR_DESC>No data returned</ERR_DESC></error>")
    return output.getvalue()


def _mock_reports(monkeypatch, price, load, renewable):
    payloads = {"PRC_LMP": price, "SLD_FCST": load, "SLD_REN_FCST": renewable}

    def download(url, timeout=60):
        report = parse_qs(urlparse(url).query)["queryname"][0]
        return payloads[report]

    monkeypatch.setattr(readiness, "_download", download)


def test_prc_lmp_url_and_ready_november_8(monkeypatch, capsys):
    price, load, renewable = _rows()
    for rows in (price, load, renewable):
        for row in rows:
            row["OPR_DT"] = str(date.fromisoformat(row["OPR_DT"]) - timedelta(days=1))
    # 查询不接受 lmp_type；响应包含 MCC 时仍只统计 LMP。
    price.append({**price[0], "LMP_TYPE": "MCC", "OPR_DT": "2026-11-08"})
    _mock_reports(monkeypatch, _payload(price), _payload(load), _payload(renewable))
    assert readiness.main(["--as-of", "2026-11-08", "--once"]) == 0
    result = json.loads(capsys.readouterr().out)
    report = result["reports"]["PRC_LMP"]
    params = parse_qs(urlparse(report["url"]).query)
    assert params["version"] == ["12"]
    assert params["node"] == ["TH_SP15_GEN-APND"]
    assert "lmp_type" not in params
    assert params["startdatetime"] == ["20261101T07:00-0000"]
    assert params["enddatetime"] == ["20261108T08:00-0000"]
    assert report["hours"] == 24
    assert report["expected"]["D-1"] == "2026-11-07"
    assert report["latest_opr_dt"] == "2026-11-07"
    assert result["ready"] is True
    assert result["errors"] == []


@pytest.mark.parametrize("empty_response", [_xml_payload(), _payload([])])
def test_no_data_is_not_ready_without_errors(monkeypatch, capsys, empty_response):
    price, _, renewable = _rows()
    _mock_reports(monkeypatch, _payload(price), empty_response, _payload(renewable))
    assert readiness.main(["--as-of", "2026-11-09", "--once"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["ready"] is False
    assert result["errors"] == []
    assert result["reports"]["SLD_FCST"]["hours"] == dict.fromkeys(readiness.TARGET_LOADS, 0)
    assert result["reports"]["SLD_FCST"]["latest_opr_dt"] is None


def test_empty_csv_with_header_is_no_data():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("response.csv", "OPR_DT,OPR_HR,MW\n")
    assert readiness._rows(stream.getvalue()) == []


@pytest.mark.parametrize("payload", [b"not a ZIP", _payload(_rows()[0]).replace(b"PK", b"XX")])
def test_bad_zip_is_error(monkeypatch, capsys, payload):
    monkeypatch.setattr(readiness, "_download", lambda *args, **kwargs: payload)
    assert readiness.main(["--as-of", "2026-11-09", "--once"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["errors"]


def test_crc_failure_is_readiness_error():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("response.csv", "OPR_DT,OPR_HR,MW\n2026-11-09,1,10\n")
    corrupted = stream.getvalue().replace(b"2026-11-09,1,10", b"2026-11-09,1,99")
    with pytest.raises(readiness.ReadinessError, match="corrupt ZIP"):
        readiness._rows(corrupted)


def test_watch_continues_after_no_data_and_error(monkeypatch, capsys):
    now = datetime(2026, 11, 8, 16, tzinfo=timezone.utc)
    state = {"seconds": 0.0}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now + timedelta(seconds=state["seconds"])

    calls = []
    def check(as_of):
        calls.append(state["seconds"])
        if len(calls) == 2:
            raise readiness.ReadinessError("network error: temporary")
        return {"ready": len(calls) == 3, "errors": []}

    monkeypatch.setattr(readiness, "datetime", Clock)
    monkeypatch.setattr(readiness, "check_once", check)
    monkeypatch.setattr(readiness.time, "monotonic", lambda: state["seconds"])
    monkeypatch.setattr(readiness.time, "sleep", lambda seconds: state.update(seconds=state["seconds"] + seconds))
    assert readiness.main(["--as-of", "2026-11-09", "--watch", "--interval", "300", "--until", "2026-11-08T18:00:00+00:00"]) == 0
    assert calls == [0, 300, 600]
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(lines) == 3
    assert lines[0]["errors"] == []
    assert lines[1]["errors"] == ["network error: temporary"]
    assert lines[2]["ready"] is True


@pytest.mark.parametrize("errors,code", [([], 2), (["network error"], 1)])
def test_watch_deadline_returns_last_state(monkeypatch, errors, code):
    monkeypatch.setattr(readiness, "check_once", lambda as_of: {"ready": False, "errors": errors})
    assert readiness.main(["--as-of", "2026-11-09", "--watch", "--until", "2000-01-01T00:00:00+00:00"]) == code
