# MiniHermes

MiniHermes 是一个基于 Python 的 AI 编程助手 CLI，支持DeepSeek，提供交互式终端界面，具备工具执行、记忆持久化和技能系统。

## 目录

- [安装与启动](#安装与启动)
- [基本使用](#基本使用)
- [斜杠命令](#斜杠命令)
- [工具系统](#工具系统)
- [子 Agent 委派](#子-agent-委派)
- [规划模式](#规划模式)
- [技能系统](#技能系统)
- [记忆系统](#记忆系统)
- [上下文引用](#上下文引用)
- [配置说明](#配置说明)
- [会话管理](#会话管理)
- [审批系统](#审批系统)
- [上下文压缩](#上下文压缩)
- [项目上下文文件](#项目上下文文件)

---

## 安装与启动

### 环境要求

- Python >= 3.11
- 推荐使用 [uv](https://docs.astral.sh/uv/) 管理依赖
- 支持 macOS / Linux / Windows

### 安装

```bash
# 克隆项目后安装依赖
uv sync

# 直接运行
python main.py

# 或构建 wheel 包安装
bash build_wheel.sh
pip install dist/minihermes-*.whl

# 安装后可通过 minihermes 命令全局启动
minihermes
```

### 首次启动

首次运行时，程序会自动进入**交互式配置向导**，引导你设置 API 密钥、API 基础 URL、模型名称等。

配置保存在 `~/.minihermes/config.yaml`，后续可通过 `/setup` 命令随时修改。

---

## 基本使用

启动后进入交互式终端界面，直接输入问题或指令即可与 AI 对话。

### 键盘操作

| 操作 | 快捷键/方式 |
|------|-------------|
| 发送消息 | `Enter` |
| 换行（多行输入） | `Shift+Enter` / `Cmd+Enter` |
| 中断 AI 回复 | `Ctrl+C` |
| 退出程序 | `/exit` / `/quit` / `Ctrl+D` |

### 界面说明

- **流式输出**：AI 回复逐 token 实时显示
- **工具调用**：以 `┊ 🔧 tool_name` 格式显示正在执行的工具
- **工具结果**：以 `┊ ✓ tool_name` 格式显示工具执行耗时
- **思考过程**：如果开启推理模式，以青铜色显示，包裹在 `┌─ Reasoning ─┐` 边框内
- **Diff 渲染**：`write_file` 操作后自动显示统一 diff 对比

---

## 斜杠命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示所有可用命令 |
| `/clear` | 清除当前对话历史，开始新会话 |
| `/compress` | 强制触发下一轮对话的上下文压缩 |
| `/plan [描述]` | 进入规划模式，AI 只读分析后生成执行计划 |
| `/init` | 扫描当前工作目录，生成 `minihermes.md` 项目上下文文件 |
| `/history` | 显示当前会话 ID、对话轮次和消息总数 |
| `/sessions` | 列出最近的会话记录（含标题和时间） |
| `/resume [id]` | 恢复到指定会话（自动跟随压缩链） |
| `/title <名称>` | 设置当前会话标题 |
| `/sysprompt` | 打印当前完整的系统提示词（调试用） |
| `/setup` | 运行时配置向导（修改 API 密钥、模型等） |
| `/exit` / `/quit` / `/q` | 退出程序 |
| `<技能名称>` | 加载并执行指定技能（如 `/code-review`） |

---

## 工具系统

MiniHermes 内置 15 个工具，AI 会根据任务自动选择和调用。工具遵循 OpenAI function calling 协议。

### 文件操作

| 工具 | 说明 |
|------|------|
| `read_file` | 读取文件内容，带行号，支持偏移量分段读取 |
| `write_file` | 写入或追加文件内容 |
| `list_dir` | 列出目录内容，支持显示隐藏文件 |

### Shell 执行

| 工具   | 说明                                                         |
|--------|--------------------------------------------------------------|
| `bash` | 执行 shell 命令，默认超时 30s，超时自动加倍重试（上限 120s） |

### 网络搜索

| 工具           | 说明                                       |
|----------------|--------------------------------------------|
| `web_search`   | Exa AI 搜索引擎，返回 LLM 提取的关键片段    |
| `web_extract`  | 抓取网页内容并转为纯文本                    |

### 代码执行

| 工具             | 说明                                                                   |
|------------------|------------------------------------------------------------------------|
| `execute_code`   | 云端沙箱执行代码，支持 Python / JavaScript / TypeScript / Java / R / Bash |

### 系统信息

| 工具 | 说明 |
|------|------|
| `process` | 列出系统进程（只读） |
| `session_search` | 全文搜索历史对话（SQLite FTS5） |

### 记忆与任务

| 工具 | 说明 |
|------|------|
| `memory` | 跨会话持久记忆管理（增/删/改/查） |
| `todo` | 当前会话的临时任务列表 |

### 其他工具

| 工具 | 说明 |
|------|------|
| `clarify` | 向用户提问获取澄清信息 |
| `generate_image` | 通过 Pollinations.ai 生成图片（免费，无需 API Key） |
| `delegate_task` | 创建子 Agent 处理独立子任务 |
| `skill_view` | 加载技能指令 |
| `skill_manage` | 创建/更新/归档技能 |

---

## 子 Agent 委派

AI 可以通过 `delegate_task` 工具创建**子 Agent** 来独立处理复杂子任务。

- **独立预算**：每个子 Agent 默认 50 次迭代
- **自动批准**：子 Agent 的工具调用无需用户审批
- **无持久化**：子 Agent 的对话不存入数据库
- **工具限制**：子 Agent 不能再次委派或向用户提问

---

## 规划模式

使用 `/plan` 命令进入规划模式，让 AI 先分析再执行。

1. **分析阶段**：AI 以只读模式运行（仅允许读取类工具），分析代码库并生成执行计划
2. **审批阶段**：计划以格式化面板呈现，用户选择执行或取消
3. **执行阶段**：批准后，计划作为输入传给主 Agent 执行

所有计划保存在 `.minihermes/plans/`，方便后续查阅。

---

## 技能系统

技能是预定义的 Markdown 指令模板，存储在目录结构中，通过斜杠命令或 `skill_view` 工具加载。设计参考 Hermes 的技能架构，支持两层缓存、条件激活、来源追踪和安全扫描。

### 技能目录结构

```
skill-name/
├── SKILL.md          # 必需：主指令文件（含 YAML frontmatter）
├── references/       # 可选：参考文档
├── templates/        # 可选：输出模板
├── scripts/          # 可选：可执行脚本
└── assets/           # 可选：静态资源
```

### Frontmatter 格式（YAML）

```yaml
---
name: skill-name                    # 必需，kebab-case，最长 64 字符
description: 简要描述                # 必需，最长 1024 字符
version: 1.0.0                      # 可选
platforms: [macos, linux]           # 可选 — 限制适用平台
metadata:
  hermes:
    tags: [标签1, 标签2]
    related_skills: [其他技能]
    fallback_for_tools: [主工具]         # 主工具可用时自动隐藏
    requires_tools: [依赖工具]           # 依赖工具不可用时隐藏
    fallback_for_toolsets: [工具集]      # 工具集可用时自动隐藏
    requires_toolsets: [工具集]          # 工具集不可用时隐藏
required_environment_variables:          # 所需环境变量声明
  - name: API_KEY
    prompt: 请输入你的 API 密钥
    optional: false
---
# 技能正文（Markdown）
```

### 技能来源与优先级

| 来源 | 路径 | 优先级 |
|------|------|--------|
| 用户全局 | `~/.minihermes/skills/<name>/SKILL.md` | 最高 |
| 项目专属 | `./.minihermes/skills/<name>/SKILL.md` | 中 |
| 外部目录 | 通过 `EXTERNAL_DIRS` 常量配置 | 低 |
| 内置技能 | 首次启动从 `_builtin_skills/` 同步到用户目录 | — |

同名技能以优先级高的版本为准。

### 工具接口

| 工具 | 说明 |
|------|------|
| `skill_view(name, file_path?, preprocess?)` | 加载技能的完整指令。返回结构化 JSON，包含正文、附属文件列表、环境变量需求、平台兼容性、setup 状态。支持 `file_path` 参数读取技能目录内的附属文件 |
| `skill_manage` | 技能生命周期管理，支持 8 种操作：`create`、`edit`（全量重写）、`patch`（查找替换）、`archive`（归档）、`restore`（恢复）、`list`（列表）、`write_file`（写附属文件）、`remove_file`（删附属文件） |

### skill_view 返回结构

```json
{
  "success": true,
  "name": "skill-name",
  "description": "技能描述",
  "content": "预处理后的正文",
  "path": "/absolute/path/to/SKILL.md",
  "skill_dir": "/absolute/path/to/skill/",
  "linked_files": {
    "references": ["references/api.md"],
    "templates": ["templates/report.tmpl"],
    "scripts": ["scripts/helper.py"],
    "assets": ["assets/logo.png"]
  },
  "required_env_vars": [{"name": "API_KEY", "prompt": "...", "optional": false}],
  "setup_needed": false,
  "platform_compatible": true,
  "category": "可选分类",
  "readiness_status": "available"
}
```

### 调用方式

1. **工具调用**：Agent 调用 `skill_view("skill-name")` → 加载 SKILL.md，预处理，返回 JSON
2. **斜杠命令**：用户输入 `/skill-name` → CLI 调用 `load_skill_structured()`，构建富文本激活消息
3. **系统提示**：`build_skills_index()` 生成技能索引块；Agent 看到后决定调用 `skill_view`

### 预处理

`skills/preprocessing.py` 提供两种变换（由模块级常量控制开关）：

1. **模板变量替换**（`TEMPLATE_VARS_ENABLED = True`）：`${MINIHERMES_SKILL_DIR}` → 技能目录路径，`${MINIHERMES_SESSION_ID}` → 当前会话 ID
2. **内联 Shell 展开**（`INLINE_SHELL_ENABLED = False`）：`` `!cmd` `` → 命令输出（出于安全默认关闭）

### 缓存机制

`prompt/builder.py` 实现两层缓存，避免每次构建系统提示都扫描文件系统：

1. **进程内 LRU 缓存**（`OrderedDict`，上限 8 条）：最快，按 `(技能目录, 可用工具, 可用工具集)` 建 key
2. **磁盘快照**（`.skills_prompt_snapshot.json`）：用 mtime/size 清单校验有效性，跨重启保留
3. **文件系统扫描**：兜底方案，完成后回写两层缓存

技能变更（create/edit/patch/archive/restore/sync）后自动通过 `clear_skills_system_prompt_cache()` 使缓存失效。

### 条件激活

技能可在 frontmatter 的 `metadata.hermes` 中声明可见性规则：

- `fallback_for_tools`：技能是备用方案 — 主工具可用时隐藏
- `requires_tools`：技能依赖此工具 — 工具不可用时隐藏
- `fallback_for_toolsets` / `requires_toolsets`：同上逻辑，作用于工具集

无规则声明则始终显示（向后兼容）。

### 来源追踪

技能按来源分类，确保安全生命周期管理：

| 来源 | 识别方式 | Curator 策略 |
|------|----------|-------------|
| 内置 (bundled) | `.bundled_manifest` 中记录（SHA-256 哈希） | 永不被 curator 归档 |
| Agent 创建 | 不在 bundled manifest 中的所有技能 | 受 stale/archive 生命周期管控 |
| Hub 安装 | `.hub/lock.json` 记录（未来） | 永不被 curator 归档 |

`sync_builtin_skills()` 每次运行时写入 `.bundled_manifest`，按 `name:sha256_hash` 追踪。

### 遥测数据

统一遥测数据库 `~/.minihermes/skills/.usage.json`（首次加载时自动从旧的独立 `.usage.json` sidecar 文件迁移）：

```json
{
  "skill-name": {
    "use_count": 5,
    "view_count": 5,
    "patch_count": 2,
    "last_used_at": "2026-06-27T...",
    "last_viewed_at": "2026-06-27T...",
    "last_patched_at": "2026-06-27T...",
    "created_at": "2026-06-20T...",
    "state": "active",
    "pinned": false
  }
}
```

### 技能生命周期（Curator）

`evolution/curator.py` 在 session 退出时后台运行（每 7 天检查一次）：

- **第一阶段（确定性）**：Agent 创建且非 pinned 的技能：7 天未使用 → 标记 `stale`，30 天 → 归档到 `_archived/`
- **第二阶段（LLM）**：Agent 创建技能 ≥ 5 个时，生成子 Agent 合并重叠技能为更宽泛的 umbrella 技能

Pinned 技能（`set_pinned(name, True)`）跳过所有生命周期转换。

### 安全扫描

`skills/guard.py` 对 agent 创建的技能进行威胁扫描（由 `GUARD_AGENT_CREATED = False` 控制，默认关闭）：

- **30+ 威胁模式**：数据渗出、注入、破坏性命令、持久化、网络管道执行、混淆、凭据暴露、供应链攻击
- **结构检查**：文件数量上限、文件大小上限、符号链接逃逸检测
- **不可见字符检测**：零宽字符、BOM 等
- **判定结果**：`safe` / `suspicious` / `dangerous`（dangerous → 阻止安装）

### 自动技能创建（Nudge）

每 10 次工具迭代，系统自动触发技能复盘。Nudge agent 分析对话中的操作模式，识别可复用的工作流程并用 `skill_manage` 创建或更新技能。支持创建 `references/` / `templates/` / `scripts/` / `assets/` 附属文件。

---

## 记忆系统

记忆系统提供**跨会话持久化**的知识存储，双轨道设计：

| 轨道     | 文件                                  | 用途                  |
|----------|---------------------------------------|-----------------------|
| Memory   | `~/.minihermes/memory/MEMORY.md`      | 环境事实、项目约定     |
| User     | `~/.minihermes/memory/USER.md`        | 用户偏好、背景信息     |

- **冻结快照**：会话启动时加载并注入系统提示词，会话期间不变
- **实时状态**：通过工具修改后立即持久化，下次会话生效

### 自动记忆（Nudge）

每 10 轮用户对话，系统自动触发记忆复盘，分析对话中的用户偏好和环境事实并写入记忆。

---

## 上下文引用

使用 `@file:` 语法在消息中引用文件内容：

```bash
@file:src/main.py              # 引用整个文件
@file:src/main.py:42           # 引用特定行
@file:src/main.py:10-25        # 引用行范围
@file:"path/with spaces/file"  # 带空格的路径
```

自动检测二进制文件并跳过，引用内容展开为带语法高亮的代码块并显示 token 计数。

---

## 配置说明

配置文件位于 `~/.minihermes/config.yaml`，可通过 `/setup` 命令或手动编辑。

```yaml
model:
  name: "deepseek-v4-pro"       # 模型名称
  base_url: ""                  # API 基础 URL（OpenAI 兼容）
  api_key: ""                   # API 密钥
  max_iterations: 100           # 每轮对话最大工具调用次数
  show_thinking: true           # 是否显示模型思考过程
  reasoning_mode: "enabled"     # 推理模式

search:
  api_key: ""                   # Exa AI API Key
  count: 5                      # 每次搜索返回结果数

code_execution:
  api_key: ""                   # 沙箱 API Key

evolution:
  enabled: true                 # 自动记忆/技能复盘
```

### 支持的模型

任何兼容 OpenAI Chat Completions API 的服务均可使用：DeepSeek、Claude（通过兼容网关）、GPT 系列、本地 Ollama / vLLM 等。

---

## 会话管理

所有对话自动持久化到 `~/.minihermes/state.db`（SQLite，WAL 模式），包含：

- 每条消息的完整内容、角色、工具调用和 token 用量
- 会话标题和时间
- 全文搜索索引（FTS5）

### 会话命令

```bash
/sessions              # 列出最近会话
/resume <session_id>   # 恢复历史会话（自动跟随压缩链）
/clear                 # 开始新会话
/history               # 查看当前会话信息
/title <名称>          # 设置会话标题
```

---

## 审批系统

工具调用前经过两层安全防线：

### 硬拦截（不可绕过）

`rm /`、`mkfs`、`dd of=/dev/`、fork 炸弹、`shutdown` / `reboot`、`kill -9 1` 等破坏性命令直接拒绝。

### 软拦截（需用户确认）

`rm`、`kill`、`chmod 777`、`git push --force`、`git reset --hard`、`curl | sh`、`sudo`、`DROP TABLE`、`DELETE FROM`、以及向 `/etc/`、`~/.ssh/`、`.env` 等敏感路径的写入操作。

审批选项：**允许一次 / 允许本次会话 / 拒绝**。子 Agent 默认自动批准。

---

## 上下文压缩

当对话 token 接近上下文窗口的 50% 时，自动触发五阶段压缩：

| 阶段 | 说明 |
|------|------|
| 边界确定 | 保护头部消息，确保最近的用户消息在尾部 |
| 工具输出剪枝 | 超过 500 字符的工具结果替换为单行摘要 |
| LLM 摘要 | 使用结构化模板压缩中间消息 |
| 工具对清理 | 移除孤立工具结果，为缺失项插入存根 |
| 组装与分裂 | 创建子会话，标记压缩原因 |

使用 `/compress` 可在下一轮对话手动触发压缩。

---

## 项目上下文文件

在项目根目录放置上下文文件，AI 会自动加载。搜索优先级（从高到低）：

```
minihermes.md → .hermes.md → HERMES.md → AGENTS.md → CLAUDE.md → .cursorrules
```

使用 `/init` 命令可自动扫描代码库并生成 `minihermes.md`。

---

## 常见问题

**Q: 如何更换模型？**
使用 `/setup` 命令或直接编辑 `~/.minihermes/config.yaml`。

**Q: 支持哪些 API 提供商？**
任何兼容 OpenAI Chat Completions API 的服务均可使用。

**Q: 对话记录存在哪里？**
`~/.minihermes/state.db`（SQLite），可通过 `/sessions` 和 `/resume` 管理。

**Q: 如何让 AI 记住我的偏好？**
AI 会自动通过 Nudge 系统学习，你也可以直接说"记住…"。
