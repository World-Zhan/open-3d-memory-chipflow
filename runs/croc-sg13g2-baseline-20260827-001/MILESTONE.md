# Croc / IHP SG13G2 基线里程碑（Attempt 2 终局）

生成日期：2026-08-30<br>
Run ID：`croc-sg13g2-baseline-20260827-001`<br>
总体结论：**未签核通过**。RTL、门级仿真、APR 和 GDS 已跑通；公开 DRC 与顶层 LVS 均失败。不得称为 `public_rule_signoff` 或 foundry tapeout-ready。

机读配套文件：

- `milestone.json`：本里程碑的结构化状态、版本、DRC/LVS 计数与证据索引。
- `signoff.attempt-2/lvs/port_mismatch_analysis.json`：流式、低内存的 52→composite 端口映射、135,057 formal-port 分类和前 100 个异常样本。
- `signoff.attempt-2/signoff_summary.json`：attempt 2 原始严格验收汇总。

## 三轨总体状态

| 轨道 | 当前状态 | 可制造性口径 | 不能声称的内容 |
|---|---|---|---|
| A：Croc/IHP 可制造学习基线 | **进行中；signoff FAIL** | APR/GDS 已过；DRC=1,585、LVS mismatch | 尚不是公开规则签核级 GDS；IHP 开放 PDK仍为 preview |
| B：TaiWei-Pin-3D | **诊断已启动；route FAIL** | 永久标记 `research_only`；pin-access 定点修复有效但 route DRC=642 | 不是 route PASS、3D closure 或真实 3D PDK/送厂包 |
| C：SRAM/3D-memory 扩展 | **未开始** | 必须等 A/B 原版流程稳定后再改 RTL | 尚无 OBI traffic endpoint 或 3D SRAM 映射结果 |

## 阶段检查点

以下“实际命令”来自 `manifest.json`；`make RUN_ID=... <target>` 是用户入口。

| 阶段 | 状态 | 实际命令 | 主要证据 |
|---|---|---|---|
| 软件 + Verilator RTL | PASS | `bash scripts/croc_flow.sh rtl` | `logs/croc-rtl.log`、`stage_evidence/croc-rtl.json`；UART 为 `Hello World from Croc!` |
| Yosys+Slang 综合 + 门级仿真 | PASS | `bash scripts/croc_flow.sh netlist-sim` | `logs/croc-netlist-sim.log`、`stage_evidence/croc-netlist-sim.json`；无 latch/unresolved reference，SRAM blackbox 在白名单内 |
| OpenROAD APR | PASS | `bash scripts/croc_flow.sh pnr` | `logs/croc-pnr.log`、`stage_evidence/croc-pnr.json`、`upstream/croc/openroad/reports/open3d_acceptance.rpt` |
| GDS finishing | PASS（attempt 4） | `bash scripts/croc_flow.sh gds` | `stage_evidence/croc-gds.attempt-4.json`；四个 GDS 均非空 |
| IHP 完整 DRC | FAIL（attempt 2） | `bash scripts/croc_signoff.sh` | `signoff.attempt-2/drc/croc.filled.gds_croc_chip_sealed_full.lyrdb` |
| 顶层 LVS | FAIL（attempt 2） | `bash scripts/croc_signoff.sh` | `signoff.attempt-2/lvs/croc.log`、`croc.lvsdb`、`croc_extracted.cir` |

APR 证据：`unrouted_nets=0`，VDD/VSS PDN connected，WNS/TNS=`0.0/0.0 ns`，setup/hold violations=`0/0`。这些结果不能替代 DRC=0 和 LVS exact match。

## 固定版本

- 本项目运行时提交：`16e49c36c27f8c3adf6919c639b6d242c3a7947d`
- Croc：`968bab17b37e88d9200a0899cb9181e42850ec87`
- mlem-tapeout 对照：`f54fdab3f463181f6b91646e36b29321c39432b1`
- IHP Open PDK：`331c00484213b13414777eec1336ef5c29b969bd`
- TaiWei-Pin-3D：`c85b79352eefc31a588da3ef873e4fd68a3df3f2`
- ORFS-Research：`568eb04da9173695d6bfc1b10ba868e0b6b8a9fa`
- Pin3D OpenROAD：`305d3ba2ddfd00591924cc586ad408179f566afe`
- 容器：`hpretl/iic-osic-tools:2025.12`，镜像 ID/digest `sha256:92961478ad3c4f508efb42d9ccdba12ab262eb42a14926d2bd49862230ba8521`

## Pin3D route-only 诊断（2026-09-01，research_only）

