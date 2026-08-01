import React, { useEffect, useState } from 'react';

export default function SkillsView({ clientRef, setError }) {
  const [skills, setSkills] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const client = clientRef.current;
    if (!client) return;
    client.getSkills()
      .then((r) => setSkills(r.skills || []))
      .catch((e) => setError(e.message));
  }, [clientRef, setError]);

  const openSkill = async (name) => {
    setSelected(name);
    setDetail(null);
    setLoading(true);
    try {
      const r = await clientRef.current.getSkill(name);
      setDetail(r.skill);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="skills-view">
      <div className="panel-header">
        <h2>技能管理</h2>
        <span className="panel-sub">{skills.length} 个可用技能</span>
      </div>
      <div className="skills-layout">
        <div className="skill-list">
          {skills.length === 0 && <div className="panel-loading">暂无技能</div>}
          {skills.map((s) => (
            <button
              key={s.name}
              className={`skill-card ${selected === s.name ? 'active' : ''}`}
              onClick={() => openSkill(s.name)}
            >
              <div className="skill-card-title">
                <span className="skill-icon">🧩</span>
                <span className="skill-name">{s.name}</span>
                {s.version && <span className="skill-version">v{s.version}</span>}
              </div>
              <div className="skill-desc">{s.description || '暂无描述'}</div>
            </button>
          ))}
        </div>
        <div className="skill-detail">
          {loading && <div className="panel-loading">加载中…</div>}
          {detail && (
            <div className="skill-detail-content">
              <h3>{detail.name}</h3>
              <div className="skill-meta">
                {detail.version && <span>v{detail.version}</span>}
                {detail.category && <span>{detail.category}</span>}
                <span>{detail.platform_compatible ? '✅ 平台兼容' : '⚠️ 平台不兼容'}</span>
              </div>
              <div className="skill-path" title={detail.path}>{detail.path}</div>
              {detail.required_env_vars?.length > 0 && (
                <div className="skill-env">
                  <strong>需要环境变量：</strong>
                  {detail.required_env_vars.map((v) => (
                    <code key={v.name} className="tool-tag">{v.name}{v.optional ? '' : ' *'}</code>
                  ))}
                </div>
              )}
              <pre className="skill-content">{detail.content}</pre>
            </div>
          )}
          {!detail && !loading && (
            <div className="panel-loading">选择左侧技能查看详情</div>
          )}
        </div>
      </div>
    </div>
  );
}
