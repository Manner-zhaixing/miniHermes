import React, { useEffect, useState } from 'react';

export default function SettingsView({ clientRef, setError }) {
  const [tab, setTab] = useState('model');
  const [config, setConfig] = useState(null);
  const [memory, setMemory] = useState({ user: '', project: '' });
  const [tools, setTools] = useState([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [update, setUpdate] = useState({ status: 'idle' });

  useEffect(() => {
    const client = clientRef.current;
    if (!client) return;
    client.getConfig().then(setConfig).catch((e) => setError(e.message));
    client.getMemory().then(setMemory).catch((e) => setError(e.message));
    client.getTools().then((r) => setTools(r.tools || [])).catch(() => {});
  }, [clientRef, setError]);

  const saveConfig = async () => {
    setSaving(true);
    try {
      await clientRef.current.saveConfig({ model: config.model });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
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

  const setModel = (key, value) => {
    setConfig((c) => ({ ...c, model: { ...(c?.model || {}), [key]: value } }));
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

  const m = config.model || {};

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
        {tab === 'model' && (
          <div className="form-grid">
            <label className="field">
              <span>模型名称</span>
              <input value={m.name || ''} onChange={(e) => setModel('name', e.target.value)} placeholder="deepseek-v4-pro" />
            </label>
            <label className="field">
              <span>Base URL</span>
              <input value={m.base_url || ''} onChange={(e) => setModel('base_url', e.target.value)} placeholder="留空使用默认（OpenAI 兼容）" />
            </label>
            <label className="field">
              <span>API Key</span>
              <input type="password" value={m.api_key || ''} onChange={(e) => setModel('api_key', e.target.value)} placeholder="sk-..." />
            </label>
            <label className="field">
              <span>最大迭代次数</span>
              <input type="number" value={m.max_iterations ?? 100} onChange={(e) => setModel('max_iterations', Number(e.target.value) || 100)} />
            </label>
            <label className="field checkbox">
              <input type="checkbox" checked={!!m.reason} onChange={(e) => setModel('reason', e.target.checked)} />
              <span>启用深度思考（reason）</span>
            </label>
            <label className="field checkbox">
              <input type="checkbox" checked={!!m.show_thinking} onChange={(e) => setModel('show_thinking', e.target.checked)} />
              <span>展示思考过程</span>
            </label>
            <div className="field-actions">
              <button className="btn send" onClick={saveConfig} disabled={saving}>
                {saved ? '✓ 已保存' : '保存配置'}
              </button>
              <span className="cfg-path">配置文件：~/.minihermes/config.yaml</span>
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
