import React, { useState } from 'react';

/**
 * Plan 模式审批弹窗：显示生成好的实施计划，用户选择「执行方案」或「取消」。
 */
export default function PlanApprovalModal({ request, onAnswer }) {
  const { request_id: rid, plan_text, plan_path } = request;
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const copyPath = () => {
    if (navigator.clipboard && plan_path) {
      navigator.clipboard.writeText(plan_path).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }).catch(() => {});
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal plan-modal">
        <div className="modal-header">
          <span className="modal-icon">📋</span>
          <h3>实施计划已生成</h3>
        </div>
        <div className="modal-body">
          {plan_path && (
            <div className="plan-path-row">
              <span className="plan-path" title={plan_path}>{plan_path}</span>
              <button className="plan-copy-btn" onClick={copyPath}>{copied ? '✓ 已复制' : '复制路径'}</button>
            </div>
          )}
          <div className="plan-preview">
            <button className="plan-toggle" onClick={() => setOpen(!open)}>
              <span className="plan-chevron">{open ? '▾' : '▸'}</span>
              {open ? '收起方案' : '展开完整方案'}
            </button>
            {open && (
              <pre className="plan-text">{plan_text}</pre>
            )}
            {!open && (
              <pre className="plan-text collapsed">
                {plan_text.slice(0, 500)}{plan_text.length > 500 ? '…' : ''}
              </pre>
            )}
          </div>
        </div>
        <div className="modal-actions">
          <button className="btn deny" onClick={() => onAnswer(rid, 'cancel')}>取消</button>
          <button className="btn allow-session" onClick={() => onAnswer(rid, 'execute')}>▶ 执行方案</button>
        </div>
      </div>
    </div>
  );
}
