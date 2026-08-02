import React, { useEffect, useMemo, useRef, useState } from 'react';
import MessageItem, { WhaleAvatar } from './MessageItem.jsx';

function fmtDay(ts) {
  const d = new Date(ts);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return '今天';
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return '昨天';
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

/** 在消息之间插入日期分隔线 */
function withDividers(messages) {
  const out = [];
  let lastDay = null;
  messages.forEach((m, idx) => {
    const day = fmtDay(m.ts);
    if (day !== lastDay) {
      out.push({ id: `div_${idx}`, role: '__divider__', label: day });
      lastDay = day;
    }
    out.push(m);
  });
  return out;
}

export default function ChatView({
  messages, streaming, activeSid, cwd, modelName,
  tokens = { input: 0, output: 0, reasoning: 0 },
  fileCount, filesPanelOpen, onToggleFiles,
  onSend, onInterrupt, onTitleEdited,
  onCommand, commands = [], stopRequested = false,
  onChangeCwd, mode = 'normal', onModeChange,
}) {
  const [draft, setDraft] = useState('');
  const listRef = useRef(null);
  const inputRef = useRef(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, streaming]);

  const handleKeyDown = (e) => {
    // 命令补全列表键盘导航
    if (showCmdList && matchedCommands.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setCmdActive((i) => (i + 1) % matchedCommands.length);
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setCmdActive((i) => (i - 1 + matchedCommands.length) % matchedCommands.length);
        return;
      }
      if (e.key === 'Tab') {
        e.preventDefault();
        pickCommand(matchedCommands[cmdActive]);
        return;
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (showCmdList && matchedCommands.length > 0) {
        pickCommand(matchedCommands[cmdActive]);
        return;
      }
      submit();
    } else if (e.key === 'Escape') {
      setShowCmdList(false);
    }
  };

  /** 命令补全下拉：输入以 / 开头时显示 */
  const [showCmdList, setShowCmdList] = useState(false);
  const [cmdActive, setCmdActive] = useState(0);

  const matchedCommands = useMemo(() => {
    const kw = draft.startsWith('/') ? draft.toLowerCase() : '';
    if (!kw) return [];
    return (commands || []).filter((c) => c.cmd.startsWith(kw) || kw === '/');
  }, [draft, commands]);

  const onDraftChange = (v) => {
    setDraft(v);
    setCmdActive(0);
    setShowCmdList(v.startsWith('/') && !v.includes(' '));
  };

  const pickCommand = (c) => {
    setDraft(c.has_arg ? `${c.cmd} ` : c.cmd);
    setShowCmdList(false);
    inputRef.current?.focus();
  };

  const submit = () => {
    const text = draft.trim();
    if (!text || streaming) return;
    setShowCmdList(false);
    setDraft('');
    if (text.startsWith('/')) {
      onCommand(text);
    } else if (mode === 'plan') {
      // Plan 模式：自动注入 __PLAN_MODE__: 前缀，后端进入只读规划流程
      onSend(`__PLAN_MODE__:${text}`);
    } else {
      onSend(text);
    }
    inputRef.current?.focus();
  };

  /** 上传文件：Electron 走系统文件选择器，选中的路径以 @file: 引用插入输入框 */
  const onAttachFile = async () => {
    try {
      if (window.desktop && window.desktop.openFileDialog) {
        const res = await window.desktop.openFileDialog();
        if (res && res.canceled === false && res.paths && res.paths.length > 0) {
          insertFileRef(res.paths[0]);
        }
        return;
      }
      // 浏览器调试模式：用隐藏 input 选择文件（仅拿到文件名占位）
      if (fileInputRef.current) {
        fileInputRef.current.click();
      }
    } catch (_e) { /* ignore */ }
  };

  const insertFileRef = (p) => {
    const ref = /[\s"']/.test(p) ? `@file:"${p}"` : `@file:${p}`;
    setDraft((d) => (d ? `${d} ${ref}` : ref));
    inputRef.current?.focus();
  };

  const onBrowserFilePick = (e) => {
    const f = e.target.files && e.target.files[0];
    if (f) insertFileRef(f.name);
    e.target.value = '';
  };

  const activeTitle = (() => {
    if (!activeSid) return '';
    return activeSid.split('_').slice(-1)[0] || activeSid;
  })();

  const rows = withDividers(messages);

  return (
    <div className="chat-view">
      {/* 顶部工具栏：工作目录选择器 + Plan 模式开关 */}
      <div className="chat-toolbar">
        <button className={`cwd-picker ${cwd ? '' : 'empty'}`} onClick={onChangeCwd} title="选择工作目录（Agent 的工具/文件操作基于此目录）">
          <span className="cwd-picker-ic">📁</span>
          <span className="cwd-picker-path">{cwd || '选择工作目录…'}</span>
          <span className="cwd-picker-btn">切换</span>
        </button>
        <div className="mode-switch" title="Plan 模式：先只读分析并生成实施计划，审批后执行；普通模式：直接执行">
          <button
            className={`mode-btn ${mode === 'plan' ? '' : 'active'}`}
            onClick={() => onModeChange('normal')}
          >普通</button>
          <button
            className={`mode-btn ${mode === 'plan' ? 'active' : ''}`}
            onClick={() => onModeChange('plan')}
          >📋 Plan</button>
        </div>
      </div>

      <div className="chat-header">
        <div className="chat-header-info">
          <span className="chat-title">对话 {activeTitle}</span>
          {modelName && <em className="model-chip">{modelName}</em>}
        </div>
        <button
          className={`files-toggle ${filesPanelOpen ? 'active' : ''}`}
          onClick={onToggleFiles}
          title="成果文件面板"
        >
          <span className="files-toggle-ic" />
          成果{fileCount > 0 ? ` (${fileCount})` : ''}
        </button>
      </div>

      <div className="message-list" ref={listRef}>
        {messages.length === 0 && !streaming && (
          <div className="empty-state">
            <div className="empty-logo"><WhaleAvatar size={60} /></div>
            <h2>MiniHermes Desktop</h2>
            <p>底层内核 minihermes · 工具调用 / 记忆 / 技能</p>
            <p className="empty-hint">开始输入你的问题吧 👇</p>
          </div>
        )}
        {rows.map((m, i) => {
          if (m.role === '__divider__') {
            return <div key={m.id} className="date-divider">{m.label}</div>;
          }
          return (
            <MessageItem
              key={m.id}
              msg={m}
              isLast={i === rows.length - 1}
              streaming={streaming && i === rows.length - 1}
            />
          );
        })}
      </div>

      <div className="input-area">
        <input
          ref={fileInputRef}
          type="file"
          style={{ display: 'none' }}
          onChange={onBrowserFilePick}
        />
        <div className="input-box">
          <textarea
            ref={inputRef}
            value={draft}
            onChange={(e) => onDraftChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入消息…（Enter 发送，Shift+Enter 换行，/ 命令，@file: 引用文件）"
            rows={Math.min(8, Math.max(2, draft.split('\n').length + 1))}
          />
          {showCmdList && matchedCommands.length > 0 && (
            <div className="cmd-popup">
              {matchedCommands.map((c, i) => (
                <button
                  key={c.cmd}
                  className={`cmd-item ${i === cmdActive ? 'active' : ''}`}
                  onMouseEnter={() => setCmdActive(i)}
                  onClick={() => pickCommand(c)}
                >
                  <span className="cmd-name">{c.cmd}</span>
                  <span className="cmd-desc">{c.desc}</span>
                </button>
              ))}
            </div>
          )}
          <div className="input-actions">
            <button className="attach-btn" onClick={onAttachFile} title="上传文件（以 @file 引用注入）">
              <span className="attach-ic">📎</span>
            </button>
            <span className="stats-model" title="当前模型">{modelName || '未配置模型'}</span>
            <TokenRing
              used={(tokens.input || 0) + (tokens.output || 0)}
              total={tokens.context_window || 1000000}
            />
            <span className="stats-num" title="上下文占用 tokens">
              {fmtTokens((tokens.input || 0) + (tokens.output || 0))} / {fmtTokens(tokens.context_window || 1000000)}
            </span>
            <span className="actions-spacer" />
            {streaming ? (
              <button
                className="btn stop"
                onClick={onInterrupt}
                disabled={stopRequested}
                title={stopRequested ? '已发送停止请求，等待内核响应…' : '停止当前回复'}
              >
                {stopRequested ? '⏹ 正在停止…' : '⏹ 停止'}
              </button>
            ) : (
              <button
                className="btn send"
                onClick={submit}
                disabled={!draft.trim()}
              >
                发送 ➤
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/** 圆形上下文进度条 */
function TokenRing({ used, total }) {
  const pct = total > 0 ? Math.min(100, Math.max(0, (used / total) * 100)) : 0;
  const r = 15.2;
  const c = 2 * Math.PI * r;
  const offset = c * (1 - pct / 100);
  const label = total > 0 ? `${pct < 10 ? pct.toFixed(1) : Math.round(pct)}%` : '0%';
  return (
    <span className="token-ring" title={`上下文占用 ${used.toLocaleString()} / ${total.toLocaleString()} tokens (${label})`}>
      <svg width="32" height="32" viewBox="0 0 36 36">
        <circle cx="18" cy="18" r={r} fill="none" stroke="var(--border)" strokeWidth="3.4" />
        <circle
          cx="18" cy="18" r={r} fill="none"
          stroke={pct > 85 ? 'var(--danger)' : 'var(--accent)'}
          strokeWidth="3.4" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={offset}
          transform="rotate(-90 18 18)"
        />
        <text x="18" y="18.6" textAnchor="middle" dominantBaseline="central"
          fontSize="8.5" fontWeight="500" fill="var(--text-dim)">{label}</text>
      </svg>
    </span>
  );
}

function fmtTokens(n) {
  if (!n || n <= 0) return '0';
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}
