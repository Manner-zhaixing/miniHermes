/**
 * 后端客户端：WebSocket 双向通信 + HTTP API。
 * Electron 环境通过 window.desktop.getBackendUrl() 获取动态端口；
 * 浏览器调试模式可用 localStorage('mh_backend_url') 覆盖。
 */

const DEFAULT_URL = 'http://127.0.0.1:8765';

export function getBackendUrl() {
  if (window.desktop && window.desktop.getBackendUrl) {
    return window.desktop.getBackendUrl();
  }
  return Promise.resolve(localStorage.getItem('mh_backend_url') || DEFAULT_URL);
}

export class BackendClient {
  constructor(baseUrl) {
    this.baseUrl = baseUrl;
    this.ws = null;
    this.connected = false;
    this._handlers = new Map(); // type -> Set<fn>
    this._reconnectTimer = null;
    this._closedByUser = false;
  }

  // ── 事件订阅 ─────────────────────────────────────────────
  on(type, fn) {
    if (!this._handlers.has(type)) this._handlers.set(type, new Set());
    this._handlers.get(type).add(fn);
    return () => this._handlers.get(type)?.delete(fn);
  }

  _emit(type, payload) {
    const set = this._handlers.get(type);
    if (set) set.forEach((fn) => fn(payload));
  }

  _emitAll(payload) {
    this._emit(payload.type, payload);
  }

  // ── WebSocket ────────────────────────────────────────────
  connect() {
    return new Promise((resolve) => {
      const wsUrl = this.baseUrl.replace(/^http/, 'ws') + '/ws';
      const ws = new WebSocket(wsUrl);
      this.ws = ws;

      ws.onopen = () => {
        this.connected = true;
        this._emit('open', {});
        resolve();
      };
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          this._emitAll(data);
        } catch (_e) {
          console.warn('[ws] 非 JSON 消息', ev.data);
        }
      };
      ws.onclose = () => {
        this.connected = false;
        this._emit('close', {});
        if (!this._closedByUser) this._scheduleReconnect();
      };
      ws.onerror = () => {
        /* onclose 会触发重连 */
      };
    });
  }

  _scheduleReconnect() {
    if (this._reconnectTimer) return;
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      if (!this._closedByUser) this.connect();
    }, 2000);
  }

  send(payload) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    } else {
      console.warn('[ws] 未连接，丢弃消息', payload);
    }
  }

  /** 关键消息（如 interrupt）：断线时排队，等连接恢复后补发 */
  sendWhenReady(payload, timeoutMs = 10000) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.send(payload);
      return;
    }
    const start = Date.now();
    const trySend = () => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.send(payload);
        return;
      }
      if (Date.now() - start > timeoutMs) return;
      setTimeout(trySend, 400);
    };
    trySend();
  }

  close() {
    this._closedByUser = true;
    if (this.ws) this.ws.close();
  }

  // ── HTTP ─────────────────────────────────────────────────
  async http(path, options = {}) {
    const res = await fetch(this.baseUrl + path, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
    return res.json();
  }

  get(path) { return this.http(path); }
  post(path, body) { return this.http(path, { method: 'POST', body: JSON.stringify(body ?? {}) }); }
  del(path) { return this.http(path, { method: 'DELETE' }); }

  // ── 业务便捷方法 ─────────────────────────────────────────
  loadSessions() { return this.get('/api/sessions'); }
  newSessionHttp(body) { return this.post('/api/sessions', body ?? {}); }
  getPersonas() { return this.get('/api/personas'); }
  getConfig() { return this.get('/api/config'); }
  getProviders() { return this.get('/api/providers'); }
  saveConfig(patch) { return this.post('/api/config', patch); }
  testProviderConnection(payload) { return this.post('/api/providers/test', payload); }
  setActiveModel(payload) { return this.post('/api/providers/model', payload); }
  getMemory() { return this.get('/api/memory'); }
  saveMemory(patch) { return this.post('/api/memory', patch); }
  getSkills() { return this.get('/api/skills'); }
  getSkill(name) { return this.get(`/api/skills/${encodeURIComponent(name)}`); }
  getTools() { return this.get('/api/tools'); }
  getCommands() { return this.get('/api/commands'); }
  getCwd() { return this.get('/api/cwd'); }
  setCwd(path, sessionId) { return this.post('/api/cwd', { path, session_id: sessionId || null }); }
  setTitle(sid, title) { return this.post(`/api/sessions/${sid}/title`, { title }); }
  deleteSession(sid) { return this.del(`/api/sessions/${sid}`); }
  getSessionFiles(sid) { return this.get(`/api/sessions/${sid}/files`); }
}

let _client = null;
export function getClient() {
  return _client;
}
export async function initClient() {
  const url = await getBackendUrl();
  _client = new BackendClient(url);
  await _client.connect();
  return _client;
}
