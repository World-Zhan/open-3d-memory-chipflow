# Croc / IHP SG13G2 基线里程碑（Attempt 2 终局）

生成日期：2026-08-28<br>
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
| B：TaiWei-Pin-3D | **未开始** | 未来结果只能标记 `research_only` | 不是真实 3D PDK/送厂包 |
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

1. **首选**：逐个核对 5 个 `NoMatch` leaf 的官方 CDL/SPICE、GDS 提取与 deck 器件归一化规则，先用 `DCNDiode`/`DCPDiode` 的单 leaf strict-deep case 解释 `cathode$1`/`anode$1` 分裂。
2. 仅使用 PDK 文档明确支持的 IO hierarchy/abstract/局部 flatten 机制做小型 wrapper A/B；不得把 extracted netlist 当 reference，也不得隐藏 guard/substrate 设备。
3. 如果公开 PDK/deck 无法让官方 IO GDS 与官方 schematic 严格匹配，把它记录为 PDK IO-library/deck blocker 并准备最小可复现 upstream issue；不要用 full-chip attempt 试错。

明确禁止：`ignore_top_ports_mismatch`、implicit nets、关闭 strict port、关闭 simplify，或在未完成小型验证前启动 full attempt 3。

## 下一步门槛

1. 用一个 `DCNDiode`/`DCPDiode` 最小 strict-deep case 区分标签连通分量、guard/substrate split 与器件参数/归一化差异，并要求 exact match；不得重跑 15-cell sweep。
2. 检查公开 deck/PDK 是否有受支持的 IO leaf abstract、hierarchy 或 selective flatten 用法；没有文档证据就不启用。
3. 小型 IO leaf/wrapper strict LVS exact 前不得修改 full-chip runner，不得启动 attempt 3；exact 后仍需审查 Croc 52 个 top pin text 与实际 ring connectivity。
4. 新 full-chip LVS 只有 exact match 才能继续处理 pad/sealring 与 density DRC；不得把 6/6 或 10/10 port-set exact 当作 LVS exact。
5. 只有 DRC=0、顶层 LVS exact match、无未布通网络、STA/PDN 证据齐全时，A 轨才可称公开规则签核级。
6. A 轨收敛后才启动 B 轨；B 始终标记 `research_only/not_started`。C 轨仍为 `not_started`。

## 查看方式

- 文本/JSON：`less runs/croc-sg13g2-baseline-20260827-001/MILESTONE.md`；`python3 -m json.tool .../milestone.json | less`
- 端口映射：`python3 -m json.tool .../signoff.attempt-2/lvs/port_mismatch_analysis.json | less`
- DRC：在 KLayout Marker Browser 中打开 `...full.lyrdb`，并同时加载 `upstream/croc/klayout/out/croc.filled.gds.gz`。
- LVS：在 KLayout LVS Browser 中打开 `croc.lvsdb`；该文件很大，优先使用已生成的 40 KiB 流式摘要。
- APR：用 OpenROAD GUI 打开 `upstream/croc/openroad/out/croc.odb`，报告见 `upstream/croc/openroad/reports/`。
