import React, { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { initClient, getClient } from './api.js';
import { convertDbMessages } from './dbConvert.js';
import Sidebar from './components/Sidebar.jsx';
import ChatView from './components/ChatView.jsx';
import SettingsView from './components/SettingsView.jsx';
import SkillsView from './components/SkillsView.jsx';
import ApprovalModal from './components/ApprovalModal.jsx';
import ClarifyModal from './components/ClarifyModal.jsx';
import FilesPanel from './components/FilesPanel.jsx';
import ExpertsView from './components/ExpertsView.jsx';

let _uid = 0;
const uid = () => `m${Date.now()}_${_uid++}`;

/** 从 GET /api/providers 响应推导当前激活厂商的展示信息（resolved 值）。 */
function deriveProviderInfo(res) {
  if (!res) return null;
  const { active, providers } = res;
  if (!active) return null;
  const p = (providers || []).find((x) => x.name === active) || {};
  return {
    name: active,
    title: p.title || active,
    model: p.model || '',
    models: p.models || [], // [{id, context_window}] 预设候选
    context_window: p.context_window || 0,
    thinking_effort: p.thinking_effort || 'max',
    thinking_effort_levels: (p.thinking_effort_levels || ['off', 'medium', 'high', 'max']),
    has_key: !!p.has_key,
  };
}

export default function App() {
  const [view, setView] = useState('chat');
  const [connected, setConnected] = useState(false);
  const [sessions, setSessions] = useState([]);
  const [activeSid, setActiveSid] = useState(null);
  const [messagesBySid, setMessagesBySid] = useState({}); // sid -> Message[]（每会话独立消息流）
  const [streamingSids, setStreamingSids] = useState({});  // sid -> bool（每会话流式状态）
  const [error, setError] = useState(null);
  const [approval, setApproval] = useState(null);
  const [clarify, setClarify] = useState(null);
  const [providerInfo, setProviderInfo] = useState(null);
  const [cwd, setCwd] = useState('');
  const [defaultCwd, setDefaultCwd] = useState(''); // 「默认」目录（侧栏分组锚点）
  const [sessionFiles, setSessionFiles] = useState({}); // sid -> [{path, tool}]
  const [filesPanelOpen, setFilesPanelOpen] = useState(true);
  const [toast, setToast] = useState(null);
  const [commands, setCommands] = useState([]);
  const commandsRef = useRef([]);
  const [stopRequested, setStopRequested] = useState(false);
  const stopRequestedRef = useRef(false);
  const interruptRetryRef = useRef(null);
  const [compressing, setCompressing] = useState(false);
  const [personas, setPersonas] = useState([]); // manifest 数组（GET /api/personas）
  const personasByIdRef = useRef({});           // id -> manifest 快速查表
  const pendingInitPromptRef = useRef('');      // 应用专家后待发送的 default_init_prompt

  const messagesBySidRef = useRef({});       // 消息流真实存储（ref 为准，后台会话不触发渲染）
  const streamingSidsRef = useRef({});       // 流式状态镜像（ref 为准，避免后台流式引发重渲染）
  const activeSidRef = useRef(activeSid);
  const sessionWaitersRef = useRef([]);
  const clientRef = useRef(null);
  const pendingRequestsRef = useRef([]);     // 后台会话待处理的 clarify/approval 请求（切回时弹出）

  /** 每会话流式状态：写 ref（真实），仅激活会话同步到 state 触发渲染 */
  const setSessionStreaming = useCallback((sid, v) => {
    streamingSidsRef.current = { ...streamingSidsRef.current, [sid]: !!v };
    if (sid === activeSidRef.current) setStreamingSids(streamingSidsRef.current);
  }, []);

  /** 切回会话时一次性把 ref 流式状态同步进 state（后台流式态需要可见） */
  const syncStreamingToState = useCallback(() => {
    setStreamingSids({ ...streamingSidsRef.current });
  }, []);

  /** 每会话消息流更新：只写 ref；仅激活会话触发 React 渲染（后台高频 delta 不重渲染） */
  const updateFor = useCallback((sid, fn) => {
    const cur = messagesBySidRef.current;
    const arr = cur[sid] || [];
    const next = fn(arr);
    if (next === arr) return; // fn 未产生新数组（无变化）
    messagesBySidRef.current = { ...cur, [sid]: next };
    if (sid === activeSidRef.current) setMessagesBySid(messagesBySidRef.current);
  }, []);

  /** 判断某会话是否在流式生成中（ref 为准，供动作守卫用） */
  const isStreaming = useCallback((sid) => !!streamingSidsRef.current[sid], []);

  /** 向指定会话推一条消息（默认当前激活会话） */
  const pushMessage = useCallback((msg, sid) => {
    const target = sid || activeSidRef.current;
    if (!target) return;
    updateFor(target, (msgs) => [...msgs, msg]);
  }, [updateFor]);

  /** 推送一条系统消息（命令结果等，可指定会话） */
  const pushSystem = useCallback((text, sid) => {
    pushMessage({ id: uid(), role: 'system', content: text, ts: Date.now() }, sid);
  }, [pushMessage]);

  /** 纯函数：更新最后一条 assistant 消息（流式累积） */
  const patchLastAssistantIn = useCallback((msgs, fn) => {
    const next = [...msgs];
    for (let i = next.length - 1; i >= 0; i--) {
      if (next[i].role === 'assistant') {
        next[i] = fn(next[i]);
        break;
      }
    }
    return next;
  }, []);

  /** 追加有序片段：thinking/text 连续时合并，类型切换时新开片段 */
  const appendPart = useCallback((msg, part) => {
    const parts = [...(msg.parts || [])];
    const last = parts[parts.length - 1];
    if ((part.type === 'text' || part.type === 'thinking') && last && last.type === part.type) {
      parts[parts.length - 1] = { ...last, text: (last.text || '') + (part.text || '') };
    } else {
      parts.push(part);
    }
    return { ...msg, parts };
  }, []);

  /** 纯函数：对最后一条「运行中」的 subagent part 应用 fn（子代理事件累积） */
  const patchLastSubagentIn = useCallback((msgs, fn) => {
    const next = [...msgs];
    for (let i = next.length - 1; i >= 0; i--) {
      const m = next[i];
      if (m.role !== 'assistant') continue;
      const parts = m.parts || [];
      for (let j = parts.length - 1; j >= 0; j--) {
        if (parts[j].type === 'subagent' && parts[j].status === 'running') {
          const copy = [...parts];
          copy[j] = fn(parts[j]);
          next[i] = { ...m, parts: copy };
          return next;
        }
      }
    }
    return next;
  }, []);

  /** 等待会话创建（new_session 的应答） */
  const ensureSession = useCallback(() => {
    const sid = activeSidRef.current;
    if (sid) return Promise.resolve(sid);
    return new Promise((resolve) => {
      sessionWaitersRef.current.push(resolve);
      clientRef.current.send({ type: 'new_session' });
    });
  }, []);

  // ── 初始化：连接后端 + 订阅事件 ──────────────────────────
  useEffect(() => {
    let disposed = false;

    (async () => {
      try {
        const client = await initClient();
        if (disposed) return;
        clientRef.current = client;
        setConnected(true);

        // 订阅 WS 事件
        client.on('open', () => setConnected(true));
        client.on('close', () => setConnected(false));

        client.on('sessions', (d) => setSessions(d.sessions || []));

        // 恢复其他目录会话时后端自动导航 → 更新 cwd 状态
        client.on('cwd_changed', (d) => {
          setCwd(d.cwd || '');
          if (d.default_cwd) setDefaultCwd(d.default_cwd);
        });

        client.on('session_created', (d) => {
          const sid = d.session_id;
          activeSidRef.current = sid;
          setActiveSid(sid);
          // 初始化该会话的消息流（不影响其他会话的 bucket）
          if (!messagesBySidRef.current[sid]) {
            messagesBySidRef.current[sid] = [];
            setMessagesBySid({ ...messagesBySidRef.current });
          }
          setSessionStreaming(sid, false);
          setSessionFiles((prev) => ({ ...prev, [sid]: [] }));
          sessionWaitersRef.current.forEach((w) => w(sid));
          sessionWaitersRef.current = [];
          // 应用专家时若带 default_init_prompt：新建会话后自动作为首个消息发送
          const initPrompt = pendingInitPromptRef.current;
          pendingInitPromptRef.current = '';
          if (initPrompt) {
            // 与 sendMessage 一致：先推一条 user 消息进消息流，再发送（后端不广播用户消息）
            pushMessage({ id: uid(), role: 'user', content: initPrompt, ts: Date.now() }, sid);
            setTimeout(() => {
              if (clientRef.current) {
                clientRef.current.send({
                  type: 'send_message',
                  session_id: sid,
                  content: initPrompt,
                });
              }
            }, 0);
          }
        });

        client.on('session_messages', (d) => {
          const sid = d.session_id;
          activeSidRef.current = sid;
          setActiveSid(sid);
          // 切回连续性：本地已有 bucket（在途/历史流式态）→ 保留，不覆盖；
          // 仅当该会话本地无 bucket（首次进入）才从 DB 全量加载
          if (!messagesBySidRef.current[sid]) {
            updateFor(sid, () => convertDbMessages(d.messages || []));
          }
          setSessionStreaming(sid, !!d.busy);
          syncStreamingToState();
          // 拉取该会话的历史成果文件（从 DB 推导）
          client.getSessionFiles(sid)
            .then((r) => setSessionFiles((prev) => ({ ...prev, [sid]: r.files || [] })))
            .catch(() => {});
        });

        client.on('file_written', (d) => {
          // 成果文件本就按 sid 存储，无需会话守卫
          setSessionFiles((prev) => {
            const list = prev[d.session_id] || [];
            const exists = list.some((f) => f.path === d.path);
            return {
              ...prev,
              [d.session_id]: exists ? list : [...list, { path: d.path, tool: d.tool || 'write_file' }],
            };
          });
        });

        client.on('turn_start', (d) => {
          setSessionStreaming(d.session_id, true);
          // 侧栏需看到后台会话的流式态：按 turn 边界把 ref 全量镜像到 state（非 per-token，开销可接受）
          setStreamingSids({ ...streamingSidsRef.current });
          updateFor(d.session_id, (msgs) => [...msgs, {
            id: uid(), role: 'assistant', parts: [], ts: Date.now(),
          }]);
        });

        client.on('thinking', (d) => {
          updateFor(d.session_id, (msgs) =>
            patchLastAssistantIn(msgs, (m) => appendPart(m, { type: 'thinking', text: d.text })));
        });

        client.on('delta', (d) => {
          updateFor(d.session_id, (msgs) =>
            patchLastAssistantIn(msgs, (m) => appendPart(m, { type: 'text', text: d.text })));
        });

        client.on('tool_start', (d) => {
          updateFor(d.session_id, (msgs) =>
            patchLastAssistantIn(msgs, (m) => appendPart(m, {
              type: 'tool', name: d.tool_name, status: 'running', args: '', result: '',
            })));
        });

        client.on('tool_result', (d) => {
          updateFor(d.session_id, (msgs) =>
            patchLastAssistantIn(msgs, (m) => {
              const parts = [...m.parts];
              for (let i = parts.length - 1; i >= 0; i--) {
                if (parts[i].type === 'tool' && parts[i].name === d.tool_name && parts[i].status === 'running') {
                  parts[i] = { ...parts[i], status: d.status === 'error' ? 'error' : 'done', result: d.result };
                  break;
                }
              }
              return { ...m, parts };
            }));
        });

        // ── 子代理事件（默认折叠，点击展开查看全部过程）──────────────────
        client.on('subagent_start', (d) => {
          updateFor(d.session_id, (msgs) =>
            patchLastAssistantIn(msgs, (m) => appendPart(m, {
              type: 'subagent', subagentId: d.subagent_id, task: d.task || '',
              status: 'running', parts: [], open: false,
            })));
        });

        client.on('subagent_thinking', (d) => {
          updateFor(d.session_id, (msgs) =>
            patchLastSubagentIn(msgs, (sa) => ({
              ...sa,
              parts: appendPart({ parts: sa.parts }, { type: 'thinking', text: d.text }).parts,
            })));
        });

        client.on('subagent_delta', (d) => {
          updateFor(d.session_id, (msgs) =>
            patchLastSubagentIn(msgs, (sa) => ({
              ...sa,
              parts: appendPart({ parts: sa.parts }, { type: 'text', text: d.text }).parts,
            })));
        });

        client.on('subagent_tool_start', (d) => {
          updateFor(d.session_id, (msgs) =>
            patchLastSubagentIn(msgs, (sa) => ({
              ...sa,
              parts: [...sa.parts, {
                type: 'tool', name: d.tool_name, status: 'running', args: '', result: '',
              }],
            })));
        });

        client.on('subagent_tool_result', (d) => {
          updateFor(d.session_id, (msgs) =>
            patchLastSubagentIn(msgs, (sa) => {
              const parts = [...sa.parts];
              for (let i = parts.length - 1; i >= 0; i--) {
                if (parts[i].type === 'tool' && parts[i].name === d.tool_name && parts[i].status === 'running') {
                  parts[i] = { ...parts[i], status: d.status === 'error' ? 'error' : 'done', result: d.result };
                  break;
                }
              }
              return { ...sa, parts };
            }));
        });

        client.on('subagent_end', (d) => {
          updateFor(d.session_id, (msgs) =>
            patchLastSubagentIn(msgs, (sa) => ({ ...sa, status: 'done' })));
        });

        client.on('turn_end', (d) => {
          const resultSid = d.session_id;
          const origSid = d.orig_session_id || resultSid;
          // 压缩可能产生新会话：把该轮消息流 bucket 从 orig 迁移到 result，跟随新 sid
          if (resultSid && resultSid !== origSid && messagesBySidRef.current[origSid]) {
            const migrated = messagesBySidRef.current[origSid];
            const rest = { ...messagesBySidRef.current };
            delete rest[origSid];
            rest[resultSid] = migrated;
            messagesBySidRef.current = rest;
            streamingSidsRef.current = { ...streamingSidsRef.current, [resultSid]: false, [origSid]: false };
            if (activeSidRef.current === origSid) {
              activeSidRef.current = resultSid;
              setActiveSid(resultSid);
              client.getSessionFiles(resultSid)
                .then((r) => setSessionFiles((prev) => ({ ...prev, [resultSid]: r.files || [] })))
                .catch(() => {});
            }
            setMessagesBySid({ ...rest });
            setStreamingSids({ ...streamingSidsRef.current });
          } else {
            setSessionStreaming(resultSid || origSid, false);
            setStreamingSids({ ...streamingSidsRef.current });
          }
          // 仅激活会话复位 stop 状态（后台会话各自独立）
          if (resultSid === activeSidRef.current || origSid === activeSidRef.current) {
            setStopRequested(false);
            stopRequestedRef.current = false;
            clearTimeout(interruptRetryRef.current);
          }
        });

        client.on('compress_start', (d) => {
          if (d.session_id === activeSidRef.current) setCompressing(true);
        });

        client.on('compress_end', (d) => {
          if (d.session_id === activeSidRef.current) {
            setCompressing(false);
            setToast('上下文压缩完成');
            setTimeout(() => setToast(null), 3000);
          }
        });

        client.on('error', (d) => {
          setError(d.message || '未知错误');
          if (d.session_id) setSessionStreaming(d.session_id, false);
          setTimeout(() => setError(null), 6000);
        });

        client.on('toast', (d) => {
          if (!d.message) return;
          setToast(d.message);
          setTimeout(() => setToast(null), 5000);
        });

        client.on('command_result', (d) => {
          if (d.text) pushSystem(d.text, d.session_id);
        });

        // ── 审批/澄清弹窗：按会话归属——激活会话直接弹，后台会话暂存切回再弹 ──
        client.on('clarify_request', (d) => {
          if (d.session_id && d.session_id !== activeSidRef.current) {
            pendingRequestsRef.current.push({ type: 'clarify', ...d });
            return;
          }
          setClarify(d);
        });
        client.on('approval_request', (d) => {
          if (d.session_id && d.session_id !== activeSidRef.current) {
            pendingRequestsRef.current.push({ type: 'approval', ...d });
            return;
          }
          setApproval(d);
        });

        // 初始加载会话列表、配置、命令、专家
        const [sessRes, cfgRes, provRes, cmdRes, cwdRes, persRes] = await Promise.all([
          client.loadSessions(),
          client.getConfig().catch(() => null),
          client.getProviders().catch(() => null),
          client.getCommands().catch(() => ({ commands: [] })),
          client.getCwd().catch(() => null),
          client.getPersonas().catch(() => ({ personas: [] })),
        ]);
        if (disposed) return;
        setSessions(sessRes.sessions || []);
        setPersonas(persRes.personas || []);
        personasByIdRef.current = {};
        (persRes.personas || []).forEach((p) => { personasByIdRef.current[p.id] = p; });
        setProviderInfo(deriveProviderInfo(provRes));
        // 优先用后端实时 cwd（config 可能未写入 general.cwd）
        setCwd(cwdRes?.cwd || cfgRes?.general?.cwd || '');
        setDefaultCwd(cwdRes?.default_cwd || '');
        const cmds = cmdRes.commands || [];
        setCommands(cmds);
        commandsRef.current = cmds;

        // 恢复最近会话（若有），否则自动新建
        const recent = (sessRes.sessions || [])[0];
        if (recent) {
          client.send({ type: 'resume_session', session_id: recent.id });
        } else {
          client.send({ type: 'new_session' });
        }
      } catch (e) {
        setError(`后端连接失败: ${e.message}`);
      }
    })();

    return () => { disposed = true; };
  }, []);

  // 设置页保存配置后刷新头部厂商/模型信息（厂商/模型切换立即反映）
  const refreshProviderInfo = useCallback(async () => {
    try {
      const res = await clientRef.current.getProviders();
      setProviderInfo(deriveProviderInfo(res));
    } catch {
      // 忽略刷新失败（下次启动自然更新）
    }
  }, []);

  // 对话窗口切换模型：全局生效（等价 CLI /model），切换成功后刷新徽章
  const changeModel = useCallback(async (model) => {
    if (!providerInfo || isStreaming(activeSidRef.current)) return;
    try {
      const res = await clientRef.current.setActiveModel({ provider: providerInfo.name, model });
      if (!res.ok) {
        setError(res.error || '切换模型失败');
        return;
      }
      if (res.rebuild_warning) setError(res.rebuild_warning);
      await refreshProviderInfo();
    } catch (e) {
      setError(e.message);
    }
  }, [providerInfo, refreshProviderInfo]);

  // ── 动作 ─────────────────────────────────────────────────
  const sendMessage = useCallback(async (text, options = {}) => {
    const content = text.trim();
    if (!content || isStreaming(activeSidRef.current)) return;
    setError(null);
    const client = clientRef.current;
    try {
      const sid = await ensureSession();
      // 自动生成标题：第一轮且未命名
      if ((messagesBySidRef.current[sid] || []).length === 0) {
        const title = content.slice(0, 30);
        client.setTitle(sid, title);
      }
      pushMessage({ id: uid(), role: 'user', content, ts: Date.now() }, sid);
      const payload = { type: 'send_message', session_id: sid, content };
      // 每轮思考强度覆盖（undefined 不序列化 → 服务端走厂商默认）
      if (options.thinking_effort) payload.thinking_effort = options.thinking_effort;
      client.send(payload);
    } catch (e) {
      setError(e.message);
    }
  }, [ensureSession, pushMessage, isStreaming]);

  const interrupt = useCallback(() => {
    // 定向停止当前激活会话（后台会话各自独立，不受影响）
    const sid = activeSidRef.current;
    // 关键消息走排队发送，避免 WS 重连瞬间被丢弃
    clientRef.current?.sendWhenReady({ type: 'interrupt', session_id: sid });
    setStopRequested(true);
    stopRequestedRef.current = true;
    // 保险：内核在"无 chunk 期间"（模型静默/工具执行中）不检查中断，
    // 3 秒未收到 turn_end 则重发一次，确保停止一定生效
    clearTimeout(interruptRetryRef.current);
    interruptRetryRef.current = setTimeout(() => {
      if (isStreaming(sid) && stopRequestedRef.current) {
        clientRef.current?.sendWhenReady({ type: 'interrupt', session_id: sid });
      }
    }, 3000);
  }, [isStreaming]);

  const newSession = useCallback(() => {
    // 多会话并行：不再自动中断其他会话的生成
    clientRef.current?.send({ type: 'new_session' });
  }, []);

  /** 打开专家选择界面（主区域 view 切换；专家徽章点击也走这里） */
  const openExperts = useCallback(() => setView('experts'), []);

  /** 应用专家：立即新建会话并注入该专家（换专家 = 新建会话，原会话保留），随后切回对话 */
  const applyExpert = useCallback((persona) => {
    if (!clientRef.current) {
      setError('内核未连接，无法应用专家');
      return;
    }
    // 多会话并行：不再自动中断其他会话的生成
    // 应用专家后自动发送 default_init_prompt（若有）
    pendingInitPromptRef.current = persona && persona.default_init_prompt
      ? persona.default_init_prompt : '';
    clientRef.current.send({
      type: 'new_session',
      persona_id: persona ? persona.id : '',
    });
    setView('chat');
  }, []);

  /** 当前会话绑定的专家（从 sessions + personas 派生，单一事实源） */
  const activePersonaId = useMemo(() => {
    if (!activeSid) return '';
    const s = sessions.find((x) => x.id === activeSid);
    return (s && s.persona_id) || '';
  }, [activeSid, sessions]);
  const activePersona = useMemo(
    () => (activePersonaId ? (personasByIdRef.current[activePersonaId] || null) : null),
    [activePersonaId, personas],
  );

  const resumeSession = useCallback((sid) => {
    // 切回连续性：先切 activeSid + 一次性同步 ref 状态。
    // 本地已有消息流 bucket（在途/历史）→ 保留，不发 resume（不打断后台生成、不重载）；
    // 本地无 bucket → 向后端要该会话全量历史。不再"切前自动中断"——这是并行前提。
    activeSidRef.current = sid;
    setActiveSid(sid);
    syncStreamingToState();
    setMessagesBySid({ ...messagesBySidRef.current });
    if (!messagesBySidRef.current[sid]) {
      clientRef.current?.send({ type: 'resume_session', session_id: sid });
    }
    // 切回后弹出来自该会话的后台审批/澄清请求
    const idx = pendingRequestsRef.current.findIndex((r) => r.session_id === sid);
    if (idx >= 0) {
      const [req] = pendingRequestsRef.current.splice(idx, 1);
      if (req.type === 'clarify') setClarify(req);
      else if (req.type === 'approval') setApproval(req);
    }
  }, [syncStreamingToState]);

  const deleteSession = useCallback(async (sid) => {
    const client = clientRef.current;
    try {
      const res = await client.deleteSession(sid);
      setSessions(res.sessions || []);
      // 清理该会话的本地状态（消息流 / 流式标记 / 成果文件 / 后台弹窗）
      const rest = { ...messagesBySidRef.current };
      delete rest[sid];
      messagesBySidRef.current = rest;
      const srest = { ...streamingSidsRef.current };
      delete srest[sid];
      streamingSidsRef.current = srest;
      setMessagesBySid({ ...rest });
      setStreamingSids({ ...srest });
      setSessionFiles((prev) => {
        const f = { ...prev };
        delete f[sid];
        return f;
      });
      pendingRequestsRef.current = pendingRequestsRef.current.filter((r) => r.session_id !== sid);
      if (sid === activeSidRef.current) {
        const remaining = (res.sessions || []).filter((s) => s.id !== sid);
        if (remaining.length > 0) client.send({ type: 'resume_session', session_id: remaining[0].id });
        else client.send({ type: 'new_session' });
      }
    } catch (e) {
      setError(e.message);
    }
  }, []);

  const answerApproval = useCallback((requestId, answer) => {
    clientRef.current?.send({ type: 'approval_answer', request_id: requestId, answer });
    setApproval(null);
  }, []);

  const answerClarify = useCallback((requestId, answer) => {
    clientRef.current?.send({ type: 'clarify_answer', request_id: requestId, answer });
    setClarify(null);
  }, []);

  const onTitleEdited = useCallback(async (sid, title) => {
    try {
      await clientRef.current.setTitle(sid, title);
      const res = await clientRef.current.loadSessions();
      setSessions(res.sessions || []);
    } catch (_e) { /* ignore */ }
  }, []);

  /** 选择并切换工作目录：系统目录选择器 → 后端 chdir（守卫 A 权威校验）→ 更新状态 */
  const changeCwd = useCallback(async () => {
    const sid = activeSidRef.current;
    // 当前会话已有消息时禁止切换（前端兜底；后端按 message_count 权威校验）
    if ((messagesBySidRef.current[sid] || []).length > 0) {
      setToast('当前会话已有消息，请新建会话后再切换工作目录');
      setTimeout(() => setToast(null), 4000);
      return;
    }
    try {
      // Electron 环境：系统目录选择器；浏览器调试环境兜底用默认目录
      let chosen = null;
      if (window.desktop?.openDirectoryDialog) {
        const res = await window.desktop.openDirectoryDialog();
        if (res.canceled || !res.paths?.length) return;
        chosen = res.paths[0];
      }
      if (!chosen) return;
      // 带上 session_id：后端守卫 A 权威校验 + 空会话跟随新目录（重绑定）
      const res = await clientRef.current.setCwd(chosen, sid);
      if (res.ok) {
        setCwd(res.cwd);
        if (res.default_cwd) setDefaultCwd(res.default_cwd);
        // 空会话重绑定后目录分组可能变化，刷新会话列表
        if (res.rebound_session_id) {
          const s = await clientRef.current.loadSessions().catch(() => null);
          if (s) setSessions(s.sessions || []);
        }
        setToast(`工作目录已切换到 ${res.cwd}`);
        setTimeout(() => setToast(null), 4000);
      } else {
        setToast(res.error || '切换工作目录失败');
        setTimeout(() => setToast(null), 4000);
      }
    } catch (e) {
      setToast(e.message || '切换工作目录失败');
      setTimeout(() => setToast(null), 4000);
    }
  }, []);

  /** 斜杠命令分发：纯 UI 命令前端处理，内核命令走后端 */
  const handleCommand = useCallback((raw) => {
    const trimmed = raw.trim();
    const parts = trimmed.split(/\s+/);
    const cmd = (parts[0] || '').toLowerCase();
    const arg = trimmed.slice(parts[0]?.length || 0).trim();
    const client = clientRef.current;

    if (cmd === '/help') {
      const list = commandsRef.current || [];
      const lines = list.map((c) => `  ${c.cmd.padEnd(14)} — ${c.desc}`);
      pushSystem(`可用命令：\n${lines.join('\n')}`);
      return;
    }
    if (cmd === '/clear') {
      newSession();
      pushSystem('[history cleared — starting new session]');
      return;
    }
    if (cmd === '/exit') {
      if (window.desktop && window.desktop.quit) window.desktop.quit();
      else window.close();
      return;
    }
    // 后端命令 / 技能命令
    client.send({ type: 'command', cmd: trimmed, session_id: activeSidRef.current || '' });
  }, [newSession, resumeSession, pushSystem]);

  // ── 派生（激活会话视角）──────────────────────────────
  const streaming = !!streamingSids[activeSid];
  const activeMessages = messagesBySid[activeSid] || [];
  // cwd 切换锁定：当前会话已有消息（turn_start 已推 assistant → 含流式中）→ 置灰按钮
  const cwdLocked = useMemo(
    () => !!activeSid && (messagesBySid[activeSid] || []).length > 0,
    [activeSid, messagesBySid],
  );

  // ── 渲染 ─────────────────────────────────────────────────
  return (
    <div className="app">
      <Sidebar
        sessions={sessions}
        activeSid={activeSid}
        view={view}
        providerInfo={providerInfo}
        connected={connected}
        personas={personas}
        defaultCwd={defaultCwd}
        streamingSids={streamingSids}
        onNewSession={newSession}
        onResume={resumeSession}
        onDelete={deleteSession}
        onView={setView}
      />

      <main className="main">
        {view === 'chat' && (
          <div className="chat-wrap">
            {compressing && (
              <div className="compress-banner">
                <span className="compress-spin" /> 正在压缩上下文，请稍候…
              </div>
            )}
            <ChatView
              messages={activeMessages}
              streaming={streaming}
              activeSid={activeSid}
              cwd={cwd}
              cwdLocked={cwdLocked}
              onChangeCwd={changeCwd}
              providerInfo={providerInfo}
              tokens={(sessions.find((s) => s.id === activeSid) || {}).tokens || { input: 0, output: 0, reasoning: 0 }}
              fileCount={(sessionFiles[activeSid] || []).length}
              filesPanelOpen={filesPanelOpen}
              onToggleFiles={() => setFilesPanelOpen((v) => !v)}
              onSend={sendMessage}
              onCommand={handleCommand}
              commands={commands}
              onInterrupt={interrupt}
              stopRequested={stopRequested}
              onTitleEdited={onTitleEdited}
              onModelChange={changeModel}
              activePersona={activePersona}
              onOpenExperts={openExperts}
            />
            {filesPanelOpen && (
              <FilesPanel
                files={sessionFiles[activeSid] || []}
                onClose={() => setFilesPanelOpen(false)}
              />
            )}
          </div>
        )}
        {view === 'experts' && (
          <ExpertsView
            personas={personas}
            activePersonaId={activePersonaId}
            onApply={applyExpert}
          />
        )}
        {view === 'settings' && (
          <SettingsView clientRef={clientRef} setError={setError} onConfigSaved={refreshProviderInfo} />
        )}
        {view === 'skills' && <SkillsView clientRef={clientRef} setError={setError} />}
      </main>

      {error && <div className="toast error">{error}</div>}
      {toast && <div className="toast info">{toast}</div>}

      {approval && (
        <ApprovalModal
          request={approval}
          onAnswer={answerApproval}
        />
      )}
      {clarify && (
        <ClarifyModal
          request={clarify}
          onAnswer={answerClarify}
        />
      )}
    </div>
  );
}
