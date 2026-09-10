<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="HYDRA-UMC-DEV-SERVER 横幅" width="100%">
</p>

# 🖥️ HYDRA-UMC-DEV-SERVER

<p align="center"><a href="README.md">🇺🇸 English</a> | <a href="README_spa.md">🇪🇸 Español</a> | <a href="README_fra.md">🇫🇷 Français</a> | <a href="README_ita.md">🇮🇹 Italiano</a> | <a href="README_deu.md">🇩🇪 Deutsch</a> | 🇨🇳 <b>简体中文</b> | <a href="README_jpn.md">🇯🇵 日本語</a></p>

### 🏗️ 面向整个生态系统的可复现开发服务器

<p align="center">
  <img src="https://img.shields.io/badge/许可证-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/语言-Python%203.11%2B-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/核心-仅标准库-brightgreen.svg" alt="仅标准库核心">
  <img src="https://img.shields.io/badge/交付-DS08%2F10-367BF5.svg" alt="DS08/10">
</p>

> **状态：v0.0.8，脚手架阶段 - 十次交付中的 DS08（契约、边界与可验证的骨架）。**
> 一套真实、经过测试的配置模式(`config validate`)，其默认策略**不向任何任务授予部署权限**；
> 以及只读的清单发现功能(`inventory scan`)，可找到本生态系统自身的
> `hydra-umc.project.json` 文件——包括本仓库自己的那份。
> DS02 新增一个经校验的远程站点配置(`station validate`)、一项**只读**的主机预检——
> 它仅报告某台主机是否就绪(`station preflight`，不改变任何东西)，
> 以及一份**空跑**的置备计划(`station plan`，从不执行任何步骤)。DS03 新增**保守迁移**（`migrate inventory` / `migrate plan`）：它对源 checkout 中的每个文件计算哈希并分类，并将每一类——干净、本地已修改、未跟踪、私有——规划到它**各自独立的目标**，若某个私有文件会落到任何可共享的位置则拒绝。它不复制任何内容，也从不触碰源。以上都只读取与描述。**DS04 新增受限执行器**（`task validate` / `task run`）：它在**按任务隔离的工作区**中运行**一个**白名单命令（`..`、绝对路径或指向工作区之外的 symlink 都会被拒绝；两个任务永不共享同一个），使用**已清理的环境**（不继承 `*_TOKEN` / `*_KEY` / `*_SECRET`），并在有界超时后**杀死整个进程组**。**DS05 新增一个持久的 SQLite 队列 + 执行日志**（`queue …`），可在重启后存活：重复的 `enqueue` 绝不是第二个作业；崩溃 worker 的租约会过期，`reconcile` 将任务退回 `queued`；来自不再持有租约的 worker 的结果会被**拒绝，而非标记为已完成**；自入队以来发生变化的基线**即使退出码为 0 也会阻止晋级**。它仍然不部署任何内容。
> DS06 新增位于安全契约之后的确定性假 AI 提供方；真实提供方由用户决定。
> 完整、真实的命令界面见 [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)。

---

## 1. 🛠️ 技术概览

HYDRA-UMC-DEV-SERVER 是 HYDRA-UMC/URTC 生态系统的开发基础设施：一台可复现的主机
（目标平台：从 NVMe 启动的 Raspberry Pi 5 或 Compute Module 5，8GB），
将托管本生态系统自身的源代码，并运行受限、受策略约束的编程/构建/测试任务——
无论是人还是 AI 助手皆是如此。它**不是**要训练的新 AI，**不是**替代操作系统，
并且它绝不会自行判定某台机器可以安全修改。

DS01 带来了两个真实、各自独立有用的部分：

1. **配置模式**(`config validate`) - 三份 JSON 文档
   (`HostProfile`、`ToolchainPolicy`、`TaskPolicy`)，每一份都有真实的校验，
   以及针对每种被拒绝形态的真实反例测试。从第一天起最重要的不变量：
   `TaskPolicy.allow_deploy` 默认为 `False`，只有文档显式设置了字面
   JSON 布尔值 `true`，才可能生成授予该权限的策略。
