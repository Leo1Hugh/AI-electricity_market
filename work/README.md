# work/ 说明

本目录是**建模过程的本地工作区**，不是生产代码。

## 会入库的

- **hourly.csv.gz**：2023-11-01 ～ 2026-10-31 的建模宽表（26304 行）。
  由 CAISO 价格 + 负荷/风光预测合并而来；W1 的 build_panel 以它为输入。

## 只在本地、不会入库的

- **raw_combined/**：本地合并的大 ZIP（sld_fcst.zip、sld_ren_fcst.zip）。
  它们不在 data/raw/caiso 的 manifest 里，放回数据目录会让 verify 测试报异常。
- **crops/、pdf/、rules_png/、sub_png/**：PDF 截图与中间图。
- **pred_*.csv、*.png**：回测预测与图，体积大。
- **旧脚本**：build_dataset.py、model.py、winter_bt2.py、check_mtl.py 等，
  是 reports/电价预测方案.md 的取证脚本；保留在本机供追溯，不作为新流水线的一部分。
  新流水线在 src/em/ 与 scripts/。

## 重建 hourly.csv.gz

旧脚本依赖本地数据布局；在新环境请优先用：

~~~powershell
python scripts/caiso_oasis_collect.py --help
~~~

或直接用仓库里已提交的 work/hourly.csv.gz。不要把 raw_combined/ 放回 data/raw/caiso/。
