# W1-R4 独立兜底彩排

本报告记录独立 `naive_fallback` 与正式 B 管线的三天彩排。两条路径都只使用本地
缓存；彩排中的 RMSE 只用于检查输出链路，不用于模型选择。

## 运行命令

```text
python scripts/predict_and_submit.py --as-of 2026-10-28 --out-dir deepseek过程文件/05_中间数据/submissions
python scripts/predict_and_submit.py --as-of 2026-10-29 --out-dir deepseek过程文件/05_中间数据/submissions
python scripts/predict_and_submit.py --as-of 2026-10-30 --out-dir deepseek过程文件/05_中间数据/submissions
python scripts/fallback_submit.py --as-of 2026-10-28 --out-dir deepseek过程文件/05_中间数据/submissions
python scripts/fallback_submit.py --as-of 2026-10-29 --out-dir deepseek过程文件/05_中间数据/submissions
python scripts/fallback_submit.py --as-of 2026-10-30 --out-dir deepseek过程文件/05_中间数据/submissions
```

## 结果

三天命令均返回 0；每个输出均为 24 行、hour=1..24、NaN=0。RMSE 只比较缓存中的
历史真实价格，不参与模型选型。

| as_of | B 管线 | fallback | 两者均 24 点 | fallback NaN | sanity RMSE（B / fallback） |
|---|---:|---:|---:|---:|---:|
| 2026-10-28 | 0 | 0 | 是 | 0 | 7.36578 / 7.88984 |
| 2026-10-29 | 0 | 0 | 是 | 0 | 11.26302 / 13.55536 |
| 2026-10-30 | 0 | 0 | 是 | 0 | 6.79116 / 2.04719 |

B 管线三次 metadata 均为 `fallback=false`，`train_end` 分别为 2026-10-27、
2026-10-28、2026-10-29，严格早于对应 as_of；组件状态均为成功。

使用缺少 D-1 hour=1、2 的本地 fixture 模拟上游缺小时：fallback 返回 0，产出 24 行
有限价格，source_counts 为 `p_lag1=22`、`recent_7d_mean=2`。

## 审计结论

- 训练截止必须满足 `max(train.day) < as_of`；fallback 只读取 D 之前的历史价格。
- D 日缺小时不会改变输出结构；fallback 按 lag1、七日同小时均值、最近可用日顺序回退。
- fallback 不调用网络，也不导入正式 pipeline/model 模块。
- 预测文件只写入 `deepseek过程文件/05_中间数据/`，不提交 Git。
