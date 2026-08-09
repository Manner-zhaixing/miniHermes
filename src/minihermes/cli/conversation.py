"""后台对话循环线程。"""

from pathlib import Path

from minihermes.cli.state import AppState
from minihermes.cli.commands import handle_slash_command
from minihermes.cli.plan_ui import make_plan_approval_callback
from minihermes.core.services.plan import run_plan_flow, PLAN_MODE_PREFIX
from minihermes.core.services.context_ref import preprocess as preprocess_refs
from minihermes.core.output import _cprint, _AMBER, _BOLD, _DIM, _GOLD, _RST, print_error
from minihermes.cli.renderer import StreamRenderer
from minihermes.core.session import SessionDB


def _rebuild_provider(state: AppState) -> str:
    """按当前配置重建 Provider/Agent 并更新共享状态，返回新模型名。

    /provider /model 切换后调用：先刷新配置缓存，再以新解析结果构建
    Provider，复用现有 Agent（switch_provider 保留 callbacks / db）。
    """
    import minihermes.core.config as cfg
    from minihermes.core.provider import Provider

    cfg.reload_config()
    provider = Provider()
    if not provider.has_api_key:
        _cprint(f"\n{_AMBER}⚠ {provider.provider_name} 未配置 API Key，"
                f"首个请求将失败。用 /setup 或编辑 config.yaml 添加。{_RST}")
    state.agent.switch_provider(provider)
    state.model_name = provider.model
    state.context_window = provider.context_window
    return provider.model


def _handle_provider_command(user_input: str, state: AppState):
    """/provider [name]：列出预设厂商或切换当前厂商（立即生效）。"""
    import minihermes.core.config as cfg
    from minihermes.core.provider import provider_names, get_preset

    parts = user_input.strip().split(None, 1)
    arg = parts[1].strip() if len(parts) > 1 else ""
    names = provider_names()

    if not arg:
        active = cfg.get_provider_config().get("provider")
        lines = ["[available providers]"]
        for name in names:
            preset = get_preset(name)
            marker = " ◀ active" if name == active else ""
            title = preset.title if preset else name
            lines.append(f"  {name} — {title}{marker}")
        lines.append("[usage: /provider <name>]")
        print("\n".join(lines))
        return

    if arg not in names:
        print(f"[unknown provider: {arg}. Available: {', '.join(names)}]")
        return

    cfg.set_active_provider(arg)
    new_model = _rebuild_provider(state)
    print(f"[switched to provider: {arg} ({new_model})]")


def _handle_model_command(user_input: str, state: AppState):
    """/model [name]：列出当前厂商候选模型或切换模型（立即生效）。"""
    import minihermes.core.config as cfg
    from minihermes.core.provider import model_ids_for

    parts = user_input.strip().split(None, 1)
    arg = parts[1].strip() if len(parts) > 1 else ""

    if not arg:
        active = cfg.get_provider_config().get("provider")
        current = cfg.get_provider_config().get("name")
        candidates = model_ids_for(active)
        lines = [f"[model for {active}] current: {current}"]
        lines.append(f"  candidates: {', '.join(candidates) or '(none)'}")
        lines.append("[usage: /model <model-name>]")
        print("\n".join(lines))
        return

    active = cfg.get_provider_config().get("provider")
    cfg.set_provider_override(active, model=arg)
    new_model = _rebuild_provider(state)
    print(f"[switched model: {new_model}]")