该检查点只复用 `ASAP7_3D/GCD` 已有 `4_cts.*`，没有重跑 Croc、LVS、
DRC 或 full smoke。原始 upper-tier placement 先因 `MAX_ROUTING_LAYER=M2_m`
排除 pin 所在 `M1_m` 而报 `GRT-0029`；固定 `M1_m` 后，route 又对 6 个
upper-tier 标准单元输入 pin 报 `DRT-0073`。OpenROAD 定点 patch 只在 pin
已经处于路由栈顶时为标准单元尝试相邻 DOWN via；没有关闭 pin-access、
没有把 `min_access_points` 设为 0，也没有 waiver 或规则弱化。

受控 strict-pin-access A/B：

| 指标 | 结果 | 验收解释 |
|---|---:|---|
| `stdCellPinCnt` | 1,485（global/detail 各一次） | 输入 pin 数量已实际扫描 |
| `stdCellPinNoAp` | 0 / 0 | 原 6 个 `DRT-0073` 消失；pin-access 定点修复有效 |
| detailed routing | 完成，命令 exit 0 | 只说明工具完成，不等于 route PASS |
| antenna net/pin violations | 0 / 0 | 天线检查通过 |
| final route DRC | **642** | route 验收失败，禁止 full smoke |
| DRC 类型 | Cut Spacing 530；Short 82；Metal Spacing 19；Corner Spacing 11 | 530 个集中在 `hb_layer`；M1_m 共 104 个 marker |
| cross-tier route-after | all/UB/UIO/BIO/UBIO/UNK 均为 0 | 不能声称 HBT/cross-tier closure |
| HBT via | 70 | 从最终 `5_route.def` 的 70 个不同网络、不同坐标 `hb_layer_0` 实例直接计数 |
| 上下层实例、WNS/TNS | `null` | 缺失指标不能当成 0 或 PASS |

证据：

- `runs/pin3d-openroad-pa-ab-20260901-003/summary.json`：结构化检查、类型/层计数、输入输出 SHA-256。
- `runs/pin3d-openroad-pa-ab-20260901-003/logs/route-down-via-strict-pa.log`：实际 strict-pin-access 命令日志。
- `upstream/taiwei-pin-3d/reports/asap7_3D/gcd/openroad/5_route_drc.rpt`：642 个 route marker（生成大文件，不进 Git）。
- `patches/openroad/0001-top-routing-layer-standard-cell-down-via.patch`：可从 pinned OpenROAD 正向应用、构建后恢复源码 clean 的最小 patch。

结论必须写成 `diagnostic_started_route_failed`：pin-access blocker 已缩小并修复，
但 route DRC 非零且 3D closure 指标为 0/null，所以 B 轨仍 FAIL，下一门槛
是先消除 hybrid-bond/M1_m route DRC，不是启动 full smoke。

### HBT spacing 根因检查点（2026-09-03）

对现有 DEF、实际 TECH_LEF、partition 日志和 route DRC 做了纯文本、低内存
交叉验证，没有重跑 OpenROAD：

- `5_route.def` 有 70 个 `hb_layer_0`，分别属于 70 个网络和 70 个坐标；全部落在
  M7 的 64 DBU（0.064 µm）routing-track 网格上。
- 实际日志确认使用 `asap7_tech_1x_2A6M7M.lef`。其中 HBT cut 为
  0.032×0.032 µm，边到边最小间距 1.568 µm，对应合法方形 pitch 1.6 µm。
- 用矩形边到边欧氏距离逐对计算 70 个 cut，预测 530 个违规网络对；与
  `5_route_drc.rpt` 的 530 个 `Cut Spacing@hb_layer` 网络对逐项完全一致，
  `missing=0`、`extra=0`。因此这 530/642 个 marker 的直接几何根因已证明。
- partition 却使用硬编码 `width=0.5 / spacing=0.5 / pitch=1.0 µm`，且所有候选
  均 `feasible=0`；最终仍传递 cut=62 的方案，后续 CTS/route 增长为 70 个 HBT。
- 当前 6.676×6.676 µm die 在 1.6 µm 方形 pitch 下只有 5×5=25 个 site，
  明显小于 70；不能靠关闭 DRC、减小阈值或 waiver 解决容量合同错误。

结构化证据为
`runs/pin3d-openroad-pa-ab-20260901-003/hbt_spacing_analysis.json`。
它只证明 530 个 HBT marker；剩余 112 个 M1_m/其他金属 marker 仍未闭环。
该容量门槛已由下面的 bounded A/B 实现；它仍不等于 HBT 坐标已经落在合法
1.6 µm lattice，也不等于 route DRC 已清零。

### HBT 容量合同 stage A/B（2026-09-03）

