#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CAISO SLD_FCST / SLD_REN_FCST 字段可删性审计。

判定:
  KEEP      维度或度量, 不可删
  CONST     全表单值 -> 抽取完成后无信息量
  DERIV     可由其他列唯一推出 (0 例冲突) -> 删掉不丢信息
  TIME-ALT  OPR_DT / OPR_HR / INTERVALSTARTTIME_GMT 三者一一对应, 只留其一

用法: python audit_fields.py
输出: 终端摘要 + 同目录 audit_fields_report.md
"""
from __future__ import annotations

import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

FILES = {
    "SLD_FCST": os.path.join(
        ROOT, "data/raw/caiso/sld_fcst/sld_fcst_2023-11-01_2023-11-30",
        "20231101_20231201_SLD_FCST_DAM_20261031_22_19_32_v1.csv"),
    "SLD_REN_FCST": os.path.join(
        ROOT, "data/raw/caiso/sld_ren_fcst/sld_ren_fcst_2023-11-01_2023-11-30",
        "20231101_20231201_SLD_REN_FCST_DAM_20261031_22_19_39_v1.csv"),
}

DST_NOTE = ("2023-11-05 是 25 小时日。当天 OPR_HR 的真实顺序是 1@07:00Z 2@08:00Z 3@10:00Z "
            "… 24@07:00Z(+1d) 25@09:00Z —— 夏令时回拨的那一小时被编成 25 号、排在末尾。"
            "所以 (OPR_DT, OPR_HR) 无法用固定公式还原 UTC, 时间轴请以 INTERVALSTARTTIME_GMT 为准。"
            "春季 23 小时日 (2024-03-10 等) 未出现在本次两个文件里, 未验证。")


def load(path):
    with open(path, newline="", encoding="utf-8") as fh:
        rd = csv.reader(fh)
        header = next(rd)
        rows = [r for r in rd if r]
    return header, rows


def is_function(rows, ia, ib):
    m, conflicts = {}, 0
    for r in rows:
        k, v = r[ia], r[ib]
        if k in m and m[k] != v:
            conflicts += 1
        else:
            m[k] = v
    return conflicts == 0, conflicts


def parse_iso(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S-00:00")


def _nth_sunday(year, month, n):
    first_wd = datetime(year, month, 1).weekday()  # Mon=0
    first_sun = 1 + ((6 - first_wd) % 7)
    return first_sun + (n - 1) * 7


def _is_dst(y, m, d):
    if m < 3 or m > 11:
        return False
    if m == 3:
        return d >= _nth_sunday(y, 3, 2)
    if m == 11:
        return d < _nth_sunday(y, 11, 1)
    return True


def dst_check(rows, ix):
    """检验 (OPR_DT, OPR_HR) 能否用「当地午夜 + (hr-1) 小时」还原 UTC。"""
    bad, samples = 0, []
    for r in rows:
        y, m, d = [int(x) for x in r[ix["OPR_DT"]].replace("/", "-").split("-")]
        off = -7 if _is_dst(y, m, d) else -8
        midnight = datetime(y, m, d) - timedelta(hours=off)
        expect = (midnight + timedelta(hours=int(r[ix["OPR_HR"]]) - 1)).strftime("%Y-%m-%dT%H:%M:%S-00:00")
        actual = r[ix["INTERVALSTARTTIME_GMT"]]
        if expect != actual:
            bad += 1
            if len(samples) < 3:
                samples.append(f"{r[ix['OPR_DT']]} HR{r[ix['OPR_HR']]}: 公式={expect} 实际={actual}")
    out = [f"用「当地午夜 + (hr-1) 小时」反推 UTC: 违例 {bad}/{len(rows)}"]
    if bad:
        # 抽出受影响那一天的小时映射
        days = sorted({s.split()[0] for s in samples})
        out += ["  受影响日期: " + ", ".join(days)]
        out += ["  " + s for s in samples]
        out.append("  -> (OPR_DT, OPR_HR) 不能替代 INTERVALSTARTTIME_GMT 做时间轴")
    return out


def hierarchy_checks(rows, ix):
    out = []
    if "TAC_AREA_NAME" not in ix:
        return out
    a, mw, dt, hr = ix["TAC_AREA_NAME"], ix["MW"], ix["OPR_DT"], ix["OPR_HR"]
    by_hour = defaultdict(dict)
    for r in rows:
        by_hour[(r[dt], r[hr])][r[a]] = float(r[mw])
    tacs = ["PGE-TAC", "SCE-TAC", "MWD-TAC", "SDGE-TAC", "VEA-TAC"]
    bad, maxerr = 0, 0.0
    for m in by_hour.values():
        if "CA ISO-TAC" not in m:
            continue
        err = abs(sum(m.get(t, 0.0) for t in tacs) - m["CA ISO-TAC"])
        maxerr = max(maxerr, err)
        if err > 0.05:
            bad += 1
    out.append(f"恒等式 CA ISO-TAC == Σ(5 个 -TAC): 违例 {bad}/{len(by_hour)} 小时, "
               f"最大误差 {maxerr:.2f} MW (源数据两位小数舍入)")
    total_all = sum(float(r[mw]) for r in rows)
    total_caiso = sum(float(r[mw]) for r in rows if r[a] == "CA ISO-TAC")
    out.append(f"朴素 Σ(全部 {len({r[a] for r in rows})} 个区域) = CA ISO-TAC 的 "
               f"{total_all / total_caiso:.2f} 倍 —— 直接求和会重复计 3 层")
    return out


def audit(name, path):
    header, rows = load(path)
    ix = {c: i for i, c in enumerate(header)}
    n = len(rows)
    verdict, evidence, uniq = {}, {}, {}

    for i, col in enumerate(header):
        vals = {r[i] for r in rows}
        uniq[col] = len(vals)
        if len(vals) == 1:
            verdict[col] = "CONST"
            evidence[col] = "全表仅一个取值: " + next(iter(vals))

    s, e = ix["INTERVALSTARTTIME_GMT"], ix["INTERVALENDTIME_GMT"]
    bad = sum(1 for r in rows if parse_iso(r[e]) - parse_iso(r[s]) != timedelta(hours=1))
    verdict["INTERVALENDTIME_GMT"] = "DERIV" if bad == 0 else "KEEP"
    evidence["INTERVALENDTIME_GMT"] = f"END-START == 1h, 违例 {bad}/{n}"

    stamps = {r[s] for r in rows}
    pairs = {(r[ix["OPR_DT"]], r[ix["OPR_HR"]]) for r in rows}
    if len(stamps) == len(pairs):
        for c in ("INTERVALSTARTTIME_GMT", "OPR_DT", "OPR_HR"):
            verdict[c] = "TIME-ALT"
            evidence[c] = (f"与另两列一一对应 ({len(stamps)} 个时间戳 ↔ {len(pairs)} 个"
                           f"(日期,小时) 对), 信息等价; 但 (日期,小时)→UTC 无闭式公式, 建议留 GMT")

    probe = ([("POS", "TAC_AREA_NAME"), ("GROUP", None)] if name == "SLD_FCST"
             else [("RENEW_POS", "RENEWABLE_TYPE"), ("GROUP", None)])
    for col, src in probe:
        if col not in ix:
            continue
        if src:
            ok, conf = is_function(rows, ix[src], ix[col])
            if ok:
                verdict[col] = "DERIV"
                evidence[col] = f"{src} 唯一决定该列, 冲突 {conf}/{n}"
        else:
            dims = (("TAC_AREA_NAME", "OPR_DT") if name == "SLD_FCST"
                    else ("TRADING_HUB", "RENEWABLE_TYPE", "OPR_DT"))
            blocks = defaultdict(set)
            for r in rows:
                blocks[tuple(r[ix[d]] for d in dims)].add(r[ix[col]])
            if all(len(v) == 1 for v in blocks.values()):
                verdict[col] = "DERIV"
                evidence[col] = (f"({' × '.join(dims)}) 唯一决定该列, "
                                 f"{len(blocks)} 个块 0 冲突")

    for i, col in enumerate(header):
        verdict.setdefault(col, "KEEP")
        evidence.setdefault(col, f"取值 {uniq[col]} 个")

    return {"name": name, "header": header, "rows": rows, "ix": ix, "n": n,
            "verdict": verdict, "evidence": evidence, "uniq": uniq}


def main():
    results = [audit(k, v) for k, v in FILES.items() if os.path.exists(v)]
    lines = ["# CAISO 两张预测表的字段可删性审计", "",
             f"生成时间: {datetime.now().isoformat(timespec='seconds')}", "",
             "判定口径: CONST = 全表单值; DERIV = 可由其他列唯一推出; "
             "TIME-ALT = 三列一一对应、只留其一; KEEP = 维度/度量。", ""]

    for res in results:
        name = res["name"]
        dims = ["TAC_AREA_NAME"] if name == "SLD_FCST" else ["TRADING_HUB", "RENEWABLE_TYPE"]
        lines += [f"## {name}", "",
                  f"- 行数 {res['n']}, 列数 {len(res['header'])}", "",
                  "| 列 | 取值数 | 判定 | 依据 |", "| --- | --- | --- | --- |"]
        for c in res["header"]:
            lines.append(f"| {c} | {res['uniq'][c]} | {res['verdict'][c]} | {res['evidence'][c]} |")
        lines.append("")

        dc = dst_check(res["rows"], res["ix"])
        lines += ["**时间轴校验**", ""] + [f"- {x}" for x in dc] + [""]

        hc = hierarchy_checks(res["rows"], res["ix"])
        if hc:
            lines += ["**层级校验**", ""] + [f"- {x}" for x in hc] + [""]

        drop = [c for c in res["header"] if res["verdict"][c] in ("CONST", "DERIV")]
        alt = [c for c in res["header"] if res["verdict"][c] == "TIME-ALT"]
        keep = [c for c in dims + ["MW"]]
        lines += [f"**删掉 {len(drop)} 列**（常量/可推导）: " + ", ".join(drop), "",
                  f"**时间三列信息等价**: " + ", ".join(alt)
                  + " -> 保留 INTERVALSTARTTIME_GMT（见上方时间轴校验）", "",
                  f"**建议最终 schema（{len(keep) + 1} 列）**: "
                  + ", ".join(keep[:1] + ["INTERVALSTARTTIME_GMT"] + keep[1:]), ""]

    lines += ["## 共用注意", "", f"- {DST_NOTE}", "",
              "- 两个报表的 OPR_DT 原文格式一致 (2023-11-01); 工作区里 sld_fcst 的 2023-11 "
              "CSV 已被改写成 2023/11/1, 与 zip 原件不一致, 合并前请以 zip 为准。", "",
              "- 常量列在抽取阶段是过滤条件, 过滤完成后才可删。", ""]

    out = os.path.join(HERE, "audit_fields_report.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\n[written] {out}")


if __name__ == "__main__":
    main()
