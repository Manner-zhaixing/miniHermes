import React, { useEffect, useRef, useState, useCallback } from 'react';
import { initClient, getClient } from './api.js';
import { convertDbMessages } from './dbConvert.js';
import Sidebar from './components/Sidebar.jsx';
import ChatView from './components/ChatView.jsx';
import SettingsView from './components/SettingsView.jsx';
import SkillsView from './components/SkillsView.jsx';
import ApprovalModal from './components/ApprovalModal.jsx';
import ClarifyModal from './components/ClarifyModal.jsx';
import PlanApprovalModal from './components/PlanApprovalModal.jsx';
import FilesPanel from './components/FilesPanel.jsx';

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
  const [messages, setMessages] = useState([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState(null);
  const [approval, setApproval] = useState(null);
  const [clarify, setClarify] = useState(null);
  const [providerInfo, setProviderInfo] = useState(null);
  const [cwd, setCwd] = useState('');
  const [sessionFiles, setSessionFiles] = useState({}); // sid -> [{path, tool}]
  const [filesPanelOpen, setFilesPanelOpen] = useState(true);
  const [toast, setToast] = useState(null);
  const [commands, setCommands] = useState([]);
  const commandsRef = useRef([]);
  const [stopRequested, setStopRequested] = useState(false);
  const stopRequestedRef = useRef(false);
  const interruptRetryRef = useRef(null);
  const [compressing, setCompressing] = useState(false);
  const [mode, setMode] = useState('normal'); // 'normal' | 'plan'
  const [planApproval, setPlanApproval] = useState(null);

  const messagesRef = useRef(messages);
  const activeSidRef = useRef(activeSid);
  const streamingRef = useRef(false);
  const sessionWaitersRef = useRef([]);
  const clientRef = useRef(null);

  const setStreamingBoth = useCallback((v) => {
    streamingRef.current = v;
    setStreaming(v);
  }, []);

  /** 会话隔离：流式事件只处理当前活跃会话的 */
  const isCurrentSession = useCallback((sid) => {
    return !sid || sid === activeSidRef.current;
  }, []);

  const syncMessages = useCallback((next) => {
    messagesRef.current = next;
    setMessages(next);
  }, []);

  const pushMessage = useCallback((msg) => {
    syncMessages([...messagesRef.current, msg]);
  }, [syncMessages]);

  /** 推送一条系统消息（命令结果等） */
  const pushSystem = useCallback((text) => {
    syncMessages([...messagesRef.current, {
      id: uid(), role: 'system', content: text, ts: Date.now(),
    }]);
  }, [syncMessages]);

  /** 更新最后一条 assistant 消息（流式累积） */
  const patchLastAssistant = useCallback((fn) => {
    const msgs = [...messagesRef.current];
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role === 'assistant') {
        msgs[i] = fn(msgs[i]);
        break;
      }
    }
    syncMessages(msgs);
  }, [syncMessages]);

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

        client.on('session_created', (d) => {
          const sid = d.session_id;
          activeSidRef.current = sid;
          setActiveSid(sid);
          syncMessages([]);
          setStreamingBoth(false);
          setSessionFiles((prev) => ({ ...prev, [sid]: [] }));
          sessionWaitersRef.current.forEach((w) => w(sid));
          sessionWaitersRef.current = [];
        });

        client.on('session_messages', (d) => {
          activeSidRef.current = d.session_id;
          setActiveSid(d.session_id);
          syncMessages(convertDbMessages(d.messages || []));
          setStreamingBoth(false);
          // 拉取该会话的历史成果文件（从 DB 推导）
          client.getSessionFiles(d.session_id)
            .then((r) => setSessionFiles((prev) => ({ ...prev, [d.session_id]: r.files || [] })))
            .catch(() => {});
        });

        client.on('file_written', (d) => {
          if (!isCurrentSession(d.session_id)) return;
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
          if (!isCurrentSession(d.session_id)) return;
          setStreamingBoth(true);
          pushMessage({
            id: uid(), role: 'assistant', parts: [], ts: Date.now(),
          });
        });

        client.on('thinking', (d) => {
          if (!isCurrentSession(d.session_id)) return;
          patchLastAssistant((m) => appendPart(m, { type: 'thinking', text: d.text }));
        });

        client.on('delta', (d) => {
          if (!isCurrentSession(d.session_id)) return;
          patchLastAssistant((m) => appendPart(m, { type: 'text', text: d.text }));
        });

        client.on('tool_start', (d) => {
          if (!isCurrentSession(d.session_id)) return;
          patchLastAssistant((m) => appendPart(m, {
            type: 'tool', name: d.tool_name, status: 'running', args: '', result: '',
          }));
        });

        client.on('tool_result', (d) => {
          if (!isCurrentSession(d.session_id)) return;
          patchLastAssistant((m) => {
            const parts = [...m.parts];
            for (let i = parts.length - 1; i >= 0; i--) {
              if (parts[i].type === 'tool' && parts[i].name === d.tool_name && parts[i].status === 'running') {
                parts[i] = { ...parts[i], status: d.status === 'error' ? 'error' : 'done', result: d.result };
                break;
              }
            }
            return { ...m, parts };
          });
        });

        client.on('turn_end', (d) => {
          // 不检查 sid：上下文压缩可能产生新的 session_id，此时若不复位
          // streaming 状态会卡死（无法发送下一条消息）。turn_start 已有
          // 会话隔离，这里仅负责复位。
          setStreamingBoth(false);
          setStopRequested(false);
          stopRequestedRef.current = false;
          clearTimeout(interruptRetryRef.current);
          // 压缩可能产生新会话：前端跟随新的 session_id
          if (d.session_id && d.session_id !== activeSidRef.current) {
            activeSidRef.current = d.session_id;
            setActiveSid(d.session_id);
            client.getSessionFiles(d.session_id)
              .then((r) => setSessionFiles((prev) => ({ ...prev, [d.session_id]: r.files || [] })))
              .catch(() => {});
          }
        });

        client.on('compress_start', () => {
          setCompressing(true);
        });

        client.on('compress_end', () => {
          setCompressing(false);
          setToast('上下文压缩完成');
          setTimeout(() => setToast(null), 3000);
        });

        client.on('error', (d) => {
          setError(d.message || '未知错误');
          setStreamingBoth(false);
          setTimeout(() => setError(null), 6000);
        });

        client.on('toast', (d) => {
          if (!d.message) return;
          setToast(d.message);
          setTimeout(() => setToast(null), 5000);
        });

        client.on('command_result', (d) => {
          if (d.text) pushSystem(d.text);
        });

        client.on('clarify_request', (d) => setClarify(d));
        client.on('approval_request', (d) => setApproval(d));
        client.on('plan_approval_request', (d) => setPlanApproval(d));

        // 初始加载会话列表、配置与命令
        const [sessRes, cfgRes, provRes, cmdRes, cwdRes] = await Promise.all([
          client.loadSessions(),
          client.getConfig().catch(() => null),
          client.getProviders().catch(() => null),
          client.getCommands().catch(() => ({ commands: [] })),
          client.getCwd().catch(() => null),
        ]);
        if (disposed) return;
        setSessions(sessRes.sessions || []);
        setProviderInfo(deriveProviderInfo(provRes));
        // 优先用后端实时 cwd（config 可能未写入 general.cwd）
        setCwd(cwdRes?.cwd || cfgRes?.general?.cwd || '');
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
    if (!providerInfo || streamingRef.current) return;
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
    if (!content || streamingRef.current) return;
    setError(null);
    const client = clientRef.current;
    try {
      const sid = await ensureSession();
      // 自动生成标题：第一轮且未命名
      if (messagesRef.current.length === 0) {
        const title = content.slice(0, 30);
        client.setTitle(sid, title);
      }
      pushMessage({ id: uid(), role: 'user', content, ts: Date.now() });
      const payload = { type: 'send_message', session_id: sid, content };
      // 每轮思考强度覆盖（undefined 不序列化 → 服务端走厂商默认）
      if (options.thinking_effort) payload.thinking_effort = options.thinking_effort;
      client.send(payload);
    } catch (e) {
      setError(e.message);
    }
  }, [ensureSession, pushMessage]);

  const interrupt = useCallback(() => {
    // 关键消息走排队发送，避免 WS 重连瞬间被丢弃
    clientRef.current?.sendWhenReady({ type: 'interrupt' });
    setStopRequested(true);
    stopRequestedRef.current = true;
    // 保险：内核在"无 chunk 期间"（模型静默/工具执行中）不检查中断，
    // 3 秒未收到 turn_end 则重发一次，确保停止一定生效
    clearTimeout(interruptRetryRef.current);
    interruptRetryRef.current = setTimeout(() => {
      if (streamingRef.current && stopRequestedRef.current) {
        clientRef.current?.sendWhenReady({ type: 'interrupt' });
      }
    }, 3000);
  }, []);

  const newSession = useCallback(() => {
    // 若正在生成，先中断，避免旧事件串台
    if (streamingRef.current) clientRef.current?.send({ type: 'interrupt' });
    clientRef.current?.send({ type: 'new_session' });
  }, []);

  const resumeSession = useCallback((sid) => {
    // 切换会话前中断正在进行的生成
    if (streamingRef.current) clientRef.current?.send({ type: 'interrupt' });
    clientRef.current?.send({ type: 'resume_session', session_id: sid });
  }, []);

  const deleteSession = useCallback(async (sid) => {
    const client = clientRef.current;
    try {
      const res = await client.deleteSession(sid);
      setSessions(res.sessions || []);
      if (sid === activeSidRef.current) {
        const rest = (res.sessions || []).filter((s) => s.id !== sid);
        if (rest.length > 0) client.send({ type: 'resume_session', session_id: rest[0].id });
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

  const answerPlanApproval = useCallback((requestId, answer) => {
    clientRef.current?.send({ type: 'plan_approval_answer', request_id: requestId, answer });
    setPlanApproval(null);
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

  /** 选择并切换工作目录：系统目录选择器 → 后端 chdir → 更新状态 */
  const changeCwd = useCallback(async () => {
    // 当前会话已有消息时禁止切换，避免历史上下文与新目录不一致
    if (messagesRef.current.length > 0) {
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
      const res = await clientRef.current.setCwd(chosen);
      if (res.ok) {
        setCwd(res.cwd);
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

  // ── 渲染 ─────────────────────────────────────────────────
  return (
    <div className="app">
      <Sidebar
        sessions={sessions}
        activeSid={activeSid}
        view={view}
        providerInfo={providerInfo}
        connected={connected}
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
              messages={messages}
              streaming={streaming}
              activeSid={activeSid}
              cwd={cwd}
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
              mode={mode}
              onModeChange={setMode}
              onModelChange={changeModel}
            />
            {filesPanelOpen && (
              <FilesPanel
                files={sessionFiles[activeSid] || []}
                onClose={() => setFilesPanelOpen(false)}
              />
            )}
          </div>
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
      {planApproval && (
        <PlanApprovalModal
          request={planApproval}
          onAnswer={answerPlanApproval}
        />
      )}
    </div>
  );
}
