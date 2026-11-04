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
