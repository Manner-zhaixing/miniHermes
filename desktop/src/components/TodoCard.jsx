import React, { useState } from 'react';

/** todo 状态图标（与 CLI _render_todo 一致） */
const TODO_ICON = {
  completed: '✔',
  in_progress: '▶',
  pending: '○',
  cancelled: '✘',
};

/** todo 工具卡片：折叠态（默认）渲染选项列表 + 进展（UI 美化）；
 *  展开态只给原始的工具输入输出内容（args + result 原样），不渲染选项列表。 */
export default function TodoCard({ result, args, running }) {
  const [expanded, setExpanded] = useState(false);

  // 解析 result（字符串 JSON 或对象）→ data；同时保留原始文本 raw 供展开态展示
  let data = null;
  let raw = result;
  if (typeof result === 'string') {
    raw = result;
    try { data = JSON.parse(result); } catch { data = null; }
  } else if (result && typeof result === 'object') {
    data = result;
    raw = JSON.stringify(result, null, 2);
  }

  const todos = data && Array.isArray(data.todos) ? data.todos : null;
  const summary = data && data.summary ? data.summary : {};
  const argsRaw = args == null || args === ''
    ? ''
    : (typeof args === 'string' ? args : JSON.stringify(args, null, 2));

  const chevron = expanded ? '▾' : '▸';

  // 非 todo 结构 / 运行中尚无数据 → 回退迷你卡片（同样两态）
  if (!todos) {
    return (
      <div className="todo-card">
        <button className="todo-head" onClick={() => setExpanded(!expanded)}
          title={expanded ? '收起原始输出' : '展开原始输出'}>
          <span className="tool-emoji">📋</span>
          <span className="todo-title">todo</span>
          <span className={`tool-status ${running ? 'running' : 'done'}`}>
            {running ? '执行中…' : '完成'}
          </span>
          <span className="tool-chevron">{chevron}</span>
        </button>
        {expanded && raw != null && raw !== '' && (
          <div className="todo-detail">
            <pre className="tool-result">{raw}</pre>
          </div>
        )}
      </div>
    );
  }

  const total = summary.total != null ? summary.total : todos.length;
  const done = summary.completed != null
    ? summary.completed
    : todos.filter(t => t.status === 'completed').length;
  const inProgress = summary.in_progress != null
    ? summary.in_progress
    : todos.filter(t => t.status === 'in_progress').length;
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;

  return (
    <div className="todo-card">
      <button className="todo-head" onClick={() => setExpanded(!expanded)}
        title={expanded ? '收起原始输出' : '展开原始输出'}>
        <span className="tool-emoji">📋</span>
        <span className="todo-title">Tasks</span>
        <span className="todo-summary">{done}/{total} done</span>
        {inProgress > 0 && <span className="todo-progress-badge">▶ {inProgress} 进行中</span>}
        <span className="todo-detail-label">{expanded ? '原始输出' : '查看原始输出'}</span>
        <span className="tool-chevron">{chevron}</span>
      </button>

      {expanded ? (
        <div className="todo-detail">
          {argsRaw && <pre className="tool-args">{argsRaw}</pre>}
          {raw != null && raw !== '' && <pre className="tool-result">{raw}</pre>}
        </div>
      ) : (
        <div className="todo-body">
          <div className="todo-progress-track">
            <div className="todo-progress-bar" style={{ width: `${pct}%` }} />
          </div>
          {todos.length === 0 ? (
            <div className="todo-empty">(empty list)</div>
          ) : (
            <ul className="todo-list">
              {todos.map((t, i) => {
                const status = t.status || 'pending';
                const icon = TODO_ICON[status] || '?';
                return (
                  <li key={t.id || i} className={`todo-item ${status}`}>
                    <span className="todo-icon">{icon}</span>
                    <span className="todo-content">{t.content}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
