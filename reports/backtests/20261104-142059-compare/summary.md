# Model comparison 20261104-142059-compare

mode: `annual`; metrics are mean daily 24-hour RMSE (USD/MWh)

| window | model | mean | median | max | p90 | crash_rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| annual | naive_d1 | 7.24628 | 5.84121 | 49.4946 | 13.5901 | 0.0273973 |
| annual | ridge | 6.63836 | 5.7281 | 45.01 | 10.2325 | 0.0219178 |
| annual | lgbm | 6.771 | 5.35138 | 66.309 | 9.77078 | 0.0328767 |
| annual | mtlasso | 7.14124 | 6.06797 | 30.666 | 11.9364 | 0.0192308 |
| annual | mean2 | 6.14873 | 5.10995 | 43.9428 | 9.42523 | 0.0246575 |
| annual | mean3 | 5.6456 | 4.70062 | 38.2484 | 8.62796 | 0.0192308 |
| annual | shrink | 5.39286 | 4.36554 | 39.0091 | 8.34679 | 0.0164835 |
