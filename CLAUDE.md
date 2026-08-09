# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MiniHermes is a Python-based AI coding assistant CLI. It provides an interactive terminal interface backed by OpenAI-compatible LLM APIs with tool execution, memory persistence, and skills.

## Build & Run

```bash
uv sync                    # Install dependencies
python main.py             # Run the CLI
bash build_wheel.sh        # Build wheel for distribution
pip install dist/minihermes-*.whl  # Install globally → `minihermes` command
```

Configuration lives at `~/.minihermes/config.yaml` (created by setup wizard from `config/config.yaml` template).

### Testing

```bash
uv sync --extra test       # Install test deps (pytest, pytest-mock)
pytest                     # Run tests（pytest 只收集 tests/；pyproject testpaths 已配置）
```

测试套件位于 `tests/`：核心（personas/白名单/字节兼容/team delegate）、CLI `/persona`、桌面后端 API（隔离 DB，不污染真实 state.db）。`desktop/backend/*_test.py` 是 WS 集成脚本（手动跑），非 pytest 用例。

## Directory Structure

```
main.py                       # 根入口 shim → minihermes.main（python main.py 可用）
src/minihermes/               # ★ 单发行版 minihermes（hatchling 打包此目录）
  __init__.py  __main__.py    # python -m minihermes
  main.py                     # CLI 入口（console script: minihermes = minihermes.main:main）
  core/                       # ★ 共享核心（前端无关；禁止 import cli/prompt_toolkit/rich）
    agent/        agent.py    # Conversation loop orchestrator
                  delegate.py # Sub-agent delegation
    approval/     engine.py   # Security approval engine
    provider/     provider.py # OpenAI SDK wrapper (streaming, retry, reasoning)
                  registry.py # 多厂商预设注册表（deepseek/glm…，OpenAI 兼容）
    context/      context.py  # ConversationContext (tokens, budget)
                  compressor.py  # 5-phase context compression
                  token_utils.py # Shared token estimation
    personas/     manifest.py # 专家数据模型 PersonaManifest + md 解析校验（ManifestError）
                  registry.py # 双源注册表（内置 _builtin/ + ~/.minihermes/personas/ 覆盖）
                  team.py     # build_team_roster（主理人花名册）/ build_member_prompt（团员 prompt）
                  _builtin/   # 内置专家 md ×7（go-backend-expert/doc-writer/research-analyst/dev-team…）
    prompt/       builder.py  # 12-layer system prompt assembly
    config/       config.py   # Config class + legacy accessor functions + register_setup_wizard
                  config.yaml # Default config template（包数据）
    tools/        registry.py # ToolRegistry (registration, schema query, execution)
                  __init__.py # Public API + eager imports for @register side effects
                  retry.py    # Tool execution retry with backoff
                  approval.py # Approval pattern data (HARDLINE, DANGEROUS, SENSITIVE)
                  bash.py     # Shell command execution
                  files.py    # File read/write/list
                  search.py   # Exa AI web search
                  code_execution.py  # Cloud sandbox code execution
                  memory.py   # Cross-session persistent memory
                  delegate.py # Delegate task schema (execution in core/agent/delegate.py)
                  todo.py     # Task planning
                  clarify.py  # User clarification
                  image_gen.py # Image generation via Pollinations.ai
                  process_tool.py  # System process listing
                  session_search.py  # FTS5 session search
                  skills_tool.py    # Skill loading
                  skill_manage.py   # Skill lifecycle management
                  web_extract.py    # Web page content extraction
    session/      db.py       # SQLite WAL persistence（含 get_token_stats）
    skills/       manager.py  # Skill discovery, YAML frontmatter parsing, index building
                  preprocessing.py  # Template var substitution, inline shell expansion
                  guard.py          # Security scanner for agent-created skills
                  __init__.py       # Public API exports
    output.py                 # ANSI 旁路输出（纯 print，无 prompt_toolkit/rich）
    rendering.py              # Renderer Protocol + NullRenderer（核心↔前端事件缝）
    services/                 # ★ 共享编排（CLI 与桌面复用）
      plan.py                 # Plan 常量 + run_plan_flow（统一两端三阶段流程）
      context_ref.py          # @file reference preprocessor
      session_service.py      # session_id / token 统计 / session_to_ui
      commands.py             # 斜杠命令注册表（CLI + 桌面单一事实源）
    _builtin_skills/          # Built-in skill templates（包数据）
  cli/                        # ★ 终端前端（prompt_toolkit + rich）
    conversation.py           # Background conversation loop thread
    state.py                  # AppState (shared mutable state between threads)
    commands.py               # Slash command handlers（消费 core/services）
    plan_ui.py                # Plan 审批面板（UI 半部）
    renderer.py               # StreamRenderer / SubagentRenderer（终端渲染实现）
    setup_wizard.py           # 首次运行向导 + /setup（CLI 专用，经 config 钩子注册）
    layout.py                 # prompt_toolkit layout builder
    keybindings.py            # Keyboard shortcuts
    styles.py                 # UI color styles
    completers.py             # Tab completion
    approval.py               # Approval UI rendering
    clarify.py                # Clarify UI rendering
desktop/                      # ★ 桌面前端（Electron + React + FastAPI 子进程）
  backend/server.py           # FastAPI 后端，仅 import minihermes.core.*
  backend/gui_renderer.py     # GuiRenderer（实现 core.rendering.Renderer）
  electron/ src/ scripts/ resources/ package.json
```

