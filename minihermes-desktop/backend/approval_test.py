"""Approval 流程测试：触发危险命令审批 → 模拟前端拒绝 → 验证工具被阻止。"""
import asyncio
import json
import os
import sys

import websockets

TARGET = "/tmp/mh_approval_test"


async def main():
    port = sys.argv[1]
    url = f"ws://127.0.0.1:{port}/ws"
    # 准备一个待删除目录
    os.makedirs(TARGET, exist_ok=True)
    with open(f"{TARGET}/keep.txt", "w") as f:
        f.write("keep me")

    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "new_session"}))
        while True:
            ev = json.loads(await ws.recv())
            if ev["type"] == "session_created":
                sid = ev["session_id"]
                break

        await ws.send(json.dumps({
            "type": "send_message",
            "session_id": sid,
            "content": f"请删除目录 {TARGET}（使用 bash rm 命令）。",
        }))

        approvals = 0
        denied_seen = False
        while True:
            ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=180))
            t = ev["type"]
            if t == "approval_request":
                approvals += 1
                print(f"[approval] tool={ev['tool_name']} desc={ev['description'][:60]!r}")
                # 模拟前端点击「拒绝」
                await ws.send(json.dumps({
                    "type": "approval_answer",
                    "request_id": ev["request_id"],
                    "answer": "deny",
                }))
            elif t == "tool_result":
                if ev["status"] == "error" or "denied" in ev.get("result", "").lower():
                    denied_seen = True
                    print(f"[tool_result] {ev['tool_name']} → {ev['result'][:80]!r}")
            elif t == "turn_end":
                break
            elif t == "error":
                print(f"[FAIL] {ev}")
                sys.exit(1)

        ok = os.path.isdir(TARGET)
        print(f"[ok] 收到审批请求 {approvals} 次, 拒绝生效={denied_seen}")
        print(f"[{'PASS' if ok else 'FAIL'}] 目录未被删除: {ok}")

        if approvals > 0 and ok:
            print("=== APPROVAL PASS ===")
        else:
            print("=== APPROVAL FAIL ===")
            sys.exit(1)


asyncio.run(main())
