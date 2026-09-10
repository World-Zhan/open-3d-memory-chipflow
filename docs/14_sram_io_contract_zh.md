# SRAM 电容修复与新版 IO 的实际验收边界

SPDX-License-Identifier: Apache-2.0

2026-09-10 第二轮。**64 个 SRAM 输出电容违规已清零；新芯片候选的 setup/hold/slew/cap/fanout 为 0/0/71/71/0，仍未签核。** 官方新版 IO 已完成局部接口、数字行为、三角时序和两宏完整公开 DRC 验证：它扩大了电容模型范围，但已测试的驱动均未满足 15 pF/1.2 ns；未迁移完整 IO 环。

## SRAM 修复与同阶段 PPA

`croc-full-io-sram-cap-20260910-001` 从前一轮 fanout 已清零候选继续，向每个 SRAM A_DOUT 加一颗 `sg13g2_buf_4`，共 64 颗，每颗保留四个原负载。真实运行 36.13 秒，exit 0、无 OOM，没有第二次尝试。

[独立审计](../reports/placement/full-io-sram-cap-audit-20260910-001.json)核对 34,886 个原实例的完整记录、几何、master、方位和状态，全部不变；新增 buffer 折叠后完整网络恢复，显式供电、普通 placement/核心 PG 检查通过。43 条 15 pF 命令及其余 SDC 保持；原 CLOCK/NDR 元数据和定义保持，NDR 布线策略资格仍 UNVERIFIED。结构证明不替代完整形式等价或签核。

| 相同 CTS / placement 寄生估计阶段 | 改前 | 改后 |
|---|---:|---:|
| active 面积 mm² | 0.7217894880 | 0.7227184608 |
| SRAM 输出 cap 违规 | 64 | 0 |
| 总 cap / slew 违规 | 135 / 71 | 71 / 71 |
| setup / hold / fanout 违规 | 0 / 0 / 0 | 0 / 0 / 0 |
| WNS / TNS ns | 0 / 0 | 0 / 0 |
| TT 原始默认活动功耗 mW | 5.46（不合格） | 5.46（不合格） |

面积增加 928.9728 µm²，约 0.128704%。原剩余 71 个 cap 与 71 个 slew 的端点及数值逐条保持；当前清除结果只适用于 placement 寄生估计，真实布线后的电容尚无结果。电气 die 为 3.896676 mm²，含封环规划为 4.235364 mm²；没有新 sealed GDS。100 MHz 是约束，Fmax 与可信 workload 功耗仍未知。

[机读 PPA](../reports/ppa/croc-ppa-sram-io-contract-20260910-001.json)继续引用[固定同类来源](../reports/ppa/comparison_sources_20260905.json)：ETH MLEM/Croc 为 IHP130、24 KiB、4.995225 mm²、作者典型 80 MHz/1.2 V，有上游流片/硅验证材料。本地仅 4 KiB 且未签核；不能将面积或 100 MHz 约束用于宣称性能/能效优势。

## 新版官方 IO：行为通过，原电气约束仍失败

固定 PDK 为 `331c00484213b13414777eec1336ef5c29b969bd`。选取 `sg13g2_IOPadOut16mA`、`sg13g2_IOPadInOut30mA`、`sg13g2_IOPadIn`，核对同套 LEF/CDL/Verilog/Liberty 接口、方向及 PG，再以官方 Verilog 做 42 个真实行为断言：包括 0/1/X/Z 传递、16 组双向组合、高阻、冲突和未知 enable。全部通过；不代表模拟电压、ESD、掉电或硅验证。

[三角 STA](../reports/ppa/ihp_io_suite-digital-sta-20260910-001.json)保留 15 pF、显式 1.2 ns、10 ns 周期、0.2 ns 时钟边沿，分别检查 TT、FF、SS。新库默认 3.5 ns 没有替代原约束。局部负载为 pin 电容及显式 lumped C，没有布线 R/RC 提取；不使用旧 IO 版图，也没有无 Liberty bondpad 或方向覆盖。这个实验不资格化整芯片功耗。

| pad slew / ns，限制均为 1.2 ns | FF | TT | SS |
|---|---:|---:|---:|
| Out16mA | 2.50766 | 3.56008 | 5.46864 |
| InOut30mA，TX 模式 | 1.61120 | 2.23935 | 3.39785 |
| Out30mA，单因素替代 | 1.57900 | 2.19179 | 3.32169 |

前两类均 cap/fanout=0，但边沿仍失败。其六条 slew 记录是三个信号网各自的 pin/port 观测，不能描述成六个独立物理故障。SS 的两条已约束 TX max 路径也失败；两处无效模式输入缺 input_delay，四个观察/高阻/时钟输出未约束，均明确保留，不宣称完整 MMMC。