## Message Flow

```
User Input → CLI (prompt_toolkit) → Agent.run_conversation()
  → Provider.stream() [LLM call with tool schemas]
  → Tool Execution [if tool_calls returned, loop until done or budget exhausted]
  → ContextCompressor [if approaching token limits]
  → SessionDB [persist to SQLite WAL]
  → StreamRenderer [output to terminal]
```

## CLI Interface

### Keyboard Shortcuts

| Action | Key |
| --- | --- |
| Send message | `Enter` |
| Newline (multi-line) | `Shift+Enter` / `Cmd+Enter` |
| Interrupt AI response | `Ctrl+C` |
| Exit | `/exit` / `/quit` / `Ctrl+D` |

### Slash Commands

| Command | Description |
| --- | --- |
| `/help` | Show all available commands |
| `/clear` | Clear conversation, start new session |
| `/compress` | Force context compression next turn |
| `/plan [desc]` | Enter plan mode (read-only analysis → plan → approval → execute) |
| `/init` | Scan CWD and generate `minihermes.md` context file |
| `/history` | Show current session ID, turns, message count |
| `/sessions` | List recent sessions with titles and timestamps |
| `/resume <id>` | Restore a previous session (follows compression chain) |
| `/title <name>` | Set current session title |
| `/sysprompt` | Print full system prompt (debug) |
| `/setup` | Runtime config wizard (provider, API key, model, etc.) |
| `/provider [name]` | List/switch service provider (immediate) |
| `/model [name]` | List/switch model for current provider (immediate) |
| `/persona` `/persona list` | List personas (agent/team, `◀ active` marker) |
| `/persona view <id>` | Show persona detail (tools/skills/members/body preview) |
| `/persona activate <id>` | Switch persona in-session (next turn) |
| `/persona deactivate` | Exit persona, restore default behavior |
| `/exit` `/quit` `/q` | Exit |
| `/<skill-name>` | Load and execute a skill (e.g. `/code-review`) |

## Core Layers

