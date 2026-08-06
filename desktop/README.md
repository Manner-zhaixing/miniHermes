# MiniHermes Desktop

仿照 **WorkBuddy** 打造的桌面端 AI 助手，底层内核使用 **minihermes**。

> 架构与 WorkBuddy 一致：**Electron 壳（React UI）+ 本地 Python 内核子进程（WebSocket/HTTP 双向通信）**

## 架构

```
┌─────────────────────────────────────────────────┐
│  Electron 主进程                                │
│   ├─ 窗口管理 / 生命周期                          │
│   └─ python-bridge: spawn 内核子进程, 读动态端口  │
├─────────────────────────────────────────────────┤
│  React 渲染进程 (仿 WorkBuddy 界面)              │
│   ├─ 聊天视图: 流式输出 / 思考块 / 工具卡片       │
│   ├─ 会话侧边栏: 新建 / 恢复 / 删除               │
│   ├─ 审批弹窗 / 澄清弹窗                          │
│   ├─ 设置页: 模型配置 / 用户记忆 / 系统信息        │
│   └─ 技能管理页                                  │
└──────────────┬──────────────────────────────────┘
               │ WebSocket(实时) + HTTP(REST)
┌──────────────▼──────────────────────────────────┐
│  Python 子进程 (backend/server.py, FastAPI)      │
│   ├─ GuiRenderer: 内核 StreamRenderer 接口实现    │
│   ├─ clarify/approval 回调: WS 双向阻塞等待       │
│   └─ 会话 / 配置 / 记忆 / 技能 HTTP API          │
└──────────────┬──────────────────────────────────┘
               │ 直接 import（无 IPC 序列化）
┌──────────────▼──────────────────────────────────┐
│  minihermes 内核                                 │
│   Agent.run_conversation · Provider · SessionDB  │
│   ApprovalEngine · 技能系统 · 记忆 · 上下文压缩    │
└─────────────────────────────────────────────────┘
```

## 快速开始

```bash
# 1. 安装 Python 后端依赖（内核 venv）
cd ../   # minihermes 项目根
uv pip install --python .venv/bin/python -r desktop/backend/requirements.txt

# 2. 安装前端依赖
cd desktop
npm install

# 3. 启动（自动拉起 Python 内核子进程）
npm run dev
```

> 首次运行前需配置模型（`~/.minihermes/config.yaml`，或直接打开应用 → 设置 → 模型配置）。

## 功能

- 💬 **聊天对话**：流式输出、Markdown 渲染、思考过程折叠展示、打断/停止
- 🔧 **工具调用可视化**：工具卡片实时展示执行状态（执行中/完成/失败），可展开查看参数与结果
- ⚠️ **安全审批**：危险操作弹窗确认（允许一次 / 本次会话允许 / 拒绝），复用内核 ApprovalEngine
- ❓ **澄清交互**：Agent 提问时弹窗选择/输入
- 📚 **会话管理**：新建、恢复历史会话（SQLite 持久化）、自动/手动标题、删除
- ⚙️ **设置**：模型名称 / Base URL / API Key / 迭代次数、用户记忆（USER.md / MEMORY.md）在线编辑
- 🧩 **技能管理**：浏览内核技能、查看 SKILL.md 详情与依赖
- 🧠 复用内核全部能力：上下文压缩、跨会话记忆、子 Agent 委派、规划模式

## 打包与发布

### 一次性配置（只需做一次）

**1. 告诉应用去哪检查更新**（已配置为 `Manner-zhaixing/miniHermes`，换仓库时改这两处）：

- `electron/main.js` 第 14 行：`const GITHUB_REPO = process.env.MH_GITHUB_REPO || 'Manner-zhaixing/miniHermes';`
  → 换仓库时改成 `'你的用户名/仓库名'`；不想改代码的话，每次打包前设置环境变量 `MH_GITHUB_REPO=你的用户名/仓库名` 也行
- `electron-builder.yml` 第 40-43 行：`publish.owner / publish.repo` 同样改成你的仓库

**2. （仅发布到 GitHub 时需要）登录 GitHub CLI：**

```bash
gh auth login
```

### 本地打包 DMG（macOS）

