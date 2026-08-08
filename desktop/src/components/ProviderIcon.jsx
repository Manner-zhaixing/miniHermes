import React from 'react';

/**
 * 厂商图标：品牌色定制内联 SVG（离线可用，随包分发）。
 * 参考 openworker：前端按厂商 name 解析图标（后端不携带图标字段）。
 * 新增厂商只需在 PROVIDER_META 加一条 + 下方加一个 SVG 分支。
 */
export const PROVIDER_META = {
  deepseek: { color: '#4D6BFE', mark: 'whale' }, // 蓝鲸，与应用 WhaleAvatar 同品牌色
  glm: { color: '#0E7A6E', label: 'Z' },         // Z·GLM 标记（青）
};

const FALLBACK_COLOR = '#6B7280';

export function hexToRgba(hex, alpha) {
  const h = hex.replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

export default function ProviderIcon({ name, title, size = 24 }) {
  const meta = PROVIDER_META[name];
  const color = (meta && meta.color) || FALLBACK_COLOR;
  const bg = hexToRgba(color, 0.12);
  const label = (meta && meta.label) || (title || name || '?').trim()[0] || '?';

  return (
    <svg width={size} height={size} viewBox="0 0 28 28" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <rect width="28" height="28" rx="7" fill={bg} />
      {name === 'deepseek' ? (
        <g fill={color}>
          <path d="M6.4 15.6C6.4 12.1 9.4 9.6 12.9 9.6C15.8 9.6 18.3 11.1 19.7 13.5C18.4 15.1 16.4 16.1 13.9 16.1C10.9 16.1 8.4 15.3 6.9 13.9C7.1 14.9 7.9 15.7 8.9 16.3C9.9 16.9 11.1 17.1 12.4 17.1C14.9 17.1 17.4 16.1 19.4 14.6C20.7 15.3 20.9 16.1 20.7 16.9C19.9 17.9 18.7 18.5 17.4 18.8C15.4 19.3 13.4 19.4 11.4 18.9C9.4 18.4 7.7 17.1 6.6 15.6Z" />
          <path d="M19.7 13.5L22.6 11.9L21.6 14.8Z" />
          <circle cx="11" cy="12.3" r="1" fill="#fff" />
        </g>
      ) : (
        <text x="14" y="15.5" textAnchor="middle" dominantBaseline="middle"
          fontSize="15" fontWeight="700" fill={color} fontFamily="inherit">{label}</text>
      )}
    </svg>
  );
}
