"""WS 集成测试：模拟前端完整交互链路。"""
import asyncio
import json
import sys

import websockets

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else None
URL = f"ws://127.0.0.1:{PORT}/ws" if PORT else None


async def main():
    if URL is None:
        print("usage: python ws_test.py <port>")
        return
    async with websockets.connect(URL) as ws:
        events = []

        async def recv_until(pred, timeout=180):
            while True:
                ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
                events.append(ev)
                if pred(ev):
                    return ev

        # 1. 新建会话
        await ws.send(json.dumps({"type": "new_session"}))
        created = await recv_until(lambda e: e["type"] == "session_created")
        sid = created["session_id"]
        print(f"[ok] 新建会话: {sid}")

        # 2. 发送消息：让它读取一个文件（触发工具调用链路）
        await ws.send(json.dumps({
            "type": "send_message",
            "session_id": sid,
            "content": "请用 read_file 工具读取 /Users/camille/codeProjects/miniHermes/readme.md 的前 5 行，然后一句话总结这个项目是什么。",
        }))

        thinking_chars = 0
        delta_chars = 0
        tools = []
        final = None

        while True:
            ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=180))
            events.append(ev)
            t = ev["type"]
            if t == "thinking":
                thinking_chars += len(ev.get("text", ""))
            elif t == "delta":
                delta_chars += len(ev.get("text", ""))
            elif t == "tool_start":
                tools.append(("start", ev["tool_name"]))
                print(f"[tool] start: {ev['tool_name']}")
            elif t == "tool_result":
                tools.append(("result", ev["tool_name"], ev.get("status")))
                print(f"[tool] result: {ev['tool_name']} status={ev.get('status')} len={len(ev.get('result',''))}")
            elif t == "error":
                print(f"[FAIL] error: {ev}")
                sys.exit(1)
            elif t == "turn_end":
                final = ev
                break

        print(f"\n[ok] 思考流 {thinking_chars} 字符, 文本流 {delta_chars} 字符")
        print(f"[ok] 工具事件: {[(x[0], x[1]) for x in tools]}")
        print(f"[ok] 最终回复: {final['final_response'][:120]!r}")
        print(f"[ok] compressed={final.get('compressed')}")

        # 3. 恢复会话测试
        await ws.send(json.dumps({"type": "resume_session", "session_id": sid}))
        msgs = await recv_until(lambda e: e["type"] == "session_messages")
        roles = [m.get("role") for m in msgs["messages"]]
        print(f"[ok] 恢复会话: {len(msgs['messages'])} 条消息, roles={roles}")

        print("\n=== ALL PASS ===")


asyncio.run(main())
