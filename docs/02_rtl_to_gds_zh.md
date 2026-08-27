# 从 RTL 到 GDS：可执行的中文教程

SPDX-License-Identifier: Apache-2.0

这份教程按“每一步在消除哪一种不确定性”来解释流程。命令可以复制执行，但不要只看退出码：每一节都列出了输入、输出和验收证据。

## 0. 先建立芯片流程的心智模型

软件程序描述 CPU 要执行的指令；RTL 描述寄存器在时钟边沿如何更新；综合网表把 RTL 变成工艺库中的逻辑门；APR 决定这些门和连线在硅片上的具体坐标；GDS 是几何层数据库；DRC 判断几何是否违反工艺规则；LVS 判断这些几何抽取出的电路是否和设计网表相同。

可以把它看成逐层收窄：

```text
C/hex -> RTL 行为 -> 门级连接 -> 带坐标门级连接 -> 金属/扩散几何 -> 公开规则检查
```

任何前一步错误都会被后一步“忠实地物理实现”，所以不能跳过 RTL 和门级仿真直接看漂亮版图。

## 1. 软件与 RTL 仿真：电路行为对不对

命令：

```bash
export RUN_ID=croc-baseline-001
make croc-rtl
```

实际工作：

1. Croc 的 RISC-V 交叉编译器把 `sw/helloworld.c` 编译成 ELF/HEX；
2. Verilator 把 SystemVerilog RTL 翻译成 C++ 仿真器；
3. 测试台驱动时钟、复位和 JTAG，把程序装入 SRAM；
4. CVE2 执行指令，通过 OBI 访问 UART；
5. UART 模型打印严格签名 `Hello World from Croc!`。

输入：

```text
upstream/croc/rtl/**/*.sv
upstream/croc/sw/helloworld.c
upstream/croc/Bender.lock
```

关键输出：

```text
upstream/croc/sw/bin/helloworld.hex
runs/<run-id>/logs/croc-rtl.log
runs/<run-id>/stage_evidence/croc-rtl.json
```

验收器要求软件 HEX 非空且 UART 签名完全匹配。仅“仿真器退出 0”不够，因为测试台也可能在程序没有运行时正常退出。

常见失败：

- 找不到交叉编译器：容器镜像或 PATH 没有正确启动；
- JTAG 超时：检查 reset、时钟、HEX 路径和 boot address；
- 有输出但乱码：UART 时钟/波特率假设不一致；
- 没有精确签名：从日志中找第一个异常 PC、OBI error 或 JTAG timeout。

## 2. 综合：RTL 能否映射成 SG13G2 门和 SRAM

命令：

```bash
make croc-netlist-sim RUN_ID=croc-baseline-001
```

Yosys+Slang 做五类转换：

1. 解析 SystemVerilog package/interface/generate；
2. elaboration：把 parameter、generate 和层次实例具体化；
3. 把 `always_ff/always_comb` 变成寄存器和组合逻辑；
4. 布尔优化、常量传播、删除不可达逻辑；
5. 用 IHP Liberty 中实际存在的标准单元完成 technology mapping。

SRAM 不应该被拆成几万个位触发器。Croc 的 `tc_sram_impl` 在 `sg13g2` 模式必须解析到公开的 `RM_IHPSG13_1P_512x32_c2_bm_bist` 硬宏。`tc_sram_blackbox` 是不支持配置的显式失败标记，不在白名单。

综合网表不是“更精确的 RTL 文本”，而是工艺库单元之间的连接图。随后门级 Verilator 用同一个 HEX 再跑一次；UART 签名一致说明综合没有改变可观察软件行为。

验收条件：

- `croc_yosys.v` 存在且非空；
- 无 unresolved reference；
- 无 inferred latch；
- 无 `tc_sram_blackbox`；
- 门级仿真仍打印精确 UART 签名。

## 3. Floorplan：芯片外框、IO、宏和供电骨架放在哪里

`make croc-pnr` 会顺序执行五个 OpenROAD stage。第一个是 floorplan。