def _handle_persona_command(user_input: str, state: AppState, db, agent):
    """/persona [list|view <id>|activate <id>|deactivate]：专家列表/详情/切换。

    CLI 可同会话切换：activate/deactivate 立即换身份与工具集，下一轮生效（不打断当前轮）。
    """
    from minihermes.core.personas import get_persona_registry

    parts = user_input.strip().split(None, 2)
    sub = parts[1].lower() if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""
    reg = get_persona_registry()

    if not sub or sub == "list":
        lines = ["[available personas] 本地自建: ~/.minihermes/personas/*.md"]
        for m in reg.list():
            kind = "team" if m.is_team() else "agent"
            marker = " ◀ active" if m.id == state.current_persona_id else ""
            blurb = m.tagline or (m.description[:40] if m.description else "")
            lines.append(f"  {m.id} [{kind}] — {m.name}: {blurb}{marker}")
        lines.append("[usage: /persona view <id> | /persona activate <id> | /persona deactivate]")
        print("\n".join(lines))
        return

    if sub == "view":
        if not arg:
            print("[usage: /persona view <id>]")
            return
        m = reg.get(arg)
        if not m:
            print(f"[unknown persona: {arg}]")
            return
        lines = [
            f"[{m.id} ({m.name})] 来源: {m.source} | 类型: {m.expert_type}",
            f"  图标: {m.icon or '-'} | 类别: {m.category} | soul_mode: {m.soul_mode}",
        ]
        if m.tagline:
            lines.append(f"  一句话: {m.tagline}")
        if m.description:
            lines.append(f"  描述: {m.description}")
        lines.append(f"  工具白名单: {', '.join(m.tools) or '(全开)'}")
        lines.append(f"  捆绑技能: {', '.join(m.skills) or '(无)'}")
        if m.is_team():
            members = ", ".join(mm.id for mm in m.resolved_members) or "(无)"
            lines.append(f"  团员: {members} | max_team_iterations: {m.max_team_iterations}")
        if m.default_init_prompt:
            lines.append(f"  激活开场: {m.default_init_prompt[:60]}{'...' if len(m.default_init_prompt) > 60 else ''}")
        lines.append(f"  正文预览: {m.system_prompt[:150]}{'...' if len(m.system_prompt) > 150 else ''}")
        print("\n".join(lines))
        return

    if sub == "activate":
        if not arg:
            print("[usage: /persona activate <id>]")
            return
        m = reg.resolve(arg)
        if m is None:
            print(f"[unknown persona: {arg}]")
            return
        agent.apply_persona(m)
        db.set_persona(state.session_id, m.id)
        state.current_persona_id = m.id
        print(f"[persona activated: {m.name} ({m.id}) — 下一轮生效]")
        return

    if sub == "deactivate":
        agent.apply_persona(None)
        db.set_persona(state.session_id, None)
        state.current_persona_id = ""
        print("[persona deactivated — 恢复默认行为]")
        return

    print(f"[unknown /persona subcommand: {sub}. usage: list | view <id> | activate <id> | deactivate]")


def _handle_slash_commands(user_input: str, agent, state, db, model_name: str):
    """处理斜杠命令。返回 (is_init_run, handled, should_skip)。

    should_skip 为 True 时调用方应跳过本轮对话。
    """
    is_init_run = user_input.strip().lower().startswith("/init")

    # /setup: 需要 run_in_terminal 桥接，单独处理
    if user_input.strip().lower().startswith("/setup"):
        state.status_text = f" ⚕ {model_name[:26]} │ configuring..."
        state.invalidate()
        from minihermes.cli.setup_wizard import run_setup_cli
        try:
            run_setup_cli(app_loop=state._main_loop)
        except Exception as e:
            print(f"[Setup error: {e}]")
        # 向导可能改了厂商/模型/上下文窗口 → 立即重建生效
        _rebuild_provider(state)
        state.status_text = f" ⚕ {state.model_name[:26]}"
        state.invalidate()
        return is_init_run, True

    # /provider /model: 运行时切换厂商/模型（需 state 更新共享状态，单独处理）
    if user_input.strip().lower().startswith("/provider"):
        _handle_provider_command(user_input, state)
        state.status_text = f" ⚕ {state.model_name[:26]}"
        state.invalidate()
        return is_init_run, True

    # /persona: 专家列表/详情/切换（需 state + db + agent，单独处理）
    if user_input.strip().lower().startswith("/persona"):
        _handle_persona_command(user_input, state, db, agent)
        state.status_text = f" ⚕ {model_name[:26]}"
        state.invalidate()
        return is_init_run, True

    if user_input.strip().lower().startswith("/model"):
        _handle_model_command(user_input, state)
        state.status_text = f" ⚕ {state.model_name[:26]}"
        state.invalidate()
        return is_init_run, True

    handled, history, sid, override_msg = handle_slash_command(
        user_input, state.conversation_history, db, state.session_id,
        agent=agent,
    )
    if handled:
        state.conversation_history = history
        if sid:
            state.session_id = sid
            # /clear 新建会话：继承当前专家（同一 Agent 实例已带 persona，补 DB 持久化）
            if user_input.strip().lower().startswith("/clear") and state.current_persona_id:
                db.set_persona(sid, state.current_persona_id)
            # /resume 恢复会话：带出绑定专家（读 DB → 重新 apply）
            if user_input.strip().lower().startswith("/resume"):
                from minihermes.core.personas import get_persona_registry
                pid = db.get_persona(sid) or ""
                m = get_persona_registry().resolve(pid) if pid else None
                agent.apply_persona(m)
                state.current_persona_id = pid
        if user_input.strip().lower().startswith("/compress"):
            agent.request_compress()
        agent.reset_token_tracking()
        state.status_text = f" ⚕ {model_name[:26]}"
        state.invalidate()
        return is_init_run, True

    return is_init_run, False


