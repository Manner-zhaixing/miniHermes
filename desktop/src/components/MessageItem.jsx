import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize';
import ToolCallCard from './ToolCallCard.jsx';
import TodoCard from './TodoCard.jsx';
import MermaidDiagram from './MermaidDiagram.jsx';

// 模型输出 HTML 图的消毒 schema：默认 schema 已允许 code 的 language-* className；
// 补放开全局 style/className，让模型的内联样式 HTML 图能渲染。script/事件/javascript: 仍被默认剥除。
const sanitizeSchema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    '*': [...(defaultSchema.attributes['*'] || []), 'className', 'style'],
  },
};

/** rehype 插件：修复 rehype-raw（hast-util-raw 重序列化）在表格周围把表内空白
 *  文本节点提升为巨型换行节点的问题——把纯空白文本节点压到 ≤1 空行（\n\n），
 *  消除正文里的大段空行。pre/code/script/style/textarea 等空白有语义的容器跳过。 */
function rehypeCollapseWhitespace() {
  const SIGNIFICANT = new Set(['pre', 'code', 'script', 'style', 'textarea']);
  const walk = (node) => {
    if (!node || !Array.isArray(node.children)) return;
    if (SIGNIFICANT.has(String(node.tagName || '').toLowerCase())) return;
    const out = [];
    let sawBlank = false; // out 尾部是否已压入一个空行节点（连续空白只留一个）
    for (const child of node.children) {
      if (child.type === 'text' && !/\S/.test(child.value)) {
        // 纯空白文本节点：含换行 → 合并为 1 个空行；仅空格/制表符 → 丢弃
        if (/(\n|\r)/.test(child.value) && !sawBlank) {
          out.push({ type: 'text', value: '\n\n' });
          sawBlank = true;
        }
        continue;
      }
      sawBlank = false;
      walk(child);
      out.push(child);
    }
    // 去掉容器末尾的空白文本节点（raw HTML 块常以换行结尾）
    while (out.length && out[out.length - 1].type === 'text' && !/\S/.test(out[out.length - 1].value)) {
      out.pop();
    }
    node.children = out;
  };
  return walk;
}

/** rehype 管道：raw（模型可输出内联 HTML 图）→ sanitize（剥脚本/事件/javascript:）
 *  → 空白折叠（修复 rehype-raw 在表格周围注入巨型空行的 bug）。顺序固定。 */
const REHYPE_PLUGINS = [rehypeRaw, [rehypeSanitize, sanitizeSchema], rehypeCollapseWhitespace];

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

/** 中文 LLM 输出预处理：
 *  - 全角盒线分隔行（━━━ / ─── 等）→ markdown hr（---）；盒线+标题+盒线 → ### 标题
 *  - 非代码块内连续 ≥2 空行折叠为 1、去掉首尾空行（配合 pre-wrap 防「空行太多」）
 *  - 行尾去 \r；代码围栏（``` / ~~~）内部逐行原样保留，不折叠空行、不改写内容 */
function preprocessMd(text) {
  if (!text) return text;
  const lines = text.split('\n');
  const out = [];
  let inCode = false;
  let blankRun = 0; // 连续空行计数（流式围栏状态失同步时也把空行压到上限，避免巨大空档）
  const lastIsBlank = () => out.length === 0 || out[out.length - 1].trim() === '';
  for (const line of lines) {
    const cleaned = line.replace(/\r$/, '');
    const trimmed = cleaned.trim();
    const fence = trimmed.match(/^(`{3,}|~{3,})/);
    if (fence) inCode = !inCode;
    const isBlank = trimmed === '';
    blankRun = isBlank ? blankRun + 1 : 0;
    if (isBlank) {
      if (!inCode) {
        // 围栏外：连续空行折叠为 1
        if (lastIsBlank()) continue;
      } else if (blankRun > 2) {
        // 围栏内：空行最多保留 2（真实代码 PEP8/JS 风格本就要求 ≤2 空行）
        continue;
      }
      out.push(cleaned);
      continue;
    }
    if (!inCode) {
      if (/^[─-╿―—\s]+$/.test(trimmed)) {
        if (!lastIsBlank()) out.push('');
        out.push('---');
        out.push('');
        continue;
      }
      const m = trimmed.match(/^[─-╿―—]+\s*(.+?)\s*[─-╿―—]+$/);
      if (m) {
        if (!lastIsBlank()) out.push('');
        out.push('### ' + m[1]);
        out.push('');
        continue;
      }
    }
    out.push(cleaned);
  }
  while (out.length && out[out.length - 1].trim() === '') out.pop();
  return out.join('\n');
}

/** 渲染子代理内的单个 part（thinking / tool / text） */
function renderSubagentPart(p, i, live) {
  if (p.type === 'thinking') {
    return <ThinkingBlock key={i} text={p.text} streaming={live} />;
  }
  if (p.type === 'tool') {
    if (p.name === 'todo') {
      return <TodoCard key={i} result={p.result} args={p.args} running={live && p.status === 'running'} />;
    }
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
    <div key={i} className="msg-content markdown subagent-text">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={REHYPE_PLUGINS}
        components={buildMdComponents(live)}
      >
        {preprocessMd(p.text || '')}
      </ReactMarkdown>
    </div>
  );
}

function SubagentCard({ part, live }) {
  const [open, setOpen] = useState(false);
  const innerParts = part.parts || [];
  const task = part.task || '';
  const truncated = task.length > 60 ? task.slice(0, 60) + '…' : task;
  return (
    <div className={`subagent-block ${part.status || ''}`}>
      <button className="subagent-toggle" onClick={() => setOpen(!open)} title={open ? '收起' : '展开'}>
        <span className="subagent-chevron">{open ? '▾' : '▸'}</span>
        <span className="subagent-icon">🤝</span>
        <span className="subagent-task">{truncated || '子代理任务'}</span>
        <span className="subagent-meta">
          {innerParts.length} 条记录
          {part.status === 'done' ? ' · 完成' : (live ? ' · 执行中' : '')}
        </span>
      </button>
      {open && (
        <div className="subagent-content">
          {innerParts.length === 0 ? (
            <div className="subagent-empty">(无事件)</div>
          ) : (
            innerParts.map((p, i) => renderSubagentPart(p, i, live))
          )}
        </div>
      )}
    </div>
  );
}

/** 构建 markdown 渲染组件。live=true（streaming 中）时 mermaid 先显示源码，
 *  结束后才渲染成图（避免对不完整语法反复渲染/报错）。 */
function buildMdComponents(live) {
  return {
    code({ className, children, node, ...props }) {
      if (className === 'language-mermaid') {
        const raw = String(
          node && node.children && node.children[0] ? node.children[0].value : (children || '')
        );
        if (live) {
          return (
            <pre className="code-block">
              <code className={className}>{raw}</code>
            </pre>
          );
        }
        return <MermaidDiagram code={raw} />;
      }
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
}

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
          {msg.toolName === 'todo' ? (
            <TodoCard result={msg.content} args="" />
          ) : (
            <ToolCallCard name={msg.toolName || 'tool'} status="done" result={msg.content} args="" />
          )}
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
            if (p.name === 'todo') {
              return <TodoCard key={i} result={p.result} args={p.args} running={live && p.status === 'running'} />;
            }
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
          if (p.type === 'subagent') {
            return <SubagentCard key={i} part={p} live={live} />;
          }
          return (
            <div key={i} className="msg-content markdown">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={REHYPE_PLUGINS}
                components={buildMdComponents(live)}
              >
                {preprocessMd(p.text || '')}
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