Floorplan 决定：die/core 尺寸、标准单元行、IO pad/ring、两块 512x32 SRAM 的位置、placement blockage、VDD/VSS ring/stripe。它解决的是“是否存在一个有希望放得下且供得上电的几何框架”，还没有决定每个标准单元的位置。

需要看：

- 宏是否越界或重叠；
- IO 顺序是否与顶层端口一致；
- core utilization 不能高到无布线空间；
- SRAM 的 halo/channel 是否足够；
- PDN 是否跨过宏并连到标准单元 rails。

本仓库在最终 ODB 上额外执行 `check_power_grid -net VDD` 和 `check_power_grid -net VSS`。只看到 PDN 图形不等于电气连通。

## 4. Placement：每个标准单元坐标是什么

Global placement 把时序、线长、密度和拥塞作为代价函数，求近似坐标；detailed placement 把单元吸附到合法 row/site，消除重叠。

这一阶段会插 buffer、调整门尺寸、修复 transition/capacitance。综合网表和 placement 后网表的逻辑连接可能不同，但功能等价、时序更可实现。

常见失败定位：

- utilization overflow：floorplan 太小或宏通道太窄；
- many cells cannot be legalized：blockage/row 切分不合理；
- congestion hotspot：宏边界、IO pin 或总线集中；
- max transition 大量违规：缓冲不足或约束过紧。

## 5. CTS：时钟为什么不能当普通信号线

一个时钟驱动成千上万个寄存器。若直接从一个端口拉长线，线电阻/电容造成不同寄存器看到边沿的时间不同，这叫 skew。CTS 插入层次化 clock buffer，让插入延迟、skew、slew 在可控范围。

CTS 后必须同时看 setup 和 hold：

- setup 检查数据是否在下一个采样边沿前到达；
- hold 检查数据是否在当前采样边沿后保持足够久。

修 setup 常通过加速数据路径，修 hold 常通过在过快路径加延迟；两者可能相互影响。

## 6. Routing：逻辑网络变成实际金属和 via

Global routing 先分配粗略通道并估计拥塞；detailed routing 在每个工艺 track 上放精确 wire/via，同时满足 width、spacing、min-area 等几何规则。Croc 上游会做 antenna repair，再运行 detailed route。

本仓库不从日志猜“看起来都连了”，而是在最终 ODB 调用 OpenROAD `design_is_routed`。返回 false 时阶段失败。

最终报告必须解析出：

- WNS >= 0；
- TNS >= 0；
- setup/hold violation 为 0（若工具报告该字段）；
- 未布通网络为 0；
- VDD/VSS power grid 连通。

如果 WNS/TNS 无法从报告解析，验收也失败，不能把“未知”当成 0。

## 7. GDS、seal ring 和 fill：从逻辑几何到完整芯片几何

```bash
make croc-gds RUN_ID=croc-baseline-001
```

四个文件代表四个明确阶段：

```text
croc.gds.gz            DEF + 标准单元/SRAM/IO GDS stream-out
croc.sealed.gds.gz     外围加入 seal ring
croc.metfilled.gds.gz  加入金属密度 fill
croc.filled.gds.gz     再加入 active fill，最终 DRC 输入
```

Seal ring 用于芯片切割边缘的机械/工艺保护。Fill 不是“装饰”：CMP 等制造步骤要求局部图形密度落在窗口内。只对未填充 GDS 跑主 DRC，不能代表最终版图。

Croc 的公开工艺适配把 `technology` 指向一个扁平化的 `ihp13/pdk` 目录，供综合和 stream-out 统一读取 LEF/lib/GDS；IHP 的 `filler.py` 则按标准 Open PDK 结构从 `$PDK_ROOT/$PDK/libs.tech/...` 查找 fill macro。仓库 wrapper 因此把独立锁定的 `upstream/ihp-open-pdk/ihp-sg13g2` 只读挂载到容器内该标准路径。这样 fill 与后续 DRC/LVS 使用同一锁定 PDK，同时不修改 Croc 子模块或复制工艺文件。

## 8. DRC：几何是否符合公开规则

```bash
make croc-signoff RUN_ID=croc-baseline-001
```

