import React, { useEffect, useState } from 'react';
import ProviderIcon from './ProviderIcon.jsx';

export default function SettingsView({ clientRef, setError, onConfigSaved }) {
  const [tab, setTab] = useState('model');
  const [config, setConfig] = useState(null);
  const [providers, setProviders] = useState({ active: 'deepseek', providers: [] });
  const [selected, setSelected] = useState(null); // null = 卡片画廊；name = 详情编辑
  const [memory, setMemory] = useState({ user: '', project: '' });
  const [tools, setTools] = useState([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [update, setUpdate] = useState({ status: 'idle' });
  const [testState, setTestState] = useState({ status: 'idle', models: [], error: '', latency_ms: 0 });

  useEffect(() => {
    const client = clientRef.current;
    if (!client) return;
    client.getConfig().then((c) => {
      setConfig(c);
    }).catch((e) => setError(e.message));
    client.getProviders().then(setProviders).catch(() => {});
    client.getMemory().then(setMemory).catch((e) => setError(e.message));
    client.getTools().then((r) => setTools(r.tools || [])).catch(() => {});
  }, [clientRef, setError]);

  const saveConfig = async () => {
    setSaving(true);
    try {
      const res = await clientRef.current.saveConfig({
        provider: config.provider,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      if (res && res.rebuild_warning) setError(res.rebuild_warning);
      if (onConfigSaved) onConfigSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  /** 设为当前厂商：切换 active 并落盘（不影响画廊浏览时的线上对话） */
  const setActiveProvider = async () => {
    setSaving(true);
    try {
      const next = { ...config, provider: { ...(config.provider || {}), active: selected } };
      setConfig(next);
      const res = await clientRef.current.saveConfig({ provider: next.provider });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      if (res && res.rebuild_warning) setError(res.rebuild_warning);
      if (onConfigSaved) onConfigSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const saveMemory = async () => {
    setSaving(true);
    try {
      await clientRef.current.saveMemory(memory);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const setProviderField = (key, value) => {
    setConfig((c) => ({
      ...c,
      provider: {
        ...(c?.provider || {}),
        list: {
          ...(c?.provider?.list || {}),
          [selected]: { ...(c?.provider?.list?.[selected] || {}), [key]: value },
        },
      },
    }));
  };

  /** 进入某厂商的详情编辑（仅浏览，不改变 active） */
  const openDetail = (name) => {
    setSelected(name);
    setTestState({ status: 'idle', models: [], error: '', latency_ms: 0 });
  };

  /** 测试连接：请求厂商 /models 接口验证 key / base_url（pending 值直发，无需先保存） */
  const testConnection = async () => {
    setTestState({ status: 'testing', models: [], error: '', latency_ms: 0 });
    try {
      const res = await clientRef.current.testProviderConnection({
        provider: selected,
        api_key: p?.api_key || '',
        base_url: p?.base_url || '',
      });
      if (res && res.ok) {
        setTestState({ status: 'success', models: res.models || [], latency_ms: res.latency_ms || 0, error: '' });
      } else {
        setTestState({ status: 'error', models: [], latency_ms: res?.latency_ms || 0, error: res?.error || '测试失败' });
      }
    } catch (e) {
      setTestState({ status: 'error', models: [], latency_ms: 0, error: e.message || '测试失败' });
    }
  };

  // ── 应用更新 ─────────────────────────────────────────
  const checkUpdate = async () => {
    if (!window.desktop || !window.desktop.checkUpdate) return;
    setUpdate({ status: 'checking' });
    try {
      const res = await window.desktop.checkUpdate();
      if (!res.ok) {
        setUpdate({ status: 'error', error: res.error || '检查失败' });
        return;
      }
      if (!res.hasUpdate) setUpdate({ status: 'latest', current: res.current });
      else setUpdate({ status: 'available', info: res });
    } catch (e) {
      setUpdate({ status: 'error', error: e.message });
    }
  };

  const downloadUpdate = async () => {
    if (!window.desktop || !window.desktop.downloadUpdate) return;
    setUpdate((s) => ({ ...s, status: 'downloading' }));
    try {
      const res = await window.desktop.downloadUpdate(s.info.dmgUrl, s.info.assetName);
      if (!res.ok) {
        setUpdate((st) => ({ ...st, status: 'error', error: res.error || '下载失败' }));
        return;
      }
      setUpdate((st) => ({ ...st, status: 'downloaded', path: res.path, size: res.size }));
    } catch (e) {
      setUpdate((st) => ({ ...st, status: 'error', error: e.message }));
    }
  };

  const installUpdate = async () => {
    if (!window.desktop || !window.desktop.installUpdate || !update.path) return;
    const res = await window.desktop.installUpdate(update.path);
    if (!res.ok) setUpdate((s) => ({ ...s, status: 'error', error: res.error }));
  };

  if (!config) {
    return <div className="panel-loading">加载配置中…</div>;
  }

  const p = selected ? config?.provider?.list?.[selected] || {} : {};
  const meta = selected ? providers.providers?.find((x) => x.name === selected) : null;
  const active = config?.provider?.active || 'deepseek';

  return (
    <div className="settings-view">
      <div className="panel-header">
        <h2>设置</h2>
        <div className="tab-bar">
          <button className={`tab ${tab === 'model' ? 'active' : ''}`} onClick={() => setTab('model')}>模型配置</button>
          <button className={`tab ${tab === 'memory' ? 'active' : ''}`} onClick={() => setTab('memory')}>用户记忆</button>
          <button className={`tab ${tab === 'system' ? 'active' : ''}`} onClick={() => setTab('system')}>系统信息</button>
        </div>
      </div>

      <div className="panel-body">
        {tab === 'model' && !selected && (
          <div className="provider-settings">
            <div className="settings-subhead">
              <span>选择一个厂商查看并编辑配置</span>
              <span className="cfg-path">配置文件：~/.minihermes/config.yaml</span>
            </div>
            {providers.providers.length === 0 ? (
              <div className="provider-empty">暂无可用厂商</div>
            ) : (
              <div className="provider-grid">
                {providers.providers.map((pr) => (
                  <button
                    key={pr.name}
                    className={`provider-card ${pr.name === active ? 'current' : ''}`}
                    onClick={() => openDetail(pr.name)}
                  >
                    <ProviderIcon name={pr.name} title={pr.title} size={40} />
                    <span className="provider-card-body">
                      <span className="provider-card-title">
                        {pr.title}
                        {pr.name === active && <em className="current-badge">当前</em>}
                      </span>
                      <span className="provider-card-meta">
                        {pr.has_key ? '✓ 已配置 Key' : '未配置 Key'}
                      </span>
                      <span className="provider-card-model">{pr.model || '未配置模型'}</span>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {tab === 'model' && selected && (
          <div className="provider-detail">
            <button className="detail-back" onClick={() => setSelected(null)}>‹ 返回全部厂商</button>

            <div className="detail-header">
              <ProviderIcon name={selected} title={meta?.title} size={40} />
              <div className="detail-header-text">
                <div className="detail-title">
                  {meta?.title || selected}
                  {selected === active && <em className="current-badge">当前生效</em>}
                </div>
                <div className="detail-sub">
                  {p.api_key ? '✓ 已配置 Key' : '未配置 Key'} · {meta?.base_url || ''}
                </div>
              </div>
              <button
                className="btn activate"
                onClick={setActiveProvider}
                disabled={saving || selected === active}
                title="将当前编辑的厂商设为线上生效厂商"
              >
                {selected === active ? '✓ 当前生效' : '设为当前厂商'}
              </button>
            </div>

            <div className="form-grid">
              <label className="field">
                <span>API Key{meta?.env_key ? `（环境变量 ${meta.env_key} 可兜底）` : ''}</span>
                <div className="field-row">
                  <input
                    type="password"
                    value={p.api_key || ''}
                    onChange={(e) => setProviderField('api_key', e.target.value)}
                    placeholder="sk-..."
                  />
                  <button
                    className="btn test"
                    onClick={testConnection}
                    disabled={testState.status === 'testing'}
                  >
                    {testState.status === 'testing' ? '测试中…' : '测试连接'}
                  </button>
                </div>
                {testState.status === 'success' && (
                  <span className="test-result ok">
                    ✓ 连接成功{testState.latency_ms ? `（${testState.latency_ms}ms）` : ''}
                    {testState.models.length > 0 && `，共 ${testState.models.length} 个模型：${testState.models.join('；')}`}
                  </span>
                )}
                {testState.status === 'error' && (
                  <span className="test-result err">✗ {testState.error}</span>
                )}
              </label>

              <label className="field">
                <span>模型（可自由输入，或从预设候选中选择）</span>
                <input
                  value={p.model || ''}
                  onChange={(e) => setProviderField('model', e.target.value)}
                  placeholder={meta?.model || '输入模型 id'}
                />
                <div className="model-list">
                  {(meta?.models || []).map((m) => (
                    <button
                      key={m.id}
                      className={`model-chip ${p.model === m.id ? 'active' : ''}`}
                      onClick={() => setProviderField('model', m.id)}
                    >
                      {m.id}
                      <em className="model-window">· {fmtWindow(m.context_window)}</em>
                    </button>
                  ))}
                  {!p.model && (
                    <span className="model-list-hint">点击候选填入，或直接输入自定义模型 id</span>
                  )}
                </div>
              </label>

              <p className="detail-note">
                上下文长度按所选模型预设解析；思考强度请在对话窗口底部选择，每轮可自由切换。
              </p>

              <div className="field-actions">
                <button className="btn send" onClick={saveConfig} disabled={saving}>
                  {saved ? '✓ 已保存' : '保存配置'}
                </button>
              </div>
            </div>
          </div>
        )}

        {tab === 'memory' && (
          <div className="memory-editor">
            <div className="memory-note">
              记忆文件会在每次会话启动时注入系统提示词，保存后即时生效。
            </div>
            <label className="field">
              <span>USER.md — 用户偏好 / 背景信息</span>
              <textarea
                rows={10}
                value={memory.user}
                onChange={(e) => setMemory((mem) => ({ ...mem, user: e.target.value }))}
                placeholder="# 关于我&#10;"
              />
            </label>
            <label className="field">
              <span>MEMORY.md — 项目环境 / 约定</span>
              <textarea
                rows={10}
                value={memory.project}
                onChange={(e) => setMemory((mem) => ({ ...mem, project: e.target.value }))}
                placeholder="# 项目记忆"
              />
            </label>
            <div className="field-actions">
              <button className="btn send" onClick={saveMemory} disabled={saving}>
                {saved ? '✓ 已保存' : '保存记忆'}
              </button>
            </div>
          </div>
        )}

        {tab === 'system' && (
          <div className="system-info">
            <h3>MiniHermes 内核</h3>
            <p className="sys-desc">
              底层运行 minihermes 内核：流式对话 · 工具调用 · 记忆持久化 · 技能系统 · 上下文压缩 · 安全审批
            </p>
            <h4>已注册工具（{tools.length}）</h4>
            <div className="tool-tags">
              {tools.map((t) => (
                <span key={t} className="tool-tag">{t}</span>
              ))}
            </div>

            <h3 style={{ marginTop: 28 }}>应用更新</h3>
            <div className="update-card">
              {update.status === 'idle' && (
                <div className="update-row">
                  <span className="update-ver">检查 GitHub 上是否有新版本</span>
                  <button className="btn send" onClick={checkUpdate}>检查更新</button>
                </div>
              )}
              {update.status === 'checking' && (
                <div className="update-row"><span className="update-ver">正在检查更新…</span><span className="update-spin" /></div>
              )}
              {update.status === 'latest' && (
                <div className="update-row">
                  <span className="update-ver">已是最新版本（v{update.current}）</span>
                  <button className="btn send" onClick={checkUpdate}>重新检查</button>
                </div>
              )}
              {update.status === 'available' && (
                <div className="update-avail">
                  <div className="update-row">
                    <span className="update-ver">
                      发现新版本：v{update.info.latest} <em className="update-cur">（当前 v{update.info.current}）</em>
                    </span>
                    <button className="btn send" onClick={downloadUpdate} disabled={!update.info.dmgUrl}>
                      {update.info.dmgUrl ? '下载安装包' : '无可用安装包'}
                    </button>
                  </div>
                  {update.info.notes && (
                    <pre className="update-notes">{update.info.notes}</pre>
                  )}
                </div>
              )}
              {update.status === 'downloading' && (
                <div className="update-row"><span className="update-ver">正在下载安装包，请稍候…</span><span className="update-spin" /></div>
              )}
              {update.status === 'downloaded' && (
                <div className="update-row">
                  <span className="update-ver">
                    下载完成（{fmtSize(update.size)}）
                    <br />
                    <span className="update-path">{update.path}</span>
                  </span>
                  <button className="btn send" onClick={installUpdate}>打开并安装</button>
                </div>
              )}
              {update.status === 'error' && (
                <div className="update-row">
                  <span className="update-ver update-err">{update.error}</span>
                  <button className="btn send" onClick={checkUpdate}>重试</button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function fmtSize(bytes) {
  if (!bytes) return '';
  if (bytes > 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  return `${Math.round(bytes / 1024)} KB`;
}

function fmtWindow(n) {
  if (!n) return '';
  if (n >= 1e6) return `${n / 1e6}M`;
  if (n >= 1000) return `${n / 1000}K`;
  return String(n);
}