仅运行新的隔离 variants，没有运行 placement、CTS、route 或 full smoke：

```text
NUM_CORES=6 bash scripts/with_taiwei_hbt_contract_patch.sh run \
  bash upstream/taiwei-pin-3d/test/common/run_stage.sh \
  asap7_3D hbt_contract_ab_20260903_001 openroad gcd ord-tier-partition
NUM_CORES=6 bash scripts/with_taiwei_hbt_contract_patch.sh run \
  bash upstream/taiwei-pin-3d/test/common/run_stage.sh \
  asap7_3D hbt_contract_ab_20260903_001 openroad gcd ord-pre
NUM_CORES=6 bash scripts/with_taiwei_hbt_contract_patch.sh run \
  bash upstream/taiwei-pin-3d/test/common/run_stage.sh \
  asap7_3D hbt_contract_ab_20260903_002 openroad gcd ord-3d-floorplan
```

`patches/taiwei-pin-3d/0001-tech-derived-hbt-capacity-contract.patch` 从明确的
3D TECH_LEF 读取 HBT rule，并在 floorplan 中再次与实际 OpenROAD tech DB
比对；partition 产生 `hbt_capacity.contract.tcl`，floorplan 只有验证实际
ODB core 后才写 `capacity_validated=1`。wrapper 会在每个 stage 结束后恢复
pinned TaiWei 子模块。

| 检查项 | 结果 | 解释 |
|---|---:|---|
| HBT rule | 0.032 µm cut / 1.568 µm spacing / 1.6 µm pitch | 来自 `asap7_tech_1x_2A6M7M.lef`，非硬编码 0.5/0.5 |
| 2D partition die | 9.13×9.13 µm；6×6=36 sites | 0.8 上限下可用 28，仍小于 cut demand 62 |
| partition | cut=62；`requires_floorplan_expansion=1` | infeasible 不再被误当作物理 floorplan 已可交付 |
| 最小 HBT core | 14.085453×14.085453 µm；需要 78 sites | 采用同仓库 Cadence flow 的 pitch-area/utilization 方法并离散化 |
| requested-size-only 尝试 | **REJECTED by post audit** | 实际 core 被 site/row snap 到 14.04×13.77 µm，utilization=0.820976 > 0.8 |
| site-snap-guarded 尝试 | **PASS（仅容量合同）** | 请求 14.625453×14.625453 µm；实际 ODB core=14.58×14.31 µm，10×9=90 sites，utilization=0.760737 |
| route | **NOT RUN** | 既有 DRC 仍为 642；530 个 HBT marker 与 112 个其他 marker 均未宣称消失 |

机读证据：

- `runs/pin3d-hbt-capacity-contract-20260903-001/summary.json`
- `runs/pin3d-hbt-capacity-contract-20260903-001/stage_ab.json`
- `scripts/analyze_pin3d_hbt_capacity_contract.py`
- `scripts/collect_pin3d_hbt_contract_ab.py`
- `scripts/with_taiwei_hbt_contract_patch.sh`

本检查点状态必须写成 `floorplan_contract_ab_passed_route_not_run`。容量合同
只证明 floorplan 有足够合法 site 数量；下一门槛是在任何 bounded reroute 前
建立并验证 HBT legal-lattice placement/window contract。

## DRC：FAIL，两个计数口径不得混用

- `marker_total=1585`：来自合并数据库 `signoff.attempt-2/drc/croc.filled.gds_croc_chip_sealed_full.lyrdb` 中全部 `<items><item>`。
- `nonempty_rule_categories=12`：同一合并数据库的非空 rule category 数。
- `maximal_raw_error_count=652`：来自 `logs/croc-signoff.attempt-2.log` 和 `..._sg13g2_maximal.log` 的 `Number of DRC errors for maximum rule set: 652`，仅等于 `Pad.kR 576 + Pad.d1R 72 + Pad.dR 4`。
- `density_unwaived=8`，`disabled_rules=[]`，未关闭规则、改阈值或增加 waiver。

前 10 类（其余两类也列在后面）：

