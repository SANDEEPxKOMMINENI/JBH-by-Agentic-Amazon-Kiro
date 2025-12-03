import { spawn } from 'child_process';
import { EventEmitter } from 'events';
import * as path from 'path';
import * as fs from 'fs';
import { fileURLToPath } from 'url';
import { app } from 'electron';
import { frontendLogger, pythonLogger } from './utils/logger.js';
import { LOCAL_BACKEND_PORT, LOCAL_BACKEND_URL } from '../config.js';
// ES module equivalent of __dirname
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
export class FastAPIWorker extends EventEmitter {
    process = null;
    isConnected = false;
    serverUrl = '';
    port = LOCAL_BACKEND_PORT;
    constructor(port = LOCAL_BACKEND_PORT) {
        super();
        this.port = port;
        this.serverUrl = LOCAL_BACKEND_URL.replace('localhost', '127.0.0.1');
    }
    async start() {
        // Collect all output for debugging
        let stdoutBuffer = '';
        let stderrBuffer = '';
        try {
            const backendExecutable = await this.findBackendExecutable();
            frontendLogger.log('🚀 Starting FastAPI server...');
            frontendLogger.log('Backend executable:', backendExecutable);
            if (!fs.existsSync(backendExecutable)) {
                throw new Error(`Backend executable not found: ${backendExecutable}`);
            }
            // Check if this is a PyInstaller executable or Python interpreter
            // Support both forward and backward slashes for cross-platform compatibility
            const isPyInstaller = backendExecutable.includes('fastapi_server/fastapi_server') ||
                backendExecutable.includes('fastapi_server\\fastapi_server') ||
                backendExecutable.endsWith('.exe');
            const args = isPyInstaller
                ? ['--port', this.port.toString(), '--host', '127.0.0.1']
                : [
                    path.join(__dirname, '..', '..', '..', 'backend', 'fastapi_server.py'),
                    '--port',
                    this.port.toString(),
                    '--host',
                    '127.0.0.1',
                ];
            const cwd = isPyInstaller
                ? path.dirname(backendExecutable)
                : path.join(__dirname, '..', '..', '..', 'backend');
            frontendLogger.log('Using PyInstaller:', isPyInstaller);
            if (!isPyInstaller) {
                frontendLogger.log('Using Python script:', args[0]);
            }
            // Determine APP_ENV for the backend
            // Priority: 1) app-env.json config file (set at build time), 2) process.env, 3) default
            let appEnv = app.isPackaged ? 'production' : 'local';
            try {
                // Read APP_ENV from bundled config file (set during build)
                const configPath = app.isPackaged
                    ? path.join(process.resourcesPath, 'app.asar', 'dist', 'config', 'app-env.json')
                    : path.join(__dirname, '..', '..', 'dist', 'config', 'app-env.json');
                if (fs.existsSync(configPath)) {
                    const configData = fs.readFileSync(configPath, 'utf-8');
                    const config = JSON.parse(configData);
                    appEnv = config.APP_ENV || appEnv;
                    frontendLogger.log(`Loaded APP_ENV from config: ${appEnv}`);
                }
                else {
                    frontendLogger.warn(`Config file not found: ${configPath}, using default: ${appEnv}`);
                }
            }
            catch (error) {
                frontendLogger.warn(`Failed to read app-env.json, using default: ${appEnv}`, error);
            }
            // Allow process.env to override (for development)
            if (process.env.APP_ENV) {
                appEnv = process.env.APP_ENV;
                frontendLogger.log(`APP_ENV overridden by process.env: ${appEnv}`);
            }
            frontendLogger.log(`Backend will use APP_ENV=${appEnv}`);
            this.process = spawn(backendExecutable, args, {
                stdio: ['pipe', 'pipe', 'pipe'],
                cwd,
                env: {
                    ...process.env,
                    PYTHONUNBUFFERED: '1',
                    APP_ENV: appEnv,
                },
            });
            this.process.stdout?.on('data', data => {
                const output = data.toString();
                stdoutBuffer += output;
                const lines = output.split('\n').filter((line) => line.trim());
                for (const line of lines) {
                    try {
                        const response = JSON.parse(line);
                        if (response.type === 'initialization' && response.status === 'complete') {
                            this.serverUrl = response.server_url || this.serverUrl;
                            this.isConnected = true;
                            frontendLogger.log('✅ FastAPI server initialized:', this.serverUrl);
                        }
                    }
                    catch (e) {
                        if (line.trim()) {
                            pythonLogger.log('[SERVER]', line.trim());
                            frontendLogger.log('[SERVER STDOUT]', line.trim());
                        }
                    }
                }
            });
            this.process.stderr?.on('data', data => {
                const output = data.toString();
                stderrBuffer += output;
                const trimmed = output.trim();
                if (trimmed) {
                    pythonLogger.log('[SERVER]', trimmed);
                    frontendLogger.error('[SERVER STDERR]', trimmed);
                }
            });
            this.process.on('exit', (code, signal) => {
                const exitMsg = `FastAPI server exited with code ${code}, signal ${signal}`;
                frontendLogger.log(exitMsg);
                frontendLogger.error(exitMsg);
                // Log all collected output if process exited with error
                if (code !== 0 && code !== null) {
                    frontendLogger.error(`Backend process exited with error code ${code}`);
                    if (stdoutBuffer) {
                        frontendLogger.error('[FULL STDOUT]', stdoutBuffer);
                    }
                    if (stderrBuffer) {
                        frontendLogger.error('[FULL STDERR]', stderrBuffer);
                    }
                }
                this.isConnected = false;
                this.emit('disconnected');
            });
            this.process.on('error', error => {
                const errorMsg = `FastAPI server spawn error: ${error.message}`;
                frontendLogger.error(errorMsg, error);
                pythonLogger.error('[SERVER]', errorMsg);
                this.isConnected = false;
                this.emit('error', error);
            });
            // Log process details for debugging
            frontendLogger.log('Backend process spawned:', {
                pid: this.process.pid,
                cwd,
                executable: backendExecutable,
                args,
            });
            await this.waitForServer();
        }
        catch (error) {
            frontendLogger.error('Failed to start FastAPI server:', error);
            throw error;
        }
    }
    async waitForServer() {
        return new Promise((resolve, reject) => {
            let checkCount = 0;
            const maxChecks = 30; // 30 seconds total
            const timeout = setTimeout(() => {
                // Check if process is still running
                if (this.process && !this.process.killed) {
                    const exitCode = this.process.exitCode;
                    if (exitCode !== null && exitCode !== 0) {
                        reject(new Error(`FastAPI server startup timeout - process exited with code ${exitCode}`));
                    }
                    else {
                        reject(new Error('FastAPI server startup timeout - server did not respond'));
                    }
                }
                else {
                    reject(new Error('FastAPI server startup timeout - process is not running'));
                }
            }, 30000);
            // Also check if process exits early
            const exitHandler = (code, signal) => {
                clearTimeout(timeout);
                reject(new Error(`FastAPI server process exited early with code ${code}, signal ${signal}`));
            };
            if (this.process) {
                this.process.once('exit', exitHandler);
            }
            const checkServer = async () => {
                checkCount++;
                // Check if process has exited
                if (this.process && this.process.exitCode !== null) {
                    clearTimeout(timeout);
                    if (this.process.exitCode === 0) {
                        reject(new Error('FastAPI server process exited unexpectedly with code 0'));
                    }
                    else {
                        reject(new Error(`FastAPI server process exited with error code ${this.process.exitCode}`));
                    }
                    return;
                }
                try {
                    const response = await fetch(`${this.serverUrl}/status`);
                    if (response.ok) {
                        clearTimeout(timeout);
                        if (this.process) {
                            this.process.removeListener('exit', exitHandler);
                        }
                        frontendLogger.log(`✅ FastAPI server is ready (checked ${checkCount} times)`);
                        resolve();
                    }
                    else {
                        if (checkCount < maxChecks) {
                            setTimeout(checkServer, 1000);
                        }
                    }
                }
                catch (error) {
                    if (checkCount < maxChecks) {
                        setTimeout(checkServer, 1000);
                    }
                    else {
                        clearTimeout(timeout);
                        if (this.process) {
                            this.process.removeListener('exit', exitHandler);
                        }
                        reject(new Error(`Failed to connect to FastAPI server after ${checkCount} attempts: ${error instanceof Error ? error.message : String(error)}`));
                    }
                }
            };
            // Start checking after a short delay to allow process to initialize
            setTimeout(checkServer, 2000);
        });
    }
    async executeTask(task) {
        const response = await fetch(`${this.serverUrl}/tasks`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(task),
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to execute task');
        }
    }
    async pauseTask(taskId) {
        const response = await fetch(`${this.serverUrl}/tasks/${taskId}/pause`, {
            method: 'POST',
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to pause task');
        }
    }
    async resumeTask(taskId) {
        const response = await fetch(`${this.serverUrl}/tasks/${taskId}/resume`, {
            method: 'POST',
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to resume task');
        }
    }
    async cancelTask(taskId) {
        const response = await fetch(`${this.serverUrl}/tasks/${taskId}/cancel`, {
            method: 'POST',
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to cancel task');
        }
    }
    async controlWorkflow(workflowId, action) {
        const response = await fetch(`${this.serverUrl}/workflows/${workflowId}/control`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action }),
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to control workflow');
        }
    }
    async importChromeContext() {
        const response = await fetch(`${this.serverUrl}/chrome/import`, {
            method: 'POST',
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to import Chrome context');
        }
    }
    async getStatus() {
        const response = await fetch(`${this.serverUrl}/status`);
        if (!response.ok) {
            throw new Error('Failed to get server status');
        }
        return await response.json();
    }
    async sendChatMessage(_data) {
        return { content: 'Chat functionality not yet implemented in FastAPI server' };
    }
    async stop() {
        try {
            if (this.isConnected) {
                try {
                    await fetch(`${this.serverUrl}/shutdown`, { method: 'POST' });
                }
                catch (error) {
                    // Server might already be shutting down
                }
            }
            if (this.process) {
                this.process.kill('SIGTERM');
                await new Promise(resolve => {
                    const timeout = setTimeout(() => {
                        if (this.process) {
                            this.process.kill('SIGKILL');
                        }
                        resolve();
                    }, 5000);
                    this.process?.on('exit', () => {
                        clearTimeout(timeout);
                        resolve();
                    });
                });
            }
        }
        catch (error) {
            frontendLogger.error('Error stopping FastAPI server:', error);
        }
        finally {
            this.process = null;
            this.isConnected = false;
        }
    }
    isRunning() {
        return this.isConnected && this.process !== null;
    }
    isReady() {
        return this.isConnected;
    }
    getWorkerStatus() {
        return {
            isRunning: this.isRunning(),
            isConnected: this.isConnected,
            hasProcess: this.process !== null,
            serverUrl: this.serverUrl,
        };
    }
    async findBackendExecutable() {
        if (process.platform === 'win32') {
            return await this.findWindowsBackend();
        }
        else {
            return await this.findMacBackend();
        }
    }
    async findWindowsBackend() {
        if (app.isPackaged) {
            // In production, Windows uses .exe in asar.unpacked
            const resourcesPath = process.resourcesPath;
            // Primary path: app.asar.unpacked (electron-builder asarUnpack)
            const asarUnpackedPath = path.join(resourcesPath, 'app.asar.unpacked', 'backend', 'dist', 'fastapi_server', 'fastapi_server.exe');
            if (fs.existsSync(asarUnpackedPath)) {
                frontendLogger.log('📦 [Windows] Using PyInstaller backend:', asarUnpackedPath);
                return asarUnpackedPath;
            }
            // Fallback: Direct resources path (older structure)
            const directPath = path.join(resourcesPath, 'backend', 'dist', 'fastapi_server', 'fastapi_server.exe');
            if (fs.existsSync(directPath)) {
                frontendLogger.log('📦 [Windows] Using PyInstaller backend (fallback):', directPath);
                return directPath;
            }
            throw new Error(`Windows backend not found. Tried:\n- ${asarUnpackedPath}\n- ${directPath}`);
        }
        else {
            // Development mode on Windows
            const pyinstallerDevPath = path.join(__dirname, '..', '..', '..', 'backend', 'dist', 'fastapi_server', 'fastapi_server.exe');
            if (fs.existsSync(pyinstallerDevPath)) {
                frontendLogger.log('🔧 [Windows Dev] Using PyInstaller bundle:', pyinstallerDevPath);
                return pyinstallerDevPath;
            }
            // Fallback to Python for development
            frontendLogger.warn('⚠️ [Windows Dev] PyInstaller bundle not found, using Python + .py');
            return await this.findPythonForDev();
        }
    }
    async findMacBackend() {
        if (app.isPackaged) {
            // In production, macOS uses Unix executable in asar.unpacked
            const resourcesPath = process.resourcesPath;
            // Primary path: app.asar.unpacked (electron-builder asarUnpack)
            const asarUnpackedPath = path.join(resourcesPath, 'app.asar.unpacked', 'backend', 'dist', 'fastapi_server', 'fastapi_server');
            if (fs.existsSync(asarUnpackedPath)) {
                frontendLogger.log('📦 [macOS] Using PyInstaller backend:', asarUnpackedPath);
                return asarUnpackedPath;
            }
            // Fallback: Direct resources path (older structure)
            const directPath = path.join(resourcesPath, 'backend', 'dist', 'fastapi_server', 'fastapi_server');
            if (fs.existsSync(directPath)) {
                frontendLogger.log('📦 [macOS] Using PyInstaller backend (fallback):', directPath);
                return directPath;
            }
            throw new Error(`macOS backend not found. Tried:\n- ${asarUnpackedPath}\n- ${directPath}`);
        }
        else {
            // Development mode on macOS
            const pyinstallerDevPath = path.join(__dirname, '..', '..', '..', 'backend', 'dist', 'fastapi_server', 'fastapi_server');
            if (fs.existsSync(pyinstallerDevPath)) {
                frontendLogger.log('🔧 [macOS Dev] Using PyInstaller bundle:', pyinstallerDevPath);
                return pyinstallerDevPath;
            }
            // Fallback to Python for development
            frontendLogger.warn('⚠️ [macOS Dev] PyInstaller bundle not found, using Python + .py');
            return await this.findPythonForDev();
        }
    }
    async findPythonForDev() {
        // Development-only fallback to find Python
        const backendVenvPath = path.join(__dirname, '..', '..', '..', 'backend', 'venv', 'bin', 'python');
        if (fs.existsSync(backendVenvPath)) {
            frontendLogger.log('🐍 Using backend venv Python');
            return backendVenvPath;
        }
        const possiblePaths = ['python3.11', 'python3', 'python'];
        for (const pythonPath of possiblePaths) {
            try {
                const result = await new Promise(resolve => {
                    const child = spawn(pythonPath, ['--version'], { stdio: 'pipe' });
                    child.on('close', code => resolve({ code: code || 0 }));
                    child.on('error', () => resolve({ code: 1 }));
                });
                if (result.code === 0) {
                    frontendLogger.log(`Found Python: ${pythonPath}`);
                    return pythonPath;
                }
            }
            catch (error) {
                continue;
            }
        }
        throw new Error('Python executable not found for development');
    }
}
//# sourceMappingURL=python-server.js.map