- **Entry point** (`main.py`): Wires Config, Provider, Agent, SessionDB, builds CLI app, starts background conversation thread.
- **Agent** (`agent/agent.py`): Orchestrates the conversation loop with ConversationContext (budget, token tracking). Delegates tool dispatch to ToolRegistry, approval to ApprovalEngine, compression to ContextCompressor. Main method: `run_conversation()`.
- **ApprovalEngine** (`approval/engine.py`): Two-tier security policy — HARDLINE (7 patterns, unrejectable: `rm /`, `mkfs`, `dd of=/dev/`, fork bomb, shutdown/reboot, `kill -9 1`, `kill -1`) and DANGEROUS (19 patterns requiring user confirmation: `rm`, `kill`, `chmod 777`, `git push --force`, `git reset --hard`, `curl | sh`, `sudo`, `DROP TABLE`, writes to `/etc/` / `~/.ssh/` / `.env`, etc.). Manages session whitelist for "allow for session" approvals.
- **ConversationContext** (`context/context.py`): State container for a single conversation run — token estimation, iteration budget, compression triggers.
- **Provider** (`provider/provider.py` + `provider/registry.py`): OpenAI SDK wrapper supporting streaming with `on_delta`/`on_thinking` callbacks, tool calling, and multi-vendor presets. `registry.py` declares preset vendors (deepseek / glm / …) with default base_url, model candidates, context windows, and thinking-effort defaults; config.yaml stores only per-vendor overrides (api_key / model / context_window / thinking_effort). `get_provider_config()` merges preset + overrides + env fallback into one resolved dict. Per-call params (`reasoning_effort`, temperature) and context window (`Provider.context_window`) are now configurable. API-level retry with jittered exponential backoff.
- **ToolRegistry** (`tools/registry.py`): Decorator-based tool registration (`@register(schema)`) with schema filtering and execution dispatch. Each instance maintains an independent registry.
- **CLI** (`cli/`): prompt_toolkit Application with streaming renderer, slash commands, approval flows, clarification modals. Conversation runs in a **background daemon thread** consuming from `AppState.input_queue`; the **main thread** runs the UI event loop.
- **Skills** (`skills/`): Markdown instruction templates with YAML frontmatter. Discovered from `~/.minihermes/skills/` (global, including built-in synced on first start), `./.minihermes/skills/` (project-local), and external directories. Two-layer cache (LRU + disk snapshot) avoids filesystem scans on every prompt build. Supports conditional activation (hide/show based on available tools), platform matching, supporting files (references/templates/scripts/assets), template variable substitution, and provenance tracking (bundled vs agent-created). See [Skill System](#skill-system) below.
- **Persona/Expert** (`personas/`): 会话级专家系统。manifest 为单 md（frontmatter 能力声明 + 正文=身份 system prompt），`parse_persona_md` 严格校验（非法抛 `ManifestError`）。`PersonaRegistry` 双源合一（内置 `_builtin/` 优先、`~/.minihermes/personas/` 同 id 覆盖），team 成员惰性解析（缺失剔除+log）。支持 `agent`/`team` 双类型（team = 主理人 + 团员子代理，走 `delegate_task(persona_id=...)`）；`soul_mode: replace|stack`；工具硬白名单（`tools` 声明则白名单∩已注册，空=全开）。`Agent.apply_persona()` 会话级切换（换身份+工具集+token 开销），桌面端按会话懒应用（`_apply_persona_for_session`，`_turn_lock` 内、幂等）；`db.sessions.persona_id` 持久化，压缩子会话继承。无专家时行为逐字节兼容（单测锁定）。CLI `/persona`；桌面主区域专家界面（侧栏导航项「对话|🧠 专家|技能」，`manifest_to_dict` 透传完整 `system_prompt`，卡片墙 → 详情滚动展示角色简介 → 应用=新建会话注入）。
- **Context Compression** (`context/compressor.py`): 5-phase strategy — boundary determination (HEAD/MIDDLE/TAIL), tool output pruning (>500 chars → one-line summary), LLM summary (12-section structured template), tool pair sanitization (fix orphaned tool_call/result pairs), assembly + session splitting. Anti-thrashing with 60s cooldown between compressions.
- **Session** (`session/db.py`): SQLite with WAL mode for multi-turn conversation persistence. FTS5 full-text search.
- **Prompt** (`prompt/builder.py`): Multi-layer system prompt builder. ~6 active layers: Layer 1 Identity (SOUL.md), Layer 7 Memory snapshot, Layer 9 Context files, Layer 10 Model name, Layer 11 Environment detection, Layer 12 Platform guidance. Invisible-char and prompt-injection scanning. No timestamp/date is injected.

## Sub-agent Delegation

`agent/delegate.py` allows the main agent to spawn sub-agents for self-contained tasks, with their own iteration budget and tool access. The tool schema is registered in `tools/delegate.py`; actual execution is intercepted by `Agent._execute_tool()`.

Sub-agents have: independent iteration budget (default 50), auto-approved tool calls (no user prompts), no DB persistence, and restricted tool access (cannot delegate further or use clarify).

## Plan Mode

`/plan` launches a two-phase workflow managed by `cli/conversation.py:_execute_plan_mode()`:

1. **Analysis phase**: A temporary Agent is spawned with `tool_filter={"include": PLAN_ALLOWED_TOOLS}` (read-only tools only: `read_file`, `list_dir`, `bash`, `web_search`, etc.). It analyzes the codebase and produces a structured implementation plan.
2. **Approval phase**: The plan is rendered in a formatted panel. User chooses Execute / Cancel.
3. **Execution phase**: If approved, the plan text is injected as the next user message with the prefix `"Execute the following approved implementation plan..."` so the main Agent executes it.

Plans are saved to `.minihermes/plans/` for later reference. The plan agent runs with `auto_approve=True` and `max_iterations_override=50`.

## Memory System

Dual-track persistent storage at `~/.minihermes/memory/`:

| File | Purpose |
| --- | --- |
| `MEMORY.md` | Environment facts, project conventions, cross-session knowledge |
| `USER.md` | User preferences, background info, communication style |

Two states:

- **Frozen snapshot**: Loaded at session start and injected into system prompt (Layer 7). Does not change during a session.
- **Live state**: Modified via the `memory` tool — changes persist immediately and take effect next session.

Memories follow a structured format: frontmatter with `name`, `description`, `metadata` (type: user/feedback/project/reference), and body with **Why:** and **How to apply:** lines. Related memories linked via `[[name]]` wikilinks.

## Context Files

When building the system prompt (Layer 9), the project root is scanned for context files in this priority order:

```
minihermes.md → .hermes.md → HERMES.md → AGENTS.md → CLAUDE.md → .cursorrules
```

First match wins. `/init` generates `minihermes.md` by scanning the codebase.

`@file:` references in user input are preprocessed by `cli/context_ref.py`:

- `@file:path.py` — entire file
- `@file:path.py:42` — single line
- `@file:path.py:10-25` — line range
- `@file:"path with spaces/file"` — quoted paths

Resolved relative to CWD, injected as a code block with token count.

## Skill System

Skills are reusable Markdown instruction templates with YAML frontmatter, stored as directory structures under the skills directories. The design follows Hermes' skill architecture with two-layer caching, conditional activation, provenance tracking, and security scanning.

### Directory Structure

```
skill-name/
├── SKILL.md          # Required: main instructions with YAML frontmatter
├── references/       # Optional: supporting reference documents
├── templates/        # Optional: output templates
├── scripts/          # Optional: executable scripts
└── assets/           # Optional: static resources
```

### Frontmatter Format (YAML)

```yaml
---
name: skill-name                    # Required, kebab-case, max 64 chars
description: Brief description      # Required, max 1024 chars
version: 1.0.0                      # Optional
platforms: [macos, linux]           # Optional — restrict to specific OS
metadata:
  hermes:
    tags: [tag1, tag2]
    related_skills: [other-skill]
    fallback_for_tools: [primary_tool]    # Hide when tool IS available
    requires_tools: [required_tool]       # Hide when tool is NOT available
    fallback_for_toolsets: [toolset]      # Hide when toolset IS available
    requires_toolsets: [toolset]          # Hide when toolset is NOT available
required_environment_variables:          # Structured env var declarations
  - name: API_KEY
    prompt: Enter your API key
    optional: false
---
# Skill body (markdown)
```

### Skill Sources & Priority

| Source | Path | Priority |
|--------|------|----------|
| User global | `~/.minihermes/skills/<name>/SKILL.md` | Highest |
| Project local | `./.minihermes/skills/<name>/SKILL.md` | Medium |
| External dirs | configured via `EXTERNAL_DIRS` constant | Low |
| Built-in | synced from `_builtin_skills/` to user dir on first start | — |

Name conflicts: first discovered wins (user > project > external).

### Tool Interface

| Tool | Purpose |
|------|---------|
| `skill_view(name, file_path?, preprocess?)` | Load a skill's full instructions. Returns structured JSON with content, linked files, env requirements, platform compatibility, setup status. Supports `file_path` for reading supporting files. |
| `skill_manage` | CRUD operations: `create`, `edit` (full rewrite), `patch` (find-and-replace), `archive`, `restore`, `list`, `write_file`, `remove_file`. |

### skill_view Response Structure

```json
{
  "success": true,
  "name": "skill-name",
  "description": "...",
  "content": "<preprocessed body>",
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
  "category": "optional-category",
  "readiness_status": "available"
}
```

### Invocation Paths

1. **Tool call**: Agent calls `skill_view("skill-name")` → loads SKILL.md, preprocesses content, returns JSON
2. **Slash command**: User types `/skill-name` → CLI calls `load_skill_structured()`, builds rich activation message
3. **System prompt**: `build_skills_index()` generates an index block listing available skills; agent sees this and decides to call `skill_view`

### Preprocessing

`skills/preprocessing.py` applies two transformations (controlled by module-level constants):

1. **Template variable substitution** (`TEMPLATE_VARS_ENABLED = True`): `${MINIHERMES_SKILL_DIR}` → skill directory path, `${MINIHERMES_SESSION_ID}` → current session ID
2. **Inline shell expansion** (`INLINE_SHELL_ENABLED = False`): `` `!cmd` `` → command output (disabled by default for safety)

### Caching

Two-layer cache in `prompt/builder.py` eliminates filesystem scans on every system prompt build:

1. **In-process LRU** (`OrderedDict`, max 8 entries): Fastest, keyed by (skills_dirs, tools, toolsets)
2. **Disk snapshot** (`.skills_prompt_snapshot.json`): Validated by mtime/size manifest, survives restarts
3. **Filesystem scan**: Fallback, writes both caches on completion

Cache is invalidated automatically after skill mutations (create/edit/patch/archive/restore/sync) via `clear_skills_system_prompt_cache()`.

### Conditional Activation

Skills can declare visibility rules in `metadata.hermes` frontmatter:

- `fallback_for_tools`: Skill is a fallback — hide when the primary tool IS available
- `requires_tools`: Skill needs this tool — hide when it's NOT available
- `fallback_for_toolsets` / `requires_toolsets`: Same logic for toolsets

No conditions declared → always shown (backward compatible default).

### Provenance Tracking

Skills are classified by origin（供 `skill_manage` 标记 source 与归档保护使用）:

| Origin | How Identified |
|--------|---------------|
| Bundled | Listed in `.bundled_manifest` (SHA-256 hash per entry) |
| Agent-created | Everything not in bundled manifest |

`sync_builtin_skills()` writes `.bundled_manifest` on each run, tracking `name:sha256_hash` per skill. `skill_manage` 的 `archive` 仅允许 agent-created 技能，bundled 技能受保护（不可被 agent 归档）。

### Security Guard

`skills/guard.py` scans agent-created skills for threats (controlled by `GUARD_AGENT_CREATED = False`):

- **30+ threat patterns**: exfiltration, injection, destructive commands, persistence, network pipe-to-shell, obfuscation, credential exposure, supply chain
- **Structural checks**: file count limits, size limits, symlink escape detection
- **Invisible unicode detection**: zero-width characters, BOM, etc.
- **Verdicts**: `safe` / `suspicious` / `dangerous` (dangerous → blocked from install)

### Backward Compatibility

All old APIs preserved: `discover_skills()` returns same shape, `load_skill()` returns plain text, `build_skills_index()` returns same format, `_parse_frontmatter` still works.

## Key Conventions

- All tools follow OpenAI function calling schema, registered via the `@register` decorator. New tool modules must be imported in `tools/__init__.py` to trigger registration.
- Tool execution retry is always enabled for `bash`, `web_extract`, `web_search` — up to 2 retries on timeout/transient errors. Bash timeout doubles on each retry (max 120s).
- All tool outputs go through `truncate_output()` (50K char limit, head 40% + tail 60%).
- Config merging: user config at `~/.minihermes/config.yaml` is merged over the default template at `config/config.yaml`. A `Config` class provides injectable access with lazy loading. Missing top-level keys are auto-filled on load. Legacy `model:` blocks auto-migrate to `provider:` + `agent:` on load.
- 多厂商：`provider.active` 指向当前厂商，`provider.list.<name>` 存用户覆盖项（api_key/base_url/model/context_window/thinking_effort，空 = 预设默认）；`agent.max_iterations` / `agent.show_thinking` 为通用 Agent 参数。运行时切换厂商/模型走 `set_active_provider()` / `set_provider_override()` + `reload_config()` 后重建 `Provider`（CLI 命令 `/provider` `/model`；桌面保存设置后 `Kernel.rebuild_provider()`）。
- Single distribution `minihermes`: hatchling packages `src/minihermes` (`pyproject.toml` `packages = ["src/minihermes"]`), console script `minihermes = minihermes.main:main`. `config.yaml` 与 `_builtin_skills/` 作为包数据随 wheel 发布。`build_wheel.sh` 只是 `uv build` 的封装。
- 布局与边界：共享核心在 `minihermes.core`（前端无关，禁止 import `cli`/`prompt_toolkit`/`rich`）；终端前端在 `minihermes.cli`；桌面后端 `desktop/backend/server.py` 仅 import `minihermes.core.*`。核心↔前端通过 `core/rendering.py` 的 `Renderer` Protocol 解耦。
- The CLI runs two threads: main thread (prompt_toolkit UI event loop) and daemon thread (conversation loop consuming from `AppState.input_queue`). `AppState` (`cli/state.py`) is the shared mutable state.
- Primary language in commits and comments is Chinese.

## Tech Stack

- **Python ≥3.11**, packaged with hatchling
- **OpenAI SDK** for LLM integration (any OpenAI-compatible endpoint)
- **prompt_toolkit** for terminal UI
- **Rich** for formatted console output
- **SQLite** (WAL mode) for session persistence
- **Exa AI SDK** for web search
- **e2b-code-interpreter** for cloud code sandbox
- **PyYAML** for configuration