| Rule | 数量 | 坐标热点/范围 | 主要来源对象 |
|---|---:|---|---|
| `Pad.fR_M2` | 581 | top-edge 样例 `y=1839..1843 µm`；全边界 `73..1843 µm` | top cell pad opening 周围 M2 exit；pad/IO 边界，不是 core routing 主体 |
| `Pad.kR` | 576 | bondpad 局部坐标 `x=5.19..64.81, y=-64.81..-5.19 µm`；样例 `y=-11.43..-10.53` | `bondpad_CDNS_701964819630` 四种旋转/镜像；Pad 下 TopVia2 |
| `Pad.fR_TM2` | 88 | top-edge 样例 `y=1839..1843 µm` | pad opening 周围 TM2 exit |
| `Pad.d1R` | 72 | top-edge 样例约 `y=1839.688..1848.447 µm` | pad opening 到 IO-ring active 的推荐间距 |
| `Pad.fR_M3` | 64 | 四周 pad 边界，坐标范围 `73..1843 µm` | pad opening 周围 M3 exit |
| `Pad.fR_M4` | 64 | 四周 pad 边界，坐标范围 `73..1843 µm` | pad opening 周围 M4 exit |
| `Pad.fR_M5` | 64 | 四周 pad 边界，坐标范围 `73..1843 µm` | pad opening 周围 M5 exit |
| `Pad.fR_TM1` | 64 | 四周 pad 边界，坐标范围 `73..1843 µm` | pad opening 周围 TM1 exit |
| `Pad.dR` | 4 | bondpad 局部 edge-pair：pad `y=2.135` 对 seal edge `y=-5.6 µm` | `bondpad_70x70` 四边与 sealring 推荐距离 |
| `M2Fil.h` | 3 | 800×800 µm² 窗口：`(400,400)-(1200,1200)`、`(400,800)-(1200,1600)`、`(800,800)-(1600,1600)` | core 局部 M2 density，最低 19.878%（规则 25%） |

其余：`M3Fil.h=3`（最低 21.762%）和 `M1Fil.h=2`（最低 20.726%）。合计 8 个 density marker。1,577 个其余 marker 主要集中在 pad/bondpad/IO/sealring/pad-exit。

## LVS：FAIL，首层根因已定位

Attempt 2 运行 8,114.558 s；KLayout 日志峰值为 `8,104,608 K`（按 KiB 约 7.73 GiB）。运行在 strict port mode，`flag_missing_ports` 开启，未启用 `ignore_top_ports_mismatch` 或 implicit nets，最终为：

```text
ERROR : Netlists don't match
```

低内存流式分析（没有加载 609 MB `croc.lvsdb`）得到：

| 指标 | 数值 |
|---|---:|
| schematic `.SUBCKT croc_chip` formal ports | 52 |
| extracted `.SUBCKT croc_chip` formal ports | 135,057 |
| exact-name shared ports | 0 |
| 在唯一 composite alias 中恢复的期望端口 | 52 |
| 非期望/内部 formal ports | 135,005 |

典型映射：

- `VDD → VDD|VDD!|VDDARRAY!|in|pad|pin1|pin2|supply|vdd`
- `VSS → VSS|VSS!|anode|cathode|vss`
- `VSSIO → VSSIO|anode|cathode|guard|iovss`
- `clk_i → anode|cathode|clk_i|core|pad`
- `gpio0_io → anode|cathode|core|gpio0_io|pad`

formal-port 分类：

- expected power/ground composite：4
- expected signal composite：48
- generic standard-cell pin-label composite：32,028
- other internal composite：24,058
- single generic cell-pin label：641
- single other internal：78,278

因此本轮不是“普通器件参数差异”：顶层 pin/net 边界已经失真，net/device/subcircuit/parameter 配对均应标记 `NOT_COMPARED`，不能误报为 match。

保留证据：

- `signoff.attempt-2/lvs/croc.log`
- `signoff.attempt-2/lvs/lvs_run_2026_08_27_16_36_24.log`
- `signoff.attempt-2/lvs/croc.lvsdb`（609,009,139 bytes；不再做全量 Python 加载）
- `signoff.attempt-2/lvs/croc_extracted.cir`（108,294,772 bytes）
- `signoff.attempt-2/croc.cdl`（6,120,723 bytes）
- `signoff.attempt-2/lvs/port_mismatch_analysis.json`

## Strict-LVS pin/extraction boundary 定点诊断（2026-08-29）

本节是诊断检查点，不改变 A 轨验收状态：full-chip attempt 2 仍为 **DRC FAIL / LVS FAIL**。以下任一“端口集合 exact”都不能写成 LVS exact match。

所有用例保持：strict port mode、`flag_missing_ports=true`、simplify 开启、`ignore_top_ports_mismatch=false`、无 implicit nets、无 waiver，且没有启动 full-chip attempt 3。

### 1. IO + inverter 的 deep/flat × TOP_LVL_PINS A/B

输入由一个 `sg13g2_IOPadIn`、一个 `sg13g2_inv_1` 和 10 个显式父级标签组成。命令与完整结果见：

- `lvs-pin-boundary-ab/input_manifest.json`
- `lvs-pin-boundary-ab/summary.json`
- 每个变体的 `variants/<name>/command.txt`、`.log`、extracted netlist 和小型 `.lvsdb`

