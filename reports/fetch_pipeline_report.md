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