2. **清单发现**(`inventory scan`) - 与 HYDRA-UMC-OPS-AGENT 自身 edge 角色
   已使用的、用于查找和校验 `hydra-umc.project.json` 的同一套真实、经测试的模式，
   在此复用而非重写。

DS02 又新增三项，全部位于 `station` 子命令之下，且仍然是"只校验与描述，绝不执行"：

3. **远程站点配置**(`station validate`) - 一份 JSON 文档
   (`RemoteIdentity` + `RemoteAccess` + 所需工具链)，采用同样会累积错误的校验。
   其第一天的不变量：远程编辑端点绑定 loopback/私有地址，可路由地址一律被拒绝，
   除非文档将字面布尔值 `allow_public_bind: true` 显式设为真；身份是专用的系统账户，
   绝不是 `root` 或登录用户。
4. **主机预检**(`station preflight`) - 读取一份配置，并通过一个可注入的检查器接口
   报告*本*主机是否真的已准备好成为该站点（Python 版本、可用磁盘、工作区可写、
   `PATH` 中的工具、端口空闲、身份为真实的系统账户）。它绝不改变主机。
5. **空跑置备计划**(`station plan`) - 呈现真实安装程序*将会*执行的内容
   （每一步的 argv 以数据形式记录）以及完整的 systemd unit 文本，
   并且在预检失败时拒绝构建计划。不执行任何内容。

DS03 新增保守迁移，同样遵循"只读取与描述，绝不执行"——它不复制任何内容，也从不触碰源：

6. **迁移清单 + 计划**（`migrate inventory` / `migrate plan`）——遍历一个源 checkout（只包含 git 认为属于项目的文件——本地 `.venv` 或构建输出在 gitignore 中，永远看不到），对每个文件计算 SHA-256 并分类：`tracked-clean`、`tracked-modified`、`untracked`、`private`（一个可扩展的 `PrivacyPolicy`：私有文档文件夹、`.env*`、`*.pem`、`id_ed25519*` ……）。已提交但从未推送的提交单独记录。`migrate plan` 将每一类映射到其**各自**的目标——四个可证明彼此分离的根（`MigrationDestinations.from_dict` 拒绝相等或嵌套的根），打包未推送的提交，输出完整的哈希清单，若某个私有文件会落到可共享的根之下则打印 `REFUSED`。

DS04 是第一个执行子进程的交付——并且仍然受到严格约束：

7. **任务配方 + 工作区执行器**（`task validate` / `task run`）——`TaskRecipe` 固定一个 `revision`（分支名会被拒绝）和一个白名单 `command`（`argv[0]` 必须在策略的 `allowed_commands` 中，否则该次运行为 `rejected` 且不启动任何东西）。`task run` 创建 `<base>/<task_id>/`——若已存在则拒绝，因此**两个任务永不共享一个工作区**——在其中以**已清理的环境**运行该命令（只有 `PATH` / `HOME` / `LANG` / `TZ`；绝不继承 `GITHUB_TOKEN`、`AWS_SECRET_ACCESS_KEY`、`ANTHROPIC_API_KEY`、`SSH_AUTH_SOCK`），受 `timeout_seconds` 约束，超时或取消时**杀死整个进程组**——由一个启动孙进程并确认两者都消失的真实测试证明。`input_paths` 中的 `..`、绝对路径或指向工作区之外的 symlink 都会被拒绝。它不部署任何内容。

DS05 新增持久性——一个任务队列及其执行日志，可在进程重启后存活。它记录，不执行：

8. **持久队列 + 执行日志**（`queue enqueue` / `status` / `reconcile` / `journal`）——一个 SQLite 存储（WAL，租约用立即事务）。`enqueue` 是幂等的——用相同 `task_id` 的第二次调用返回 `created=False`，**绝不是第二个作业**。`lease(worker, ttl)` 认领最旧的 `queued` 条目；`reconcile()` 将过期租约退回 `queued`（每次启动都安全）。来自不再持有租约的 worker 的 `record_result` 会被**拒绝，而非接受为已完成**——中断绝不会变成虚假的成功。若记录结果时观察到的基线指纹与 `enqueue` 时记录的不同，则该结果存为 `failed` / 不可晋级，**即使退出码为 0**。日志的 `completed` 事件始终携带 `revision` + `recipe_fingerprint`；日志只保留截断的尾部，`prune_journal` 限制行数，因此磁盘保持有界。

