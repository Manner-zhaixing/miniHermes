# 10 — 专家(Persona)系统设计

> 会话级单专家 · 混合 soul_mode · 硬限制工具白名单 · 内置+本地目录 | `core/personas/`

---

## 1. 背景与目标

MiniHermes 已具备完整的 agent 基础设施(ReAct 主循环、分层 system prompt、技能系统、todo、委派、记忆、审批、上下文压缩),但缺少"专家/角色"能力——用户无法让同一内核以不同专业身份工作(Go 后端专家、文档撰写、深度研究等)。

目标:参考 OpenWorker(persona)与 WorkBuddy(专家)两家的成熟设计,在 MiniHermes 现有架构上以**最小侵入**新增专家系统,遵循其"轻量、可插拔、纯 Python"的项目气质。

已确认的设计决策:

| 决策 | 结论 |
|------|------|
| 专家形态 | **会话级单专家**(一个会话绑定一个专家,切专家 = 换会话) |
| 与 SOUL.md 关系 | **混合 soul_mode**:默认 `replace`(专家替换身份层),可选 `stack`(人格+角色叠加) |
| 工具白名单 | **硬限制**:声明则白名单外工具不可见;`tools: []` 默认全开 |
| 来源范围(第一期) | **内置 + 本地目录**(`~/.minihermes/personas/*.md`) |

---

## 2. 参考:OpenWorker 专家(persona)架构

OpenWorker(andrewyng 开源,Python)的 persona 体系是本次设计的主要参照:

### 2.1 定义格式:一个 Markdown 文件 = 一份专家

```
personas/builtin/ops.md
├─ YAML frontmatter   → 身份 + 能力声明
│    id / name / icon / tagline / family(code|knowledge)
│    tools: [...]              ← 工具白名单(引用 vetted catalog)
│    messaging / connectors    ← 通道开关
│    recommended_models        ← 推荐模型
│    default_permission_mode   ← discuss/plan/interactive/custom/auto
│    recommends[]              ← 推荐连接(connector/mcp + reason + tier)
└─ Markdown 正文       → 即 system prompt(角色、规范、工作流)
```

设计哲学:**persona 不携带可执行代码,只做"能力声明 + 文本定义"**,因此安装是轻信任事件。

### 2.2 运行时链路(6 环节)

| 环节 | 实现文件 | 要点 |
|------|----------|------|
| 解析 | `personas/manifest.py` | frontmatter 严格校验,非法即 `ManifestError`(fail loudly) |
| 注册 | `personas/registry.py` | 双源合一:内置走代码 builder,第三方走 manifest;`id → Agent` 统一解析 |
| 物化 | `manifest.to_agent()` | 产出 `Agent(name, system_prompt, tool_factory)`,`tools:` 经 catalog 展开 |
| 注入 | `agent.py build_engine` | persona prompt 作为 instructions 基底 → 拼环境 → 约定 → 记忆 |
| 安装 | `personas/loading.py` | git/目录 → `consent_summary` 用户批准 → 快照复制到受管目录 |
| 会话绑定 | `sessions.py` `SessionRecord.agent` | 会话元数据存 persona id;新会话用 `default_id()`,恢复用 `record.agent` |

### 2.3 三个关键设计决策

1. **会话级单专家**:一个会话由一个 persona 诞生,`SessionRecord.agent` 记录,不混用。
2. **快照安装**:安装即复制到受管目录,与源目录解耦,定义稳定可复现。
3. **静态基底 + 动态增量**:persona prompt 静态拼进 system prompt(每会话一次);skill 目录/记忆走每轮动态注入(上下文经济学)。

---

## 3. MiniHermes 现状盘点(可复用资产)

