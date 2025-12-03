const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods that allow the renderer process to use
// the ipcRenderer without exposing the entire object
contextBridge.exposeInMainWorld('electronAPI', {
  // Task management
  executeTask: taskData => ipcRenderer.invoke('execute-task', taskData),
  pauseTask: taskId => ipcRenderer.invoke('pause-task', taskId),
  resumeTask: taskId => ipcRenderer.invoke('resume-task', taskId),
  cancelTask: taskId => ipcRenderer.invoke('cancel-task', taskId),

  // Chat functionality
  sendChatMessage: data => ipcRenderer.invoke('send-chat-message', data),

  // Chrome context
  importChromeContext: () => ipcRenderer.invoke('import-chrome-context'),

  // Workflow control
  controlWorkflow: (workflowId, action) =>
    ipcRenderer.invoke('control-workflow', workflowId, action),

  // Status
  getWorkerStatus: () => ipcRenderer.invoke('get-worker-status'),
  waitForWorkerReady: () => ipcRenderer.invoke('wait-for-worker-ready'),
  restartWorker: () => ipcRenderer.invoke('restart-worker'),

  // Event listeners
  onTaskUpdate: callback => {
    ipcRenderer.on('task-update', (event, data) => callback(data));
  },
  onChromeContextImported: callback => {
    ipcRenderer.on('chrome-context-imported', (event, data) => callback(data));
  },
  onStatusUpdate: callback => {
    ipcRenderer.on('status-update', (event, data) => callback(data));
  },
  onWorkerError: callback => {
    ipcRenderer.on('worker-error', (event, data) => callback(data));
  },
  onWorkerDisconnected: callback => {
    ipcRenderer.on('worker-disconnected', (event, data) => callback(data));
  },
  onWorkerConnectionError: callback => {
    ipcRenderer.on('worker-connection-error', (event, data) => callback(data));
  },

  // Remove listeners
  removeAllListeners: channel => {
    ipcRenderer.removeAllListeners(channel);
  },

  // File system operations for resume management
  checkFileExists: filename => ipcRenderer.invoke('check-file-exists', filename),
  getDownloadsPath: () => ipcRenderer.invoke('get-downloads-path'),
  readLocalFile: filePath => ipcRenderer.invoke('read-local-file', filePath),
  autoDownloadFile: (fileUrl, filename) =>
    ipcRenderer.invoke('auto-download-file', fileUrl, filename),
  revealInFolder: filename => ipcRenderer.invoke('reveal-in-folder', filename),

  // PDF export operations
  exportHtmlToPdf: (htmlContent, filename) =>
    ipcRenderer.invoke('export-html-to-pdf', htmlContent, filename),
  openFile: filePath => ipcRenderer.invoke('open-file', filePath),
  generatePdfBlob: (htmlContent, options) =>
    ipcRenderer.invoke('generate-pdf-blob', htmlContent, options),

  // External URL operations
  openExternalUrl: url => ipcRenderer.invoke('open-external-url', url),

  // Window management
  hideWindow: () => ipcRenderer.invoke('hide-window'),

  // Tray menu updates
  updateTrayMetadata: metadata => ipcRenderer.send('update-tray-metadata', metadata),

  // Auth token backup operations
  writeUserAuth: authData => ipcRenderer.invoke('write-user-auth', authData),

  // Browser setup operations
  getPath: name => ipcRenderer.invoke('get-path', name),
  ensureDir: dirPath => ipcRenderer.invoke('ensure-dir', dirPath),
  writeFile: (filePath, data) => ipcRenderer.invoke('write-file', filePath, data),
  extractZip: (zipPath, targetDir) => ipcRenderer.invoke('extract-zip', zipPath, targetDir),
  deleteFile: filePath => ipcRenderer.invoke('delete-file', filePath),
  setExecutablePermissions: filePath => ipcRenderer.invoke('set-executable-permissions', filePath),
  checkChromeAvailability: () => ipcRenderer.invoke('check-chrome-availability'),
  launchChromeForAutomation: options => ipcRenderer.invoke('launch-chrome-for-automation', options),
  launchChromeWithProfile: options => ipcRenderer.invoke('launch-chrome-with-profile', options),

  // Auto-updater operations
  checkForUpdates: () => ipcRenderer.invoke('check-for-updates'),
  downloadUpdate: () => ipcRenderer.invoke('download-update'),
  installUpdate: () => ipcRenderer.invoke('install-update'),
  openDmg: filePath => ipcRenderer.invoke('open-dmg', filePath),
  quitApp: () => ipcRenderer.invoke('quit-app'),

  // Main process console log forwarding (for debugging)
  onMainConsoleLog: callback => {
    ipcRenderer.on('main-console-log', (event, data) => callback(data));
  },

  // Auto-updater event listeners
  onUpdateChecking: callback => {
    ipcRenderer.on('update-checking', () => callback());
  },
  onUpdateAvailable: callback => {
    ipcRenderer.on('update-available', (event, data) => callback(data));
  },
  onUpdateNotAvailable: callback => {
    ipcRenderer.on('update-not-available', () => callback());
  },
  onUpdateDownloadProgress: callback => {
    ipcRenderer.on('update-download-progress', (event, data) => callback(data));
  },
  onUpdateDownloaded: callback => {
    ipcRenderer.on('update-downloaded', (event, data) => callback(data));
  },
  onUpdateError: callback => {
    ipcRenderer.on('update-error', (event, data) => callback(data));
  },

  // Quit confirmation modal
  onShowQuitConfirmation: callback => {
    ipcRenderer.on('show-quit-confirmation', () => callback());
  },
  respondToQuitConfirmation: response => ipcRenderer.send('quit-confirmation-response', response),

  // Navigate to infinite hunting page
  onNavigateToInfiniteHunting: callback => {
    ipcRenderer.on('navigate-to-infinite-hunting', () => callback());
  },
});
