# SRAM / 3D memory 扩展最小规格 v0.1

SPDX-License-Identifier: Apache-2.0

状态：**规格与验证计划已建立，RTL 尚未实现**。这是可修订的学习基线，不是用户已确认的产品指标。下一步可以独立实现 C1，不需要等待 Croc 全芯片 DRC/LVS 或 Pin3D 路由清零。与基线集成和物理实现必须形成独立 run。

## 1. 已核实的接口事实

固定 Croc 提交为 `968bab17b37e88d9200a0899cb9181e42850ec87`。

| 项目 | 当前事实 | 来源 |
|---|---|---|
| 系统 SRAM | 2 个 512×32 单端口 bank，总计 4 KiB | `upstream/croc/rtl/croc_pkg.sv` |
| Bank 地址，左闭右开 | `[0x10000000, 0x10000800)`、`[0x10000800, 0x10001000)` | `CrocAddrMap` |
| 用户域地址 | `[0x20000000, 0x80000000)` | `CrocAddrMap` |
| 当前 UserDesign 解码 | `[0x20000000, 0x30000000)`，内部仍接 `obi_err_sbr` | `user_pkg.sv`、`user_domain.sv` |
| subordinate 协议 | 32-bit address/data，4-bit BE，保留 aid/rid；`UseRReady=0`、`CombGnt=0` | `croc_pkg::SbrObiCfg` |
| 本地 traffic 合同 | 控制窗口 `0x20001000`、4 KiB；latency 1、outstanding 1；1024 transactions、stride 4、seed 20260826 | `config/traffic_spec.json` |
| 基线时钟约束 | 系统 10 ns、JTAG 25 ns、RTC 50 ns，时钟组异步，uncertainty 0.1 ns | `upstream/croc/openroad/src/constraints.sdc` |

控制窗口不是新增 4 KiB SRAM，也不与现有 SRAM 地址重叠。当前 UserDesign 的宽解码需要在集成时收窄到 `[0x20001000, 0x20002000)`，窗口外继续送 error subordinate。禁止为了接入模块而意外接管整个用户域。

## 2. 分阶段架构

**C1：OBI 控制/诊断 endpoint。** 实现少量 CSR、字节写、精确握手、响应 ID、错误路径和诊断计数；本阶段没有 SRAM 宏或主动发起内存访问的 manager。模块和 testbench 放在本仓库独立目录，保持 pinned upstream 内容不变；集成差异用可审查 patch 表达。

**C2：复用现有 SRAM 的测试流量路径。** 先用软件测试已分配的 SRAM scratch 区间；为避免破坏程序/栈/数据，必须由 linker map 确定可用区间。需要硬件 traffic manager 时再定义 manager 端口、crossbar 仲裁、保留地址、超时和 counter 语义，形成 v0.2 规格。不得把两个现有 bank 简单并接给另一个 controller，也不能用修改控制窗口的方式伪装 SRAM 地址。

**C3：3D memory 研究映射。** 在 C2 功能证据和 Pin3D legal-lattice/route 门槛满足后，再定义 logic/memory tier、HBT 预算、bank 划分与热/功率活动输入。两颗 2D SRAM 宏不是 3D SRAM 工艺；DRAM 还需要刷新、时序和真实宏模型，当前均未提供。

## 3. C1 的可实现合同

- 时钟为 `clk_i`；`rst_ni` 低有效复位。异步置位复位状态，同步释放由集成层保证。复位期间 `gnt=0`、`rvalid=0`；未完成请求被取消，不产生复位后幽灵响应。
- 接受请求的唯一事件是时钟边沿采样到 `req && gnt`。未获 grant 时，manager 保持地址、we、BE、data、aid 不变。
- 最多 1 笔未完成请求。`gnt` 使用寄存状态驱动，不形成 req→gnt 的组合路径。地址在周期 n 接受后，周期 n+1 输出一次 `rvalid`；没有 rready，响应不得等待下游 ready。C1 允许气泡，不承诺每周期一笔。
- 响应 `rid` 等于接受时的 `aid`，不能使用响应时的实时输入 ID。optional 输出固定为 0。
- `addr[1:0] != 0`、未定义 offset、写只读 CSR 或读只写 CSR：仍必须完成握手并返回 `err=1, rdata=0`，不改变目标寄存器；禁止挂死或静默成功。
- 成功写操作 `err=0, rdata=0`；合法读按下表返回数据。SCRATCH 采用 little-endian 字节写：BE[i] 控制 `[8*i +: 8]`；BE=0 是合法无操作写。读操作忽略 BE，返回整个 32-bit 字。
- 计数器模 2^32；ACCEPTED 计每次地址握手，包含失败访问和读取计数器本身。读计数返回本次事务接受前快照。ERRORS 对本次地址被判定错误时加 1；复位清零。
- CLEAR 仅接受 BE=1111、wdata=1 的写；清零两计数器，清零优先于计数，本次 CLEAR 不保留在 ACCEPTED 中。其他写值/掩码返回错误并正常计入 ACCEPTED/ERRORS。