| 能力 | MiniHermes 现状 | 专家方案怎么用 |
|------|-----------------|----------------|
| 主循环 | `run_conversation` ReAct 循环 | 不动,专家只是换 system prompt + 工具集 |
| 分层 prompt | `build_system_prompt`(Layer 1 身份 SOUL.md → 工具引导 → 记忆 → 上下文文件 → Skills 索引 → 环境/平台) | **插入点**:身份层后加"专家层" |
| 身份层 | `~/.minihermes/SOUL.md` + `_scan_for_injection` 注入检测 | 专家正文同样过注入检测 |
| 技能系统 | SKILL.md + `parse_frontmatter` + `build_skills_index` 目录注入 + `skill_view` 按需加载(渐进披露) | 专家 frontmatter 声明 `skills:` 捆绑 |
| 工具注册 | `registry.get_schemas(include=...)` 已支持 include 过滤 | 专家白名单直接复用 include 参数 |
| 子 agent | `delegate_task` 工具(隔离执行) | 专家可声明是否允许委派 |
| 审批 | clarify / approval | 第二期 git 导入的 consent 复用 |
| 记忆 | `~/.minihermes/memory/MEMORY.md + USER.md` | 专家会话沿用现有记忆层 |
| 上下文压缩 | 五阶段压缩 | 专家长 prompt 天然受益 |
| persona/expert | **不存在(需新增)** | 本次方案核心 |

---

## 4. 详细设计

### 4.1 模块结构

```
src/minihermes/core/personas/
├── __init__.py
├── manifest.py     # PersonaManifest + parse_persona_md()
├── registry.py     # PersonaRegistry:扫描内置+全局目录 → id → PersonaEntry
└── tools.py        # persona_list / persona_view / persona_activate(工具注册)
```

### 4.2 数据模型(`manifest.py`)

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class PersonaManifest:
    id: str
    name: str
    icon: str = ""
    tagline: str = ""
    description: str = ""
    category: str = "general"
    tools: list[str] = field(default_factory=list)    # 空=全开;非空=白名单(硬限制)
    skills: list[str] = field(default_factory=list)   # 捆绑技能(索引优先展示)
    soul_mode: str = "replace"                        # "replace" | "stack"
    system_prompt: str = ""                           # markdown 正文(= 角色 prompt)
    source: str = "builtin"                           # "builtin" | "local"
    path: Optional[str] = None                        # 来源文件路径(provenance)

class ManifestError(ValueError):
    """manifest 非法(字段缺失/未知枚举值)→ fail loudly,不静默降级"""

def parse_persona_md(path) -> PersonaManifest:
    """解析专家 md:复用 skills 模块的 parse_frontmatter 提取 frontmatter,
    正文 = 其余部分;正文需过 _scan_for_injection 注入检测(与 SOUL.md 一致)。"""
