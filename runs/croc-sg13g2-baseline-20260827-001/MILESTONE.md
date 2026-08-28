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

## 直接生成原因与最小修复假设

源码与运行证据形成闭环：

1. `scripts/croc_signoff.sh` 把 full-chip LVS 固定为 `--run_mode flat`；实际日志也记录 `flat mode is enabled`。
2. deck 从每层 datatype 25 读取 label（例如 M1=`8/25`、M2=`10/25`、M3=`30/25`），并用 `connect(metal*_con, metal*_text)` 把所有标签附到电气网络。
3. attempt 2 在 flat 视图看到 M1/M2/M3 text 分别为 352,964 / 1,673,352 / 716,860 个；子层标准单元、IO pad 和宏的 pin text 被展平到 top extraction context，最终把大量内部 label-net 变成顶层 formal ports。
4. `TOP_LVL_PINS=false` 只让后处理跳过 `netlist.make_top_level_pins`；它不会删除提取阶段已经由 GDS label 形成的 formal ports。
5. Croc 自带 IHP LibreLane 配置明确把 `KLAYOUT_LVS_OPTIONS` 设为 `run_mode deep`，SRAM support 的手工回归脚本也使用 deep。这支持“full-chip 应先验证 deep hierarchy”这一最小假设。

按证据优先级排列的最小修复假设：

1. **首选**：在小型 IO+标准单元代表结构上验证 `deep` 能保留层次并只暴露预期顶层端口；通过后再把本项目 full-chip LVS 从 flat 改为 deep。
2. 若 deep 仍产生额外端口，只检查 top/IO/macro 的 datatype-25 label 与 datatype-2 pin shape 传播，限制错误的子层 label 暴露；不删除真实顶层端口。
3. 核对 OpenROAD/KLayout stream-out 的 top pin text 是否只包含 52 个芯片端口，并让 pad-side、core-side alias 在层次边界内正确连接。

明确禁止：`ignore_top_ports_mismatch`、implicit nets、关闭 strict port、关闭 simplify，或在未完成小型验证前启动 full attempt 3。

## 下一步门槛

1. 先提交并推送本诊断脚本、测试和里程碑。
2. 对最小代表结构做 deep/flat pin-boundary A/B 验证；预期 deep 顶层 formal ports 等于该结构的 schematic 端口集合。
3. 通过后才修改 full-chip runner 并安排 attempt 3；随后再处理 pad/sealring 和 density DRC。
4. 只有 DRC=0、顶层 LVS exact match、无未布通网络、STA/PDN 证据齐全时，A 轨才可称公开规则签核级。
5. A 轨收敛后才启动 B 轨；B 始终标记 `research_only`。C 轨仍需等待两条原版流程跑绿。

## 查看方式

- 文本/JSON：`less runs/croc-sg13g2-baseline-20260827-001/MILESTONE.md`；`python3 -m json.tool .../milestone.json | less`
- 端口映射：`python3 -m json.tool .../signoff.attempt-2/lvs/port_mismatch_analysis.json | less`
- DRC：在 KLayout Marker Browser 中打开 `...full.lyrdb`，并同时加载 `upstream/croc/klayout/out/croc.filled.gds.gz`。
- LVS：在 KLayout LVS Browser 中打开 `croc.lvsdb`；该文件很大，优先使用已生成的 40 KiB 流式摘要。
- APR：用 OpenROAD GUI 打开 `upstream/croc/openroad/out/croc.odb`，报告见 `upstream/croc/openroad/reports/`。
