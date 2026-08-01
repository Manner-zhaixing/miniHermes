import React, { useState } from 'react';

/** 每个工具类型的特定图标 */
const TOOL_EMOJI = {
  bash: '💻', read_file: '📖', write_file: '✍️', list_dir: '📂',
  web_search: '🔍', web_extract: '🌐', search_files: '🔎',
  todo: '📋', clarify: '❓', memory: '🧠',
  skill_view: '🧩', skill_manage: '🔧',
  execute_code: '🐍', delegate_task: '🤝',
  session_search: '🔎', process_tool: '🖥️', image_gen: '🎨',
};

const STATUS_LABEL = {
  running: '执行中',
  done: '完成',
  error: '失败',
  pending: '等待结果',
};

export default function ToolCallCard({ name, status, args, result, running }) {
  const [open, setOpen] = useState(false);
  const emoji = TOOL_EMOJI[name] || '⚡';
  const label = STATUS_LABEL[status] || status;

  return (
    <div className={`tool-card ${status} ${running ? 'running' : ''}`}>
      <button className="tool-card-head" onClick={() => setOpen(!open)} title={open ? '收起详情' : '展开详情'}>
        <span className="tool-emoji">{emoji}</span>
        <span className="tool-name">{name}</span>
        <span className={`tool-status ${status}`}>
          {running ? '执行中…' : label}
        </span>
        <span className="tool-chevron">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="tool-card-body">
          {args && (
            <pre className="tool-args">{typeof args === 'string' ? args : JSON.stringify(args, null, 2)}</pre>
          )}
          {result != null && result !== '' && (
            <pre className={`tool-result ${status === 'error' ? 'err' : ''}`}>{result}</pre>
          )}
        </div>
      )}
    </div>
  );
}
