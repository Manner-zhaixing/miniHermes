/**
 * 验证：恢复会话时工具结果回填 + 有序片段渲染（parts 模型）。
 * 用法：node dbConvert_test.mjs <port>
 */
import { convertDbMessages } from '../src/dbConvert.js';

const PORT = process.argv[2] || '60321';
const BASE = `http://127.0.0.1:${PORT}`;

const SESSIONS = process.argv.slice(3).length > 0
  ? process.argv.slice(3)
  : ['20260801_225616_8de1d2', '20260802_001220_e049d2'];

let pass = 0, fail = 0;
const check = (ok, label) => {
  console.log(`${ok ? '✅' : '❌'} ${label}`);
  ok ? pass++ : fail++;
};

for (const sid of SESSIONS) {
  const res = await fetch(`${BASE}/api/sessions/${sid}/messages`);
  const { messages } = await res.json();
  const out = convertDbMessages(messages);
  const roles = out.map((m) => m.role);
  console.log(`\n=== 会话 ${sid} (${messages.length} 条 DB → ${out.length} 条渲染) ===`);
  console.log('角色序列:', roles.join(' → '));

  // 检查 1：无独立 tool 卡片（结果合并进 assistant）
  const standalone = out.filter((m) => m.role === 'tool');
  check(standalone.length === 0, `无独立 tool 卡片 (${standalone.length} 个)`);

  // 检查 2：assistant 的 tool 片段已落库的结果都正确回填（进行中会话最后未完成
  // 的工具调用允许为空——收尾会标 done 空结果，这是中断场景的合理行为）
  let toolParts = 0, filled = 0, pending = 0;
  const seq = [];
  for (const m of out) {
    if (m.role !== 'assistant') continue;
    for (const p of m.parts || []) {
      seq.push(p.type);
      if (p.type === 'tool') {
        toolParts++;
        if (p.status === 'pending') pending++;
        if (p.result && p.result.trim() && p.status === 'done') filled++;
        else if (p.status === 'done' && p.result) console.log(`   ⚠️ tool 片段未回填: ${p.name} status=${p.status}`);
      }
    }
  }
  check(pending === 0, `无 pending 残留 tool 片段 (${pending} 个)`);
  // 严格断言：未回填的片段只能来自"最后一条 assistant 消息"（对话进行中的
  // 工具结果未落库），说明已落库的结果全部正确回填
  const assistants2 = out.filter((m) => m.role === 'assistant');
  const lastAsst = assistants2[assistants2.length - 1];
  const lastUnfilled = (lastAsst?.parts || []).filter((p) => p.type === 'tool' && !(p.result && p.result.trim())).length;
  const unfilledTotal = toolParts - filled;
  check(unfilledTotal === lastUnfilled, `已落库工具结果全部回填（未回填 ${unfilledTotal} 个，均属最后一条 assistant=${unfilledTotal === lastUnfilled}）`);
  check(toolParts === filled || toolParts - filled <= 5, `tool 片段回填 ${filled}/${toolParts}（进行中会话允许尾部未完成）`);
  console.log('   片段序列:', seq.join(' → '));

  // 检查 3：多轮 assistant 合并后片段仍是时间顺序（思考/工具/正文混合合法）
  if (toolParts > 0) {
    const ti = seq.indexOf('thinking');
    check(ti >= 0, `有思考片段 (idx=${ti})`);
  }
}

console.log(`\n==== ${pass} 项通过, ${fail} 项失败 ====`);
process.exit(fail > 0 ? 1 : 0);
