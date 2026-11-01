# CAISO 预测数据核验报告

- 核验时间（UTC）：2026-11-01T08:42:58.210532+00:00
- 目标日期（加州当地交易日）：2023-11-01 至 2026-10-31
- ZIP 文件数：102；总 CSV 记录数：1059407
- manifest 记录：102；非成功状态记录：11
- `--allow-known-missing`：启用

## 目标记录统计

- `load:CA ISO-TAC`：26304 行；1096/1096 个目标日期
- `load:SCE-TAC`：26304 行；1096/1096 个目标日期
- `load:SDGE-TAC`：26304 行；1096/1096 个目标日期
- `renewable:SP15:Solar`：26232 行；1093/1096 个目标日期
- `renewable:SP15:Wind`：26232 行；1093/1096 个目标日期

## 字段与时间核验

- 目标行要求 `MARKET_RUN_ID=DAM`、日前预测 LABEL/XML_DATA_ITEM、有限数值 MW。
- UTC 开始/结束时间必须相差一小时，并与 `OPR_DT` 的 America/Los_Angeles 当地日期一致。
- 每个目标序列按 UTC 开始时间检查缺失、重复、小时数和 OPR_HR 顺序。
- 历史可用时间未验证：下载时间、ZIP 时间和 schema/version 不证明预测发布时间或无未来信息泄漏。

## 夏令时日期

- `2023-11-05`：期望 25 小时；load:CA ISO-TAC=25; load:SCE-TAC=25; load:SDGE-TAC=25; renewable:SP15:Solar=25; renewable:SP15:Wind=25
- `2024-03-10`：期望 23 小时；load:CA ISO-TAC=23; load:SCE-TAC=23; load:SDGE-TAC=23; renewable:SP15:Solar=23; renewable:SP15:Wind=23
- `2024-11-03`：期望 25 小时；load:CA ISO-TAC=25; load:SCE-TAC=25; load:SDGE-TAC=25; renewable:SP15:Solar=25; renewable:SP15:Wind=25
- `2025-03-09`：期望 23 小时；load:CA ISO-TAC=23; load:SCE-TAC=23; load:SDGE-TAC=23; renewable:SP15:Solar=23; renewable:SP15:Wind=23
- `2025-11-02`：期望 25 小时；load:CA ISO-TAC=25; load:SCE-TAC=25; load:SDGE-TAC=25; renewable:SP15:Solar=25; renewable:SP15:Wind=25
- `2026-03-08`：期望 23 小时；load:CA ISO-TAC=23; load:SCE-TAC=23; load:SDGE-TAC=23; renewable:SP15:Solar=23; renewable:SP15:Wind=23

## 已知缺失

- SP15 Solar/Wind：2024-03-09、2025-03-08、2026-03-07。CAISO 原始响应为 `ERR_CODE=1000 No data returned for the specified selection`；未插值、未使用实际值或其他区域数据。
- 只有显式使用 `--allow-known-missing` 才接受上述缺失；任何其他缺失仍会使程序返回非零。

## manifest 错误记录

