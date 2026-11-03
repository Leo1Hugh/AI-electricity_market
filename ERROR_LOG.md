# 事故与陷阱记录（ERROR_LOG）

> 规则：每个 bug 必须写"能抓住它的那条不变量"，否则下次还会犯。
> 格式：ID / 日期 / 现象 / 根因 / 不变量 / 修复 / 回归测试。

## E-001 双向插值会泄漏未来价格
- 日期：2026-11-03（代码审查发现，尚未造成结果污染）
- 现象：work/winter_bt2.py 对 P/L/S/W 使用 interpolate(limit_direction="both")。
- 根因：为了让矩阵无 NaN，顺手用了双向插值；当前 price 无缺测，所以没影响数值；一旦价格缺测就会把未来值带进滞后特征。
- **不变量**：只用 <=D 的原始数据重算，D 日特征必须逐元素不变（tests/test_panel_contract.py::test_truncated_rebuild_has_same_features）。
- 修复：面板禁用双向插值；缺测保留 NaN。
- 回归：截断重算测试。

## E-002 25 小时日按行号 shift 会错位
- 日期：2026-11-03
- 现象：2023-11-05、2024-11-03、2025-11-02 有 OPR_HR=25；若按行数 shift，次日 HE1 会取到重复的 HE2。
- 根因：把"小时"当成了连续行号，而不是 (日, 小时) 键。
- **不变量**：p_lag1(d,h) == P(d-1,h)，逐元素；与行号无关。
- 修复：面板固定 24 行/日，丢弃 hour 25，按日历日 shift。
- 回归：test_lag1_and_lag7 + test_dst_fallback_hour25_dropped。

## E-003 春季 23 小时日不能丢整天
- 日期：2026-11-03
- 现象：2024-03-10、2025-03-09、2026-03-08 缺 OPR_HR=3；若 pivot 后直接 dropna 会丢整天。
- 根因：把"缺一小时"当成"缺一天"。
- **不变量**：每天必须有 24 行；春季三天 hour=3 存在且 y is NaN。
- 修复：reindex 到 24 小时全网格。
- 回归：test_dst_spring_missing_hour。

## E-004 风光缺测三天
- 日期：2026-11-03
- 现象：2024-03-09、2025-03-08、2026-03-07 的 SP15 Solar/Wind 在 OASIS 返回 no-data。
- 根因：源数据缺失，不是采集 bug。
- **不变量**：这三天 solar/wind/netload 全为 NaN，且不得用相邻日填补。
- 修复：保留 NaN；报告中列出。
- 回归：test_missing_renewables。

## E-005 公共仓库里的个人文件
- 日期：2026-11-03
- 现象：工作区有身份证/研究生证 PDF、报名表 DOCX；GitHub 仓库是 public。
- 根因：本地文件夹是"下载的 ZIP + 个人材料"混合。
- **不变量**：git ls-files 中不得出现 *.pdf（手册除外）/ *.docx / *身份证* / *研究生证*。
- 修复：.gitignore 先生效；只 stage 白名单路径。
- 回归：提交前检查暂存区文件名，出现 pdf/docx/身份证/研究生证 即失败。

## E-006 本地合并 ZIP 污染 verify 测试
- 日期：2026-11-03
- 现象：data/raw/caiso 下多了 sld_fcst.zip / sld_ren_fcst.zip（本地合并包），不在 manifest；verify 报 2165 anomalies，旧幂等测试 2 条失败。
- 根因：为了方便把分月 ZIP 合并成一个大 ZIP，并改写了 OPR_DT 格式；data/raw/caiso 应只放 manifest 列出的文件。
- **不变量**：data/raw/caiso 下每个 *.zip 必须能在 manifest 找到；合并包只能放 work/raw_combined/。
- 修复：移动两个合并包到 work/raw_combined/；旧 build_dataset.py 的路径同步（该脚本仅本地保留）。
- 回归：pytest -q 全绿（10 passed, 2 skipped）。

## E-007 把 pooled RMSE 当成 mean daily RMSE
- 日期：2026-11-03
- 现象：计划 G3 原写 "naive 年度 RMSE ≈ 9.21"，但新 harness 的 summary.mean 是 mean daily ≈ 7.25；直接比较会误判模型崩了/好了。
- 根因：旧 model.py 的 rmse 是小时级 pooled；冬季表是 daily。两个口径同名。
- **不变量**：mean_d(daily_rmse_d) != sqrt(mean_hour(e_h^2))；naive 实例 7.246 vs 9.206。
- 修复：G3 改用 mean daily 7.25；报告强制写口径。
- 回归：docs/建模契约 §7 + G3 文本 + 本记录。

## 模板

## E-XXX 标题
- 日期：
- 现象：
- 根因：
- **不变量**：
- 修复：
- 回归：
