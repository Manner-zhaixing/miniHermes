import React, { useMemo, useState } from 'react';
import { WhaleAvatar } from './MessageItem.jsx';
import ProviderIcon from './ProviderIcon.jsx';

const APP_VERSION = 'v0.1.4'; // 与 package.json version 保持一致

const ICONS = {
  chat: '💬',
  skills: '🧩',
  settings: '⚙️',
};

/** 相对时间：今天 → HH:MM；昨天 → 昨天；7 天内 → 周X；同年 → MM-DD；跨年 → YY-MM-DD */
function relTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const now = new Date();
  const startOfDay = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.floor((startOfDay(now) - startOfDay(d)) / 86400000);
  if (days <= 0) return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  if (days === 1) return '昨天';
  if (days < 7) return d.toLocaleDateString('zh-CN', { weekday: 'short' });
  if (d.getFullYear() === now.getFullYear()) {
    return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
  }
  return d.toLocaleDateString('zh-CN', { year: '2-digit', month: '2-digit', day: '2-digit' });
}

/** 目录路径拆分：主标签 = basename，次标签 = 父路径（「默认」组无路径） */
function dirLabel(key) {
  if (!key) return { name: '默认', parent: '' };
  const parts = String(key).split('/').filter(Boolean);
  if (!parts.length) return { name: key, parent: '' };
  return { name: parts[parts.length - 1], parent: parts.slice(0, -1).join('/') };
}

/** 目录路径规范化：\\ → /，折叠重复斜杠，去末尾斜杠（根目录除外） */
function normPath(p) {
  if (!p) return '';
  let s = String(p).replace(/\\/g, '/');
  s = s.replace(/\/+/g, '/');
  if (s.length > 1 && s.endsWith('/')) s = s.slice(0, -1);
  return s;
}

/** 会话头像色板（persona 会话）：[淡底, 前景]。按 persona_id 哈希稳定取色。 */
const AVATAR_PALETTE = [
  ['#E8F0FE', '#1A73E8'], // 蓝
  ['#E6F4EA', '#188038'], // 绿
  ['#FEF7E0', '#B06000'], // 琥珀
  ['#FCE8E6', '#C5221F'], // 红
  ['#F3E8FD', '#8430CE'], // 紫
  ['#E0F7FA', '#00796B'], // 青
];

function pickAvatarColor(id) {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return AVATAR_PALETTE[h % AVATAR_PALETTE.length];
}

export default function Sidebar({
  sessions, activeSid, view, providerInfo, connected, personas = [],
  defaultCwd = '', streamingSids = {}, onNewSession, onResume, onDelete, onView,
}) {
  const [filter, setFilter] = useState('');
  const [collapsedDirs, setCollapsedDirs] = useState(() => new Set()); // 折叠的目录 key

  const toggleDir = (dirKey) => {
    setCollapsedDirs((prev) => {
      const next = new Set(prev);
      if (next.has(dirKey)) next.delete(dirKey);
      else next.add(dirKey);
      return next;
    });
  };

  // persona_id → manifest 快速查表（会话项徽章用）
  const personaById = useMemo(() => {
    const m = {};
    personas.forEach((p) => { m[p.id] = p; });
    return m;
  }, [personas]);

  // 会话按工作目录分组：「默认」组（cwd 为空或 == defaultCwd）排最前，其余按路径排序
  const groups = useMemo(() => {
    const kw = filter.trim().toLowerCase();
    const filtered = kw
      ? sessions.filter((s) => (s.title || '').toLowerCase().includes(kw))
      : sessions;
    const byDir = new Map();
    filtered.forEach((s) => {
      const key = normPath(s.cwd || defaultCwd || '');
      if (!byDir.has(key)) byDir.set(key, []);
      byDir.get(key).push(s);
    });
    const entries = [...byDir.entries()].map(([key, list]) => {
      const isDefault = !key || normPath(defaultCwd) === key;
      return { key, isDefault, label: isDefault ? '默认' : key, list };
    });
    entries.sort((a, b) => {
      if (a.isDefault !== b.isDefault) return a.isDefault ? -1 : 1;
      return a.key.localeCompare(b.key);
    });
    return entries;
  }, [sessions, filter, defaultCwd]);

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
            className={`nav-item ${view === 'experts' ? 'active' : ''}`}
            onClick={() => onView('experts')}
            title="选择专家：卡片墙 → 详情 → 应用（新建会话注入）"
          >
            <span className="nav-icon">🧠</span> 专家
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

        <button className="new-chat-btn" onClick={onNewSession} title="新建会话（普通模式，无专家）">
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
        {sessions.length > 0 && groups.length === 0 && (
          <div className="session-empty-search">无匹配会话</div>
        )}
        {groups.map(({ key, isDefault, list }) => {
          const { name, parent } = dirLabel(key);
          return (
            <div key={key || '__default__'} className="session-group">
              <div
                className="session-group-label dir"
                onClick={() => toggleDir(key)}
                title={key ? `工作目录：${key}` : '未绑定目录 / 默认目录的会话'}
              >
                <span className="dir-caret">{collapsedDirs.has(key) ? '▸' : '▾'}</span>
                <span className="dir-icon">{isDefault ? '🏠' : '📁'}</span>
                <span className="dir-name">{name}</span>
                {parent && <span className="dir-parent">{parent}</span>}
                <span className="dir-count">{list.length}</span>
              </div>
              {!collapsedDirs.has(key) && (
                <div className="session-group-body">
                  {list.map((s) => {
                    const persona = s.persona_id ? personaById[s.persona_id] : null;
                    const isStreaming = !!streamingSids[s.id];
                    const [aBg, aFg] = s.persona_id ? pickAvatarColor(s.persona_id) : ['', ''];
                    return (
                      <div
                        key={s.id}
                        className={`session-item ${s.id === activeSid ? 'active' : ''} ${isStreaming ? 'streaming' : ''}`}
                        onClick={() => onResume(s.id)}
                        title={s.id}
                      >
                        <span
                          className={`session-avatar ${persona ? 'persona' : ''}`}
                          style={persona ? { background: aBg, color: aFg } : undefined}
                        >
                          {persona ? persona.icon || '🧠' : '💬'}
                        </span>
                        <div className="session-item-main">
                          <div className="session-title-row">
                            <span className="session-title">{s.title}</span>
                            {isStreaming && (
                              <span className="session-streaming">
                                <i className="stream-dot" />生成中
                              </span>
                            )}
                          </div>
                          <div className="session-meta">
                            <span className="session-time">{relTime(s.started_at)}</span>
                            {s.message_count > 0 && (
                              <span className="session-count">{s.message_count} 条</span>
                            )}
                            {persona && (
                              <span className="session-persona" title={`专家: ${persona.name}`}>
                                {persona.name}
                              </span>
                            )}
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
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
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
