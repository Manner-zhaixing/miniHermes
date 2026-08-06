"""验证成果面板数据链路：Agent 写文件 → file_written 事件 → files API 恢复。"""
import asyncio
import json
import sys

import websockets


async def main():
    port = sys.argv[1]
    url = f"ws://127.0.0.1:{port}/ws"
    base = f"http://127.0.0.1:{port}"

    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "new_session"}))
        while True:
            ev = json.loads(await ws.recv())
            if ev["type"] == "session_created":
                sid = ev["session_id"]
                break
        print(f"[ok] 新会话 {sid}")

        target = "/tmp/mh_artifact_test.md"
        await ws.send(json.dumps({
            "type": "send_message",
            "session_id": sid,
            "content": (
                f"请用 write_file 工具写一个文件：路径 {target}，"
                "内容是 '# 成果面板测试\\n\\n这是一份测试文档。'，然后告诉我写完了。"
            ),
        }))

        file_events = []
        while True:
            ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=180))
            t = ev["type"]
            if t == "file_written":
                file_events.append(ev)
                print(f"[file_written] {ev['path']} (sid={ev.get('session_id')})")
            elif t == "turn_end":
                break
            elif t == "error":
                print(f"[FAIL] {ev}")
                sys.exit(1)

        # 验证事件带 session_id 且路径正确
        ok_event = any(fe.get("session_id") == sid and target in fe.get("path", "") for fe in file_events)
        print(f"[{'PASS' if ok_event else 'FAIL'}] file_written 事件推送: {len(file_events)} 条")

        # 验证文件确实写成功
        import os
        ok_file = os.path.exists(target)
        print(f"[{'PASS' if ok_file else 'FAIL'}] 文件实际存在")

        # 验证恢复 API
        import urllib.request
        with urllib.request.urlopen(f"{base}/api/sessions/{sid}/files") as r:
            data = json.loads(r.read())
        paths = [f["path"] for f in data.get("files", [])]
        ok_restore = any(target in p for p in paths)
        print(f"[{'PASS' if ok_restore else 'FAIL'}] files API 恢复: {paths}")

        if ok_event and ok_file and ok_restore:
            print("=== ARTIFACT PASS ===")
        else:
            print("=== ARTIFACT FAIL ===")
            sys.exit(1)


asyncio.run(main())
