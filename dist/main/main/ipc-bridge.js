import { ipcMain } from 'electron';
import { FastAPIWorker } from './python-server.js';
import { frontendLogger } from './utils/logger.js';
import { LOCAL_BACKEND_PORT } from '../config.js';
export class FastAPICoordinator {
    fastApiWorker;
    mainWindow = null;
    constructor(port = LOCAL_BACKEND_PORT) {
        this.fastApiWorker = new FastAPIWorker(port);
        this.setupIPCHandlers();
        this.setupFastAPIWorkerListeners();
    }
    setMainWindow(window) {
        this.mainWindow = window;
    }
    async initialize() {
        try {
            frontendLogger.log('🔗 Initializing FastAPI Coordinator...');
            await this.fastApiWorker.start();
            frontendLogger.log('✅ FastAPI Coordinator initialized');
        }
        catch (error) {
            frontendLogger.error('❌ FastAPI Coordinator initialization failed:', error);
            throw error;
        }
    }
    setupIPCHandlers() {
        // Task execution
        ipcMain.handle('execute-task', async (event, taskData) => {
            try {
                const workerStatus = this.fastApiWorker.getWorkerStatus();
                frontendLogger.log('🔍 FastAPI Worker status before task execution:', workerStatus);
                if (!this.fastApiWorker.isReady()) {
                    frontendLogger.error('❌ FastAPI worker not ready for task execution');
                    return {
                        success: false,
                        error: 'FastAPI worker not ready. Please wait for initialization to complete.',
                    };
                }
                await this.fastApiWorker.executeTask(taskData);
                return { success: true };
            }
            catch (error) {
                console.error('Task execution error:', error);
                return { success: false, error: error.message };
            }
        });
        // Task control
        ipcMain.handle('pause-task', async (event, taskId) => {
            try {
                await this.fastApiWorker.pauseTask(taskId);
                return { success: true };
            }
            catch (error) {
                console.error('Pause task error:', error);
                return { success: false, error: error.message };
            }
        });
        ipcMain.handle('resume-task', async (event, taskId) => {
            try {
                await this.fastApiWorker.resumeTask(taskId);
                return { success: true };
            }
            catch (error) {
                console.error('Resume task error:', error);
                return { success: false, error: error.message };
            }
        });
        ipcMain.handle('cancel-task', async (event, taskId) => {
            try {
                await this.fastApiWorker.cancelTask(taskId);
                return { success: true };
            }
            catch (error) {
                console.error('Cancel task error:', error);
                return { success: false, error: error.message };
            }
        });
        // Chrome context import
        ipcMain.handle('import-chrome-context', async (event) => {
            try {
                await this.fastApiWorker.importChromeContext();
                return { success: true };
            }
            catch (error) {
                console.error('Chrome context import error:', error);
                return { success: false, error: error.message };
            }
        });
        // Status requests
        ipcMain.handle('get-worker-status', async (event) => {
            try {
                const status = this.fastApiWorker.getWorkerStatus();
                const serverStatus = await this.fastApiWorker.getStatus();
                return {
                    success: true,
                    ...status,
                    serverStatus,
                };
            }
            catch (error) {
                console.error('Get status error:', error);
                return { success: false, error: error.message };
            }
        });
        // Wait for worker ready
        ipcMain.handle('wait-for-worker-ready', async (event) => {
            try {
                if (this.fastApiWorker.isReady()) {
                    return { success: true, ready: true };
                }
                return new Promise(resolve => {
                    const timeout = setTimeout(() => {
                        resolve({
                            success: false,
                            ready: false,
                            error: 'Timeout waiting for FastAPI worker to be ready',
                        });
                    }, 15000);
                    const checkReady = () => {
                        if (this.fastApiWorker.isReady()) {
                            clearTimeout(timeout);
                            resolve({ success: true, ready: true });
                        }
                        else {
                            setTimeout(checkReady, 100);
                        }
                    };
                    checkReady();
                });
            }
            catch (error) {
                console.error('Wait for worker ready error:', error);
                return { success: false, error: error.message };
            }
        });
        // Restart worker
        ipcMain.handle('restart-worker', async (event) => {
            try {
                await this.fastApiWorker.stop();
                await this.fastApiWorker.start();
                return { success: true };
            }
            catch (error) {
                console.error('Restart worker error:', error);
                return { success: false, error: error.message };
            }
        });
        // Workflow control
        ipcMain.handle('control-workflow', async (event, workflowId, action) => {
            try {
                await this.fastApiWorker.controlWorkflow(workflowId, action);
                return { success: true };
            }
            catch (error) {
                console.error('Control workflow error:', error);
                return { success: false, error: error.message };
            }
        });
        // Chat functionality (placeholder)
        ipcMain.handle('send-chat-message', async (event, data) => {
            try {
                const response = await this.fastApiWorker.sendChatMessage(data);
                return response;
            }
            catch (error) {
                console.error('Chat message error:', error);
                return { error: error.message };
            }
        });
    }
    setupFastAPIWorkerListeners() {
        // Since we're using HTTP instead of real-time events,
        // we'll need to implement polling or WebSocket for real-time updates
        // For now, we'll handle basic events
        this.fastApiWorker.on('disconnected', () => {
            this.sendToRenderer('worker-disconnected', {});
        });
        this.fastApiWorker.on('error', (error) => {
            this.sendToRenderer('worker-connection-error', {
                error: error.message,
            });
        });
        // For task updates, we would need to implement WebSocket or polling
        // This is a simplified version - in production you'd want real-time updates
    }
    sendToRenderer(channel, data) {
        if (this.mainWindow && !this.mainWindow.isDestroyed()) {
            this.mainWindow.webContents.send(channel, data);
        }
    }
    async shutdown() {
        try {
            await this.fastApiWorker.stop();
            frontendLogger.log('✅ FastAPI Coordinator shutdown complete');
        }
        catch (error) {
            frontendLogger.error('❌ FastAPI Coordinator shutdown error:', error);
        }
    }
}
//# sourceMappingURL=ipc-bridge.js.map