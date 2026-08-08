# MiniHermes

轻量级 AI 编程助手 CLI，仿照 [Claude Code](https://claude.ai/code) 和 [Hermes](https://github.com/NousResearch/hermes-agent) 设计。基于 Python 构建，支持任意 OpenAI 兼容 API（DeepSeek、智谱 GLM 等），提供交互式终端界面，具备工具调用、记忆持久化和可扩展技能系统。
内置多厂商 Provider 预设注册表：只需填入 API Key 即可使用，模型 / 上下文长度 / 思考强度均可由用户控制，并支持运行时切换厂商。

`每个模块的详细文档都放在了目录/docs下，可以查看`

## 快速开始

```bash
# 全局安装
pip install minihermes

# 或源码运行
git clone https://github.com/xxx/minihermes.git
cd minihermes
uv sync
python main.py
```

首次启动自动进入配置向导：选择厂商（DeepSeek / 智谱 GLM）→ 填入 API Key → 可选模型。

```bash
minihermes   # 启动交互式对话
```

### 多厂商 Provider

预设厂商注册表内置在代码中（`core/provider/registry.py`），用户只需在配置里填 API Key 即可，其余参数均可用默认值：

```yaml
# ~/.minihermes/config.yaml
provider:
  active: "deepseek"          # 当前生效厂商
  list:
    deepseek:                 # 空字段 = 用预设默认
      api_key: "sk-..."       # 或环境变量 DEEPSEEK_API_KEY
      base_url: ""            # 空 → https://api.deepseek.com
      model: ""               # 空 → deepseek-v4-flash
      context_window: 0       # 0 → 预设默认
      thinking_effort: ""     # off|low|medium|high|max
    glm:
      api_key: ""
      ...
agent:
  max_iterations: 100
  show_thinking: true
```

- 旧版扁平 `model:` 配置会在首次启动时自动迁移为 `provider:` + `agent:` 结构。
- 运行时切换厂商 / 模型：`/provider`、`/model`（立即生效，无需重启）。

## 基本操作

| 操作 | 方式 |
| --- | --- |
| 发送消息 | `Enter` |
| 多行输入 | `Ctrl+J` |
| 中断回复 | `Ctrl+C` |
| 退出 | `/exit` 或 `Ctrl+D` |
| 查看帮助 | `/help` |
| 规划模式 | `/plan <描述>` |
| 加载技能 | `/<skill-name>`，如 `/code-review` |
| 切换厂商 | `/provider`（列出）/ `/provider glm`（切换） |
| 切换模型 | `/model deepseek-v4-pro` |

## 打包

```bash
bash build_wheel.sh                    # 构建 wheel 包到 dist/
pip install dist/minihermes-*.whl      # 全局安装
```

hatchling 直接打包 `src/minihermes`（含 `cli/`、`core/`、`core/services/` 与 `_builtin_skills`、`config.yaml` 包数据），安装后 `minihermes` 命令全局可用。

## 主要特性

流式对话 · 15 个内置工具 · 技能系统（条件激活 + 安全扫描） · 跨会话记忆 · 安全审批（两层防线） · 上下文自动压缩 · SQLite 持久化 + FTS5 全文搜索 · 子 Agent 委派 · 规划模式（只读分析 → 审批 → 执行） · **多厂商 Provider（DeepSeek / 智谱 GLM，运行时切换）**

## 详细文档

完整架构设计和模块文档见 [`docs/`](docs/)：

| 文档 | 内容 |
| --- | --- |
| [整体架构](docs/整体架构.md) | 项目总览与架构设计 |
| [调用链路](docs/01-call-chain.md) | 消息处理主流程 |
| [系统提示词](docs/02-system-prompt.md) | 12 层系统提示词组装 |
| [上下文压缩](docs/03-context-compression.md) | 五阶段压缩策略 |
| [记忆系统](docs/04-memory.md) | 双轨道记忆与自动复盘 |
| [工具系统](docs/05-tools.md) | 工具注册、执行、审批 |
| [Provider](docs/06-provider.md) | LLM API 封装 |
| [Agent 引擎](docs/07-agent.md) | 对话循环与子 Agent |
| [CLI 界面](docs/08-cli.md) | prompt_toolkit 终端 UI |
| [会话持久化](docs/09-session.md) | SQLite WAL + FTS5 |

## 环境

Python ≥ 3.11 · macOS / Linux / Windows


## 演示

![demo-1](asset/1.png)

![demo-2](asset/2.png)

![demo-3](asset/3.png)

![demo-4](asset/4.png)

## License

MIT