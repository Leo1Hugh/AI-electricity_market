# CAISO 预测数据采集说明

## 来源和查询

- 官方说明：[OASIS Frequently Asked Questions](https://www.caiso.com/documents/oasis-frequently-asked-questions.pdf)
- 官方接口：`https://oasis.caiso.com/oasisapi/SingleZip`
- 负荷报表：`queryname=SLD_FCST&market_run_id=DAM&resultformat=6&startdatetime=...&enddatetime=...&version=1`
- 风光报表：`queryname=SLD_REN_FCST&market_run_id=DAM&resultformat=6&startdatetime=...&enddatetime=...&version=1`

两个报表均按加州当地日期的午夜边界转换为 UTC 查询。`resultformat=6` 使 ZIP 内返回 CSV；原始 ZIP 未改写。OASIS 每次最多接受 31 天，本次使用不跨超过 30 个当地日期的批次，并在春季夏令时附近进一步拆分。

## 字段核对

`SLD_FCST` 的目标行使用 `TAC_AREA_NAME`：`CA ISO-TAC`、`SCE-TAC`、`SDGE-TAC`。预测字段为 `XML_DATA_ITEM=SYS_FCST_DA_MW`，数值字段为 `MW`，标签为 `Demand Forecast Day Ahead`，市场字段为 `MARKET_RUN_ID=DAM`。

`SLD_REN_FCST` 的目标行使用 `TRADING_HUB=SP15` 和 `RENEWABLE_TYPE` 为 `Solar` 或 `Wind`。预测字段为 `XML_DATA_ITEM=RENEW_FCST_DA_MW`，数值字段为 `MW`，标签为 `Renewable Forecast Day Ahead`，市场字段为 `MARKET_RUN_ID=DAM`。

负荷 TAC 区域是 CAISO 报表地域口径，不能直接当作 SP15 的地域范围；本次没有用这些区域与 SP15 风光数据计算净负荷。

## 范围和结果

- 目标日期：加州当地交易日 2023-11-01 至 2026-10-31。
- 负荷：三个目标 TAC 各覆盖 1096 个目标日期、26304 行。
- SP15 Solar/Wind：各覆盖 1093 个目标日期、26232 行。
- 风光缺失日期：2024-03-09、2025-03-08、2026-03-07。对这些日期，OASIS 返回 HTTP 200 但 ZIP 内只有 XML `ERR_CODE=1000` 的 no-data 响应；原始错误 ZIP 保存在 `data/raw/caiso/errors/`，未插值或用其他日期替代。

春季切换日的跨 DST 大批次也曾返回 no-data XML；拆分后其余日期均已成功取得。秋季回拨和春季跳过的有效日期保留实际小时数：报告中可见 23 小时和 25 小时序列，真实顺序按 UTC 开始时间判断，未强制补齐 24 行。

## 预测发布时间限制

CAISO 文档描述 DAM 预测通常在运行日前一天早间发布，但本次返回 CSV 只提供运行日、预测类型和数值，不提供可证明某一历史版本在比赛截止时间前已发布的版本发布时间。ZIP 文件名、HTTP 获取时间、`MessageHeader` 时间和 schema/version 只记录响应生成/下载信息，不能作为预测发布时间。因此历史可用时间标记为“历史可用时间未验证”，也不能据此声称已经消除未来信息泄漏。

## 复核

```bash
python scripts/verify_caiso_forecasts.py \
  --root data/raw/caiso \
  --manifest data/caiso_collection_manifest.jsonl \
  --report data/caiso_validation_report.md \
  --start-date 2023-11-01 --end-date 2026-10-31
```

`data/caiso_collection_manifest.jsonl` 记录每个请求的日期范围、完整查询地址、UTC 获取时间、HTTP 状态、ZIP 文件名、成员记录数和 SHA-256。有效响应与无数据错误响应分目录保存。