| Offset | 名称 | 权限 | Reset | 行为 |
|---|---|---|---|---|
| 0x000 | ID | RO | 0x4D454D31 | 固定 MEM1 版本标识 |
| 0x004 | SCRATCH | RW | 0 | 32-bit byte-enable 存储寄存器 |
| 0x008 | ACCEPTED | RO | 0 | 接受请求计数，返回接受前值 |
| 0x00C | ERRORS | RO | 0 | 错误请求计数，返回接受前值 |
| 0x010 | CLEAR | WO | 0 | 严格全字写 1 清零计数 |
| 0x014–0xFFF | reserved | — | — | 返回 error；不产生未声明别名 |

`traffic_spec.json` 的 1024 次 stride-4 扫描覆盖整个窗口，其中大量 offset 是 reserved；这应作为正负混合测试，不能要求所有事务成功。寄存器功能测试必须使用上表定义的合法序列，expected-error 单独统计。以后不能把历史 traffic 合同当作已实现的 DMA 配置。

## 4. 需求到验收的对应关系

下列测试当前全部为 **not_run**，不是已有 PASS。

| ID | 需求/测试 | 必须看到的证据 |
|---|---|---|
| C1-RST | 空闲/请求等待/响应前复位 | 计数清零、无幽灵响应、恢复后首笔正常 |
| C1-HS | req 拉长、grant 延迟、连续请求、不同 aid | 1 request→1 response，latency=1，outstanding≤1，rid 正确 |
| C1-BE | 全部 16 种 BE、随机 wdata、read-back | 独立 byte-array scoreboard 逐字节一致；BE=0 不改值 |
| C1-CSR | RO/RW/WO、CLEAR、counter read snapshot | 合法/非法写行为、清零优先级、计数模回绕 |
| C1-ADDR | 首末地址、窗口外、非对齐、所有 reserved offset | 无 alias、精确 err、无挂死；窗口外在集成 TB 验证 |
| C1-RAND | 固定 seed 20260826、至少 1024 事务，加 3 个固定扩展 seed | 独立模型无 mismatch；成功与预期错误分开计数 |
| C1-ASSERT | 协议断言与有限状态不变量 | 无无因响应、无丢失/重复响应、stall 时输入稳定、复位后 ID 不泄漏 |
| C1-SYN | 使用固定 Yosys/Slang 的模块综合 | 无 latch、无 unresolved reference、无意外 SRAM blackbox、资源统计 |
| C1-INTEG | 独立集成 patch 与 Croc 软件回归 | 原 Hello World 保留；CSR 软件读写/error 测试通过；新 run ID |

先写独立 scoreboard/定向用例，再实现 RTL。代码覆盖率只辅助定位空白，需求矩阵每项要有测试结果与路径；未运行 formal/CDC/RDC 不得写成通过。C1 单功能时钟不能替代 SoC 多时钟跨域审核。

## 5. 自动推进与用户输入边界

可独立推进：C1 RTL、testbench、lint/综合、证据归档；Croc 现有报告诊断；Pin3D 受限几何分析。100 MHz 只是继承的学习目标，尚无新增模块 PPA 保证；当前保持已有最多 6 线程约束。

在扩大为真实产品前需要确认：容量、带宽/延迟、功耗和面积预算；SRAM 或 DRAM；tier 数、实际工艺/宏/键合 pitch、IO/封装以及最终验收口径。没有这些输入仍能推进 C1，但不能把默认假设写成已确认产品规格。C1 验证通过后才形成 C2 接口规格，不预先实现未经定义的 DMA/ECC/cache coherency/DRAM 控制器。
