# W2-R2 模型与集成报告

基线 commit：`ecfdf5d`（`origin/main`，含 W1-R1、W1-R2 与 SP15 hourly 修正）。

数据口径为 CAISO SP15 日前价格、日前负荷/风光预测，运行日采用 `America/Los_Angeles`，预测目标为 HE1–HE24；
面板范围为 2023-11-01 至 2026-10-31。`netload` 是 CAISO TAC 负荷减 SP15 风光预测的代理特征，地域口径不完全一致。

## 可复现命令

```text
python scripts/build_panel.py --input work/hourly.csv.gz --output data/processed/panel.csv.gz
python scripts/run_compare.py --panel data/processed/panel.csv.gz --mode annual --out reports/backtests
python scripts/run_compare.py --panel data/processed/panel.csv.gz --mode winter --out reports/backtests
```

面板构建结果为 `[已验证-计算]`：26,304 行、1,096 天、88 列，`y` 有效值 26,301 行。
annual 运行目录为 `reports/backtests/20261104-142059-compare`，winter 运行目录为
`reports/backtests/20261104-142150-compare`。所有指标均为逐日 24 点 RMSE（USD/MWh），
不是 pooled hourly RMSE；崩盘阈值为 20 USD/MWh。

## 年度滚动（2025-11-01 至 2026-10-31）

以下为 `[已验证-计算]` 的 SP15 结果。MTLasso、mean3 和 shrink 只在完整 24 点目标日上计算，
因此有一个春季缺小时日被排除；mean2 只依赖 Ridge/LightGBM，保留该日的 23 个有效小时。

| 模型 | mean | median | max | p90 | crash_rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| naive_d1 | 7.24628 | 5.84121 | 49.4946 | 13.5901 | 0.0273973 |
| ridge | 6.63836 | 5.72810 | 45.0100 | 10.2325 | 0.0219178 |
| lgbm | 6.77100 | 5.35138 | 66.3090 | 9.77078 | 0.0328767 |
| mtlasso | 7.14124 | 6.06797 | 30.6660 | 11.9364 | 0.0192308 |
| mean2 | 6.14873 | 5.10995 | 43.9428 | 9.42523 | 0.0246575 |
| mean3 | 5.64560 | 4.70062 | 38.2484 | 8.62796 | 0.0192308 |
| shrink | 5.39286 | 4.36554 | 39.0091 | 8.34679 | 0.0164835 |

相对 naive_d1，shrink 的 mean 差值为 -1.85341，mean3 为 -1.60068，均为 `[已验证-计算]`。
年度最差日为 2026-09-09/10：naive_d1 为 49.4946，LightGBM 为 66.3090，mean3 为 38.2484，
shrink 为 39.0091。shrink 的平均值、p90 和崩盘率最低；mean3 的最差日略优于 shrink。

## 冬季窗口 A（2024-11-23 至 2024-12-06）

| 模型 | mean | median | max | p90 | crash_rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| naive_d1 | 7.91152 | 6.98258 | 22.0198 | 12.8751 | 0.0714286 |
| ridge | 5.66000 | 4.83536 | 10.9552 | 9.82634 | 0 |
| lgbm | 4.59074 | 3.80498 | 8.69952 | 7.64549 | 0 |
| mtlasso | 7.73982 | 6.41695 | 13.6330 | 11.8043 | 0 |
| mean2 | 4.86634 | 4.04821 | 8.89763 | 7.34600 | 0 |
| mean3 | 4.32001 | 3.70626 | 10.3020 | 5.61525 | 0 |
| shrink | 4.73909 | 3.86481 | 10.2663 | 7.87086 | 0 |

相对 naive_d1，shrink 的 mean 差值为 -3.17243，mean3 为 -3.59151，均为 `[已验证-计算]`。
最差日方面，naive_d1 为 22.0198（2024-11-25），mean3 为 10.3020，shrink 为 10.2663。

## 冬季窗口 B（2025-11-23 至 2025-12-06）

| 模型 | mean | median | max | p90 | crash_rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| naive_d1 | 7.98728 | 6.91561 | 19.0102 | 14.1848 | 0 |
| ridge | 6.35920 | 5.61701 | 11.8490 | 10.3987 | 0 |
| lgbm | 6.68056 | 6.37323 | 10.5210 | 9.09466 | 0 |
| mtlasso | 7.70861 | 7.42027 | 15.0412 | 11.2354 | 0 |
| mean2 | 6.19739 | 5.56120 | 10.1420 | 9.50011 | 0 |
| mean3 | 6.39930 | 6.60325 | 9.59992 | 8.82952 | 0 |
| shrink | 5.80167 | 5.81421 | 10.1923 | 8.41652 | 0 |

相对 naive_d1，shrink 的 mean 差值为 -2.18561，mean2 为 -1.78989，均为 `[已验证-计算]`。
最差日方面，naive_d1 为 19.0102（2025-11-23），mean3 为 9.59992，shrink 为 10.1923。

## Naive fallback、风险与后续

`NaiveD1`、`NaiveD7`、`NaiveMean7` 按任务书顺序回退到备用滞后特征；候选仍全为非有限值时明确抛出 `ValueError`。
这只处理春季缺小时造成的 lag 缺失，不改变完整数据日的主特征行为。

MTLasso 对 alpha、标准化和完整 24 点训练日敏感；本轮固定 `alpha=0.1`、`max_iter=5000`，没有在比赛窗口调参。
结果显示 MTLasso 的平均表现接近 naive，但 mean3/shrink 在三个评估范围内降低了平均误差；模型选择仍需同时观察
mean、max、p90 和崩盘率。OASIS 历史文件采用事后修订值，回测不能声称完全消除了版本发布时间偏差。