```
$ hydra-umc-dev-server config validate configs/task-policy.example.json --kind task-policy
VALID: configs/task-policy.example.json (task-policy)
{
  "allow_deploy": false,
  "max_concurrent_tasks": 2,
  "allowed_commands": ["pytest", "build.sh", "build-test.sh"]
}

$ hydra-umc-dev-server inventory scan --root ..
{
  "root": "..",
  "projects": [
    {"name": "HYDRA-UMC-DEV-SERVER", "version": "0.0.8", "maturity": "scaffolding", "manifest_path": "../HYDRA-UMC-DEV-SERVER/hydra-umc.project.json"},
    ...
  ],
  "issues": []
}
```

除了 `run.sh` 运行的演示外，本交付没有无参数的默认调用，也没有图形界面 -
完整、真实的命令界面见 [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)。

## 2. 🧱 架构与设计决策

- **默认情况下没有任何任务拥有部署权限。** 这是 DS01 字面上的验收标准，
  由 `TaskPolicy` 数据类自身的默认值强制执行——而不仅仅是文字上的声明——
  并针对文档可能试图夹带该权限的每一种方式（字段缺失、拼写错误、非布尔值）
  都有专门的测试覆盖。
- **收集器报告真实、诚实的失败——从不猜测。** `scan_project_manifests()`
  对于存在但损坏的清单返回 `ManifestScanIssue`，而不是悄悄丢弃，
  这是本生态系统已经确立的模式（见 HYDRA-UMC-OPS-AGENT 自身的
  `inventory.py`）——在此复用，而非重新发明。
- **状态归属与项目间关系不由本仓库重新决定。**
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 与
  [docs/OPS_INTEGRATION.md](docs/OPS_INTEGRATION.md) 记录了本仓库
  自身的状态归属表，以及其将 17 项跨项目关系划分为
  必要/可选/仅开发用途的分组。
- **本次交付仅使用标准库。** `config validate` 与 `inventory scan`
  不需要任何第三方依赖——只有当后续交付自身的代码真正需要时才会添加依赖
  （DS05 的持久队列驱动、DS06 的 AI 提供方 SDK），绝不投机性地预先添加。
- **本次交付只做校验与发现——尚未运行任何东西。** 本仓库中目前
  没有工作区、没有任务执行、没有队列，也没有任何网络调用。

## 📂 目录结构

