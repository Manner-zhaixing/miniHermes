# todo — 任务列表管理

代码: `tools/todo.py`

> 多会话并行（桌面后端）：任务列表按「线程当前会话」隔离分桶
> （`_items_map` 以 `runtime_ctx.current_sid()` 为键，未设置走 `""`）。
> 每个会话的 turn 跑在独立线程，thread-local 注入当前 sid，不同会话的
> todo 互不污染；CLI 单会话恒走 `""` 桶，行为不变。

---

## Schema 设计

```python
{
    "name": "todo",
    "parameters": {
        "todos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "status": {"enum": ["pending", "in_progress", "completed", "cancelled"]},
                    "activeForm": {"type": "string"}
                }
            }
        },
        "merge": {"type": "boolean", "default": False}
    },
    "required": []
}
```

## 实现

```python
_items: list[dict] = []  # 模块级全局（session 内共享）

def todo(todos: list[dict] = None, merge: bool = False) -> str:
    global _items

    if todos is None:
        return _format_output()  # 只读模式

    validated = _validate(todos)

    if merge:
        # 增量合并：按 id 匹配更新
        existing = {t["id"]: t for t in _items if "id" in t}
        for t in validated:
            if t.get("id") in existing:
                existing[t["id"]].update(t)
            else:
                _items.append(t)
    else:
        _items = validated  # 全量替换

    return _format_output()
```

## 关键设计点

### 纯内存存储

任务列表不持久化到 DB——session 结束即清除。`reset()` 在 session 切换时被调用。

### 两种更新模式

- **replace** (merge=False): 全量替换列表。LLM 维护完整任务视图时使用。
- **merge** (merge=True): 按 id 增量更新。只修改部分任务时避免全量传输。

### 无参调用 = 只读

`todos=None` 时返回当前列表的格式化输出，不修改。

### ID-based 合并

合并模式下按 `id` 字段匹配，防止重复条目。新增条目（无 id 或新 id）直接追加。

### 四种状态

`pending` / `in_progress` / `completed` / `cancelled` — 覆盖任务完整生命周期。

### activeForm 字段

进行中任务的现在时表述（如 "Installing dependencies"），增强可读性。
