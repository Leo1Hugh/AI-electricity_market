# W1-R2 日更取数管道报告

本报告记录 `scripts/fetch_daily.py` 的实现约定。日更入口默认使用
America/Los_Angeles 的本地日期窗口，覆盖 PRC_LMP、SLD_FCST 和
SLD_REN_FCST 三个 DAM 报表；请求复用现有 collector 的 URL、下载和 ZIP
核验函数。

- `--dry-run` 只打印 URL 与目标文件，不创建目录、不改 manifest。
- 默认已有文件跳过；`--refresh` 先完成新 ZIP 校验，再把旧 ZIP 移入
  `data/raw/caiso/revisions/<report>/<UTC 时间戳>/` 后原子替换。
- 每次成功动作追加 JSONL manifest，记录 SHA-256、行数、动作和替换前后摘要。
- 网络、损坏 ZIP 或 CAISO no-data 响应返回非零，旧文件保持原字节不变。

真实窗口的 dry-run 输出由验收命令生成；本报告不手写网络响应数量。

## 数据口径修正

W1-R2b 将 hourly 风光列固定为 `TRADING_HUB=SP15` 的 Solar/Wind。旧版
`work/hourly.csv.gz` 曾因未过滤交易 hub 混入 NP15 值；重建时 legacy 比较门只校验
`price`、三列负荷和 `ts_utc`，风光独立与 raw SP15 逐元素核对。旧版风光差异保留为
WARNING，不回写 NP15 数据。

本次重建结果：`work/hourly.csv.gz` 为 26301 行、9 列，SHA-256 为
`1fd735fc5c92900793cc4457108a6761f4b03b02c7d16f3482702acd4622ccf8`；raw SP15
Solar/Wind 均为 26229/26229 行精确匹配，3 个春季日期各缺少 hour=3。

## W1-R6 日更价格链路修复

历史 PRC_LMP manifest 使用 `version=12`、`node=TH_SP15_GEN-APND`，不带
`lmp_type`；fetch_daily 已同步该参数。rebuild 现在同时读取
`raw_root/prc_lmp/*.zip` 及 revisions 下的日更 ZIP，并与历史 CSV 使用同一套
版本排序，较新的源覆盖较旧源。30 天窗口由调用方保证，以覆盖 D-7。

真实临时目录验收（2026-11-11 UTC，未写仓库 `data/`）：

| 报表 | manifest 时间（UTC） | ZIP 字节 | CSV 行数 | 状态 |
|---|---|---:|---:|---|
| PRC_LMP | 2026-11-11T07:57:11.684118Z | 38,459 | 3,605 | ok |
| SLD_FCST | 2026-11-11T07:57:14.172439Z | 248,305 | 25,956 | ok |
| SLD_REN_FCST | 2026-11-11T07:57:16.141782Z | 44,805 | 5,047 | ok |

同一临时 raw 重建结果：`price_csv=37`、`price_zip=1`；输出覆盖至
2026-11-08，2026-11-07 价格 24 小时，2026-11-08 的负荷/风光均为 24 小时。
使用该 panel 运行 `run_pipeline(panel, 2026-11-08)` 得到 `fallback=false`、
`train_end=2026-11-07`、24 个有限预测。