```

字段校验规则:
- `id`:必填,`^[a-z0-9][a-z0-9_-]{0,63}$`(目录名/注册键,防路径穿越)
- `soul_mode`:仅 `replace` / `stack`
- `tools` / `skills`:逗号分隔或 YAML 列表
- 未知字段忽略;缺失必填字段抛 `ManifestError`

### 4.3 目录约定与发现(`registry.py`)

```
内置:  src/minihermes/personas/builtin/*.md        # 打包进 wheel
全局:  ~/.minihermes/personas/*.md                 # 用户自建(注册时内置优先,同 id 内置覆盖)
```

```python
@dataclass
class PersonaEntry:
    manifest: PersonaManifest
    enabled: bool = True

class PersonaRegistry:
    def __init__(self, builtin_dir=None, extra_dirs=None):
        self._entries: dict[str, PersonaEntry] = {}
        # 1) 扫描内置目录   2) 扫描 ~/.minihermes/personas/   3) 可选 extra_dirs

    def list(self) -> list[PersonaManifest]: ...      # 全部可用(名称/描述/来源)
    def get(self, persona_id) -> Optional[PersonaManifest]: ...
    def resolve(self, persona_id) -> Optional[PersonaManifest]: ...  # 不存在时 log + None(降级为无专家)
    def names(self) -> list[str]: ...
```

### 4.4 注入链路(`build_system_prompt` 改动)

`src/minihermes/core/prompt/builder.py` 的 `build_system_prompt()` 增加 `persona` 参数(默认 None,向后兼容):

```python
def build_system_prompt(
    model_name: str = "",
    memory_store=None,
    cwd: Optional[str] = None,
    tool_names: Optional[set] = None,
    persona: Optional[PersonaManifest] = None,   # ← 新增
) -> str:
    parts = []

    # Layer 1: 身份(专家替换 or SOUL.md)
    if persona and persona.soul_mode == "replace":
        parts.append(persona.system_prompt)               # 专家正文 = 唯一身份
    else:
        soul = load_soul_md()
        parts.append(soul if soul else DEFAULT_IDENTITY)
        if persona:                                        # soul_mode == "stack"
            parts.append(persona.system_prompt)           # 人格 + 角色叠加

    # Layer 2: 工具行为引导 —— 只对 persona 白名单内的工具注入 guidance
    effective_tools = persona.tools if (persona and persona.tools) else _tools
    for tool_name in effective_tools:
        guidance = _TOOL_GUIDANCE.get(tool_name)
        if guidance:
            parts.append(guidance)

    # ... Layer 7 记忆 / Layer 9 上下文文件 不变 ...

    # Skills 索引:persona.skills 优先展示,其余隐藏(渐进披露目录)
    if persona and persona.skills:
        skills_idx = build_skills_index(only=persona.skills)
    else:
        skills_idx = _get_skills_prompt_cached(available_tools=_tools)
    if skills_idx:
        parts.append(skills_idx)

    # ... Layer 10 模型标识 / 10.5 环境 / 11 环境提示 / 12 平台提示 不变 ...
    return "\n\n".join(p.strip() for p in parts if p.strip())
```

### 4.5 工具白名单(硬限制,复用 include)

`Agent` 构造与 `reload_system_prompt()` 时:

```python
# agent.py
def _get_tool_schemas(self) -> list[dict]:
    include = self.persona.tools if (self.persona and self.persona.tools) else None
    return registry.get_schemas(include=include)   # tools=[] → None → 全开
```

注意点:
- 白名单过滤后,`_TOOL_GUIDANCE` 也只对白名单内工具注入(见 4.4),避免"有指引无工具"
- `delegate_task` / `clarify` 等被 `_execute_tool` 拦截的工具,白名单未声明时对模型不可见,拦截分支不触发(无副作用)

### 4.6 会话绑定与切换

```
DB:   session 元数据新增 persona_id 列(参照 09-session.md 的 _migrate 增量迁移模式)
新会话:  CLI 参数 --persona <id> / 桌面选择器 / 缺省=无专家(行为与现状一致)
恢复会话: 读 persona_id → PersonaRegistry.resolve(id) → 注入 build_system_prompt
对话中切换: persona_activate(name) 工具 → 更新 session.persona_id
            → Agent.reload_system_prompt(persona=...) 下一轮生效
```

桌面端选择器(侧栏「专家」导航项,位于「对话」与「技能」之间):主区域切换为卡片墙,每张卡展示图标/名称/分类/一句话;点击卡片进入详情页(完整 description、工具白名单、捆绑技能、团员 chips、`default_init_prompt`,以及**完整 system_prompt 角色简介滚动展示**);卡片与详情页底部均有「应用」按钮 = 新建会话注入该专家并切回对话。数据来自 `GET /api/personas`(`manifest_to_dict` 透传完整 `system_prompt`)。

### 4.7 管理工具(`personas/tools.py`)

| 工具 | 行为 |
|------|------|
| `persona_list` | 列出可用专家:`名称(id) · 描述 · 来源 · [当前激活]` |
| `persona_view` | 查看专家详情:白名单、捆绑技能、soul_mode、正文预览(截断) |
| `persona_activate` | 切换当前会话专家:更新 session.persona_id + reload;参数为空 = 退出专家恢复默认 |

注册方式:复用 `src/minihermes/core/tools/registry.py` 的 `register(schema)`,schema 风格与 `skills_tool.py` 的 `skill_view` 一致。

### 4.8 内置专家示例(第一期 3 个)

```yaml
# src/minihermes/personas/builtin/go-backend-expert.md
---
id: go-backend-expert
name: Go 后端专家
icon: gopher
tagline: Go/Golang 后端开发专家
description: 精通 Go 服务端开发,擅长并发、性能优化、架构设计
category: engineering
tools: [bash, read_file, write_file, todo, search, skill_view, delegate_task, memory]
skills: [go-idioms]
soul_mode: replace
---
你是一位资深的 Go 后端工程师。写代码前先明确接口边界与并发模型;
优先使用标准库与官方推荐的惯用写法;关键路径给出复杂度分析;交付前自查编译与测试。
```

第一期建议:`go-backend-expert`(Go 后端)、`doc-writer`(文档/报告撰写)、`research-analyst`(深度研究)。

### 4.9 关键细节与风险

1. **注入检测**:`parse_persona_md` 正文必须过 `_scan_for_injection`(与 SOUL.md 同策略),防 prompt 注入。
2. **向后兼容**:无专家时 `build_system_prompt(persona=None)` 输出与现状逐字节一致;现有调用方不传 persona 即可。
3. **切换时机**:`persona_activate` 后**下一轮**生效(reload),当前轮不打断;切换不改会话历史,只换 system prompt 与工具集。
4. **白名单联动**:工具引导、skills 目录、schemas 三处都以 persona 白名单为准,避免"模型看到但用不了"。
5. **记忆归属**:沿用现有记忆层(不按专家分隔离);如需按专家隔离记忆,列入第二期。
6. **skills 隐藏策略**:专家会话中只展示捆绑技能(干净);如需全部技能可见,`frontmatter` 加 `skills_mode: all` 选项,列入第二期。

---

## 5. 实现阶段

### Phase 1(核心闭环)

1. `core/personas/manifest.py` — 数据模型 + 解析(复用 `parse_frontmatter`)
2. `core/personas/registry.py` — 目录扫描 + 注册表
3. `core/prompt/builder.py` — `build_system_prompt` 加 persona 参数与注入分支
4. `core/agent/agent.py` — Agent 持有 persona;`_get_tool_schemas` 白名单过滤;`reload_system_prompt` 支持 persona
5. 会话持久化 — sessions 表加 `persona_id`(增量迁移)
6. `core/personas/tools.py` — persona_list / persona_view / persona_activate
7. 内置专家 ×3(go-backend-expert / doc-writer / research-analyst)

### Phase 2(增强,后续)

- git/本地目录导入 + `consent_summary` 审批(移植 OpenWorker `loading.py`)
- 项目级 `personas/`(随 git 共享)
- persona 推荐模型 / 默认权限模式绑定
- 按专家隔离记忆
- `skills_mode: all` 选项

---

## 6. 附录:关键代码位置参考

| 文件 | 位置 | 说明 |
|------|------|------|
| `src/minihermes/core/prompt/builder.py` | `build_system_prompt` (L626) | 注入点(4.4) |
| `src/minihermes/core/prompt/builder.py` | `load_soul_md` (L226) | 身份层现有实现 |
| `src/minihermes/core/prompt/builder.py` | `_scan_for_injection` | 注入检测(复用) |
| `src/minihermes/core/prompt/builder.py` | `parse_frontmatter` (skills/manager.py L64) | frontmatter 解析(复用) |
| `src/minihermes/core/agent/agent.py` | `Agent.__init__` (L43) / `reload_system_prompt` (L117) | persona 挂载点 |
| `src/minihermes/core/agent/agent.py` | `_get_tool_schemas` (L86) | 白名单过滤点 |
| `src/minihermes/core/tools/registry.py` | `get_schemas(include=...)` (L49) | include 过滤(复用) |
| `src/minihermes/core/tools/skills_tool.py` | `skill_view` schema | 管理工具 schema 风格参照 |
| `src/minihermes/core/skills/manager.py` | `build_skills_index` (L465) | 捆绑技能索引 |
| `docs/09-session.md` | `_migrate()` | 会话表增量迁移模式参照 |
