# 竞赛日提交 runbook（W1-R5）

## 时区与硬红线

所有运行日使用 `America/Los_Angeles`。北京时间比加州早 15 或 16 小时；北京时间
02:00 截止对应加州前一日 10:00。`--as-of D` 是加州本地运行日。

先执行 readiness 预检，再取数和预测。数据未 ready 时不得运行正式模型，以免静默使用
缺失特征；fallback 的陈旧源默认拒绝，只有确认后才使用 `--allow-stale`。

## 时间表

| 北京时间 | 动作 |
|---|---|
| 00:30 | `check_data_readiness.py --as-of D --once`，不跑模型 |
| 01:00–01:15 | 以现场首次 ready 时刻为准，+5 分钟后执行 refresh 和预测 |
| 01:25 | 复核 metadata：`fallback`、`feature_missing`、`data_stale`、`model` |
| 01:35 | 仍 not-ready 或正式模型 fallback 时运行独立 fallback |
| 01:45 | 提交前人工复核并对账 |
| 02:00 | 截止；保留 JSON、日志和 stderr |

## 预检与正常路径

一次预检（只读，不写 `data/`）：

```text
python scripts/check_data_readiness.py --as-of YYYY-MM-DD --once
```

若需要等待现场 ready：

```text
python scripts/check_data_readiness.py --as-of YYYY-MM-DD --watch --interval 300 --until "YYYY-MM-DDTHH:10:00+08:00" > deepseek过程文件/04_运行日志/YYYYMMDD_sldfcst_readiness.jsonl
```

ready 后运行正式路径：

```text
python scripts/predict_and_submit.py --as-of YYYY-MM-DD --refresh-data --out-dir deepseek过程文件/05_中间数据/submissions
```

使用已经确认的缓存：

```text
python scripts/predict_and_submit.py --as-of YYYY-MM-DD --out-dir deepseek过程文件/05_中间数据/submissions
```

## 独立 fallback

```text
python scripts/fallback_submit.py --as-of YYYY-MM-DD --out-dir deepseek过程文件/05_中间数据/submissions
```

默认源优先级为 `hourly_inference.csv.gz`、`panel_inference.csv.gz`、
`work/hourly.csv.gz`。metadata 必须检查 `source_path`、`source_latest_day`、
`source_stale` 和 `allow_stale`。最新价格到 D-2 会标记 stale 并允许继续；早于 D-2
默认退出 2：

```text
python scripts/fallback_submit.py --as-of YYYY-MM-DD --allow-stale --out-dir deepseek过程文件/05_中间数据/submissions
```

## 五分钟人工复核

- readiness 三报表均 ready；负荷三个 TAC、SP15 Solar/Wind 和 D-1 价格小时数齐全。
- `predictions.csv` 恰好 24 行，hour 恰好 1..24，价格没有 NaN/inf。
- metadata 的 `train_end` 严格早于 D；检查 `fallback`、`feature_missing`、`data_stale`、`model`。
- `source_latest_day` 至少为 D-2；若为 D-2，确认已阅读 stderr 警告。
- 晚峰小时没有数量级异常，假日和缺测说明已阅读。
- `submission.json` 的日期、小时和价格顺序正确；平台粘贴后逐项对账。

## 故障分支

| 故障 | 处理 | 负责人 |
|---|---|---|
| readiness 网络/格式错误 | 保留 JSONL 和 stderr；在截止前重试一次，仍失败则不跑正式模型并转 fallback | W1 值班 |
| readiness not-ready | 等待 watch 到截止；不要运行正式模型；确认缓存日期后用 fallback | W1/Lead |
| refresh 失败或缓存缺失 | 使用已确认缓存；若源陈旧必须显式 `--allow-stale` 并记录原因 | W1 值班 |
| 正式模型异常或 fallback=true | 保留 metadata，运行独立 fallback 并复核 24 点 | W2/W1 值班 |
| 源数据早于 D-2 | 默认拒绝；Lead 确认后才加 `--allow-stale` | Lead |
| 平台提交失败 | 保存本地 `submission.json`，人工重试并记录时间 | Lead |

## 现场核验记录

readiness 现场核验目标为 D=2026-11-09。独立一次实测于
2026-11-08T06:20:14Z（CA 2026-11-07 22:20:14 PDT；北京 2026-11-08 14:20:14 CST；退出码 1）
返回 `ready=false`：PRC_LMP、SLD_FCST 是 XML/no-data，SLD_REN_FCST Solar/Wind
各 24 小时。该结果不代表后续发布时间。

`BLOCKED:` 当前会话无法在目标窗口北京 2026-11-08 22:00–2026-11-09 02:10 持续
watch，因此没有编造首次 ready 时点。现场值班在仓库根目录运行：

```text
python scripts/check_data_readiness.py --as-of 2026-11-09 --watch --interval 300 --until "2026-11-09T02:10:00+08:00" > deepseek过程文件/04_运行日志/20261108_sldfcst_readiness.jsonl
```

竞赛日预测只保存在过程目录，不提交 Git；提交前检查 `git status` 和文件日期。
