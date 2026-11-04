# work/ 说明

`hourly.csv.gz` 是 W1 面板构建的契约输入，覆盖 2023-11-01 至
2026-10-31，共 26301 行、9 列。风光口径固定为 CAISO
`TRADING_HUB=SP15` 的 Solar/Wind 日前预测；价格来自 PRC_LMP，负荷来自
CA ISO-TAC、SCE-TAC、SDGE-TAC。

列顺序固定为：

```text
opr_dt, opr_hr, ts_utc, price, load_caiso, load_sce, load_sdge, ren_solar, ren_wind
```

2024-03-10、2025-03-09、2026-03-08 是春季跳时日，原始 hourly 保留实际缺失的
hour=3 行；panel builder 会按契约补出该行并将 y 置为 NaN。秋季回拨日的
OPR_HR=25 会在重建时丢弃。

旧版 hourly 曾因未按 `TRADING_HUB` 过滤而混入 NP15 风光值；W1-R2b 已按 SP15
重建。请使用 `scripts/rebuild_hourly.py` 生成，不要把 NP15 或其他 hub 数据混回
hourly。

## 本地中间文件

`raw_combined/`、`crops/`、`pdf/`、`rules_png/`、`sub_png/` 和回测中间产物只在本地
使用，不放入 `data/raw/caiso/`。新流水线在 `src/em/` 与 `scripts/`。
