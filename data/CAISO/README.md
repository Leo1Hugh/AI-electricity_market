# CAISO SP15 日前电价

本目录保存从 [CAISO OASIS](https://oasis.caiso.com/mrioasis/logon.do) 获取的公开原始数据，供线上组电价预测和交易决策使用。市场类型为 `DAM`，交易枢纽节点为 `TH_SP15_GEN-APND`。

- 覆盖加州当地交易日 2023-11-01 至 2026-10-31，共 36 个月。
- 每月目录保留 CAISO 返回的 ZIP 及其中未经修改的 CSV。`2026-10-30/` 是此前单独采集的样本。
- `CAISO_SP15_DAM_2023-11_to_2026-10_raw_csv.zip` 汇集 36 个原始月度 CSV。
- `CAISO_SP15_DAM_2023-11_to_2026-10_manifest.json` 记录每月查询地址、文件 SHA-256、记录数和完整性检查；文件路径相对于仓库根目录。

原始 CSV 包含总电价和价格分项。筛选 `LMP_TYPE = LMP`，从 `MW` 字段读取总电价，单位为美元/MWh。三年共 26,304 条小时总电价记录；所有类型合计 131,520 行。

处理时应按 `INTERVALSTARTTIME_GMT` 确定真实顺序，并保留 `OPR_DT` 和 `OPR_HR`。夏令时切换日可能为 23 或 25 小时；秋季回拨时 `OPR_HR = 25` 表示第二次出现的 HE02，不应排序到当天最后。详见 [CAISO 夏令时说明](https://www.caiso.com/documents/daylightsavingtimelongdayinformation.pdf)。

数据为事后获取的日前市场结果。构造预测特征和回测时，需要确保每条输入在预测截止时已发布；CAISO 也可能对已发布数据进行修正。
