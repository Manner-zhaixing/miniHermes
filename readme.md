<p align="center">
  <img src="asset/1.png" alt="MiniHermes" width="480" />
</p>

<h1 align="center">MiniHermes</h1>

<p align="center">
  <b>轻量级 AI 编程助手</b> · 纯 Python · 终端 + 桌面双端
  <br/>
  多模型自由切换 · 工具调用 · 跨会话记忆 · 长对话不失控
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="License"/>
  <img src="https://img.shields.io/badge/version-1.1.7-green" alt="Version"/>
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey" alt="Platform"/>
</p>

---

## 特性

- **双端形态** — 终端 CLI（富交互界面）+ 桌面端（Electron），共享同一内核
- **多模型自由切换** — 内置 DeepSeek / 智谱 GLM，运行时秒切厂商与模型，支持任意 OpenAI 兼容 API
- **17 个内置工具** — 文件读写、命令执行、网页搜索、代码沙箱、图片生成、子任务委派…
- **跨会话记忆** — 自动记住你的偏好与项目约定
- **长对话不失控** — 五阶段上下文压缩，1M 上下文窗口也能流畅对话
- **安全有保障** — 危险命令自动拦截，敏感操作弹窗确认
- **Plan 规划模式** — 先出方案、你确认后执行
- **技能系统** — 内置技能 + 一键扩展自定义技能

---

## 架构

```mermaid
flowchart TB
    CLI["终端 CLI"] --> CORE["MiniHermes 内核"]
    DESK["桌面端"] --> CORE
    CORE --> LLM["DeepSeek / GLM 等<br/>OpenAI 兼容 API"]
```

内核统一承载：Agent 对话引擎 · 工具系统 · 记忆 · 上下文压缩 · 安全审批 · 技能系统 · 会话持久化。

---

## 快速开始

```bash
# 安装
pip install minihermes

# 或源码运行
git clone https://github.com/Manner-zhaixing/miniHermes.git
cd miniHermes
uv sync
python main.py

# 启动
minihermes
```

首次启动自动进入配置向导：选择厂商 → 填入 API Key → 选择模型。

> 桌面端体验：`cd desktop && npm install && npm run dev`，详见 [desktop/README.md](desktop/README.md)

---

## 基本操作

| 操作 | 方式 |
|------|------|
| 发送消息 / 多行输入 | `Enter` / `Ctrl+J` |
| 中断回复 | `Ctrl+C` |
| 退出 | `/exit` 或 `Ctrl+D` |
| 规划模式 | `/plan <描述>` |
| 切换厂商 / 模型 | `/provider glm` / `/model deepseek-v4-pro` |
| 加载技能 | `/code-review` |
| 引用文件 | `@file:path/to/file.py:30-50` |

---

## 配置

所有配置集中在 `~/.minihermes/config.yaml`，只需填 API Key，其余用默认值即可：

```yaml
provider:
  active: "deepseek"
  list:
    deepseek:
      api_key: "sk-..."       # 或环境变量 DEEPSEEK_API_KEY
    glm:
      api_key: ""
agent:
  max_iterations: 100
  show_thinking: true
```

> 旧版 `model:` 配置首次启动自动迁移；新增厂商只需加一条配置项。

---

## 文档

| 文档 | 内容 |
|------|------|
| [整体架构](docs/整体架构.md) | 架构设计总览 |
| [调用链路](docs/01-call-chain.md) | 消息处理主流程 |
| [系统提示词](docs/02-system-prompt.md) | 12 层提示词组装 |
| [上下文压缩](docs/03-context-compression.md) | 五阶段压缩策略 |
| [记忆系统](docs/04-memory.md) | 双轨道记忆 |
| [工具系统](docs/05-tools.md) | 工具注册与审批 |
| [Provider](docs/06-provider.md) | LLM API 封装 |
| [Agent 引擎](docs/07-agent.md) | 对话循环与子 Agent |
| [CLI 界面](docs/08-cli.md) | 终端 UI |
| [会话持久化](docs/09-session.md) | SQLite + FTS5 |

---

## 演示

![demo-1](asset/1.png)

![demo-2](asset/2.png)

![demo-3](asset/3.png)

![demo-4](asset/4.png)

---

## License

MIT