```
HYDRA-UMC-DEV-SERVER/
├── src/hydra_umc_dev_server/
│   ├── config.py          # HostProfile/ToolchainPolicy/TaskPolicy 的模式与校验（DS01）
│   ├── inventory.py       # 真实的、只读的 hydra-umc.project.json 发现（DS01）
│   ├── remote_station.py  # RemoteStationProfile：身份 + 远程访问 + 工具（DS02）
│   ├── preflight.py       # 通过可注入的检查器对主机进行只读检查（DS02）
│   ├── provision.py       # 空跑置备计划 + unit 文本，从不执行（DS02）
│   ├── migration.py       # 保守迁移的清单 + 分离目标计划，不复制任何内容（DS03）
│   ├── workspace.py       # 按任务隔离的工作区；拒绝 ../、绝对路径、指向工作区之外的 symlink（DS04）
│   ├── recipe.py          # TaskRecipe：固定的 revision + 白名单命令（DS04）
│   ├── runner.py          # 受限执行器：已清理的环境、超时、杀死整个进程组（DS04）
│   ├── durable_queue.py   # SQLite 持久队列 + 租约 + append-only 执行日志，可在重启后存活（DS05）
│   ├── ai_provider.py     # 可替换 AI 提供方 seam + 安全契约；仅确定性假提供方（DS06）
│   ├── incident_transport.py  # HMAC 签名的事件消息 + verify + 完整的往返会话（DS07）
│   ├── repair_cycle.py    # 带门禁与回滚的 repro->...->verify 周期 + 候选门禁（DS08）
│   └── cli.py             # config / inventory / station / migrate / task / queue / provider / incident / repair 子命令入口
├── configs/
│   ├── host-profile.example.json
│   ├── toolchains.example.json
│   ├── task-policy.example.json      # allow_deploy: false，以此形式发布并测试
│   ├── remote-station.example.json   # 绑定 127.0.0.1，以此形式发布并测试
│   ├── migration-destinations.example.json   # 四个可证明彼此分离的根
│   ├── task-recipe.example.json          # 固定的 revision + 白名单命令
│   └── ai-provider.example.json          # kind: fake，超时 + 调用/令牌/成本预算
├── tests/                # 上述每个模块的真实测试，包括所发布的示例配置
├── docs/
│   ├── CLI_REFERENCE.md    # 每个子命令、其参数与退出码契约
│   ├── CONFIG_SCHEMA.md    # 三份配置文档的真实 JSON 结构
│   ├── REMOTE_STATION.md   # DS02 远程站点配置、预检与空跑计划
│   ├── MIGRATION_FROM_PC.md  # DS03 保守迁移的清单、类别与计划
│   ├── WORKSPACE_AND_RUNNER.md  # DS04 的配方、隔离工作区与受限执行器
│   ├── DURABLE_QUEUE.md      # DS05 的持久队列、租约与执行日志
│   ├── AI_PROVIDER.md        # DS06 的提供方 seam 与安全契约（仅假）
│   ├── INCIDENT_TRANSPORT.md # DS07 的签名消息、校验与往返会话
│   ├── REPAIR_CYCLE.md       # DS08 的带门禁修复周期、其控制与回滚
│   ├── ARCHITECTURE.md     # 目的、工作模式、初始范围、磁盘布局
│   └── OPS_INTEGRATION.md  # 17 项关系图谱 + 归属表
├── images/                # 媒体与应用图标
├── tools/
│   ├── build_test.py      # 非版本变更的构建/编译检查
│   └── ci_validate.py     # CI 使用的清单/CHANGELOG/文档校验
├── build.sh / build.bat   # venv + 可编辑安装 + 检查 + 测试
├── build-test.sh / .bat   # 仅非变更式构建校验
├── run.sh / run.bat       # 真实的 inventory scan + config validate 演示（无参数时），或转发一条真实的 CLI 命令
├── bump_version.py        # 全生态系统"里程表式"版本递增（pyproject.toml + __init__.py）
└── bump_manifest_version.py # 将 hydra-umc.project.json 的版本与原生版本同步（--sync）
```

## ⚙️ 构建与运行指南

```bash
chmod +x build.sh   # 一次性
./build.sh          # 创建 .venv、pip install -e ".[dev]"、检查 + 测试
./run.sh                                  # 真实演示：对此 GitHub 工作区执行
                                           # inventory scan，然后 config validate
./run.sh inventory scan --root DIR
./run.sh config validate configs/task-policy.example.json --kind task-policy
```

在 Windows 上：`build.bat`，然后 `run.bat`（无参数时同样的演示）/
`run.bat inventory scan ...` / `run.bat config validate ...`。
`build-test.sh`/`.bat` 执行与项目自身 CI 工作流相同的非变更式 Python
语法检查，不会改动项目版本或 CHANGELOG——它**不会**运行测试套件本身；
运行 `./build.sh`/`build.bat`（或直接运行 `pytest tests/`）以执行完整的本地测试套件。

**故障排查**

- `config validate` 以退出码 `1` 返回 `INVALID: ...`：请阅读该消息——
  它会列出所有失败的字段，而不仅仅是第一个。参见
  [docs/CONFIG_SCHEMA.md](docs/CONFIG_SCHEMA.md) 查看确切的预期结构。
- `inventory scan` 报告了一个你以为是干净的目录中的问题：该目录中存在一个
  `hydra-umc.project.json`，但它不可读、格式错误，或缺少必需字段——
  完全没有清单的目录从不会被报告为问题。

## 🚀 路线图

本版本交付 DS01 至 DS08。按交付顺序，剩余部分为：