def _execute_plan_mode(agent, state, db, renderer, model_name: str,
                        user_input: str, plan_description: str):
    """执行 Plan Mode（只读规划 + 审批执行）。返回 (user_input, should_skip)。

    核心流程统一在 core/services/plan.run_plan_flow；这里只提供终端侧
    状态栏与审批回调（TUI 面板）。
    """
    state.command_running = True
    state.status_text = f" ⚕ {model_name[:26]} │ [PLAN] analyzing..."
    state.invalidate()

    try:
        exec_message = run_plan_flow(
            provider=agent.provider,
            db=db,
            renderer=renderer,
            session_id=state.session_id,
            plan_description=plan_description,
            base_system_prompt=agent.system_prompt,
            clarify_callback=agent.clarify_callback,
            approval=make_plan_approval_callback(state),
            on_plan_saved=lambda p: _cprint(f"\n{_DIM}Plan saved: {p}{_RST}"),
        )
    except KeyboardInterrupt:
        _cprint(f"\n{_GOLD}⚡ Plan interrupted{_RST}")
        state.command_running = False
        state.status_text = f" ⚕ {model_name[:26]}"
        state.invalidate()
        return user_input, True
    except Exception as e:
        print()
        print_error(f"Plan agent error: {e}")
        state.command_running = False
        state.status_text = f" ⚕ {model_name[:26]}"
        state.invalidate()
        return user_input, True

    if exec_message is None:
        _cprint(f"\n{_DIM}Plan cancelled.{_RST}")
        state.command_running = False
        state.status_text = f" ⚕ {model_name[:26]}"
        state.invalidate()
        return user_input, True

    _cprint(f"\n{_GOLD}▶ Executing plan...{_RST}\n")
    return exec_message, False


def _post_process(agent, state, db, result, is_init_run: bool,
                   model_name: str, context_window: int, user_input: str):
    """对话完成后的后处理：init 刷新、状态栏、session 跟踪。"""
    # /init 完成后：若 minihermes.md 已生成，刷新 system prompt
    if is_init_run:
        target = Path.cwd() / "minihermes.md"
        if target.is_file():
            agent.reload_system_prompt()
            agent.reset_token_tracking()
            _cprint(f"\n{_DIM}[minihermes.md created and loaded into system prompt]{_RST}")

    # 更新状态栏
    if agent.last_prompt_tokens > 0:
        percent = min(100, int(agent.last_prompt_tokens / context_window * 100))
        filled = round((percent / 100) * 8)
        bar = f"[{'█' * filled}{'░' * (8 - filled)}]"
        state.status_text = f" ⚕ {model_name[:26]} │ {bar} {percent}%"
    else:
        state.status_text = f" ⚕ {model_name[:26]}"
    state.invalidate()

    state.conversation_history = result.messages

    # 压缩后 session 可能改变
    if result.session_id and result.session_id != state.session_id:
        state.session_id = result.session_id

    # 第一轮自动设置 title
    user_turns = sum(1 for m in state.conversation_history if m["role"] == "user")
    if user_turns == 1:
        db.set_title(state.session_id, user_input[:10].rstrip())

    # 每 20 轮提示
    if user_turns > 0 and user_turns % 20 == 0:
        _cprint(
            f"\n{_DIM}[tip: {user_turns} turns. "
            f"Use /clear to start fresh if responses slow down.]{_RST}"
        )


