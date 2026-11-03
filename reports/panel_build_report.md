# Panel build report

## Command

`python scripts/build_panel.py --input work/hourly.csv.gz --output data/processed/panel.csv.gz`

## Input

- SHA-256: `dd5289e35ae6f9ea71ca9d71fd4ff7ac875a7ce1695a48c3b3e115054c8e860a`
- Path: `work/hourly.csv.gz`

## Output summary

- Rows: 26304
- Days: 1096
- Columns: 88
- Target non-null: 26301
- Date range: 2023-11-01 to 2026-10-31

## Missing values by column

| Column | Missing |
|---|---:|
| `day` | 0 |
| `hour` | 0 |
| `y` | 3 |
| `p_lag1` | 27 |
| `p_lag2` | 51 |
| `p_lag3` | 75 |
| `p_lag4` | 99 |
| `p_lag5` | 123 |
| `p_lag6` | 147 |
| `p_lag7` | 171 |
| `p_lagmean7` | 24 |
| `p_lagstd7` | 24 |
| `p_lag1_prev` | 27 |
| `p_lag1_next` | 27 |
| `p_lag1_daymean` | 24 |
| `p_lag1_daymax` | 24 |
| `p_lag1_daymin` | 24 |
| `load_caiso` | 3 |
| `load_sce` | 3 |
| `load_sdge` | 3 |
| `solar` | 75 |
| `wind` | 75 |
| `netload` | 75 |
| `nl_ratio` | 75 |
| `nl_ramp` | 78 |
| `nl_daymean` | 72 |
| `nl_daymax` | 72 |
| `sol_sum` | 72 |
| `sol_ratio` | 72 |
| `load_ramp` | 6 |
| `dow` | 0 |
| `month` | 0 |
| `doy` | 0 |
| `is_weekend` | 0 |
| `is_holiday` | 0 |
| `d_to_holiday` | 0 |
| `is_thanksgiving` | 0 |
| `is_black_friday` | 0 |
| `is_pre_holiday` | 0 |
| `is_post_holiday` | 0 |
| `x_p1_1` | 24 |
| `x_p1_2` | 24 |
| `x_p1_3` | 96 |
| `x_p1_4` | 24 |
| `x_p1_5` | 24 |
| `x_p1_6` | 24 |
| `x_p1_7` | 24 |
| `x_p1_8` | 24 |
| `x_p1_9` | 24 |
| `x_p1_10` | 24 |
| `x_p1_11` | 24 |
| `x_p1_12` | 24 |
| `x_p1_13` | 24 |
| `x_p1_14` | 24 |
| `x_p1_15` | 24 |
| `x_p1_16` | 24 |
| `x_p1_17` | 24 |
| `x_p1_18` | 24 |
| `x_p1_19` | 24 |
| `x_p1_20` | 24 |
| `x_p1_21` | 24 |
| `x_p1_22` | 24 |
| `x_p1_23` | 24 |
| `x_p1_24` | 24 |
| `x_nl_1` | 72 |
| `x_nl_2` | 72 |
| `x_nl_3` | 144 |
| `x_nl_4` | 72 |
| `x_nl_5` | 72 |
| `x_nl_6` | 72 |
| `x_nl_7` | 72 |
| `x_nl_8` | 72 |
| `x_nl_9` | 72 |
| `x_nl_10` | 72 |
| `x_nl_11` | 72 |
| `x_nl_12` | 72 |
| `x_nl_13` | 72 |
| `x_nl_14` | 72 |
| `x_nl_15` | 72 |
| `x_nl_16` | 72 |
| `x_nl_17` | 72 |
| `x_nl_18` | 72 |
| `x_nl_19` | 72 |
| `x_nl_20` | 72 |
| `x_nl_21` | 72 |
| `x_nl_22` | 72 |
| `x_nl_23` | 72 |
| `x_nl_24` | 72 |

## Known missing dates

- `2024-03-09`：solar/wind 源数据缺测，按契约保留 NaN。
- `2025-03-08`：solar/wind 源数据缺测，按契约保留 NaN。
- `2026-03-07`：solar/wind 源数据缺测，按契约保留 NaN。

`netload = load_caiso - solar - wind` is retained as a proxy feature; the load and SP15 renewable forecasts do not share an identical geographic scope.