[Out30 单因素验证](../reports/ppa/ihp_io_suite-maxdrive-20260910-003.json)只替换一个 master，网络、PG、SDC 和外部 GPIO 输入驱动保持；FF/TT/SS 都未满足 1.2 ns，SS max slack 为 −0.76431 ns。Out30 只验证接口和 STA，没有额外行为仿真或 GDS/LVS。**已测试的 Out16、InOut30、Out30 均无满足原条件的候选**；没有排除其他未测试电路、工艺或外部驱动方案。

整个数字/STA 分支共四个短进程。首次 TT 因不支持 `report_case_analysis` 而 exit 1，失败保留，未执行的 FF/SS 没有写为 PASS。独立续跑改用受支持的 SDC 回读并完成三角，之后才做 Out30 单因素比较。详细命令、终态与执行脚本副本均在发布清单中。

## GDS / LEF 一致性和真实 DRC

[最终物理审计](../reports/ppa/ihp-io-physical-final-20260910-001.json)证实三宏的 LEF pin 矩形均被实际同层 GDS 金属覆盖。递归 polygon 比较显示：Out16 的新旧 polygon 相同，但 LEF pin 形状不同；InOut30 和 In 的 polygon 各有 13 个 layer/datatype 改变，不能整套沿用旧物理视图。

三个独立导出的宏逐层 polygon 与官方源完全一致；[标签回读](../reports/ppa/ihp-io-labels-20260910-001.json)验证递归名称、层、全局位置及重数分别为 97/158/90，source/export 全相等；6/8/6 个 LEF pin 均具直接顶层、同金属 text 层且位于矩形内的标签。这是引脚形状/命名证明，不是导体电气连通或 LVS。

初版几何探针误用 Vector 变换，子层级标签坐标遗漏平移；原始结果保留，该 `position_um` 字段已明确弃用。正确坐标采用 Point 加完整变换，并独立与 transformed Text 对照。polygon 与金属覆盖结果不受此元数据问题影响。

Out16 与 InOut30 两宏实际执行完整 main、density、antenna、maximal DRC。FEOL/BEOL/off-grid/angle/pin/forbidden/recommended/connectivity 均开启，每宏 874 个类别、31 个 antenna 类别；真实 exit 1 为检测到违规，均无 OOM。每宏 merged 6 个 marker，全部为全局 density：`GFil.g`、`M2.j`、`M3.k`、`M4.k`、`M5.k`、`TM1.d`；其它 merged marker 为 0。**严格 macro DRC 仍 FAIL。** 上游顺序 runner 合并后删除各单项数据库，maximal raw count 未保留，保持未知。

宏级密度是在独立宏边界下测得，不能替代装配后的 IO 环/芯片密度。没有 waiver，也没有关闭任何规则。原 runner 按并行任务文件名误报 incomplete，独立审计按实际 `--mp 1` 的 main/辅助任务、开关、类别及终态核验；最终 wrapper 额外要求精确宏集合、独立终态一致及精确参数，避免空集合或参数子串误判。

## LVS：周长已解释，模型约定仍待解决

[tap 几何诊断](../reports/lvs/tap-geometry-20260910-001.md)用唯一只读探针验证：实际 ptap 是一个外框加两个孔洞，外框 33.06×10.26 µm、两孔各 30.54×3.24 µm，因此 A=141.2964 µm²，P=86.64+2×67.56=221.76 µm，与严格 raw extraction 精确相同。

CDL 的 A=141.253/P=47.54 则与按 5 nm 网格量化的 11.885 µm 等效正方形相容。这是数值假说，未证明原始生成器/设计意图。A/P 同时参与 tap 电阻模型，不能为了 LVS 匹配直接改 P。guard 有真实普通 ntap 环和 288 个 contacts，但没有生成 ntap1 器件的 well marker；CDL GUARD 本地器件引用为零。器件图的 guard 边界语义仍未解决，未加虚接或 marker。

本轮没有运行新的 leaf/parent/full-chip LVS；既有严格 LVS FAIL 保持。需要查证或重建有依据的 IO tap 参数约定和 guard 端口语义，再进入严格器件回归。

## 下一轮验收门槛

1. 保留 15 pF 和 1.2 ns；确认它们的板级依据，并寻找有实际模型支持的驱动/接口方案。已有库内实测不能支持直接全环迁移。
2. 在 tap A/P 与 guard 模型约定有依据后做严格回归；同时补 reader 数值运算后的有限正值检查，不能放宽容差或吞掉端口。
3. 新 IO 只有在成套视图及电气/严格 LVS 门槛通过后才接入整环，再验装配后的密度、连接与布线边界。
4. SRAM ECO 随后仍须 route、提取后角落/模式 STA、电容回验；全芯片 fill/seal、DRC/LVS、IR/EM、DFT、MPW 资格继续保留为未完成。

通用 skill 不是当前瓶颈。项目继续沿用明确命令、固定来源、失败保留及每轮 PPA 的证据流程；真实产品/板级合同和工艺模型问题需要对应输入，不能用测试 PASS 替代。