DRC 固定使用独立锁定的 IHP Open PDK `run_drc.py`，输入是 `croc.filled.gds.gz`，参数包含：

```text
--run_mode deep --mp 6 --density_thr 6 --antenna
```

没有 `--no_density`、`--no_offgrid`、`--no_angle`、`--no_feol`、`--no_beol` 或 `--no_recommended`。默认 main deck 包含 FEOL、BEOL、pin、geometry/off-grid/angle、recommended 与 density；`--antenna` 显式加入 antenna。

违规必须为 0。Waiver 只有在 foundry/MPW 明确给出、并作为可审计输入进入新政策版本时才可能存在；当前实现没有 waiver 接口。

## 9. LVS：画出来的晶体管是否等于设计电路

OpenROAD 从最终 ODB 和 IHP master CDL 通过 `write_cdl` 生成 `croc.cdl`。这一步按库定义的真实 pin order 输出实例，避免手写 Verilog→SPICE 映射造成总线顺序错误。

LVS 输入：

```text
layout:   croc.gds.gz（加机械 seal/fill 前的 croc_chip 电气顶层）
netlist:  runs/<run-id>/signoff/croc.cdl
topcell:  croc_chip
```

为什么不是 filled GDS：seal ring 和 fill 是机械/密度几何，不属于设计原理图的功能电路。DRC 检查最终 filled GDS；LVS 对电气顶层做 exact match。报告必须出现 IHP runner 的 `Congratulations! Netlists match.`，且进程退出 0。

禁止：

- `--ignore_top_ports_mismatch`；
- `--implicit_nets`；
- 只跑 `--net_only` 而不比较；
- 把缺失 SRAM 当黑盒跳过。

## 10. 3D ASAP7 研究轨

```bash
make pin3d-smoke RUN_ID=pin3d-gcd-001
```

封装运行的是官方 GCD OpenROAD 路径，增加 `--run-only` 是因为固定版本的默认 eval 会调用 Cadence；本工程不能把商业 Cadence 当作开源依赖。流程依次完成：2D bootstrap、逻辑分层、tier-aware 视图、mixed-fanout split、上下层宏/标准单元放置、两层独立 PDN、分层优化、owner/receive CTS、3D route、SPEF 和 final reports。

HBT 在 unified metal stack 中作为特殊 via 表示 face-to-face 垂直连接。它是研究抽象，不是 foundry hybrid-bonding rule deck。

验收器要求：

- upper/bottom tier 实例数均非零；
- bottom/upper PDN 两个 stage 都成功；
- HBT 数量和 structural cross-tier nets 均非零；
- mixed-fanout 指标存在（允许优化后为 0）；
- final ODB/DEF/Verilog/SDC/SPEF 存在；
- WNS/TNS 指标存在；
- OpenROAD route DRC 为 0。

输出无论多好都标为 `research_only`。

## 11. 热分析

```bash
make pin3d-full RUN_ID=pin3d-gcd-thermal-001
```

固定 TaiWei 提交定义了 `ord-hotspot`，但没有随仓库发布它引用的 `HotSpot/scripts` 与 `HotSpot/examples/thermal` harness。本目标不会生成假温度：缺失时明确失败。只有锁定并审计兼容 harness、生成 `hotspot_outputs` 且解析到最高温度后，full 验收才通过。

锁文件中的 Open3DFlow 仅用于参考 CPU 与堆叠 SRAM/TSV 的系统划分。实际审计的 MIT 许可提交 `b25373476eb491206f852e3c056244e79311e93e` 包含独立 thermal demo，却缺少 TaiWei 目标调用的 `divide_def.py`、`divide_grid.py`、`max_t.py`、`merge_ptrace.py` 和 `run_report_power.tcl`，不能直接接线使用。

## 12. 报告与复现

```bash
make report
```

每个 stage 的 stdout/stderr、命令、开始/结束时间、退出码、锁定版本和 evidence 都在 `runs/<run-id>/manifest.json`。`report` 只汇总实际存在的数据；缺失指标显示为空，不会补 0。
