# CAISO 两张预测表的字段可删性审计

生成时间: 2026-11-01T20:45:11

判定口径: CONST = 全表单值; DERIV = 可由其他列唯一推出; TIME-ALT = 三列一一对应、只留其一; KEEP = 维度/度量。

## SLD_FCST

- 行数 24514, 列数 14

| 列 | 取值数 | 判定 | 依据 |
| --- | --- | --- | --- |
| INTERVALSTARTTIME_GMT | 721 | TIME-ALT | 与另两列一一对应 (721 个时间戳 ↔ 721 个(日期,小时) 对), 信息等价; 但 (日期,小时)→UTC 无闭式公式, 建议留 GMT |
| INTERVALENDTIME_GMT | 721 | DERIV | END-START == 1h, 违例 0/24514 |
| LOAD_TYPE | 1 | CONST | 全表仅一个取值: 1 |
| OPR_DT | 30 | TIME-ALT | 与另两列一一对应 (721 个时间戳 ↔ 721 个(日期,小时) 对), 信息等价; 但 (日期,小时)→UTC 无闭式公式, 建议留 GMT |
| OPR_HR | 25 | TIME-ALT | 与另两列一一对应 (721 个时间戳 ↔ 721 个(日期,小时) 对), 信息等价; 但 (日期,小时)→UTC 无闭式公式, 建议留 GMT |
| OPR_INTERVAL | 1 | CONST | 全表仅一个取值: 0 |
| MARKET_RUN_ID | 1 | CONST | 全表仅一个取值: DAM |
| TAC_AREA_NAME | 34 | KEEP | 取值 34 个 |
| LABEL | 1 | CONST | 全表仅一个取值: Demand Forecast Day Ahead |
| XML_DATA_ITEM | 1 | CONST | 全表仅一个取值: SYS_FCST_DA_MW |
| POS | 7 | DERIV | TAC_AREA_NAME 唯一决定该列, 冲突 0/24514 |
| MW | 22472 | KEEP | 取值 22472 个 |
| EXECUTION_TYPE | 1 | CONST | 全表仅一个取值: DAM |
| GROUP | 1020 | DERIV | (TAC_AREA_NAME × OPR_DT) 唯一决定该列, 1020 个块 0 冲突 |

**时间轴校验**

- 用「当地午夜 + (hr-1) 小时」反推 UTC: 违例 102/24514
-   受影响日期: 2023/11/5
-   2023/11/5 HR25: 公式=2023-11-06T08:00:00-00:00 实际=2023-11-05T09:00:00-00:00
-   2023/11/5 HR1: 公式=2023-11-05T08:00:00-00:00 实际=2023-11-05T07:00:00-00:00
-   2023/11/5 HR2: 公式=2023-11-05T09:00:00-00:00 实际=2023-11-05T08:00:00-00:00
-   -> (OPR_DT, OPR_HR) 不能替代 INTERVALSTARTTIME_GMT 做时间轴

**层级校验**

- 恒等式 CA ISO-TAC == Σ(5 个 -TAC): 违例 0/721 小时, 最大误差 0.02 MW (源数据两位小数舍入)
- 朴素 Σ(全部 34 个区域) = CA ISO-TAC 的 4.05 倍 —— 直接求和会重复计 3 层

**删掉 9 列**（常量/可推导）: INTERVALENDTIME_GMT, LOAD_TYPE, OPR_INTERVAL, MARKET_RUN_ID, LABEL, XML_DATA_ITEM, POS, EXECUTION_TYPE, GROUP

**时间三列信息等价**: INTERVALSTARTTIME_GMT, OPR_DT, OPR_HR -> 保留 INTERVALSTARTTIME_GMT（见上方时间轴校验）

**建议最终 schema（3 列）**: TAC_AREA_NAME, INTERVALSTARTTIME_GMT, MW

## SLD_REN_FCST

- 行数 3605, 列数 14

