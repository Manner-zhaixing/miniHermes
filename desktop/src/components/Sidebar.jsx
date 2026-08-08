import React, { useMemo, useState } from 'react';
import { WhaleAvatar } from './MessageItem.jsx';
import ProviderIcon from './ProviderIcon.jsx';

const APP_VERSION = 'v0.1.0'; // 与 package.json version 保持一致

const ICONS = {
  chat: '💬',
  skills: '🧩',
  settings: '⚙️',
};

function fmtTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay
    ? d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
}

function groupLabel(ts) {
  if (!ts) return '更早';
  const d = new Date(ts * 1000);
  const now = new Date();
  const day = 86400000;
  const diff = Math.floor((now - d) / day);
  if (diff <= 0) return '今天';
  if (diff < 7) return '最近 7 天';
  return '更早';
}

export default function Sidebar({
  sessions, activeSid, view, providerInfo, connected,
  onNewSession, onResume, onDelete, onView,
}) {
  const [filter, setFilter] = useState('');

  const grouped = useMemo(() => {
    const kw = filter.trim().toLowerCase();
    const filtered = kw
      ? sessions.filter((s) => (s.title || '').toLowerCase().includes(kw))
      : sessions;
    const groups = { '今天': [], '最近 7 天': [], '更早': [] };
    filtered.forEach((s) => {
      const label = groupLabel(s.started_at);
      (groups[label] || groups['更早']).push(s);
    });
    return Object.entries(groups).filter(([, list]) => list.length > 0);
  }, [sessions, filter]);

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="logo">
          <span className="logo-mark"><WhaleAvatar size={32} /></span>
          <div className="logo-text">
            <span className="logo-title">MiniHermes</span>
            <span className="logo-sub">Desktop {APP_VERSION}</span>
          </div>
        </div>

        <nav className="sidebar-nav">
          <button
            className={`nav-item ${view === 'chat' ? 'active' : ''}`}
            onClick={() => onView('chat')}
          >
            <span className="nav-icon">{ICONS.chat}</span> 对话
          </button>
          <button
            className={`nav-item ${view === 'skills' ? 'active' : ''}`}
            onClick={() => onView('skills')}
          >
            <span className="nav-icon">{ICONS.skills}</span> 技能
          </button>
          <button
            className={`nav-item ${view === 'settings' ? 'active' : ''}`}
            onClick={() => onView('settings')}
          >
            <span className="nav-icon">{ICONS.settings}</span> 设置
          </button>
        </nav>

        <button className="new-chat-btn" onClick={onNewSession} title="新建会话">
          <span>+</span> 新会话
        </button>
      </div>

      <input
        className="session-search"
        placeholder="搜索会话…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />

      <div className="session-list">
        {sessions.length === 0 && (
          <div className="session-empty">暂无会话</div>
        )}
        {grouped.map(([label, list]) => (
          <div key={label}>
            <div className="session-group-label">{label}</div>
            {list.map((s) => (
              <div
                key={s.id}
                className={`session-item ${s.id === activeSid ? 'active' : ''}`}
                onClick={() => onResume(s.id)}
                title={s.id}
              >
                <div className="session-item-main">
                  <div className="session-title">{s.title}</div>
                  <div className="session-meta">
                    {fmtTime(s.started_at)} · {s.message_count} 条
                  </div>
                </div>
                <button
                  className="session-delete"
                  title="删除会话"
                  onClick={(e) => { e.stopPropagation(); onDelete(s.id); }}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        ))}
      </div>

      <div className="sidebar-footer">
        <div className="footer-status-row">
          <div className={`status-dot ${connected ? 'ok' : 'off'}`} />
          {providerInfo && <ProviderIcon name={providerInfo.name} title={providerInfo.title} size={14} />}
          <span className="footer-model" title={providerInfo ? `${providerInfo.title} · ${providerInfo.model}` : ''}>
            {providerInfo ? providerInfo.model || '未配置模型' : '未配置模型'}
          </span>
          <span className="footer-status">{connected ? '内核在线' : '重连中…'}</span>
        </div>
      </div>
    </aside>
  );
}
