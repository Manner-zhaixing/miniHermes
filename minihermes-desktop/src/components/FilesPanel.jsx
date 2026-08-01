import React, { useState } from 'react';

const EXT_COLORS = {
  md: '#D3D1C7', txt: '#D3D1C7', rst: '#D3D1C7',
  csv: '#C0DD97', xlsx: '#C0DD97', xls: '#C0DD97', tsv: '#C0DD97',
  py: '#B5D4F4', js: '#B5D4F4', ts: '#B5D4F4', jsx: '#B5D4F4', tsx: '#B5D4F4',
  html: '#FAC775', htm: '#FAC775', css: '#FAC775', scss: '#FAC775',
  json: '#F5C4B3', yaml: '#F5C4B3', yml: '#F5C4B3', toml: '#F5C4B3',
  go: '#C0DD97', rs: '#F0997B', java: '#F0997B',
  pptx: '#FAC775', ppt: '#FAC775', docx: '#B5D4F4', doc: '#B5D4F4',
  pdf: '#F7C1C1', png: '#ED93B1', jpg: '#ED93B1', jpeg: '#ED93B1',
  svg: '#9FE1CB', webp: '#ED93B1', gif: '#ED93B1',
  sh: '#D3D1C7', log: '#D3D1C7', default: '#D3D1C7',
};

function extOf(path) {
  const base = path.split('/').pop() || '';
  const idx = base.lastIndexOf('.');
  if (idx <= 0) return 'default';
  return base.slice(idx + 1).toLowerCase();
}

function fileColor(path) {
  return EXT_COLORS[extOf(path)] || EXT_COLORS.default;
}

function fileName(path) {
  const parts = path.split('/');
  return parts[parts.length - 1] || path;
}

function fileDir(path) {
  const idx = path.lastIndexOf('/');
  return idx > 0 ? path.slice(0, idx) : '';
}

export default function FilesPanel({ files, onClose }) {
  const [copied, setCopied] = useState('');

  const copyPath = async (e, p) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(p);
      setCopied(p);
      setTimeout(() => setCopied((c) => (c === p ? '' : c)), 1500);
    } catch (_err) { /* ignore */ }
  };

  const openFile = async (p) => {
    if (window.desktop && window.desktop.openPath) {
      const res = await window.desktop.openPath(p);
      if (!res.ok) window.alert(`无法打开文件：${res.error || '未知错误'}`);
    } else {
      window.alert('浏览器调试模式无法打开本地文件');
    }
  };

  return (
    <div className="files-panel">
      <div className="files-panel-header">
        <span className="files-panel-title">成果文件</span>
        <span className="files-panel-count">{files.length}</span>
        <button className="files-panel-close" onClick={onClose} title="收起">×</button>
      </div>
      <div className="files-panel-body">
        {files.length === 0 && (
          <div className="files-empty">
            暂无成果文件
            <br />
            <span>Agent 写文件后会显示在这里</span>
          </div>
        )}
        {files.map((f, i) => (
          <div
            key={`${f.path}_${i}`}
            className="file-card"
            onClick={() => openFile(f.path)}
            title={f.path}
          >
            <span className="file-ic" style={{ background: fileColor(f.path) }} />
            <div className="file-main">
              <div className="file-name">{fileName(f.path)}</div>
              <div className="file-dir">{fileDir(f.path) || '/'}</div>
            </div>
            <button
              className={`file-copy ${copied === f.path ? 'copied' : ''}`}
              onClick={(e) => copyPath(e, f.path)}
              title="复制路径"
            >
              {copied === f.path ? '✓' : '⧉'}
            </button>
          </div>
        ))}
      </div>
      <div className="files-panel-foot">点击文件用系统默认应用打开</div>
    </div>
  );
}
