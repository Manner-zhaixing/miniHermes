/**
 * DB 消息 → 前端渲染消息的转换。
 *
 * 核心职责（有序片段模型）：
 * 1. 把一次对话渲染为"有序片段"（parts）：思考 / 工具 / 正文按时间顺序排列，
 *    类型切换即新开片段，避免"工具卡片插入旧文本模块"的错乱。
 * 2. 把 DB 中 role='tool' 的消息通过 tool_call_id 关联回 assistant 的工具片段，
 *    填回结果，避免"空结果卡片 + 重复 tool 卡片"。
 * 3. 合并"同一回合"的相邻 assistant 消息（内核拆多条），深度思考不劈段。
 */

let _uid = 0;
const uid = () => `m${Date.now()}_${_uid++}`;

/** 从一条 DB assistant 消息构建片段（思考 → 工具 → 正文） */
function buildParts(m, pendingTools) {
  const parts = [];
  const reasoning = m._reasoning || m.reasoning || '';
  if (reasoning) parts.push({ type: 'thinking', text: reasoning });
  (m.tool_calls || []).forEach((tc) => {
    const entry = {
      type: 'tool',
      name: tc.function?.name || 'tool',
      status: 'pending',
      args: tc.function?.arguments || '',
      result: '',
    };
    pendingTools.push({ callId: tc.id || null, entry });
    parts.push(entry);
  });
  const content = m.content || '';
  if (content) parts.push({ type: 'text', text: content });
  return parts;
}

export function convertDbMessages(rawMessages) {
  const result = [];
  // 等待结果填充的工具调用：{ callId, entry }，entry 即 tool 片段对象
  const pendingTools = [];

  (rawMessages || []).forEach((m) => {
    const base = { id: uid(), ts: Date.now(), toolName: null };

    if (m.role === 'assistant') {
      const prev = result[result.length - 1];
      // 上一条渲染消息也是 assistant（中间隔的 tool 已合并进片段）→ 合并
      if (prev && prev.role === 'assistant') {
        prev.parts.push(...buildParts(m, pendingTools));
        return;
      }
      result.push({
        ...base,
        role: 'assistant',
        parts: buildParts(m, pendingTools),
      });
      return;
    }

    if (m.role === 'tool') {
      // 优先按 tool_call_id 精确关联；老数据无 id 时按顺序取最近未填充的
      let idx = pendingTools.findIndex((p) => p.callId && p.callId === m.tool_call_id);
      if (idx < 0) idx = pendingTools.findIndex((p) => p.entry.status === 'pending');
      if (idx >= 0) {
        const { entry } = pendingTools[idx];
        pendingTools.splice(idx, 1);
        entry.status = 'done';
        entry.result = m.content || '';
        return; // 合并进 assistant 的工具片段，不再单独渲染
      }
      // 无法关联（压缩/历史数据）：兜底渲染为独立工具卡片
      result.push({ ...base, role: 'tool', content: m.content || '', toolName: m.tool_name || 'tool' });
      return;
    }

    result.push({ ...base, role: m.role, content: m.content || '' });
  });

  // 未收到结果的事件（如中途打断）：标记为 done 空结果
  pendingTools.forEach(({ entry }) => { entry.status = 'done'; });
  return result;
}