- **DS02 - 可复现的远程站点。** ✅ 已交付：一个经校验的远程站点配置、
  一项只读的主机预检，以及一份空跑的置备计划（`station` 子命令）。
  不改变任何主机，也不执行任何步骤。
- **DS03 - 保守迁移。** ✅ 已交付：对源 checkout 中的每个文件计算哈希并分类，并将每一类（干净 / 已修改 / 未跟踪 / 私有）规划到其各自独立的目标，并为未推送的提交生成一个 bundle（`migrate` 子命令）。它不复制任何内容，也从不触碰源。执行一份已批准的计划属于后续交付。
- **DS04 - 工作区与受限执行器。** ✅ 已交付：按任务隔离的工作区（两个任务永不冲突；`..`、绝对路径和指向工作区之外的 symlink 被拒绝），只允许一个白名单命令，一个已清理的环境，以及一个杀死整个进程组的超时（`task` 子命令）。它执行一个子进程，但不部署任何内容。
- **DS05 - 持久队列与可追溯结果。** ✅ 已交付：一个带租约的 SQLite 队列和一份 append-only 执行日志，可在重启后存活；重复入队绝不是第二个作业，中断绝不是虚假成功，变化的基线会阻止晋级（`queue` 子命令）。
- **DS06 - 可替换的 AI 提供方。** ✅ 已交付（假的那一半）：一个位于安全契约之后的确定性假提供方——超时 / 格式错误 / 配额都变成有界结果，预算会停止该步骤，建议是不授予任何权限、不部署任何内容的惰性数据（`provider suggest`）。真实提供方由用户决定。
- **DS07 - 与 HYDRA-UMC-OPS-AGENT 协调的事件处理。** ✅ 已交付：一个 HMAC 认证的事件传输，带有重放 / 冒充 / 过载 / 版本检查，以及一个完整的 提交 → 诊断 → 部署后验证 往返流程，在网络中断后会进行对账（`incident verify`）。
- **DS08 - 第一个完全受控的修复周期。** ✅ 已交付：一个带门禁的状态机 repro->事件->补丁->回归->build-test->批准->隔离安装->验证，它会阻止被篡改或错误定向的候选，并在安装后检查失败时回滚（`repair check-candidate`）。
- **DS09-DS10** - 稳定的运行/恢复，以及带有诚实成熟度评估的交付包。

DS09-DS10 目前均尚未存在于本仓库中——每次交付明确包含与排除的内容，
见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 🔗 相关项目

本项目是同一作者（JuanenRac / Electro Hobby 3D）的 HYDRA-UMC 机器人生态系统的一部分。值得了解，因为某个请求实际上可能与其中之一有关，而非本仓库。