- `2024-02-29..2024-03-30` `SLD_REN_FCST`：OASIS returned a ZIP containing an XML no-data/error response and no CSV member；文件 `data/raw/caiso/errors/sld_ren_fcst_2024-02-29_2024-03-29.zip`
- `2025-02-23..2025-03-25` `SLD_REN_FCST`：OASIS returned a ZIP containing an XML no-data/error response and no CSV member；文件 `data/raw/caiso/errors/sld_ren_fcst_2025-02-23_2025-03-24.zip`
- `2026-02-18..2026-03-20` `SLD_REN_FCST`：OASIS returned a ZIP containing an XML no-data/error response and no CSV member；文件 `data/raw/caiso/errors/sld_ren_fcst_2026-02-18_2026-03-19.zip`
- `2024-02-29..2024-03-10` `SLD_REN_FCST`：response ZIP contained no CSV member; inspect XML error/no-data response；文件 `data/raw/caiso/errors/sld_ren_fcst_2024-02-29_2024-03-09.zip`
- `2025-02-23..2025-03-09` `SLD_REN_FCST`：response ZIP contained no CSV member; inspect XML error/no-data response；文件 `data/raw/caiso/errors/sld_ren_fcst_2025-02-23_2025-03-08.zip`
- `2026-02-18..2026-03-08` `SLD_REN_FCST`：response ZIP contained no CSV member; inspect XML error/no-data response；文件 `data/raw/caiso/errors/sld_ren_fcst_2026-02-18_2026-03-07.zip`
- `2025-03-03..2025-03-09` `SLD_REN_FCST`：response ZIP contained no CSV member; inspect XML error/no-data response；文件 `data/raw/caiso/errors/sld_ren_fcst_2025-03-03_2025-03-08.zip`
- `2026-03-04..2026-03-08` `SLD_REN_FCST`：response ZIP contained no CSV member; inspect XML error/no-data response；文件 `data/raw/caiso/errors/sld_ren_fcst_2026-03-04_2026-03-07.zip`
- `2024-03-09..2024-03-10` `SLD_REN_FCST`：response ZIP contained no CSV member; inspect XML error/no-data response；文件 `data/raw/caiso/errors/sld_ren_fcst_2024-03-09_2024-03-09.zip`
- `2025-03-08..2025-03-09` `SLD_REN_FCST`：response ZIP contained no CSV member; inspect XML error/no-data response；文件 `data/raw/caiso/errors/sld_ren_fcst_2025-03-08_2025-03-08.zip`
- `2026-03-07..2026-03-08` `SLD_REN_FCST`：response ZIP contained no CSV member; inspect XML error/no-data response；文件 `data/raw/caiso/errors/sld_ren_fcst_2026-03-07_2026-03-07.zip`

## 代表性字段