| 变体 | schematic ports | extracted ports | exact shared | 顶层端口集合 | strict LVS |
|---|---:|---:|---:|---|---|
| deep / TOP_LVL_PINS off | 10 | 10 | 10 | exact | **FAIL** |
| flat / TOP_LVL_PINS off | 10 | 11 | 0 | composite + `guard\|iovss\|minus` 泄漏 | **FAIL** |
| deep / TOP_LVL_PINS on | 10 | 10 | 10 | exact | **FAIL** |
| flat / TOP_LVL_PINS on | 10 | 11 | 0 | composite + `guard\|iovss\|minus` 泄漏 | **FAIL** |

结论：`deep` 确实阻止了本 fixture 的 flat child-label promotion；`TOP_LVL_PINS` 对端口计数没有可观察影响。但是两个 deep 用例仍为 `ERROR : Netlists don't match`，所以只能说“顶层 pin boundary 已正确”，不能说 LVS 通过。

### 2. inverter-only 与 IOPadIn-only 隔离

结果见 `lvs-pin-boundary-isolation-20260829-001/summary.json`：

| 直接 PDK cell | schematic ports | extracted ports | strict deep LVS | 结论 |
|---|---:|---:|---|---|
| `sg13g2_inv_1` | 4 | 4 | **PASS** | 叶级标准单元与 deck 可 exact match |
| `sg13g2_IOPadIn` | 6 | 7 | **FAIL** | 6 个预期端口均存在，另有 `iovss$1` |

这只把范围缩小到 IO pad 层次；`remaining_mismatch_isolated_to_io_substrate_boundary=false`，根因尚未完全确定。

### 3. IOPadIn 文本、连通分量与 guard/substrate 证据

低内存明细位于 `lvs-iopad-diagnostic-20260829-001/iopad_in_detail.json`。GDS DBU 为 0.001 µm；IOPadIn 有 15 个直接 `iovss` datatype-25 文本：Metal3=`30/25`、Metal4=`50/25`、Metal5=`67/25`、TopMetal1=`126/25`、TopMetal2=`134/25` 各 3 个。完整坐标均在该 JSON；示例为：

| 层 | 示例文本坐标（µm） |
|---|---|
| Metal3 `30/25` | `(42.150,24.180)`、`(41.350,51.070)`、`(41.690,132.015)` |
| Metal4 `50/25` | `(41.275,22.280)`、`(41.800,50.075)`、`(39.615,131.455)` |
| Metal5 `67/25` | `(42.065,22.195)`、`(40.840,49.815)`、`(41.190,131.455)` |
| TopMetal1 `126/25` | `(41.800,22.545)`、`(41.015,50.340)`、`(42.150,131.975)` |
| TopMetal2 `134/25` | `(47.220,15.815)`、`(42.325,43.170)`、`(54.125,130.230)` |

schematic 把同一个 `iovss` 用于 `LevelDown`、`DCNDiode`、`DCPDiode` 和 IOVSS `ptap1`。deep extracted netlist 却形成两个 formal component：

- `iovss`：只连接 `sg13g2_DCNDiode`；
- `iovss$1`：连接 `sg13g2_LevelDown`、`sg13g2_DCPDiode` 和面积 `5379.0466 p` 的 `ptap1`；
- 局部 substrate/guard net `$1` 同时连接上述三个子电路、`vss` ptap 和 `iovss$1` ptap。

这证明 IOVSS 在 standalone cell extraction 中分成两个连通分量，但尚不能仅凭此判定是 GDS cell 错误、deck label promotion，还是原本就要求父级 IO-ring 金属将多个 access region 合并。

### 4. 同库 15 个 IOPad cell 对照

`lvs-iopad-diagnostic-20260829-001/summary.json` 记录全部命令与结果：15/15 standalone IOPad strict-deep LVS 均 FAIL；`iovdd$1` 在 10 个 cell 重复，`iovss$1` 在 4 个 cell 重复，`pad\|padres` 在 analog pad 出现 1 次。由此：

| 观测类别 | 具体 IOPad cell |
|---|---|
| extra `iovss$1` | `sg13g2_IOPadIOVdd`、`sg13g2_IOPadIn`、`sg13g2_IOPadVdd`、`sg13g2_IOPadVss` |
| extra `iovdd$1` | `sg13g2_IOPadAnalog`、`sg13g2_IOPadInOut16mA/30mA/4mA`、`sg13g2_IOPadOut16mA/30mA/4mA`、`sg13g2_IOPadTriOut16mA/30mA/4mA` |
| composite `pad\|padres` | `sg13g2_IOPadAnalog` |
| 无 extra，但缺 schematic `vdd` | `sg13g2_IOPadIOVss` |

