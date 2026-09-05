# Croc bondpad DRC 根因与最小修复路径

SPDX-License-Identifier: Apache-2.0

2026-09-05。**原 Croc 焊盘宏本身在 Passiv 开窗下放置 TopVia2，是 Pad.kR 的直接来源。固定官方 PCell 的两个独立 fixture 已消除该类 marker，但仍有密度违规，不能称 fixture 或整芯片 DRC PASS。** Pad.fR 退出金属、Pad.d1R 与 Pad.dR 则需要修复 IO/布线/封环集成，单独换一个宏不能完成闭环。

## 真实证据与计数范围

固定 IHP PDK：`331c00484213b13414777eec1336ef5c29b969bd`。KLayout Python：`0.30.5`，使用现有固定容器，输入目录只读；没有改源 GDS、PDK 或已有整芯片版图。

| 问题 | 历史整芯片 merged marker | 本次直接几何观察 | 根因范围 |
|---|---:|---|---|
| Pad.kR | **576** | 每个原宏 144 颗 TopVia2 完全落在开窗内；64 个宏共 **9216** 颗，全部来源于 `bondpad_CDNS_701964819630`，路由 via cell 来源为 0 | **原宏内部** |
| Pad.fR | **925**：M2=581，M3/M4/M5/TM1 各64，TM2=88 | 朝芯片内部的 70×7 µm 出口区域中，M4/M5/TM1 的全部64个pad仅有210 µm²金属、缺280 µm²，相当于退出段只有3 µm、还缺4 µm | **pad 与 IO/布线连接处** |
| Pad.d1R | **72** | 原焊盘宏没有 Activ；历史 marker 位于 `croc_chip` 的开窗/IO Active 相邻位置 | **IO/pad 位置集成**，推荐间距11.2 µm |
| Pad.dR | **4** | 原焊盘宏没有 EdgeSeal；历史 edge-pair 样例开窗至 EdgeSeal 间距7.735 µm | **pad/封环位置集成**，推荐25 µm |
| Density | **8** | 历史整芯片 M1Fil.h=2、M2Fil.h=3、M3Fil.h=3 | 与下述孤立宏的9个global-density marker不是同一范围 |

合计 **1577 个 Pad marker + 8 个 density marker = 1585**。`576` 是层次/方向归并后的 Pad.kR marker 数，`9216` 是展开到实际芯片的物理过孔数，不能混成同一个“违规数量”。单宏 fixture 的 Pad.kR 为144，是另一明确范围。

退出区探针属于几何佐证：完整金属层 merge 超出90秒 wrapper 等待上限，容器随后生成64个pad的完整 JSON 并退出；最终退出码因 `--rm` 无法取回。已检查输出结构和各区域面积守恒，状态保留为 `output_available_and_validated_after_wrapper_timeout`，不冒称进程 PASS。正式 Pad.fR 判断仍以原规则 deck 为准。该作业没有遗留运行容器。

## LEF、原 GDS 与官方 PCell 的差异

| 项目 | 原 Croc `bondpad_70x70` | 官方 `official_default_square70` | 官方 `official_m2_square70` |
|---|---|---|---|
| 外形坐标 | `(0,0;70,70)` µm | `(-35,-35;35,35)` µm | 同左 |
| Metal2 | 70×70 整块金属 | **不存在**，默认bottomMetal=3 | 环形，面积1073.3404 µm² |
| Metal3～TopMetal1 | 每层4900 µm²整块金属 | 每层1073.3404 µm²环形 | 同左 |
| TopMetal2 / dfpad | 70×70 µm | 70×70 µm | 70×70 µm |
| Passiv 开窗 | `(2.135,2.135;67.865,67.865)` | `(-32.9,-32.9;32.9,32.9)` | 同左 |
| TopVia2 | 144颗，全部完全在开窗内 | 132颗边缘过孔；完全在开窗内=0 | 同左 |
| TopVia2 与开窗相交 | 144 | 132 | 132 |

原 LEF 对 Metal2～TopMetal2 都声明 `RECT 0 0 70 70` 可接入 pin，并声明同范围 OBS。它对应原宏的实心下层金属，却不能直接用于官方环形金属版本，否则路由可能把下层金属孔洞当作合法 pin。官方默认版本甚至没有 Metal2，所以后续 Croc 集成优先使用显式 `bottomMetal=2` 的 fixture，并生成与实际环形 GDS 匹配的 LEF。

正式 `Pad.kR` 使用 `TopVia2.inside(Passiv_dfpad)`；官方边缘过孔与开窗部分相交，不等于完全在其中。不能擅自把规则改写成“任何相交都失败”，也不能因几何探针 fully-inside=0 就跳过完整 DRC。下节用实际公开 deck 对此作了验证。

## 已执行的独立 A/B

假设：在保持公开规则、推荐规则、antenna、density、offgrid 开启的条件下，用固定官方 wire-bond PCell 的边缘过孔构造替代原宏内部过孔阵列，可消除孤立宏 Pad.kR。

