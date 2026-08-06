/**
 * Python 子进程桥接：spawn minihermes 内核服务，从 stdout 解析动态端口。
 */
const { spawn } = require('child_process');
const readline = require('readline');
const fs = require('fs');
const path = require('path');

class PythonBridge {
  constructor() {
    this.proc = null;
    this.ready = false;
    this.port = null;
    this.url = null;
    this.waiters = [];
  }

  resolvePython() {
    // 打包环境：使用随包携带的 PyInstaller 后端可执行
    const { app } = require('electron');
    if (app && app.isPackaged) {
      const bundled = path.join(process.resourcesPath, 'backend', 'minihermes-backend');
      if (fs.existsSync(bundled)) return bundled;
    }
    // 开发环境：minihermes 项目根 = desktop 的父目录
    const kernelRoot = path.resolve(__dirname, '..', '..');
    const venvPython = path.join(kernelRoot, '.venv', 'bin', 'python');
    if (fs.existsSync(venvPython)) return venvPython;
    // 允许通过环境变量指定
    if (process.env.MINIHERMES_PYTHON) return process.env.MINIHERMES_PYTHON;
    return 'python3';
  }

  start() {
    const { app } = require('electron');
    const packaged = app && app.isPackaged;
    const kernelRoot = path.resolve(__dirname, '..', '..');
    const backendScript = path.join(__dirname, '..', 'backend', 'server.py');
    const python = this.resolvePython();

    // 打包环境：直接执行 PyInstaller 产物（无脚本参数）
    // 开发环境：python server.py
    const args = packaged ? [] : [backendScript];
    const cwd = packaged ? path.dirname(path.dirname(python)) : kernelRoot;

    this.proc = spawn(python, args, {
      cwd,
      env: { ...process.env },
    });

    const rl = readline.createInterface({ input: this.proc.stdout });
    rl.on('line', (line) => {
      try {
        const data = JSON.parse(line.trim());
        if (data && data.port) {
          this.port = data.port;
          this.url = `http://127.0.0.1:${data.port}`;
          this.ready = true;
          const waiters = this.waiters;
          this.waiters = [];
          waiters.forEach((w) => w(this.url));
        }
      } catch (_e) {
        // 非 JSON 行忽略（内核可能打印警告）
      }
    });

    this.proc.stderr.on('data', (d) => {
      process.stderr.write(`[python] ${d}`);
    });

    this.proc.on('exit', (code, signal) => {
      this.ready = false;
      this.port = null;
      this.url = null;
      if (!this._stopping) {
        process.stderr.write(`[python] backend exited: code=${code} signal=${signal}\n`);
      }
    });

    this.proc.on('error', (err) => {
      process.stderr.write(`[python] failed to spawn: ${err.message}\n`);
    });
  }

  /** 返回后端 base URL（等待就绪） */
  getUrl() {
    if (this.ready && this.url) return Promise.resolve(this.url);
    return new Promise((resolve) => this.waiters.push(resolve));
  }

  stop() {
    this._stopping = true;
    if (this.proc && this.proc.exitCode === null) {
      this.proc.kill('SIGTERM');
    }
    this.proc = null;
  }
}

module.exports = PythonBridge;
