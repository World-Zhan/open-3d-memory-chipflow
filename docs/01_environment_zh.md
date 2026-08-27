# WSL、Docker 与 EDA 环境安装

SPDX-License-Identifier: Apache-2.0

## 1. 为什么工程必须放在 WSL ext4

芯片后端流程会创建大量小文件、符号链接，并频繁调用大小写敏感的 Linux 工具。`/mnt/c`、`/mnt/d` 是 Windows 文件系统经 DrvFS 暴露给 WSL：元数据操作慢，权限语义和大小写也可能不同。因此本工程固定放在：

```text
/home/james_zhan/projects/open-3d-memory-chipflow
```

`make doctor` 会拒绝 `/mnt/*` 路径。当前 Windows 侧的 `AI_chip` 模拟器是另一套源码，二者只通过 JSON 交换数据，不互相嵌套仓库。

## 2. WSL 资源

Windows 文件 `C:\Users\James Zhan\.wslconfig` 的目标配置是：

```ini
[wsl2]
memory=10GB
swap=12GB
processors=12
```

修改前应复制一份备份。修改后在 PowerShell 执行：

```powershell
wsl.exe --shutdown
```

重新打开 Ubuntu 后验证：

```bash
nproc
free -h
df -h /home/james_zhan/projects/open-3d-memory-chipflow
```

预期是 12 CPU、约 9.7 GiB 可见内存和 12 GiB swap。工具编译和 Pin3D 流程最多使用 6 个线程，留出内存给链接器、OpenROAD 数据库和文件缓存。

## 3. 安装 WSL 内原生 Docker

脚本只支持已验证的 Ubuntu 22.04 jammy，并使用 Docker 官方 apt 仓库。它需要你在可见终端中输入 sudo 密码；密码不写入脚本、日志或 Git。

```bash
cd /home/james_zhan/projects/open-3d-memory-chipflow
bash scripts/bootstrap_docker_ubuntu.sh
```

脚本执行以下可审计动作：

1. 验证 PID 1 是 systemd；
2. 安装 `ca-certificates`、`curl`；
3. 安装 Docker 官方签名密钥和 jammy apt source；
4. 安装 Engine、CLI、containerd、Buildx、Compose plugin；
5. 启用 `docker.service`；
6. 把当前 WSL 用户加入 `docker` 组；
7. 通过新的 group shell 跑 `hello-world`。

完成后从 PowerShell 执行一次 `wsl.exe --shutdown`，再验证：

```bash
docker version
docker compose version
docker run --rm hello-world
```

不要通过 `chmod 666 /var/run/docker.sock` 绕过权限。docker 组等价于高权限，只有可信用户应加入。

## 4. 固定 Croc 容器

```bash
make docker-pull
```

该目标拉取 `hpretl/iic-osic-tools:2025.12`，然后从 `RepoDigests` 读取 `sha256:...` 并写入 `versions.lock.json`。后续 Croc 命令会先比较本地镜像和锁文件；tag 指向发生漂移时拒绝运行。

当前已审计网络无法直连 Docker Hub registry。脚本会先短时尝试官方地址；失败后只允许锁文件声明的 1ms 代理 OCI 索引 `sha256:929614...ba8521`，并以有限次数复用已校验的下载层。该索引的 amd64 manifest 是 `sha256:82903a...f34678`，provenance 指向 IIC 官方内部 registry 的构建材料。完成后同时锁定远端 digest 和本地 image ID；运行命令使用校验后的 image ID。代理是传输回退而不是新的可移动信任 tag。

## 5. 构建 ORFS-Research

先安装系统依赖：

```bash
make orfs-deps
```

这个步骤调用固定 ORFS 提供的 `setup.sh`，需要 sudo 安装 apt 包。随后以普通用户编译：

```bash
make orfs-build
```

封装固定使用：

```text
./build_openroad.sh \
  --local \
  --no_init \
  --threads 6 \
  --openroad-args "-D LINK_TIME_OPTIMIZATION=OFF"
```

成功后必须同时存在：

```text
upstream/orfs-research/tools/install/OpenROAD/bin/openroad
upstream/orfs-research/tools/install/OpenROAD/bin/sta
upstream/orfs-research/tools/install/yosys/bin/yosys
```

## 6. Doctor 怎么读

```bash
make doctor
make doctor-json
```

Doctor 是只读的。它核对：WSL 内核、ext4 路径、CPU/内存/swap/磁盘、Git/Python/Make、所有递归 submodule SHA、Docker/Compose/daemon、容器 digest、ORFS 三个二进制和 GitHub DNS。

- `PASS`：本次实际观察到满足条件。
- `WARN`：不一定阻塞本地流程，但需要记录，例如 DNS 暂时失败。
- `FAIL`：不能进入真实流程。

Doctor 通过不代表 EDA 通过；它只证明“环境和版本足以开始跑”。

## 7. 常见错误

### `permission denied while trying to connect to the Docker daemon`

当前 shell 还没有刷新 docker 组。退出 WSL，PowerShell 执行 `wsl.exe --shutdown`，重新打开。不要改 socket 全局权限。

### `No space left on device`

先用 `df -h` 和 `docker system df` 判断是 ext4 空间还是容器层。不要直接执行 `docker system prune -a`；它会删除不可恢复的本地镜像缓存，应先确认目标。

### ORFS 编译 OOM

确认命令包含 `--threads 6` 和 `LINK_TIME_OPTIMIZATION=OFF`，`free -h` 中 swap 是 12 GiB。关闭 OpenROAD 的 LTO/IPO 是必要的：GCC 的 `-flto=auto` 会绕过上层 `-j6`，在最终链接阶段自行拉起 12 个 worker。配置日志应显示 `LTO/IPO is disabled`。不要同时跑 Croc P&R 和 ORFS 编译。

Croc 在第一次 GDS finishing 时会按锁定 manifest 下载较大的公开 SRAM/IO GDS。主流程只为该步骤把 `scripts/download-shims/curl` 放到 `PATH` 前端，增加 IPv4、断点续传、低速超时和 8 次重试；文件仍由 Croc 原版脚本执行 SHA-256 校验和原子替换，因此半文件不会进入 PDK。网络失败会使阶段明确失败，使用同一 `RUN_ID` 重跑会创建独立的 `attempt-N` 日志、证据和工件目录，不覆盖早先尝试。

### Git 子模块显示 `-SHA` 或 `+SHA`

`-` 表示未初始化，`+` 表示 checkout 偏离 gitlink。先运行 `make init-submodules`；不要用 `git reset --hard` 清理。
