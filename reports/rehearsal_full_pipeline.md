# W2-R9 全链路真实网络彩排报告

## 范围与基线

- 分支：`w2/r9-rehearsal`。
- 基线：`origin/main` `be93f03`（W2-R7 合并后的 main）。
- 目标日：2026-11-09、2026-11-10、2026-11-11（America/Los_Angeles，回放式）。
- 本任务只新增本报告；没有修改模型、特征、面板、契约或正式流水线代码。
- 运行时间为 2026-11-11（UTC 记录见命令输出）；这不是比赛日 00:30 实时流程，首次 ready 等待阶段未在回放中复现，真实操作仍以 `reports/submission_runbook.md` 为准。

## 正式命令与计时结果

每个目标日均执行：

```text
python scripts/predict_and_submit.py --as-of D --refresh-data --out-dir deepseek过程文件/05_中间数据/submissions_rehearsal
```

使用临时计时包装器记录 `fetch`、`rebuild`、`panel`、`train+predict` 和端到端时间。`fetch` 在 PRC_LMP 失败后返回 1，正式命令随即进入缓存回退；当时没有 D 日缓存面板，因此没有生成正式提交文件，后续阶段未执行。

计时包装器把仓库根目录加入临时进程的 import path 后调用同一 CLI `main`，以便把阶段时间拆开。直接按任务书从 shell 启动 `python scripts/predict_and_submit.py ...` 的三次命令（包括验收命令）均在进入 fetch 前返回 1，错误为 `No module named 'scripts'`；这是该脚本的启动路径问题，也作为阻断项记录。下面的阶段计时反映已隔离 import 路径后的真实 fetch 行为，未把它误记为正式 shell 命令成功。

| 目标日 | 30 天窗口（D-29..D） | fetch(s) | rebuild(s) | panel(s) | train+predict(s) | 总耗时(s) | CLI | 24 点/标签/RMSE |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 2026-11-09 | 2026-10-11..2026-11-09 | 4.729 | 未执行 | 未执行 | 未执行 | 4.878 | 1 | 未生成；RMSE 未计算 |
| 2026-11-10 | 2026-10-12..2026-11-10 | 7.996 | 未执行 | 未执行 | 未执行 | 8.099 | 1 | 未生成；RMSE 未计算 |
| 2026-11-11 | 2026-10-13..2026-11-11 | 7.465 | 未执行 | 未执行 | 未执行 | 7.574 | 1 | 未生成；RMSE 未计算 |

计时结果为本次运行的 `[已验证-计算]` 数字。三个请求均确实把 `--days 30` 传给 `fetch_daily`；SLD_FCST 和 SLD_REN_FCST ZIP 成功写入本地过程数据目录。PRC_LMP 返回：`CAISO XML error 1001: Invalid Parameters of the given report name`，因此无法取得 D 日实际价格、构建含 D 的面板，也不能把模型预测与 `p_lag1` 做日 RMSE 对账。没有为失败路径填写模型、`train_end`、`feature_missing` 或 RMSE 数字。

### 取数参数核对

正式流水线生成的 PRC_LMP 请求包含 `version=1`、`node=TH_SP15_GEN-APND` 和 `lmp_type=LMP`。这三个目标日都收到上述 XML 参数错误，故“30 天窗口”已核对，但“PRC_LMP 请求成功”未通过。

作为独立诊断，运行了：

```text
python scripts/check_data_readiness.py --as-of 2026-11-09 --once
python scripts/check_data_readiness.py --as-of 2026-11-10 --once
python scripts/check_data_readiness.py --as-of 2026-11-11 --once
```

结果分别为：2026-11-09 的 PRC_LMP 请求收到 HTTP 429（负荷和风光 24 点就绪）；2026-11-10 三报表均就绪，PRC_LMP 为 24 点、最新 `2026-11-09`；2026-11-11 的 PRC_LMP 为 24 点、最新 `2026-11-10`，两个预测报表收到 HTTP 429。该诊断使用 `version=12` 且不发送 `lmp_type`，与正式 `fetch_daily` 的请求不一致。

## 故障演练

先用本地 `work/hourly.csv.gz` 构建截至 2026-10-31 的缓存面板，然后在缓存缺少 D 日时运行无 refresh 路径：

```text
python scripts/predict_and_submit.py --as-of 2026-11-09 --out-dir deepseek过程文件/05_中间数据/fault_no_refresh
python scripts/predict_and_submit.py --as-of 2026-11-10 --out-dir deepseek过程文件/05_中间数据/fault_no_refresh
python scripts/predict_and_submit.py --as-of 2026-11-11 --out-dir deepseek过程文件/05_中间数据/fault_no_refresh
```

三次均返回 0，生成 24 行、`hour=1..24`、有限价格；`submission.json` 的 `model=naive_only`，`fallback=true`，`data_stale=true`，`naive_only=true`。缓存的 `train_end=2026-10-31`，严格早于每个目标日；这里没有把陈旧缓存结果当作正式模型结果。

独立兜底命令：

```text
python scripts/fallback_submit.py --as-of 2026-11-09 --out-dir deepseek过程文件/05_中间数据/fault_fallback
python scripts/fallback_submit.py --as-of 2026-11-10 --out-dir deepseek过程文件/05_中间数据/fault_fallback
python scripts/fallback_submit.py --as-of 2026-11-11 --out-dir deepseek过程文件/05_中间数据/fault_fallback
```

三次均按陈旧源规则返回退出码 2，没有写出提交：本地最新价格日为 `2026-10-31`，分别低于要求的 `2026-11-07`、`2026-11-08`、`2026-11-09`。这是预期的 stale-source 行为；source 为 `work/hourly.csv.gz`，未使用网络。

## 发现与交接

1. **阻断项（交 Lead）**：`scripts/fetch_daily.py` 仍为 PRC_LMP 发送 `version=1` 与 `lmp_type=LMP`，真实请求返回 XML 1001；`scripts/check_data_readiness.py` 的 `version=12`/无 `lmp_type` 查询在 2026-11-10 可取得 24 点。W2-R9 禁止修改正式流水线代码，因此本报告只记录问题，建议 Lead 开新的 W1 取数修复任务并在修复后重跑三天。
2. `reports/rehearsal_data_side.md` 在本次基线 `be93f03` 和当前 `origin/main` 均不存在，无法与 A 的数据侧数字做独立核对；本项状态为“文件缺失，未核对”，不是“一致”。
3. 因正式 PRC_LMP 失败，三天没有正式模型预测、metadata 校验或模型对 naive 的日 RMSE；这些数字待取数修复后重跑，不能用故障演练的 `naive_only` 结果代替。
4. 本次网络取数产生的 ZIP、manifest 修改和过程目录输出均属于临时产物，提交前已清理，不进入 Git。

## 验收命令

验收命令实际结果：`python -m pytest -q` 为 `102 passed, 5 warnings`；
`python scripts/predict_and_submit.py --as-of 2026-11-10 --refresh-data --out-dir deepseek过程文件/05_中间数据/submissions_rehearsal`
返回 1，错误为 `No module named 'scripts'`，随后缓存和 work hourly 均因缺少 D 日返回失败。真实网络阻断的退出码和错误已原样记录。
