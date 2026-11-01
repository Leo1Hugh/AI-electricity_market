# CAISO 预测数据核验报告

- 核验时间（UTC）：2026-11-01T07:32:46.067699+00:00
- 目标日期（加州当地交易日）：2023-11-01 至 2026-10-31
- ZIP 文件数：102；总 CSV 记录数：1059407
- manifest 记录：102；失败/无 CSV 响应：11
- 原始响应保留：是；脚本不插值、不以实际值替代预测值。

## 记录统计

### 负荷预测（SLD_FCST，DAM）

- `CA ISO-TAC`：26304 行
- `SCE-TAC`：26304 行
- `SDGE-TAC`：26304 行

### SP15 风光预测（SLD_REN_FCST，DAM）

- `Solar`：26232 行
- `Wind`：26232 行

## 核验结果

- 区间长度异常或重复 UTC 开始时间：0 条
- 关键字段缺失计数：无
- 时间戳：保留 CAISO 原始 GMT/UTC 字段；真实顺序按 UTC 开始时间检查。
- 夏令时：不强制每天 24 行；回拨日的 `OPR_HR=25` 应由 UTC 时间确认第二次 HE02。
- 地域口径：`CA ISO-TAC`、`SCE-TAC`、`SDGE-TAC` 是 TAC 区域，并不自动等同于 SP15；本报告不计算净负荷。
- 风光筛选：仅计入 `TRADING_HUB=SP15` 且 `RENEWABLE_TYPE` 为 `Solar` 或 `Wind` 的返回行。
- 历史可用时间未验证：下载时间、ZIP 时间和 schema/version 字段不视为预测发布时间，也不证明没有未来信息泄漏。

## 夏令时日期行数（目标序列）

- `2024-03-10`：load:CA ISO-TAC=23; load:SCE-TAC=23; load:SDGE-TAC=23; renewable:SP15:Solar=23; renewable:SP15:Wind=23
- `2024-11-03`：load:CA ISO-TAC=25; load:SCE-TAC=25; load:SDGE-TAC=25; renewable:SP15:Solar=25; renewable:SP15:Wind=25
- `2025-03-09`：load:CA ISO-TAC=23; load:SCE-TAC=23; load:SDGE-TAC=23; renewable:SP15:Solar=23; renewable:SP15:Wind=23
- `2025-11-02`：load:CA ISO-TAC=25; load:SCE-TAC=25; load:SDGE-TAC=25; renewable:SP15:Solar=25; renewable:SP15:Wind=25
- `2026-03-08`：load:CA ISO-TAC=23; load:SCE-TAC=23; load:SDGE-TAC=23; renewable:SP15:Solar=23; renewable:SP15:Wind=23

## manifest 失败或无数据响应

- `2024-02-29..2024-03-30` `SLD_REN_FCST`：OASIS returned a ZIP containing an XML no-data/error response and no CSV member；原始响应：`data/raw/caiso/errors/sld_ren_fcst_2024-02-29_2024-03-29.zip`
- `2025-02-23..2025-03-25` `SLD_REN_FCST`：OASIS returned a ZIP containing an XML no-data/error response and no CSV member；原始响应：`data/raw/caiso/errors/sld_ren_fcst_2025-02-23_2025-03-24.zip`
- `2026-02-18..2026-03-20` `SLD_REN_FCST`：OASIS returned a ZIP containing an XML no-data/error response and no CSV member；原始响应：`data/raw/caiso/errors/sld_ren_fcst_2026-02-18_2026-03-19.zip`
- `2024-02-29..2024-03-10` `SLD_REN_FCST`：response ZIP contained no CSV member; inspect XML error/no-data response；原始响应：`data/raw/caiso/errors/sld_ren_fcst_2024-02-29_2024-03-09.zip`
- `2025-02-23..2025-03-09` `SLD_REN_FCST`：response ZIP contained no CSV member; inspect XML error/no-data response；原始响应：`data/raw/caiso/errors/sld_ren_fcst_2025-02-23_2025-03-08.zip`
- `2026-02-18..2026-03-08` `SLD_REN_FCST`：response ZIP contained no CSV member; inspect XML error/no-data response；原始响应：`data/raw/caiso/errors/sld_ren_fcst_2026-02-18_2026-03-07.zip`
- `2025-03-03..2025-03-09` `SLD_REN_FCST`：response ZIP contained no CSV member; inspect XML error/no-data response；原始响应：`data/raw/caiso/errors/sld_ren_fcst_2025-03-03_2025-03-08.zip`
- `2026-03-04..2026-03-08` `SLD_REN_FCST`：response ZIP contained no CSV member; inspect XML error/no-data response；原始响应：`data/raw/caiso/errors/sld_ren_fcst_2026-03-04_2026-03-07.zip`
- `2024-03-09..2024-03-10` `SLD_REN_FCST`：response ZIP contained no CSV member; inspect XML error/no-data response；原始响应：`data/raw/caiso/errors/sld_ren_fcst_2024-03-09_2024-03-09.zip`
- `2025-03-08..2025-03-09` `SLD_REN_FCST`：response ZIP contained no CSV member; inspect XML error/no-data response；原始响应：`data/raw/caiso/errors/sld_ren_fcst_2025-03-08_2025-03-08.zip`
- `2026-03-07..2026-03-08` `SLD_REN_FCST`：response ZIP contained no CSV member; inspect XML error/no-data response；原始响应：`data/raw/caiso/errors/sld_ren_fcst_2026-03-07_2026-03-07.zip`

## 目标日期覆盖

- `load:CA ISO-TAC`：1096/1096 个目标日期；缺失示例：无
- `load:SCE-TAC`：1096/1096 个目标日期；缺失示例：无
- `load:SDGE-TAC`：1096/1096 个目标日期；缺失示例：无
- `renewable:SP15:Solar`：1093/1096 个目标日期；缺失示例：['2024-03-09', '2025-03-08', '2026-03-07']
- `renewable:SP15:Wind`：1093/1096 个目标日期；缺失示例：['2024-03-09', '2025-03-08', '2026-03-07']

## 代表性返回字段

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

## 缺失与限制

按 manifest 对请求失败、无记录日期、区域不适用和字段缺失分别复核。未出现的目标日期不会自动插值；需要根据对应 ZIP 的响应内容判断是源数据缺失还是报表不适用。