```bash
cd desktop

# 一条命令搞定：前端 build + Python 后端 PyInstaller + electron-builder 出 DMG
npm run dist:mac

# 产物在 release/ 下：
#   MiniHermes Desktop-0.1.0-arm64.dmg   ← 安装包（双击安装）
#   MiniHermes Desktop-0.1.0-arm64.zip   ← 备用分发格式
```

> - 首次运行 electron-builder 会自动下载打包工具（已配置 npmmirror 镜像，国内可达）
> - 无开发者证书时使用 ad-hoc 签名（`identity: null`），**首次打开 dmg 里的 app 需右键 → 打开**
> - 想快速验证产物结构而不出 dmg：`npm run dist:dir`（产出 `release/mac-arm64/MiniHermes Desktop.app`）
> - **架构说明**：`--mac` 默认打当前机器架构（Apple Silicon → arm64）。要出 Intel 版：`npm run dist:mac -- --x64`（需要本机装了对应的 Rosetta 工具链，一般没必要）

### 发布到 GitHub Releases（应用内"检查更新"的数据源）

```bash
cd desktop

# 1. 打 tag（版本号与 package.json 的 version 一致，应用按此比较新旧）
git tag v0.1.0 && git push origin v0.1.0

# 2. 构建 DMG 并自动上传到 GitHub Releases
npm run publish        # 等价于 dist:mac 后 electron-builder --publish always
```

发布后，其他用户安装的旧版本在「设置 → 系统信息 → 应用更新」点"检查更新"，
就能发现新版本 → 下载 `.dmg` → 按 macOS 标准流程安装。

### 常见问题

| 问题 | 原因 / 解决 |
| --- | --- |
| 打开 app 提示"已损坏/无法验证开发者" | ad-hoc 签名无公证，首次 **右键 → 打开**；或 `xattr -cr "/Applications/MiniHermes Desktop.app"` |
| 检查更新报"未配置 GitHub 仓库地址" | `main.js` 的 `GITHUB_REPO` 还是 `OWNER/REPO`，按上面第 1 步配置 |
| 检查更新一直"无可用更新" | Release tag 版本 ≤ 本地版本；确认 Release 附件里有 `.dmg` |
| 打包时下载慢/失败 | 已内置镜像；网络差时重试或手动下载到 `~/Library/Caches/electron-builder/` |

### 应用内更新机制

- **检查**：`GET api.github.com/repos/{owner}/{repo}/releases/latest`，对比 tag 版本与本地版本
- **下载**：下载 Release 里的 `.dmg` 到系统下载目录
- **安装**：打开 dmg 引导安装（macOS 标准流程）
- 版本比较：语义化版本（`v0.1.0` → `0.1.0`）

## 开发说明

| 目录 | 职责 |
| --- | --- |
| `electron/` | 主进程：窗口、Python 子进程 spawn 与生命周期 |
| `src/` | React 前端（Vite 构建） |
| `backend/` | FastAPI 服务：内核适配层（GuiRenderer / 回调 / REST API） |

### 已知环境坑（macOS）

- **`ELECTRON_RUN_AS_NODE`**：部分受限/代理环境会注入此变量，导致 Electron 以纯 Node 模式运行（`require('electron')` 返回 undefined）。`dev` / `start` 脚本已用 `env -u ELECTRON_RUN_AS_NODE` 显式清除。
- **无 GPU 环境**：Electron 启动可能因 GPU 初始化失败崩溃，main.js 已调用 `app.disableHardwareAcceleration()`，dev 脚本附加 `--disable-gpu --no-sandbox`。
- **Electron 二进制下载慢**：设置镜像 `export ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/` 后重装 `npm i -D electron`。

### WS 协议（前后端通信）

后端 → 前端：`thinking` / `delta` / `tool_start` / `tool_result` / `turn_start` / `turn_end` / `clarify_request` / `approval_request` / `sessions` / `session_messages` / `session_created` / `error`

前端 → 后端：`send_message` / `interrupt` / `new_session` / `resume_session` / `clarify_answer` / `approval_answer` / `refresh_sessions`

### 纯浏览器调试（不启动 Electron）

```bash
# 终端 1：手动启动后端
cd .. && .venv/bin/python desktop/backend/server.py   # 输出端口
# 终端 2：本地存储里覆盖后端地址后启动 Vite
localStorage.setItem('mh_backend_url', 'http://127.0.0.1:<port>')
npm run dev -- --host
```
