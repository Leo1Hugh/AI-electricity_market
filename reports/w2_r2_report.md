# W2-R2 模型与集成报告

基线：`origin/main`（当前基线 `ad5c4bf`）。

本报告暂不包含年度或冬季指标。旧 `work/hourly.csv.gz` 的风光字段口径为 NP15，
与契约要求的 SP15 不一致，之前基于该文件跑出的 annual/winter 结果全部作废，
不作为模型选择、PR 结论或验收依据。

**待 SP15 数据合并后重跑。**

重跑命令：

```text
python scripts/build_panel.py --input work/hourly.csv.gz --output data/processed/panel.csv.gz
python scripts/run_compare.py --panel data/processed/panel.csv.gz --mode annual --out reports/backtests
python scripts/run_compare.py --panel data/processed/panel.csv.gz --mode winter --out reports/backtests
```

重跑时需要重新核对 2023-11-01 至 2026-10-31 的 SP15 面板、年度滚动窗口、2024/2025 两段冬季窗口、
最差日和崩盘率；在 SP15 数据合并前不填写任何数值结论。
