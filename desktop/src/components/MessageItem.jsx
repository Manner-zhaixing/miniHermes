import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import ToolCallCard from './ToolCallCard.jsx';

/** DeepSeek 风格鲸鱼头像（SVG） */
export function WhaleAvatar({ size = 28 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <rect width="28" height="28" rx="8" fill="#E8F0FE" />
      <path
        d="M6.4 15.6C6.4 12.1 9.4 9.6 12.9 9.6C15.8 9.6 18.3 11.1 19.7 13.5C18.4 15.1 16.4 16.1 13.9 16.1C10.9 16.1 8.4 15.3 6.9 13.9C7.1 14.9 7.9 15.7 8.9 16.3C9.9 16.9 11.1 17.1 12.4 17.1C14.9 17.1 17.4 16.1 19.4 14.6C20.7 15.3 20.9 16.1 20.7 16.9C19.9 17.9 18.7 18.5 17.4 18.8C15.4 19.3 13.4 19.4 11.4 18.9C9.4 18.4 7.7 17.1 6.6 15.6Z"
        fill="#4D6BFE"
      />
      <path d="M19.7 13.5L22.6 11.9L21.6 14.8Z" fill="#4D6BFE" />
      <circle cx="11" cy="12.3" r="1" fill="#FFFFFF" />
      <path
        d="M13.9 8.9C13.9 8.1 14.3 7.3 14.9 6.6M13.3 8.7C12.9 7.9 12.9 6.9 13.1 6.1M12.7 8.5C12.1 7.9 11.7 7 11.8 6.1"
        stroke="#7CB8FF" strokeWidth="1.1" strokeLinecap="round" fill="none"
      />
    </svg>
  );
}

const TOOL_EMOJI = {
  bash: '💻', read_file: '📖', write_file: '✍️', list_dir: '📂',
  web_search: '🔍', todo: '📋', clarify: '❓', memory: '🧠',
  search_files: '🔎', execute_code: '🐍', delegate_task: '🤝',
  skill_view: '🧩', skill_manage: '🔧', session_search: '🔎',
  web_extract: '🌐', process_tool: '🖥', image_gen: '🎨',
};

function ThinkingBlock({ text, streaming }) {
  const [open, setOpen] = useState(false);
  const lines = (text || '').split('\n').filter(Boolean);
  if (lines.length === 0) return null;
  return (
    <div className="thinking-block">
      <button className="thinking-toggle" onClick={() => setOpen(!open)}>
        <span className="thinking-chevron">{open ? '▾' : '▸'}</span>
        <span className="thinking-label">思考过程</span>
        <span className="thinking-meta">{lines.length} 行</span>
        {streaming && <span className="thinking-dots">…</span>}
      </button>
      {open && (
        <pre className="thinking-content">{text}</pre>
      )}
    </div>
  );
}

const mdComponents = {
  code({ className, children, ...props }) {
    const isBlock = /language-/.test(className || '');
    if (isBlock) {
      return (
        <pre className="code-block">
          <code className={className}>{children}</code>
        </pre>
      );
    }
    return <code className="inline-code">{children}</code>;
  },
  a({ href, children }) {
    return (
      <a href={href} target="_blank" rel="noreferrer">{children}</a>
    );
  },
  table({ children }) {
    return <div className="table-wrap"><table>{children}</table></div>;
  },
};

export default function MessageItem({ msg, isLast, streaming }) {
  // 系统消息（命令结果等）
  if (msg.role === 'system') {
    return (
      <div className="msg-row system">
        <div className="msg-body">
          <pre className="system-msg">{msg.content}</pre>
        </div>
      </div>
    );
  }

  // 用户消息
  if (msg.role === 'user') {
    return (
      <div className="msg-row user">
        <div className="msg-body">
          <div className="msg-content user-bubble">{msg.content}</div>
        </div>
      </div>
    );
  }

  // 工具消息（历史恢复时的 tool 角色）
  if (msg.role === 'tool') {
    return (
      <div className="msg-row tool">
        <div className="msg-body">
          <ToolCallCard name={msg.toolName || 'tool'} status="done" result={msg.content} args="" />
        </div>
      </div>
    );
  }

  // assistant：按有序片段渲染（思考 / 工具 / 正文，类型切换即新开片段）
  const parts = msg.parts || [];
  const empty = parts.length === 0;
  return (
    <div className="msg-row assistant">
      <div className="msg-avatar"><WhaleAvatar size={28} /></div>
      <div className="msg-body">
        {parts.map((p, i) => {
          const isLastPart = i === parts.length - 1;
          const live = streaming && isLast && isLastPart;
          if (p.type === 'thinking') {
            return <ThinkingBlock key={i} text={p.text} streaming={live} />;
          }
          if (p.type === 'tool') {
            return (
              <ToolCallCard
                key={i}
                name={p.name}
                status={p.status}
                args={p.args}
                result={p.result}
                running={live && p.status === 'running'}
              />
            );
          }
          return (
            <div key={i} className="msg-content markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                {p.text || ''}
              </ReactMarkdown>
              {live && <span className="cursor-blink">▍</span>}
            </div>
          );
        })}
        {empty && streaming && isLast && (
          <div className="msg-content placeholder">
            <span className="cursor-blink">▍</span>
          </div>
        )}
      </div>
    </div>
  );
}
