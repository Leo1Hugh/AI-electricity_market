# W2-R6 提交流水线报告

基线：`origin/main`（含 W2-R4/W2-R5，W2-R3 已冻结 `shrink3_0.8`）。本轮没有修改基础模型、ensemble、面板构建器或模型卡。

## 模型配置

- 特征：`BASE_FEATURES`，37 列。
- Ridge：`alpha=10.0`。
- LightGBM：现有默认参数，`random_state=0`。
- MTLasso：`alpha=0.1`、`max_iter=5000`。
- 组合：`mean3 = mean(ridge, lgbm, mtlasso)`，最终 `shrink3_0.8 = 0.8 * mean3 + 0.2 * naive_d1`。
- 训练截止：严格 `day < as_of`；NaiveD1 依次回退 `p_lag2`、`p_lagmean7`、`p_lag7`，最终回退使用最近七个历史日的同小时均值。

## 可复现命令与彩排

```text
python scripts/predict_and_submit.py --as-of 2026-10-30 --out-dir deepseek过程文件/05_中间数据/submissions
python scripts/predict_and_submit.py --as-of 2026-10-15 --out-dir deepseek过程文件/05_中间数据/submissions
python scripts/predict_and_submit.py --as-of 2026-11-24 --dry-run
```

W2-R4 的两次缓存数据彩排均生成 24 行、hour=1..24、有限价格，组件全部成功，`fallback=false`：

| as_of | train_end | sanity RMSE（仅彩排） | range_warning |
| --- | --- | ---: | --- |
| 2026-10-30 | 2026-10-29 | 6.79116 | false |
| 2026-10-15 | 2026-10-14 | 3.65320 | false |

上述 RMSE 仅用于流水线 sanity check，不参与模型选择。`--dry-run` 未创建目录或文件。

W2-R5/R6 的取数/重建故障路径全部使用 mock 测试覆盖：

- refresh/fetch 失败且缓存 panel 含 D：仍生成 24 点，metadata 标记 `data_stale=true`、`fallback=true`。
- rebuild 失败且缓存不含 D：生成 24 点 naive-only，metadata 标记 `naive_only=true`。
- 缓存和 `work/hourly.csv.gz` 都不可用：返回非零并在 stderr 写明各层失败原因。
- D 日 27 个非日历特征任一缺失：不拟合模型，直接 `naive_fallback`，metadata 记录缺失列和小时。
- `naive_only`、`naive_fallback`、`shrink3_0.8` 在 metadata 和 submission.json 中使用真实标签。

## 输出与失败回退

非 dry-run 输出到 `deepseek过程文件/05_中间数据/submissions/YYYY-MM-DD/`：
`predictions.csv`（`day,hour,price`）、`metadata.json`、`submission.json`。过程文件不提交 Git。

任一 fetch/rebuild、Ridge、LightGBM、MTLasso 或组合步骤失败时，流水线按缓存、work hourly、naive-only 顺序回退；最终结构校验失败也会再次回退。
metadata 记录 `fallback`、`fallback_reason`、训练截止、数据 SHA-256 和校验结果。范围越界只标记 warning，不裁剪价格。

无 refresh 路径也复用缓存回退：缓存缺 D 日时生成 `naive_only`，缓存和 work hourly 都不可用才退出 1。

## 已验证结果

`python -m pytest -q tests/test_pipeline.py tests/test_predict_and_submit.py`：8 passed。
全量 `python -m pytest -q`：82 passed。

W2-R6 CLI 彩排 `2026-10-30` 返回 0：24 点、`fallback=false`、`data_stale=false`、`feature_missing` 为空。

未验证项：真实网络 refresh 未在新代码上运行；D 日负荷预测发布时刻由 W1-R5 实测。
