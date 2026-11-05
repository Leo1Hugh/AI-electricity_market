# 竞赛日提交 runbook

## 时区与截止

所有运行日使用 `America/Los_Angeles`。北京时间比加州早 15 或 16 小时；比赛日的
北京时间 02:00 截止对应加州前一日 10:00。命令中的 `--as-of D` 是加州本地运行日。

## 时间表

| 北京时间 | 动作 |
|---|---|
| 00:30 | 拉取最近 7 天 PRC_LMP、SLD_FCST、SLD_REN_FCST |
| 01:00 | 重建过程 hourly/panel，运行正式模型 |
| 01:20 | 检查 24 点、有限值、范围和 fallback 标记 |
| 01:40 | 人工复核晚峰、假日和 naive 偏差 |
| 01:50 | 准备并提交 24 个价格 |
| 02:00 | 截止；保留日志和 metadata |

## 正常路径

```text
python scripts/predict_and_submit.py --as-of YYYY-MM-DD --refresh-data --out-dir deepseek过程文件/05_中间数据/submissions
```

使用缓存、跳过 refresh：

```text
python scripts/predict_and_submit.py --as-of YYYY-MM-DD --out-dir deepseek过程文件/05_中间数据/submissions
```

先查看计划：

```text
python scripts/predict_and_submit.py --as-of YYYY-MM-DD --dry-run
```

## 独立 fallback

```text
python scripts/fallback_submit.py --as-of YYYY-MM-DD --out-dir deepseek过程文件/05_中间数据/submissions
```

fallback 只读本地 `work/hourly.csv.gz`，按 D-1 同小时价格、之前 7 个日历日均值、
最近可用日顺序补齐。它不联网，不覆盖 `work/hourly.csv.gz`。

## 五分钟人工复核

- `predictions.csv` 恰好 24 行，hour 恰好 1..24，价格没有 NaN/inf。
- day 与 `--as-of` 一致，metadata 的 train_end 严格早于 D。
- 晚峰小时没有数量级异常，范围 warning 已阅读。
- 与 naive fallback 的差异可解释；节假日标记和天气/负荷缺测已记录。
- `submission.json` 的日期、小时和价格顺序正确；平台粘贴后逐项对账。

## 故障分支

| 故障 | 命令/处理 | 负责人 |
|---|---|---|
| 取数失败 | 不覆盖缓存；先用无 `--refresh-data` 的缓存路径，仍失败则 fallback | W1 值班 |
| 正式模型异常 | 保留 stderr 和 metadata，运行 `fallback_submit.py` | W2/W1 值班 |
| 输出缺行或 NaN | 不提交异常文件；重新运行 fallback 并复核 24 行 | Lead 值班 |
| 平台提交失败 | 保存本地 `submission.json`，人工重试并记录时间 | Lead 值班 |

竞赛日预测只保存在过程目录，不提交 Git；提交前检查 `git status` 和文件日期。