**直接相关**
- **[HYDRA-UMC-OPS-AGENT](https://github.com/JuanenRac/HYDRA-UMC-OPS-AGENT)** — 拥有维护事件的生命周期（证据、诊断、人工批准的变更、金丝雀部署、验证）；DEV-SERVER 与它协调而非取代它，且从不批准自己的任务。
- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** — 一旦该契约存在，DEV-SERVER 与生态系统其余部分之间的每一次任务/结果交换都将据此进行校验的共享 JSON Schema 契约。
- **[HYDRA-UMC-UPDATER](https://github.com/JuanenRac/HYDRA-UMC-UPDATER)** — 由 DEV-SERVER 构建、经 OPS-AGENT 批准的候选版本的真实消费者；向节点的交付始终经过 UPDATER 自身的"先验证后原子化"路径，绝不是从执行器直接复制。
- **[HYDRA-UMC-OS-REBUILDER](https://github.com/JuanenRac/HYDRA-UMC-OS-REBUILDER)** — 另一个"Ecosystem Operations"同族项目：构建全新的 CM5 镜像，而非承载开发工作。

**同样属于本生态系统**

*核心硬件与平台*
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** — 机械臂的物理主板：CM5 主机 + 双核 STM32H745，通过 CAN-OTA/SPI-OTA 编排最多 8 条工具臂。
- **[HYDRA-UMC-OS](https://github.com/JuanenRac/HYDRA-UMC-OS)** — 面向 CM5 的可复现 Raspberry Pi OS 产品层：只读代理、经校验的配置/配置文件、WiFi 首次接触配置。

*核心后端与客户端*
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — 每个控制客户端实际通信的真实无头后端（REST/WebSocket）。
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** — 具有实时多机器人 3D 可视化的网页控制面板。
- **[HYDRA-UMC-SUITE](https://github.com/JuanenRac/HYDRA-UMC-SUITE)** — 可同时管理多台服务器的桌面（PySide6）群控中心。
- **[HYDRA-UMC-ANDROID-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-ANDROID-CONTROL)** — 原生 Android 控制应用，支持生物识别登录及配对的 Wear OS 伴侣应用。
- **[HYDRA-UMC-IOS-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-IOS-CONTROL)** — iOS/iPadOS 控制应用（Flutter），具有实时 WebSocket 同步。
- **[HYDRA-UMC-DSI](https://github.com/JuanenRac/HYDRA-UMC-DSI)** — 为板载 7 英寸 DSI 触摸屏打造的原生触控界面，直接嵌入 CM5 本身。
- **[HYDRA-UMC-EDITOR-URDF](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-URDF)** — 桌面图形化 URDF 创建/编辑器，将完成的模型推送到 STUDIO 自己的目录中。
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** — 通过真实的 VDA 5050 MQTT 发布者为 AGV/AMR 车队提供协调边界。
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** — 具有真实 GRBL 状态/控制字节访问的高层 CNC 单元协调器。
- **[HYDRA-UMC-BRIDGE-DROIDS](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-DROIDS)** — 为足式/仿人机器人提供协调边界，带有真实的 Boston Dynamics Spot 命令发送器。
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** — 读取 3 个真实钥匙/机柜/联锁 GPIO 保护装置的激光单元安全协调器。
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** — 用于 OpenPnP 贴片作业的安全高层板流协调器。
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** — 面向 Moonraker/Klipper 3D 打印机的安全协调边界，具有真实受控的作业命令。
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** — 具有真实、惰性导入的 rclpy ROS 2 传输的安全协调器。
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** — 为配备摄像头的无人机提供协调边界，带有真实的 MAVLink 命令发送器。

*URTC 工具平台*
- **[URTC](https://github.com/JuanenRac/URTC)** — 通用机器人工具控制器（Universal Robot Tool Controller）实体电路板的固件，通过 CAN 总线支持 25+ 种工具配置文件。
- **[URTC-FLASHER](https://github.com/JuanenRac/URTC-FLASHER)** — 用于 URTC 板卡的桌面图形烧录工具，支持 CAN-OTA 以及全芯片 SWD/JTAG。
- **[URTC-TESTER](https://github.com/JuanenRac/URTC-TESTER)** — 用于 URTC 板卡的桌面实时 CAN 总线诊断工具，每个工具配置文件一个面板。
- **[URTC-WEB-STUDIO](https://github.com/JuanenRac/URTC-WEB-STUDIO)** — 通过 Web Serial API 实现的浏览器版 URTC-TESTER 替代方案，无需本地安装。

*视觉 AI 节点（Hailo-8）*
- **[HYDRA-UMC-VISION-NODE](https://github.com/JuanenRac/HYDRA-UMC-VISION-NODE)** — Hailo-8 视觉流水线的集成中枢，具有真实的分阶段硬件就绪检查。
- **[HYDRA-UMC-DETECTION-HEF](https://github.com/JuanenRac/HYDRA-UMC-DETECTION-HEF)** — 具有 Hailo 架构/校验和安全加载验证的真实已编译模型注册表。
- **[HYDRA-UMC-VISION-STREAMER](https://github.com/JuanenRac/HYDRA-UMC-VISION-STREAMER)** — 真实的 GStreamer 流水线 + MediaMTX 配置生成器，具有真实的 HailoRT 集成边界。
- **[HYDRA-UMC-VISUAL-SERVOING-API](https://github.com/JuanenRac/HYDRA-UMC-VISUAL-SERVOING-API)** — 真实的基于位置的视觉伺服校正律，依据上游区域状态设有安全联锁。
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** — 真实的区域入侵检查与 E-STOP 请求，强制要求校准的新鲜度。

*认知 AI 节点（Hailo-10）*
- **[HYDRA-UMC-COGNITIVE-NODE](https://github.com/JuanenRac/HYDRA-UMC-COGNITIVE-NODE)** — Hailo-10 认知流水线（LLM/VLA/语音编排）的集成中枢。
- **[HYDRA-UMC-VLA-ENGINE](https://github.com/JuanenRac/HYDRA-UMC-VLA-ENGINE)** — 为视觉-语言-动作模型提供真实的动作令牌编解码与轨迹生成。
- **[HYDRA-UMC-VOICE-UI](https://github.com/JuanenRac/HYDRA-UMC-VOICE-UI)** — 真实的语音前端（VAD + 意图解析器），带有受限、需确认的 Watch 中继。
- **[HYDRA-UMC-SEMANTIC-PLANNER](https://github.com/JuanenRac/HYDRA-UMC-SEMANTIC-PLANNER)** — 基于规则的真实任务分解与针对 MCU 错误码的语义化错误恢复。
- **[HYDRA-UMC-DOCS-QA](https://github.com/JuanenRac/HYDRA-UMC-DOCS-QA)** — 仅使用标准库、对本生态系统自身 Markdown 文档进行真实 TF-IDF 检索。

*编排与集群*
- **[HYDRA-UMC-ORCHESTRATOR](https://github.com/JuanenRac/HYDRA-UMC-ORCHESTRATOR)** — 具有真实 gRPC/Protobuf 健康报告契约与任务状态机的集成中枢。
- **[HYDRA-UMC-JOB-DISPATCHER](https://github.com/JuanenRac/HYDRA-UMC-JOB-DISPATCHER)** — 通过真实 HTTP API 实现的具有去重功能的真实优先级作业队列。
- **[HYDRA-UMC-NODE-HEALING](https://github.com/JuanenRac/HYDRA-UMC-NODE-HEALING)** — 基于 gRPC 的真实车队健康监视器，具有自身的重试/退避及身份不匹配检测。
- **[HYDRA-UMC-PATH-PLANNER-3D](https://github.com/JuanenRac/HYDRA-UMC-PATH-PLANNER-3D)** — 基于 RRT 的真实 3D 路径规划器，具有真实的障碍物/工作空间碰撞校验。
- **[HYDRA-UMC-SWARM-SYNC](https://github.com/JuanenRac/HYDRA-UMC-SWARM-SYNC)** — 真实的 CRDT LWW-Element-Map 状态同步，针对多单元收敛进行了属性测试。

*数字孪生与仿真*
- **[HYDRA-UMC-TWIN](https://github.com/JuanenRac/HYDRA-UMC-TWIN)** — 数字孪生引擎的集成中枢，具有真实的版本兼容性同步契约。
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** — 真实的硬件在环安全联锁，在仿真与真实硬件之间路由命令。
- **[HYDRA-UMC-PHYSICS-REPLICA](https://github.com/JuanenRac/HYDRA-UMC-PHYSICS-REPLICA)** — 基于真实 URDF 子集的真实正向运动学与关节限位校验。
- **[HYDRA-UMC-SYNTHETIC-DATA-GEN](https://github.com/JuanenRac/HYDRA-UMC-SYNTHETIC-DATA-GEN)** — 真实的程序化 2D 场景生成器，支持 YOLO/COCO 标注导出。

*数据与分析*
- **[HYDRA-UMC-DATALAKE](https://github.com/JuanenRac/HYDRA-UMC-DATALAKE)** — 基于 sqlite3 的真实时间序列存储，具有真实的写入/查询 HTTP API。
- **[HYDRA-UMC-ANOMALY-DETECTOR](https://github.com/JuanenRac/HYDRA-UMC-ANOMALY-DETECTOR)** — 真实的 FFT + 统计基线异常检测器，带有漂移监测。
- **[HYDRA-UMC-PRODUCTION-REPORTS](https://github.com/JuanenRac/HYDRA-UMC-PRODUCTION-REPORTS)** — 基于 DATALAKE 历史数据的真实 OEE/可用性计算，支持可复现的 CSV 导出。
- **[HYDRA-UMC-TELEMETRY-COLLECTOR](https://github.com/JuanenRac/HYDRA-UMC-TELEMETRY-COLLECTOR)** — 向 DATALAKE 传输的真实 CAN/WebSocket 采集流水线，具有序列去重功能。

*工业网关*
- **[HYDRA-UMC-GATEWAY-INDUSTRIAL](https://github.com/JuanenRac/HYDRA-UMC-GATEWAY-INDUSTRIAL)** — 中继到工业协议的集成中枢，具有真实的命令白名单/背压层。
- **[HYDRA-UMC-OPCUA-SERVER](https://github.com/JuanenRac/HYDRA-UMC-OPCUA-SERVER)** — 真实的 OPC-UA 地址空间，通过真实的二进制协议客户端会话验证。
- **[HYDRA-UMC-MQTT-BROKER](https://github.com/JuanenRac/HYDRA-UMC-MQTT-BROKER)** — 真实的 MQTT 代理，支持可选的按客户端认证与主题 ACL。
- **[HYDRA-UMC-MTCONNECT-ADAPTER](https://github.com/JuanenRac/HYDRA-UMC-MTCONNECT-ADAPTER)** — 真实的 MTConnect `/probe` 与 `/current` XML 端点，具有降级模式输出。

*配套工具*
- **[HYDRA-UMC-DASHBOARD-AI](https://github.com/JuanenRac/HYDRA-UMC-DASHBOARD-AI)** — 基于 DATALAKE/ANOMALY-DETECTOR 的智能摘要与异常高亮面板，具有诚实的统计回退机制。
- **[HYDRA-UMC-TOOL-CLI](https://github.com/JuanenRac/HYDRA-UMC-TOOL-CLI)** — 具有真实、稳定退出码契约的车队 CLI，是 HYDRA-UMC-SERVER 自身 API 的真实在线客户端。
- **[HYDRA-UMC-WATCH](https://github.com/JuanenRac/HYDRA-UMC-WATCH)** — WearOS 伴侣应用，具有真实的触觉提醒与配对手机语音中继。
- **[HYDRA-UMC-CONNECTOR-HUB](https://github.com/JuanenRac/HYDRA-UMC-CONNECTOR-HUB)** — 外部适配器能力目录，设计上仅支持 GET。
- **[URTC-SMART-RACK](https://github.com/JuanenRac/URTC-SMART-RACK)** — 用于板卡安装机架的固件，具有真实的工具 ID 解码与 Smart Idle 预热逻辑。
- **[URTC-VISION-TOOL](https://github.com/JuanenRac/URTC-VISION-TOOL)** — 固件加上一个真实的 Python 视觉伴侣程序，用于热成像/RGB 检测工具头。

---

## 📚 文档与社区

- **[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)** — 每个子命令、其参数以及退出码契约。
- **[docs/CONFIG_SCHEMA.md](docs/CONFIG_SCHEMA.md)** — `HostProfile`/`ToolchainPolicy`/`TaskPolicy` 的真实 JSON 结构。
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — 目的、两种工作模式、初始范围与磁盘布局。
- **[docs/OPS_INTEGRATION.md](docs/OPS_INTEGRATION.md)** — 完整的 17 项关系图谱与状态归属表。
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — 提交 Pull Request 所需的技术栈与编码规范。
- **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)** — 本社区期望遵守的行为准则。
- **[SECURITY.md](SECURITY.md)** — 如何报告漏洞，以及本项目真实的安全关注重点。
- **[SUPPORT.md](SUPPORT.md)** — 在哪里提问与报告缺陷。

## 👤 作者
**JuanenRac**（Electro Hobby 3D）
📧 electrohobby3d@gmail.com
📺 [youtube.com/@electrohobby3d](https://youtube.com/@electrohobby3d)

## 📜 许可证

GPL-3.0（软件）/ CC BY-SA 4.0（文档）- 详见 [LICENSE.md](LICENSE.md)。