```json
[
  {
    "INTERVALSTARTTIME_GMT": "2023-11-01T12:00:00-00:00",
    "INTERVALENDTIME_GMT": "2023-11-01T13:00:00-00:00",
    "LOAD_TYPE": "1",
    "OPR_DT": "2023-11-01",
    "OPR_HR": "6",
    "OPR_INTERVAL": "0",
    "MARKET_RUN_ID": "DAM",
    "TAC_AREA_NAME": "CA ISO-TAC",
    "LABEL": "Demand Forecast Day Ahead",
    "XML_DATA_ITEM": "SYS_FCST_DA_MW",
    "POS": "6",
    "MW": "22215.03",
    "EXECUTION_TYPE": "DAM",
    "GROUP": "11"
  },
  {
    "INTERVALSTARTTIME_GMT": "2023-11-02T01:00:00-00:00",
    "INTERVALENDTIME_GMT": "2023-11-02T02:00:00-00:00",
    "LOAD_TYPE": "1",
    "OPR_DT": "2023-11-01",
    "OPR_HR": "19",
    "OPR_INTERVAL": "0",
    "MARKET_RUN_ID": "DAM",
    "TAC_AREA_NAME": "CA ISO-TAC",
    "LABEL": "Demand Forecast Day Ahead",
    "XML_DATA_ITEM": "SYS_FCST_DA_MW",
    "POS": "6",
    "MW": "28193.45",
    "EXECUTION_TYPE": "DAM",
    "GROUP": "11"
  },
  {
    "INTERVALSTARTTIME_GMT": "2023-11-01T14:00:00-00:00",
    "INTERVALENDTIME_GMT": "2023-11-01T15:00:00-00:00",
    "LOAD_TYPE": "1",
    "OPR_DT": "2023-11-01",
    "OPR_HR": "8",
    "OPR_INTERVAL": "0",
    "MARKET_RUN_ID": "DAM",
    "TAC_AREA_NAME": "CA ISO-TAC",
    "LABEL": "Demand Forecast Day Ahead",
    "XML_DATA_ITEM": "SYS_FCST_DA_MW",
    "POS": "6",
    "MW": "25825.89",
    "EXECUTION_TYPE": "DAM",
    "GROUP": "11"
  },
  {
    "INTERVALSTARTTIME_GMT": "2023-11-01T18:00:00-00:00",
    "INTERVALENDTIME_GMT": "2023-11-01T19:00:00-00:00",
    "LOAD_TYPE": "1",
    "OPR_DT": "2023-11-01",
    "OPR_HR": "12",
    "OPR_INTERVAL": "0",
    "MARKET_RUN_ID": "DAM",
    "TAC_AREA_NAME": "CA ISO-TAC",
    "LABEL": "Demand Forecast Day Ahead",
    "XML_DATA_ITEM": "SYS_FCST_DA_MW",
    "POS": "6",
    "MW": "20237.71",
    "EXECUTION_TYPE": "DAM",
    "GROUP": "11"
  },
  {
    "INTERVALSTARTTIME_GMT": "2023-11-02T02:00:00-00:00",
    "INTERVALENDTIME_GMT": "2023-11-02T03:00:00-00:00",
    "LOAD_TYPE": "1",
    "OPR_DT": "2023-11-01",
    "OPR_HR": "20",
    "OPR_INTERVAL": "0",
    "MARKET_RUN_ID": "DAM",
    "TAC_AREA_NAME": "CA ISO-TAC",
    "LABEL": "Demand Forecast Day Ahead",
    "XML_DATA_ITEM": "SYS_FCST_DA_MW",
    "POS": "6",
    "MW": "27814.82",
    "EXECUTION_TYPE": "DAM",
    "GROUP": "11"
  },
  {
    "INTERVALSTARTTIME_GMT": "2023-11-02T05:00:00-00:00",
    "INTERVALENDTIME_GMT": "2023-11-02T06:00:00-00:00",
    "LOAD_TYPE": "1",
    "OPR_DT": "2023-11-01",
    "OPR_HR": "23",
    "OPR_INTERVAL": "0",
    "MARKET_RUN_ID": "DAM",
    "TAC_AREA_NAME": "CA ISO-TAC",
    "LABEL": "Demand Forecast Day Ahead",
    "XML_DATA_ITEM": "SYS_FCST_DA_MW",
    "POS": "6",
    "MW": "24446.49",
    "EXECUTION_TYPE": "DAM",
    "GROUP": "11"
  },
  {
    "INTERVALSTARTTIME_GMT": "2023-11-01T07:00:00-00:00",
    "INTERVALENDTIME_GMT": "2023-11-01T08:00:00-00:00",
    "LOAD_TYPE": "1",
    "OPR_DT": "2023-11-01",
    "OPR_HR": "1",
    "OPR_INTERVAL": "0",
    "MARKET_RUN_ID": "DAM",
    "TAC_AREA_NAME": "CA ISO-TAC",
    "LABEL": "Demand Forecast Day Ahead",
    "XML_DATA_ITEM": "SYS_FCST_DA_MW",
    "POS": "6",
    "MW": "22057.64",
    "EXECUTION_TYPE": "DAM",
    "GROUP": "11"
  },
  {
    "INTERVALSTARTTIME_GMT": "2023-11-01T15:00:00-00:00",
    "INTERVALENDTIME_GMT": "2023-11-01T16:00:00-00:00",
    "LOAD_TYPE": "1",
    "OPR_DT": "2023-11-01",
    "OPR_HR": "9",
    "OPR_INTERVAL": "0",
    "MARKET_RUN_ID": "DAM",
    "TAC_AREA_NAME": "CA ISO-TAC",
    "LABEL": "Demand Forecast Day Ahead",
    "XML_DATA_ITEM": "SYS_FCST_DA_MW",
    "POS": "6",
    "MW": "24693.42",
    "EXECUTION_TYPE": "DAM",
    "GROUP": "11"
  }
]
```

## 未通过项目

- 无