def conversation_loop(
    state: AppState,
    db: SessionDB,
    renderer: StreamRenderer,
):
    """后台消费用户输入并驱动 agent 对话。在 daemon 线程中运行。"""
    while not state.should_exit:
        # 每轮从共享状态重取（/provider /model 切换后立即生效）
        agent = state.agent
        model_name = state.model_name
        context_window = state.context_window

        user_input = state.input_queue.get()
        if user_input is None:
            state.should_exit = True
            break

        # ── 斜杠命令 ──────────────────────────────────────────────
        is_init_run = False
        if user_input.startswith("/"):
            is_init_run, handled = _handle_slash_commands(
                user_input, agent, state, db, model_name)
            if handled:
                continue

        # ── Plan mode 检测与消息转换 ───────────────────────────────
        is_plan_mode = user_input.startswith(PLAN_MODE_PREFIX)
        plan_description = ""
        if is_plan_mode:
            plan_description = user_input[len(PLAN_MODE_PREFIX):]

        # ── @file 引用预处理 ──────────────────────────────────────
        if "@file:" in user_input:
            if is_plan_mode:
                # Plan 描述内的 @file 引用：展开后作为 plan_description 传给 run_plan_flow
                # （与桌面端 server.py 先展开再取描述保持一致）
                ref_result = preprocess_refs(plan_description, cwd=Path.cwd())
                for w in ref_result.warnings:
                    _cprint(f"{_AMBER}⚠ {w}{_RST}")
                plan_description = ref_result.message
            else:
                ref_result = preprocess_refs(user_input, cwd=Path.cwd())
                for w in ref_result.warnings:
                    _cprint(f"{_AMBER}⚠ {w}{_RST}")
                user_input = ref_result.message

        # 用户消息回显
        if is_plan_mode:
            _cprint(f"\n{_AMBER}{'─' * 40}{_RST}")
            _cprint(f"{_BOLD}● [PLAN] {plan_description or '(interactive)'}{_RST}\n")
        else:
            display_text = user_input[:200] + "..." if len(user_input) > 200 else user_input
            _cprint(f"\n{_AMBER}{'─' * 40}{_RST}")
            _cprint(f"{_BOLD}● {display_text}{_RST}\n")

        # ── Plan Mode ─────────────────────────────────────────────
        if is_plan_mode:
            user_input, skip_turn = _execute_plan_mode(
                agent, state, db, renderer, model_name,
                user_input, plan_description,
            )
            if skip_turn:
                continue

        # ── 执行 Agent ────────────────────────────────────────────
        state.command_running = True
        state.status_text = f" ⚕ {model_name[:26]} │ working..."
        state.invalidate()

        try:
            result = agent.run_conversation(
                user_message=user_input,
                history=state.conversation_history,
                renderer=renderer,
                session_id=state.session_id,
            )
        except KeyboardInterrupt:
            _cprint(f"\n{_GOLD}⚡ Interrupted{_RST}")
            state.command_running = False
            state.status_text = f" ⚕ {model_name[:26]}"
            state.invalidate()
            continue
        except Exception as e:
            print()
            print_error(f"Agent error: {e}")
            state.command_running = False
            state.status_text = f" ⚕ {model_name[:26]}"
            state.invalidate()
            continue

        state.command_running = False

        # ── 后处理 ────────────────────────────────────────────────
        _post_process(agent, state, db, result, is_init_run,
                       model_name, context_window, user_input)

    db.end_session(state.session_id, end_reason="user_exit")