全部 15 个 cell 的 strict-LVS 结论都是 **FAIL**，没有 PASS。上述重复性排除了“只有 IOPadIn 一颗 cell 异常”，但不能把 full-chip 的 135,057 个 formal ports 全部归因于 IO：full-chip flat extraction 还明确包含标准单元和其他内部标签提升，故 `full_chip_135057_port_mismatch_attributed_to_io_only=false`。

- 不支持“仅 `sg13g2_IOPadIn` 单 cell 数据损坏”；
- 支持“IO 库层次/父级 ring 连接语义是关键变量”，但还未证明是哪一处实现错误；
- 下一实验必须显式复现父级 IO-ring 连接，不能通过 implicit nets 或忽略端口掩盖。

### 5. Croc 代表性五-pad 父级 wrapper 与小型 LVSDB 交叉引用

`lvs-iopad-parent-wrapper-20260829-001/summary.json` 记录 Croc 实际一段顺序 `IOPadIOVss → IOPadIOVdd → IOPadIn → IOPadVss → IOPadVdd`。五个 80 µm、R0 pad 单元连续 abut，总宽 400 µm；父级只放置 6 个显式 datatype-25 标签。两种既有运行均保持 strict-deep、`flag_missing_ports=true`、simplify 开启、无 implicit nets、无 waiver：

| variant | schematic/extracted formal ports | 顶层端口集合 | strict LVS | deck runtime / peak RSS |
|---|---:|---|---|---:|
| baseline | 6 / 6 | exact | **FAIL** | 5.109 s / 534,216 KiB |
| `--combine_devices` | 6 / 6 | exact | **FAIL** | 4.664 s / 530,080 KiB |

父级 pad abutment 因此消除了 standalone `IOPadIn` 的 `iovss$1` 顶层 formal-port 增量，但没有得到 LVS exact match。`--combine_devices` 也没有改变失败类型，不能当作修复。

受限分析器只加载 7,485,910-byte 小型 LVSDB，并拒绝 609,009,139-byte full-chip LVSDB。baseline 与 `--combine_devices` 的交叉引用计数逐项相同：

| 对象 | Match | layout-only | schematic-only | paired mismatch |
|---|---:|---:|---:|---:|
| device | 4 | 32 | 5 | 1 |
| net | 4 | 36 | 10 | 3 |
| pin | 6 | 37 | 7 | 0 |

5 个 leaf circuit 为 `NoMatch`：`sg13g2_Clamp_N43N43D4R`、`sg13g2_DCNDiode`、`sg13g2_DCPDiode`、`sg13g2_RCClampInverter`、`sg13g2_SecondaryProtection`。代表性证据包括：

- `DCNDiode` schematic 两个 dantenna 共用 `cathode`，layout extraction 出现 `cathode` / `cathode$1` 分裂；`DCPDiode` 同样出现 `anode` / `anode$1`。
- `SecondaryProtection` schematic 的 `rppd` 在 extracted 侧缺失，并出现 `core|pad` 合并网络。
- `Clamp_N43N43D4R` 的 172 个 4.4 µm NMOS 指与 extracted 合并器件/`pad$N` 网络无法配对；启用 `combine_devices` 后计数仍完全相同。

这把小型 fixture 的剩余失败部分定位到 IO leaf 提取/器件归一化与局部网络分裂，但证据仍不足以把 full-chip 135,057-port mismatch 全归因于 IO。full-chip flat child-label promotion 与小型 deep IO-leaf mismatch 是两个同时存在的问题，`root_cause_state=partially_localized_to_io_leaf_extraction_not_fully_identified`。

## 官方 DCN/DCP leaf blocker：已最小复现并发布为上游 #1130

`lvs-iopad-leaf-diagnostic-20260829-001/summary.json` 对官方
`sg13g2_DCNDiode` 与 `sg13g2_DCPDiode` 各运行一次 strict-deep LVS；没有
重跑 15-cell sweep 或五-pad wrapper。两次运行都保留 strict ports、
`flag_missing_ports=true`、simplify、tap extraction；没有使用 implicit
nets、waiver、`ignore_top_ports_mismatch`、`--layout_netlist` 或修改 deck。

| leaf | schematic formal ports | extracted formal ports | strict LVS | leaf cross-reference |
|---|---|---|---|---|
| `sg13g2_DCNDiode` | 3：`anode cathode guard` | 3：`anode cathode cathode$1` | **FAIL**；`guard` 缺失、`cathode$1` 额外 | circuit `NoMatch=1`；device 3 layout-only / 1 schematic-only；net 4 / 2；pin Match 4 |
| `sg13g2_DCPDiode` | 3：`anode cathode guard` | 4：`guard cathode anode anode$1` | **FAIL**；`anode$1` 额外 | circuit `NoMatch=1`；device 3 layout-only / 1 schematic-only；net 5 / 2；pin Match 6 |

