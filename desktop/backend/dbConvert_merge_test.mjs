/**
 * 验证：恢复会话时同一回合的深度思考合并为一段（parts 模型）。
 * 用法：node dbConvert_merge_test.mjs <port> <sessionId>
 */
import { convertDbMessages } from '../src/dbConvert.js';

const PORT = process.argv[2] || '51882';
const SID = process.argv[3] || '20260802_001220_e049d2';
const BASE = `http://127.0.0.1:${PORT}`;

const res = await fetch(`${BASE}/api/sessions/${SID}/messages`);
const { messages } = await res.json();
const out = convertDbMessages(messages);

const roles = out.map((m) => m.role);
console.log(`DB ${messages.length} 条 → 渲染 ${out.length} 条`);
console.log('角色序列:', roles.join(' → '));

const assistants = out.filter((m) => m.role === 'assistant');
let pass = true;

if (assistants.length !== 1) {
  console.log(`❌ assistant 消息 ${assistants.length} 条（期望 1 条）`);
  pass = false;
} else {
  const a = assistants[0];
  const seq = (a.parts || []).map((p) => p.type);
  console.log('片段序列:', seq.join(' → '));
  const thinking = (a.parts || []).filter((p) => p.type === 'thinking');
  const tools = (a.parts || []).filter((p) => p.type === 'tool');
  console.log(`✅ assistant 合并为 1 条`);
  console.log(`    thinking 片段: ${thinking.length} 个, 总长 ${thinking.reduce((s, p) => s + (p.text || '').length, 0)}`);
  console.log(`    工具片段: ${tools.length} 个, status=${tools[0]?.status}, resultLen=${(tools[0]?.result || '').length}`);
  if (thinking.length !== 1) { console.log('❌ thinking 被拆成多段'); pass = false; }
  if (tools.length !== 1 || tools[0].status !== 'done') { console.log('❌ 工具片段异常'); pass = false; }
}

console.log(pass ? '\n=== MERGE PASS ===' : '\n=== MERGE FAIL ===');
process.exit(pass ? 0 : 1);