| 列 | 取值数 | 判定 | 依据 |
| --- | --- | --- | --- |
| OPR_DT | 30 | TIME-ALT | 与另两列一一对应 (721 个时间戳 ↔ 721 个(日期,小时) 对), 信息等价; 但 (日期,小时)→UTC 无闭式公式, 建议留 GMT |
| OPR_HR | 25 | TIME-ALT | 与另两列一一对应 (721 个时间戳 ↔ 721 个(日期,小时) 对), 信息等价; 但 (日期,小时)→UTC 无闭式公式, 建议留 GMT |
| OPR_INTERVAL | 1 | CONST | 全表仅一个取值: 0 |
| INTERVALSTARTTIME_GMT | 721 | TIME-ALT | 与另两列一一对应 (721 个时间戳 ↔ 721 个(日期,小时) 对), 信息等价; 但 (日期,小时)→UTC 无闭式公式, 建议留 GMT |
| INTERVALENDTIME_GMT | 721 | DERIV | END-START == 1h, 违例 0/3605 |
| TRADING_HUB | 3 | KEEP | 取值 3 个 |
| RENEWABLE_TYPE | 2 | KEEP | 取值 2 个 |
| LABEL | 1 | CONST | 全表仅一个取值: Renewable Forecast Day Ahead |
| XML_DATA_ITEM | 1 | CONST | 全表仅一个取值: RENEW_FCST_DA_MW |
| MARKET_RUN_ID_POS | 1 | CONST | 全表仅一个取值: 1 |
| RENEW_POS | 2 | DERIV | RENEWABLE_TYPE 唯一决定该列, 冲突 0/3605 |
| MW | 2411 | KEEP | 取值 2411 个 |
| MARKET_RUN_ID | 1 | CONST | 全表仅一个取值: DAM |
| GROUP | 150 | DERIV | (TRADING_HUB × RENEWABLE_TYPE × OPR_DT) 唯一决定该列, 150 个块 0 冲突 |

**时间轴校验**

- 用「当地午夜 + (hr-1) 小时」反推 UTC: 违例 15/3605
-   受影响日期: 2023-11-05
-   2023-11-05 HR1: 公式=2023-11-05T08:00:00-00:00 实际=2023-11-05T07:00:00-00:00
-   2023-11-05 HR25: 公式=2023-11-06T08:00:00-00:00 实际=2023-11-05T09:00:00-00:00
-   2023-11-05 HR2: 公式=2023-11-05T09:00:00-00:00 实际=2023-11-05T08:00:00-00:00
-   -> (OPR_DT, OPR_HR) 不能替代 INTERVALSTARTTIME_GMT 做时间轴

**删掉 8 列**（常量/可推导）: OPR_INTERVAL, INTERVALENDTIME_GMT, LABEL, XML_DATA_ITEM, MARKET_RUN_ID_POS, RENEW_POS, MARKET_RUN_ID, GROUP

**时间三列信息等价**: OPR_DT, OPR_HR, INTERVALSTARTTIME_GMT -> 保留 INTERVALSTARTTIME_GMT（见上方时间轴校验）

**建议最终 schema（4 列）**: TRADING_HUB, INTERVALSTARTTIME_GMT, RENEWABLE_TYPE, MW

## 共用注意

- 2023-11-05 是 25 小时日。当天 OPR_HR 的真实顺序是 1@07:00Z 2@08:00Z 3@10:00Z … 24@07:00Z(+1d) 25@09:00Z —— 夏令时回拨的那一小时被编成 25 号、排在末尾。所以 (OPR_DT, OPR_HR) 无法用固定公式还原 UTC, 时间轴请以 INTERVALSTARTTIME_GMT 为准。春季 23 小时日 (2024-03-10 等) 未出现在本次两个文件里, 未验证。

- 两个报表的 OPR_DT 原文格式一致 (2023-11-01); 工作区里 sld_fcst 的 2023-11 CSV 已被改写成 2023/11/1, 与 zip 原件不一致, 合并前请以 zip 为准。

- 常量列在抽取阶段是过滤条件, 过滤完成后才可删。

