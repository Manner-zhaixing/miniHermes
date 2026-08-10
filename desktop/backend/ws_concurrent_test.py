"""WS 并发集成测试：同一后端内多会话并行对话。

覆盖（需真实 LLM + 后端已启动，python server.py <port>）：
1. 两会话同时流式：delta/thinking/tool 事件交错、session_id 各自正确
2. 定向 interrupt：只停会话 A，B 不受影响照常完成
3. todo 会话隔离：会话 C 写任务列表，会话 D 读为空
4. persona 隔离：E 绑 doc-writer、F 绑 research-analyst，两 system_prompt 不同

用法: python ws_concurrent_test.py <port>
"""
import asyncio
import json
import sys
import time

import websockets

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else None
URL = f"ws://127.0.0.1:{PORT}/ws" if PORT else None

FAILURES = []


def fail(msg: str):
    FAILURES.append(msg)
    print(f"[FAIL] {msg}")


async def main():
    if URL is None:
        print("usage: python ws_concurrent_test.py <port>")
        return

    async with websockets.connect(URL, proxy=None) as ws:  # 本机回环不走代理
        buckets: dict[str, list[dict]] = {}  # sid -> 事件（按 arrival 顺序）
        order: list[dict] = []               # 全局事件序（交错分析用）
        T0 = time.monotonic()

        def route(ev: dict):
            t = ev.get("type")
            if t == "sessions":  # 全局事件，不参与 sid 路由
                return
            ev["_t"] = time.monotonic() - T0
            buckets.setdefault(ev.get("session_id", ""), []).append(ev)
            order.append(ev)

        async def recv_any(timeout=240) -> dict:
            ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
            route(ev)
            return ev

        async def recv_type(t, timeout=240) -> dict:
            while True:
                ev = await recv_any(timeout=timeout)
                if ev.get("type") == t:
                    return ev

        async def wait_for(sid, pred, timeout=240) -> dict:
            """等指定会话的某事件；期间收到的其他事件路由到各自 bucket。"""
            deadline = time.monotonic() + timeout
            while True:
                for e in buckets.get(sid, []):
                    if pred(e):
                        return e
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"等待会话 {sid} 事件超时")
                await recv_any(timeout=remaining)

        async def new_session(persona_id="") -> str:
            await ws.send(json.dumps({"type": "new_session", "persona_id": persona_id}))
            return (await recv_type("session_created"))["session_id"]

        # ── 1. 建普通会话 A/B，同时触发 bash sleep 3 ──────────────────────
        # 若并行：两会话的 tool_start 应在相近时刻到达，且任一 turn_end
        # 出现前两会话的 tool_start 都已到达（都在 sleep 中）。
        a = await new_session()
        b = await new_session()
        print(f"[ok] 会话 A/B 创建: {a} / {b}")

        await ws.send(json.dumps({"type": "send_message", "session_id": a,
                                  "content": '使用 bash 工具执行命令 `sleep 3`，完成后回复"这是会话A"。'}))
        await ws.send(json.dumps({"type": "send_message", "session_id": b,
                                  "content": '使用 bash 工具执行命令 `sleep 3`，完成后回复"这是会话B"。'}))

        ta = await wait_for(a, lambda e: e.get("type") == "tool_start" and e.get("tool_name") == "bash")
        tb = await wait_for(b, lambda e: e.get("type") == "tool_start" and e.get("tool_name") == "bash")
        gap = abs(ta["_t"] - tb["_t"])
        print(f"[info] A bash tool_start @ {ta['_t']:.2f}s, B @ {tb['_t']:.2f}s, 间隔 {gap:.2f}s")
        if gap > 8:
            fail(f"两会话 tool_start 间隔 {gap:.2f}s 过大，可能未真正并行")

        if any(e.get("type") == "turn_end" for e in buckets.get(a, [])) or \
           any(e.get("type") == "turn_end" for e in buckets.get(b, [])):
            fail("两会话 tool_start 到达前已有 turn_end")
        else:
            print("[ok] 两会话同时在 bash sleep 中（并发进行）")

        # ── 2. 定向 interrupt A：只停 A，B 照常完成 ──────────────────────
        await ws.send(json.dumps({"type": "interrupt", "session_id": a}))
        ia = await wait_for(a, lambda e: e.get("type") == "interrupted")
        print(f"[ok] A 收到 interrupted @ {ia['_t']:.2f}s")
        eb = await wait_for(b, lambda e: e.get("type") == "turn_end")
        print(f"[ok] B 未受影响，正常 turn_end，final={eb.get('final_response','')[:60]!r}")
        ea = await wait_for(a, lambda e: e.get("type") == "turn_end")
        print(f"[ok] A 中断收尾 turn_end，final={ea.get('final_response','')[:60]!r}")

        # ── 3. todo 会话隔离：C 写 3 条、D 读应为空 ──────────────────────
        c = await new_session()
        d = await new_session()
        print(f"[ok] 会话 C/D 创建: {c} / {d}")

        await ws.send(json.dumps({"type": "send_message", "session_id": c,
                                  "content": '请使用 todo 工具创建一个包含 3 个任务的列表（任务内容随意，id 用 1/2/3），完成后只回复"已创建"。'}))
        await wait_for(c, lambda e: e.get("type") == "turn_end")
        print("[ok] C 已写入 3 条 todo")

        await ws.send(json.dumps({"type": "send_message", "session_id": d,
                                  "content": '请使用 todo 工具读取当前任务列表，把工具返回的完整 JSON 原样粘贴在你的回复里，不要修改、不要总结。'}))
        ed = await wait_for(d, lambda e: e.get("type") == "turn_end")
        resp_d = ed.get("final_response", "")
        print(f"[info] D 读取结果: {resp_d[:200]!r}")
        if '"total": 0' in resp_d:
            print("[ok] todo 会话隔离：D 读到 total=0")
        else:
            fail(f"todo 隔离：D 未读到 total=0（可能串到 C 的列表）resp={resp_d[:200]!r}")

        # ── 4. persona 隔离：E/F 各绑专家，发一简短消息物化 runtime，再查 system_prompt ──
        e = await new_session("doc-writer")
        f = await new_session("research-analyst")
        print(f"[ok] 会话 E/F 创建: {e} / {f}")
        await ws.send(json.dumps({"type": "send_message", "session_id": e, "content": "回复：收到"}))
        await wait_for(e, lambda ev: ev.get("type") == "turn_end")
        await ws.send(json.dumps({"type": "send_message", "session_id": f, "content": "回复：收到"}))
        await wait_for(f, lambda ev: ev.get("type") == "turn_end")

        await ws.send(json.dumps({"type": "command", "cmd": "/sysprompt", "session_id": e}))
        spe = (await wait_for(e, lambda ev: ev.get("type") == "command_result"))["text"]
        await ws.send(json.dumps({"type": "command", "cmd": "/sysprompt", "session_id": f}))
        spf = (await wait_for(f, lambda ev: ev.get("type") == "command_result"))["text"]
        if spe != spf and "文档" in spe and ("研究" in spf or "research" in spf.lower()):
            print("[ok] persona 隔离：E/F system_prompt 不同（E 含文档专家、F 含研究专家）")
        else:
            fail("persona 隔离：E/F system_prompt 未体现出各自专家身份")
            print(f"      E 片段: {spe[:200]!r}")
            print(f"      F 片段: {spf[:200]!r}")

        # ── 汇总 ─────────────────────────────────────────────────────────
        total_ev = len(order)
        print(f"\n[info] 事件统计: 总 {total_ev}（A {len(buckets.get(a, []))}, B {len(buckets.get(b, []))}, "
              f"C {len(buckets.get(c, []))}, D {len(buckets.get(d, []))}）")
        interleaved = False
        for i, ev in enumerate(order):
            if ev.get("type") == "turn_start" and ev.get("session_id") in (a, b):
                for j in range(max(0, i - 3), min(len(order), i + 4)):
                    if j != i and order[j].get("session_id") not in (None, ev.get("session_id"), ""):
                        interleaved = True
        if interleaved:
            print("[ok] A/B 事件流交错（非严格串行）")
        else:
            fail("A/B 事件流未见交错")

        if FAILURES:
            print(f"\n=== {len(FAILURES)} FAIL ===")
            for m in FAILURES:
                print("  -", m)
            sys.exit(1)
        print("\n=== ALL PASS ===")


asyncio.run(main())
