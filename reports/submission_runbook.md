# 竞赛日提交 runbook（W1-R5）

## 时区与硬红线

所有运行日使用 `America/Los_Angeles`。北京时间比加州早 15 或 16 小时；北京时间
02:00 截止对应加州前一日 10:00。`--as-of D` 是加州本地运行日。

先执行 readiness 预检，再取数和预测。数据未 ready 时不得运行正式模型，以免静默使用
缺失特征；fallback 的陈旧源默认拒绝，只有确认后才使用 `--allow-stale`。

## 时间表

| 北京时间 | 动作 |
|---|---|
| 00:30 | `check_data_readiness.py --as-of D --once`，并开始每 3–5 分钟 watch；不跑模型 |
| 首次 ready + 2 分钟 | 以实测首次 ready 时刻为准，执行 refresh、rebuild、panel 和预测 |
| 01:25 | 复核 metadata：`fallback`、`feature_missing`、`data_stale`、`model` |
| 01:40 | 仍 not-ready 或正式模型 fallback 时运行独立 fallback |
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

R5b 修正了 PRC_LMP 查询参数：`version=12`、指定 node、无 `lmp_type`。此前的
PRC_LMP no-data 归因是查询参数 bug；SLD_FCST no-data 才表示负荷尚未发布。

真实复核记录（均为独立 `--once`，网络响应原样摘要）：

```json
{"as_of":"2026-11-08","checked_at":"2026-11-11T04:45:56.959146+00:00","exit_code":0,"ready":true,"PRC_LMP":{"hours":24,"latest_opr_dt":"2026-11-07"},"SLD_FCST":{"CA ISO-TAC":24,"SCE-TAC":24,"SDGE-TAC":24},"SLD_REN_FCST":{"Solar":24,"Wind":24}}
{"as_of":"2026-11-09","checked_at":"2026-11-11T04:57:08.490113+00:00","exit_code":0,"ready":true,"PRC_LMP":{"hours":24,"latest_opr_dt":"2026-11-08"},"SLD_FCST":{"CA ISO-TAC":24,"SCE-TAC":24,"SDGE-TAC":24},"SLD_REN_FCST":{"Solar":24,"Wind":24}}
```

时间换算：第一条为 CA 2026-11-10 20:45:56 PST / 北京 2026-11-11 12:45:56；
第二条为 CA 2026-11-10 20:57:08 PST / 北京 2026-11-11 12:57:08。

Lead 的现场时延记录：D=2026-11-10 的 fetch 8.7s、rebuild 11.9s、panel 0.1s、
预测 21.2s，总计 42s；因此首次 ready 后 +2 分钟足够。另有记录显示 D 日负荷在
D-1 07:33 CA（北京 23:33）和 08:00 CA 仍不可用，预期约 09:00 CA（北京 01:00）。

目标窗口的连续 watch 未在本会话保持运行，未编造首次 ready 时点。现场值班运行：

```text
python scripts/check_data_readiness.py --as-of 2026-11-09 --watch --interval 300 --until "2026-11-09T02:10:00+08:00" > deepseek过程文件/04_运行日志/20261108_sldfcst_readiness.jsonl
```

竞赛日预测只保存在过程目录，不提交 Git；提交前检查 `git status` 和文件日期。
