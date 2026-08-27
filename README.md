# open-3d-memory-chipflow

SPDX-License-Identifier: Apache-2.0

这是一个面向初学者、证据优先的开源芯片流程工程。它把两个用途不同的上游固定在可复现提交上：

- **Croc + IHP SG13G2**：从软件/RTL 仿真、Yosys+Slang 综合、门级仿真、OpenROAD APR、KLayout GDS/封装几何，到 IHP 公开 deck 的 DRC/LVS。只有这条轨道满足严格门槛后，报告才允许写成 `public_rule_signoff`。
- **TaiWei-Pin-3D + ASAP7**：复现 F2F 双层 3D 研究流程，包括分层、HBT、上下层 PDN、分层放置/CTS/布线、SPEF 与 HotSpot。所有结果永久标记为 `research_only`，不能用于送厂。
- **Open3DFlow**：只作为 CPU + 堆叠 SRAM、TSV/混合键合划分的架构参考固定在锁文件中，不作为主执行框架。

它不会把预测性 ASAP7 版图说成可制造，也不会把 IHP 开放 PDK preview 说成 foundry 最终签核。真实投片仍需要 IHP 对冻结 PDK、rule deck、waiver、封装和 MPW 入口复核。
已审计的 Open3DFlow 提交并不包含 TaiWei `ord-hotspot` 所需的完整脚本集合，因此不能用其中单独的 thermal demo 冒充兼容 harness。

## 目录

```text
config/                  版本化输入样例
docs/                    中文教程、签核政策和故障定位
schemas/                 traffic/signoff JSON Schema
scripts/                 doctor、run manifest、流程封装、报告器
tests/                   不依赖 EDA 的契约单元测试
upstream/                固定 SHA 的 Git submodule
runs/<run-id>/           每次运行的 manifest、日志、归档（不进 Git）
reports/generated/       汇总 Markdown/JSON（不进 Git）
```

## 第一次使用

必须在 WSL2 的 ext4 路径运行；不要把工程移到 `/mnt/c` 或 `/mnt/d`。

```bash
cd /home/james_zhan/projects/open-3d-memory-chipflow
make doctor
```

若 doctor 报 Docker/ORFS 缺失，按 [环境安装](docs/01_environment_zh.md) 操作。Docker 镜像拉取后会记录 repo digest，而不是只相信可移动 tag。

## 稳定入口

```bash
make doctor
make croc-rtl
make croc-netlist-sim
make croc-pnr
make croc-gds
make croc-signoff
make pin3d-smoke
make pin3d-full
make report
make test
```

默认每个目标都会生成新的 run ID。要把一组阶段归入同一次实验，显式传入同一个 ID：

```bash
export RUN_ID=croc-baseline-001
make croc-rtl croc-netlist-sim croc-pnr croc-gds croc-signoff
```

已有同名阶段不会被静默覆盖；若要重跑，请换 run ID。上游工具会在其工作目录生成临时结果，但每个成功或失败阶段的日志和声明工件都会归档到 `runs/<run-id>/`。
后续 Croc 阶段还会检查同一 run 的前置阶段确实是 `passed`，因此不能拿另一个 run 遗留的 GDS/ODB 冒充当前实验输入。

## 签核用词

- `not_run`：没有实际执行。
- `failed`：执行过但验收未通过。
- `research_only`：预测性/研究 PDK 结果，不能送厂。
- `public_rule_signoff`：Croc/IHP 轨在固定版本上满足本仓库全部公开规则门槛。
- `foundry_signoff`：本仓库永远不会自动声明；只能由 foundry/MPW 项目方确认。

详细阶段解释见 [RTL 到 GDS 中文教程](docs/02_rtl_to_gds_zh.md)，不可绕过的验收条件见 [签核政策](docs/03_signoff_policy_zh.md)。

## 许可证

仓库自有脚本、配置与文档采用 Apache-2.0；未来 `rtl/` 下的新硬件采用 Solderpad 0.51。各 submodule 保留上游许可证，详见 [LICENSES/README.md](LICENSES/README.md)。
