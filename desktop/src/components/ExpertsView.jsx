import React, { useEffect, useMemo, useState } from 'react';

/**
 * 专家选择界面（主区域 view）：
 *  1. 卡片墙 —— 整个页面铺满专家卡片（图标/名称/一句话），点卡片进详情；
 *  2. 详情页 —— 完整描述 + 角色简介（system_prompt 全文滚动）+ 应用按钮。
 * 卡片与详情页底部都有「应用」按钮（应用 = 新建会话并注入该专家）。
 */
export default function ExpertsView({
  personas = [],          // manifest 数组（GET /api/personas，含完整 system_prompt）
  activePersonaId = '',   // 当前会话绑定的专家 id（'' = 无专家）
  onApply,                // (persona) => void — 应用专家（新建会话注入）
}) {
  const [selectedId, setSelectedId] = useState(null);

  const selected = useMemo(
    () => personas.find((p) => p.id === selectedId) || null,
    [personas, selectedId],
  );

  // 选中项在 personas 变化后失效（防已删除/不可见项残留）
  useEffect(() => {
    if (selectedId && !personas.some((p) => p.id === selectedId)) {
      setSelectedId(null);
    }
  }, [personas, selectedId]);

  // 卡片墙
  if (!selected) {
    return (
      <div className="experts-view">
        <div className="panel-header experts-header">
          <h2>🧠 选择专家</h2>
          <span className="panel-sub">{personas.length} 个可用专家</span>
        </div>

        <div className="experts-tips">
          💡 点击卡片查看该专家的详细描述与角色简介；卡片或详情页底部点「应用」→
          立即新建会话并注入该专家。原「新会话」仍创建普通会话，不受影响。
        </div>

        {personas.length === 0 ? (
          <div className="experts-empty">
            暂无可用专家。内置专家随应用发布；可在 ~/.minihermes/personas/ 添加自定义专家 md。
          </div>
        ) : (
          <div className="experts-grid">
            {personas.map((p) => {
              const isActive = p.id === activePersonaId;
              return (
                <div
                  key={p.id}
                  className={`expert-card ${isActive ? 'active' : ''}`}
                  onClick={() => setSelectedId(p.id)}
                  title="点击查看详情"
                >
                  <div className="expert-card-top">
                    <span className="expert-card-icon">{p.icon || '🧠'}</span>
                    <span className="expert-card-name">
                      {p.name}
                      {p.expert_type === 'team' && <span className="expert-team-badge">专家团</span>}
                      {isActive && <span className="expert-active-badge">当前</span>}
                    </span>
                  </div>
                  <div className="expert-card-cat">{p.category}</div>
                  <p className="expert-card-tagline">{p.tagline || p.description || '暂无描述'}</p>
                  <button
                    className="expert-card-apply"
                    onClick={(e) => { e.stopPropagation(); onApply(p); }}
                    title={`应用「${p.name}」→ 新建会话并注入`}
                  >
                    应用 → 新建会话
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  // 详情页
  return (
    <div className="expert-detail-page">
      <button className="expert-detail-back" onClick={() => setSelectedId(null)}>
        ← 返回专家列表
      </button>

      <div className="expert-detail-hero">
        <span className="expert-detail-icon">{selected.icon || '🧠'}</span>
        <div className="expert-detail-head">
          <div className="expert-detail-name">
            {selected.name}
            {selected.expert_type === 'team' && <span className="expert-team-badge">专家团</span>}
            {selected.id === activePersonaId && <span className="expert-active-badge">当前</span>}
          </div>
          <div className="expert-detail-id">id: {selected.id} · {selected.source === 'builtin' ? '内置' : '本地'}</div>
        </div>
      </div>

      {selected.tagline && <p className="expert-detail-tagline">{selected.tagline}</p>}
      {selected.description && <p className="expert-detail-desc">{selected.description}</p>}

      {selected.expert_type === 'team' && (
        <div className="expert-detail-block">
          <div className="expert-detail-label">团员</div>
          <div className="expert-member-chips">
            {(selected.member_names || []).map((n, i) => (
              <span key={i} className="expert-chip">{n}</span>
            ))}
          </div>
        </div>
      )}

      <div className="expert-detail-block">
        <div className="expert-detail-label">工具白名单</div>
        <div className="expert-tools">
          {(selected.tools || []).length > 0
            ? selected.tools.join(' · ')
            : '全部工具（未限制）'}
        </div>
      </div>

      {(selected.skills || []).length > 0 && (
        <div className="expert-detail-block">
          <div className="expert-detail-label">捆绑技能</div>
          <div className="expert-tools">{selected.skills.join(' · ')}</div>
        </div>
      )}

      {selected.default_init_prompt && (
        <div className="expert-detail-block">
          <div className="expert-detail-label">激活开场（应用后自动发送）</div>
          <div className="expert-init-prompt">{selected.default_init_prompt}</div>
        </div>
      )}

      <div className="expert-detail-block">
        <div className="expert-detail-label">角色简介（系统提示预览）</div>
        <pre className="expert-sysprompt">{selected.system_prompt || '（无正文）'}</pre>
      </div>

      <div className="expert-detail-footer">
        <button className="expert-apply-btn" onClick={() => onApply(selected)}>
          应用「{selected.name}」→ 新建会话并注入
        </button>
      </div>
    </div>
  );
}
