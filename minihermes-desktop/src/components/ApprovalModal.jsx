import React from 'react';

export default function ApprovalModal({ request, onAnswer }) {
  const { request_id: rid, tool_name, args, description } = request;
  const detail = tool_name === 'bash' ? args?.command : (args?.path || args?.command || '');

  return (
    <div className="modal-overlay">
      <div className="modal approval-modal">
        <div className="modal-header">
          <span className="modal-icon">⚠️</span>
          <h3>需要授权确认</h3>
        </div>
        <div className="modal-body">
          <div className="approval-tool">
            <span className="approval-tool-name">{tool_name}</span>
            <span className="approval-risk">危险操作</span>
          </div>
          {description && <p className="approval-desc">{description}</p>}
          {detail && (
            <pre className="approval-detail">{detail}</pre>
          )}
          {args && (
            <details className="approval-args">
              <summary>查看完整参数</summary>
              <pre>{JSON.stringify(args, null, 2)}</pre>
            </details>
          )}
        </div>
        <div className="modal-actions">
          <button className="btn deny" onClick={() => onAnswer(rid, 'deny')}>拒绝</button>
          <button className="btn allow-once" onClick={() => onAnswer(rid, 'once')}>允许一次</button>
          <button className="btn allow-session" onClick={() => onAnswer(rid, 'session')}>本次会话允许</button>
        </div>
      </div>
    </div>
  );
}
