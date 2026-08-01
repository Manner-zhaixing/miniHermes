import React, { useState } from 'react';

export default function ClarifyModal({ request, onAnswer }) {
  const { request_id: rid, question, choices } = request;
  const [custom, setCustom] = useState('');

  const submitCustom = () => {
    if (custom.trim()) onAnswer(rid, custom.trim());
  };

  return (
    <div className="modal-overlay">
      <div className="modal clarify-modal">
        <div className="modal-header">
          <span className="modal-icon">❓</span>
          <h3>需要你的回答</h3>
        </div>
        <div className="modal-body">
          <p className="clarify-question">{question}</p>
          {choices && choices.length > 0 && (
            <div className="clarify-choices">
              {choices.map((c, i) => (
                <button key={i} className="btn choice" onClick={() => onAnswer(rid, c)}>
                  {c}
                </button>
              ))}
            </div>
          )}
          <div className="clarify-custom">
            <input
              value={custom}
              onChange={(e) => setCustom(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') submitCustom(); }}
              placeholder={choices && choices.length > 0 ? '或自定义回答…' : '输入你的回答…'}
              autoFocus
            />
            <button className="btn send" onClick={submitCustom} disabled={!custom.trim()}>
              提交
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
