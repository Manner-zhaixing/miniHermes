import React, { useEffect, useState } from 'react';

/** 动态 import mermaid 并初始化一次（vite 自动分包，首屏不加载大包） */
let _mermaidInit = false;
let _renderSeq = 0;

async function getMermaid() {
  const mod = await import('mermaid');
  const mermaid = mod.default;
  if (!_mermaidInit) {
    _mermaidInit = true;
    mermaid.initialize({
      startOnLoad: false,
      theme: 'default',
      securityLevel: 'strict', // 清洗标签 HTML，安全
      fontFamily: 'inherit',
    });
  }
  return mermaid;
}

/** 渲染 ```mermaid 代码块为图表。
 *  仅在非 streaming 时挂载（streaming 中由 MessageItem 显示源码），
 *  code 变化时重渲染；渲染失败回退为源码代码块 + 错误提示。 */
export default function MermaidDiagram({ code }) {
  const [svg, setSvg] = useState(null);
  const [error, setError] = useState(null);
  const id = React.useId().replace(/[^a-zA-Z0-9_-]/g, '');

  useEffect(() => {
    let cancelled = false;
    setSvg(null);
    setError(null);
    (async () => {
      try {
        const mermaid = await getMermaid();
        _renderSeq += 1;
        const res = await mermaid.render(`mermaid-${id}-${_renderSeq}`, code || '');
        if (!cancelled) setSvg(res.svg);
      } catch (e) {
        if (!cancelled) setError((e && e.message) ? e.message : String(e));
      }
    })();
    return () => { cancelled = true; };
  }, [code, id]);

  if (!code || !code.trim()) return null;

  if (error) {
    return (
      <div className="mermaid-diagram mermaid-error">
        <pre className="code-block"><code>{code}</code></pre>
        <div className="mermaid-err">⚠️ mermaid 渲染失败：{error}</div>
      </div>
    );
  }
  if (!svg) {
    return <div className="mermaid-diagram mermaid-loading">… 渲染中</div>;
  }
  return <div className="mermaid-diagram" dangerouslySetInnerHTML={{ __html: svg }} />;
}