官方 CDL 与官方 SPICE 对两颗 leaf 的网络意图一致：DCN 的两个
`dantenna` 共用一个 `cathode`，DCP 的两个 `dpantenna` 共用一个
`anode`。但 strict-deep extraction 分别把其中一个器件放到
`cathode$1` / `anode$1`。因为器件和网络没有形成 paired match，当前
不能把它降格为单纯参数容差问题。

可复现输入与小型数据库：

| leaf | 最小 GDS / CDL SHA-256 | 小型 LVSDB |
|---|---|---|
| DCN | `aa14969a...ea81f` / `e6beb7b9...e43` | 54,778 B，`d47e30b7...b07d` |
| DCP | `ca9ff63f...e5f4f` / `4179ad18...6708` | 64,085 B，`a9b5782f...a98f` |

完整命令、完整 SHA-256、输入路径和 cross-reference 分类已保存于：

- `docs/issues/ihp-sg13g2-io-diode-strict-lvs-blocker.md`：已发布为 [IHP-Open-PDK #1130](https://github.com/IHP-GmbH/IHP-Open-PDK/issues/1130)。
- `reports/blockers/ihp-sg13g2-io-diode-strict-lvs.json`：机读 blocker 索引。
- `lvs-iopad-leaf-diagnostic-20260829-001/summary.json`：两颗 leaf 的完整结果。
- 两颗 leaf 目录内的 `.lvsdb`、extracted netlist、log 和 bounded cross-reference JSON：运行大文件按 `.gitignore` 保留在本地，不进入 Git。

### 官方父级直接 M1 几何门槛

`lvs-iopad-parent-metal-closure-20260829-001/official_parent_connectivity.json`
在固定容器内对官方 `sg13g2_IOPadIn` 做了受限只读几何分析。deck 的
M1 conductor 为 `8/0 + 8/22`，文本为 `8/25`：

- DCN 两个 `cathode` access component 分别接触 parent component 1 与 0；shared set 为空。
- DCP 两个 `anode` access component 分别接触 parent component 7 与 6；shared set 为空。
- 两颗 leaf 均为 `official_parent_direct_m1_closure_observed=false`，所以
  `parent_metal_closure_lvs_ab_gate_open=false`。

该证据文件为 5,952 B，SHA-256
`9c183265fb2070d58380ae378001c0281580f671cb26fda361721e67203846de`。
没有公开父级直接 M1 闭合证据，因此没有凭空画 bridge，也没有运行
speculative closure LVS A/B。

当前分类是：**官方 IO leaf GDS/CDL/SPICE 与公开 strict-deep LVS deck
之间存在可复现 blocker，但应由上游确认是库数据、deck 提取还是受支持
hierarchy 用法问题**。这不等于已完全识别根因；也不等于 full-chip
135,057-port mismatch 全由 IO 引起。两者并存：前者是小型 deep leaf
结构 mismatch，后者首先是 full-chip flat child-label promotion。

## 公开发布检查点

- 公开复现仓库：[World-Zhan/open-3d-memory-chipflow](https://github.com/World-Zhan/open-3d-memory-chipflow)，visibility=`PUBLIC`，默认分支 `main`。
- 首次远端 commit：`864da1c28b89cb7aa134cbadad24496b746d659c`。
- 上游仓库：[IHP-GmbH/IHP-Open-PDK](https://github.com/IHP-GmbH/IHP-Open-PDK)，由 pinned submodule URL 核实。
- 上游问题：[IHP-Open-PDK #1130](https://github.com/IHP-GmbH/IHP-Open-PDK/issues/1130)，状态记录为 `OPEN`。
- 公开发布不改变技术结论：A 轨仍为 DRC/LVS FAIL；`652` 与 `1585/12` 仍是不同 DRC 口径；full-chip strict LVS 仍为 `52 vs 135057`、exact shared `0`。
- 该公开发布检查点当时没有运行新的 KLayout/OpenROAD/LVS/DRC；之后仅执行了本页记录的 Pin3D partition/pre/floorplan 容量 A/B。仍未授权 Croc full-chip attempt 3。

## 直接生成原因与最小修复假设

源码与运行证据形成闭环：

1. `scripts/croc_signoff.sh` 把 full-chip LVS 固定为 `--run_mode flat`；实际日志也记录 `flat mode is enabled`。
2. deck 从每层 datatype 25 读取 label（例如 M1=`8/25`、M2=`10/25`、M3=`30/25`），并用 `connect(metal*_con, metal*_text)` 把所有标签附到电气网络。
3. attempt 2 在 flat 视图看到 M1/M2/M3 text 分别为 352,964 / 1,673,352 / 716,860 个；子层标准单元、IO pad 和宏的 pin text 被展平到 top extraction context，最终把大量内部 label-net 变成顶层 formal ports。
4. `TOP_LVL_PINS=false` 只让后处理跳过 `netlist.make_top_level_pins`；它不会删除提取阶段已经由 GDS label 形成的 formal ports。
5. Croc 自带 IHP LibreLane 配置明确把 `KLAYOUT_LVS_OPTIONS` 设为 `run_mode deep`，SRAM support 的手工回归脚本也使用 deep。这支持“full-chip 应先验证 deep hierarchy”这一最小假设。
6. 五-pad strict-deep wrapper 已恢复 6/6 exact 顶层端口，但 leaf netlists 仍不匹配；因此“端口边界已正确”不等于“LVS exact match”。
7. `--combine_devices` 与 baseline 的 5 NoMatch / 7 Skipped circuit、device/net/pin 分类计数完全相同；器件合并不是当前最小修复。

按证据优先级排列的最小修复假设：

1. `DCNDiode`/`DCPDiode` 的官方 leaf strict-deep mismatch 已独立复现并打包为本地上游 blocker；下一步是由 IHP PDK 维护者确认库数据、deck 或受支持 hierarchy 用法。
2. 只有拿到上游明确支持的修复或用法后，才重跑这两个 leaf；不得猜改 pin text、guard/substrate、tap extraction 或器件归一化。
3. 两个 leaf strict exact 后，仍须让最小父级 IO fixture strict exact，再考虑新的 full-chip deep 验证；不能用 full-chip attempt 试错。

明确禁止：`ignore_top_ports_mismatch`、implicit nets、关闭 strict port、关闭 simplify、凭空增加 parent metal，或在未完成上游支持的小型验证前启动 full attempt 3。

## 下一步门槛

1. 跟踪已发布的 [IHP-Open-PDK #1130](https://github.com/IHP-GmbH/IHP-Open-PDK/issues/1130)，等待上游确认库数据、deck 或受支持 hierarchy 用法。
2. 获得上游支持的 PDK/library/deck 解决方案后，只重跑 DCN/DCP 两个 strict-deep leaf case，目标必须是 LVS exact match。
3. 两颗 leaf exact 后再运行一个最小父级 IO strict-deep fixture；在此之前不得修改 full-chip runner，不得启动 attempt 3。
4. 后续 full-chip LVS 只有 exact match 才能继续处理 pad/sealring 与 density DRC；不得把 6/6 或 10/10 port-set exact 当作 LVS exact。
5. 只有 DRC=0、顶层 LVS exact match、无未布通网络、STA/PDN 证据齐全时，A 轨才可称公开规则签核级。
6. B 轨已完成 partition/pre/floorplan 的 HBT 容量合同 A/B，但仍是 `research_only/diagnostic_started_route_failed`；下一步先验证 1.6 µm legal-lattice placement/window，不能直接 full route。
7. C 轨仍为 `not_started`；不得把 B 轨容量合同 PASS 当作 3D SRAM 扩展已开始。

## 查看方式

- 文本/JSON：`less runs/croc-sg13g2-baseline-20260827-001/MILESTONE.md`；`python3 -m json.tool .../milestone.json | less`
- 端口映射：`python3 -m json.tool .../signoff.attempt-2/lvs/port_mismatch_analysis.json | less`
- IO leaf blocker：`less docs/issues/ihp-sg13g2-io-diode-strict-lvs-blocker.md`；`python3 -m json.tool reports/blockers/ihp-sg13g2-io-diode-strict-lvs.json | less`
- 父级 M1 几何：`python3 -m json.tool .../lvs-iopad-parent-metal-closure-20260829-001/official_parent_connectivity.json | less`
- DRC：在 KLayout Marker Browser 中打开 `...full.lyrdb`，并同时加载 `upstream/croc/klayout/out/croc.filled.gds.gz`。
- LVS：在 KLayout LVS Browser 中打开 `croc.lvsdb`；该文件很大，优先使用已生成的 40 KiB 流式摘要。
- APR：用 OpenROAD GUI 打开 `upstream/croc/openroad/out/croc.odb`，报告见 `upstream/croc/openroad/reports/`。
- Pin3D HBT 容量合同：`python3 -m json.tool runs/pin3d-hbt-capacity-contract-20260903-001/stage_ab.json | less`。