实际运行：[croc-bondpad-drc-ab-20260905-002 审计](../runs/croc-bondpad-drc-ab-20260905-002/audit.json)。每个 arm 完成40个公开规则任务，31个 Ant 类别齐全。

| Arm | Pad.kR | 其他非密度 marker | Global density marker | 全部 marker | Fixture DRC |
|---|---:|---:|---:|---:|---|
| 原 Croc 宏 | **144** | 0 | 9 | **153** | **FAIL** |
| 官方默认 square70 | **0** | 0 | 9 | **9** | **FAIL** |
| 官方 bottomMetal=2 square70 | **0** | 0 | 9 | **9** | **FAIL** |

这里没有关闭密度规则。孤立宏的面积/金属占比导致9个global-density marker，仍如实保留 FAIL；“非密度 marker=0”只证明该 fixture 的局部结果，不能推导整芯片密度、DRC 或 LVS 通过。

原 runner 将 antenna deck 最后未打印通用 `completed` 行误认为执行不完整，因此原 manifest 的 `runner_returncode=1` 和 incomplete 标记保持。独立 `audit.json` 根据原始报告哈希、40项任务日志、全部31个 Ant 类别及末项 Ant.i 证明规则执行完成。这是对执行状态的证据复核，不是忽略违规或把失败退出码直接当成功。

## 可执行入口与后续集成门槛

成功的几何生成在 `runs/bondpad-geometry-20260905-003`；001/002是诊断器加载/图层映射失败尝试，保持原样。执行脚本快照为该run的 `executed_probe.py`；可复用入口为 [bondpad_geometry_probe.py](../reports/bondpad/bondpad_geometry_probe.py)。

固定源码依赖均已在仓库中，无安装：将 `upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/python` 与其 `pycell4klayout-api/source/python` 加入 `sys.path`；设置 `KLAYOUT=1`、`KLAYOUT_LYP_FILE` 为固定 `tech/sg13g2.lyp`。官方备用JSON的 `Layers` 为空，实际图层必须读LYP；`pypreprocessor` 是外层namespace package，不能把其内部路径错误放在前面。

已实测 API：`pya.Library.library_by_name('SG13_dev', 'sg13g2')`、`pcell_declaration('bondpad')`、`Layout.add_pcell_variant(...)`。候选参数：

```json
{"diameter":"70u","shape":"square","bottomMetal":"2","stack":"t","fill":"nil","FlipChip":"no","padType":"bondpad"}
```

默认版只显式设置 `diameter=70u, shape=square`。`passEncl` 在该源代码中仅对 `padType=probepad` 生效，不能假设修改它会改变 wire-bond pad 开窗。不得改用 `fill=t`、`FlipChip=yes` 或关闭推荐规则来回避当前 wire-bond 要求。

主任务实际 DRC 命令在固定容器 login shell 内执行，确保 KLayout 在PATH：

```bash
python3 /work/upstream/ihp-open-pdk/ihp-sg13g2/libs.tech/klayout/tech/drc/run_drc.py \
  --path /work/runs/bondpad-geometry-20260905-003/official_m2_square70.gds \
  --topcell official_m2_square70 --run_dir /output \
  --run_mode deep --mp 6 --density_thr 6 --antenna
```

下一最小集成 fixture 应包含一个真实 IO cell、焊盘及退出引线；在独立目录中将官方居中GDS平移 `(+35,+35)` 对齐原70×70原点，再用匹配的环形LEF与明确的≥7 µm退出金属。验证 pin-access、单网连接、metal/via/Pad全规则，并检查11.2 µm Active和25 µm EdgeSeal距离。未完成前不替换全芯片宏；独立宏 A/B 无法覆盖这些布局关系。

## 本轮 PPA 口径

本轮没有新的整芯片实现，功耗/时序继续引用[原全芯片RCX报告](../reports/ppa/croc-ppa-rcx-20260905-001.json)：TT **43.6 mW**、FF **55.2 mW**工具估算，100 MHz只是约束，电气仍失败。fixture的金属多边形减少不等于逻辑面积、整芯片功耗或时序优化。

直接读取原归档 `croc.filled.gds.gz` 得到 `croc_chip_sealed` bbox=`(0,0;2000,2000)` µm，即含封环的外边界 **4.000000 mm²**；原 DEF 电气 `croc_chip` 仍为 **3.671056 mm²**。这是同一历史版图的并列范围补全，不是面积改变或工艺效率提升。源GDS与几何报告SHA-256已加入[PPA来源索引](../reports/ppa/comparison_sources_20260905.json)。

成功/失败/超时run原状态与fixture审计哈希另见[诊断索引](../reports/bondpad/diagnostic_run_index_20260905.json)。全部几何、源哈希、官方参数、层次归属及后续假设见[机器诊断报告](../reports/bondpad/bondpad-diagnosis-20260905-001.json)；fixture审计以其独立run中的原始证据为准。本仓库仍无本轮整芯片DRC/LVS闭环或可流片成果。
