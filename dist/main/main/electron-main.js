import { app, BrowserWindow, ipcMain, shell, net, Tray, Menu, nativeImage } from 'electron';
import pkg from 'electron-updater';
const { autoUpdater } = pkg;
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';
import { fileURLToPath } from 'url';
import { FastAPICoordinator } from './ipc-bridge.js';
import { initializeLogger, getLogger } from './logger.js';
import { exec, spawn } from 'child_process';
import { promisify } from 'util';
import { ACTIVE_RELEASE_CONFIG, ACTIVE_RELEASE_TARGET, ACTIVE_REPO_SLUG, } from './release-config.js';
import { LOCAL_BACKEND_PORT } from '../config.js';
// Suppress harmless Electron console warnings at process level
process.stderr.write = (write => {
    return function (chunk, encoding, callback) {
        const str = chunk.toString();
        // Filter out known harmless errors
        if (str.includes('Autofill.enable') ||
            str.includes('disabling flag --expose_wasm') ||
            str.includes("wasn't found")) {
            // Skip writing these messages
            if (typeof encoding === 'function') {
                encoding();
            }
            else if (callback) {
                callback();
            }
            return true;
        }
        return write.apply(process.stderr, arguments);
    };
})(process.stderr.write);
// ES module equivalent of __dirname
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
// Keep a global reference of the window object
let mainWindow = null;
let fastApiCoordinator = null;
let isBackendShutdownInProgress = false;
let hasRequestedQuit = false;
let tray = null;
let isWindowIntentionallyHidden = false;
let isQuittingApp = false;
let shouldStartHidden = false;
let chromeAutomationProcess = null;
let fileSystemHandlersRegistered = false;
const hiddenLaunchArguments = new Set(['--hidden-launch', '--start-hidden']);
const disableAutoLaunch = process.env['DISABLE_AUTO_LAUNCH']?.toLowerCase() === 'true' ||
    process.argv.includes('--no-auto-launch');
async function shutdownFastAPI() {
    if (!fastApiCoordinator || isBackendShutdownInProgress) {
        return;
    }
    isBackendShutdownInProgress = true;
    try {
        await fastApiCoordinator.shutdown();
    }
    catch (error) {
        console.error('Failed to shutdown FastAPI coordinator:', error);
    }
    finally {
        fastApiCoordinator = null;
        isBackendShutdownInProgress = false;
    }
}
function resolveIconPath(preferredFiles) {
    const fileCandidates = preferredFiles && preferredFiles.length > 0
        ? preferredFiles
        : process.platform === 'win32'
            ? ['logo.ico', 'logo.png']
            : process.platform === 'darwin'
                ? ['logoTemplate.png', 'logo.png', 'logo.icns']
                : ['logo.png'];
    const baseCandidates = [
        path.join(__dirname, '../../frontend/app/public'),
        path.join(__dirname, '../../frontend/app'),
        path.join(__dirname, '../../app/public'),
        path.join(__dirname, '../../app'),
        path.join(__dirname, '../../../frontend/app/public'),
        path.join(__dirname, '../../../frontend/app'),
    ];
    if (process.resourcesPath) {
        baseCandidates.push(process.resourcesPath);
        baseCandidates.push(path.join(process.resourcesPath, 'app'));
        baseCandidates.push(path.join(process.resourcesPath, 'public'));
        baseCandidates.push(path.join(process.resourcesPath, 'dist', 'app'));
        baseCandidates.push(path.join(process.resourcesPath, 'dist', 'app', 'public'));
    }
    for (const base of baseCandidates) {
        for (const file of fileCandidates) {
            const candidate = path.join(base, file);
            if (fs.existsSync(candidate)) {
                return candidate;
            }
        }
    }
    return undefined;
}
function resolveChromeExecutable() {
    const candidates = [];
    if (process.platform === 'darwin') {
        candidates.push('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');
    }
    else if (process.platform === 'win32') {
        const programFilesX86 = process.env['PROGRAMFILES(X86)'] || 'C:\\Program Files (x86)';
        const programFiles = process.env['PROGRAMFILES'] || 'C:\\Program Files';
        candidates.push(path.join(programFilesX86, 'Google', 'Chrome', 'Application', 'chrome.exe'));
        candidates.push(path.join(programFiles, 'Google', 'Chrome', 'Application', 'chrome.exe'));
    }
    else {
        candidates.push('/usr/bin/google-chrome');
        candidates.push('/usr/bin/google-chrome-stable');
        candidates.push('/usr/bin/chromium-browser');
    }
    for (const candidate of candidates) {
        if (candidate && fs.existsSync(candidate)) {
            return candidate;
        }
    }
    return null;
}
function getJobhuntrBaseDir() {
    if (process.platform === 'darwin') {
        return path.join(os.homedir(), 'Library', 'Application Support', 'JobHuntr');
    }
    if (process.platform === 'win32') {
        return path.join(os.homedir(), 'AppData', 'Local', 'jobhuntr');
    }
    return path.join(os.homedir(), '.jobhuntr');
}
function sanitizeLocalPart(localPart) {
    if (!localPart) {
        return 'default';
    }
    const sanitized = localPart.toLowerCase().replace(/[^a-z0-9]/g, '');
    return sanitized || 'default';
}
function readStoredUserEmail() {
    try {
        const authPath = path.join(getJobhuntrBaseDir(), 'user_auth.json');
        if (!fs.existsSync(authPath)) {
            return null;
        }
        const content = fs.readFileSync(authPath, 'utf-8');
        const data = JSON.parse(content);
        const userInfo = data?.user_info || {};
        return (userInfo.email ||
            userInfo.user_metadata?.email ||
            userInfo.user_metadata?.preferred_email ||
            null);
    }
    catch (error) {
        console.warn('Failed to read stored user email for profile naming:', error);
        return null;
    }
}
function getJobhuntrProfileDirName() {
    const email = readStoredUserEmail();
    const localPart = email?.split('@')[0] || '';
    const suffix = sanitizeLocalPart(localPart);
    return `jobhuntr_chrome_profile_${suffix}`;
}
function getJobhuntrProfilePath() {
    return path.join(getJobhuntrBaseDir(), getJobhuntrProfileDirName());
}
function showMainWindow() {
    if (!mainWindow) {
        return;
    }
    if (process.platform === 'darwin' && app.dock) {
        try {
            app.dock.show();
        }
        catch {
            // ignore dock errors
        }
    }
    if (mainWindow.isMinimized()) {
        mainWindow.restore();
    }
    mainWindow.show();
    mainWindow.focus();
    isWindowIntentionallyHidden = false;
}
function bringMainWindowToFront() {
    if (!mainWindow) {
        return;
    }
    const wasAlwaysOnTop = mainWindow.isAlwaysOnTop();
    const wasVisibleOnAllWorkspaces = mainWindow.isVisibleOnAllWorkspaces();
    // Temporarily force the window to be everywhere so macOS/Windows reliably
    // raise it on top of other applications.
    mainWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    mainWindow.setAlwaysOnTop(true);
    if (process.platform === 'darwin') {
        app.focus({ steal: true });
    }
    mainWindow.show();
    mainWindow.focus();
    if (!wasAlwaysOnTop) {
        mainWindow.setAlwaysOnTop(false);
    }
    if (!wasVisibleOnAllWorkspaces) {
        mainWindow.setVisibleOnAllWorkspaces(false, { visibleOnFullScreen: true });
    }
}
function hideMainWindowToTray() {
    if (!mainWindow) {
        return;
    }
    isWindowIntentionallyHidden = true;
    mainWindow.hide();
    if (process.platform === 'darwin' && app.dock) {
        try {
            app.dock.hide();
        }
        catch {
            // ignore dock errors
        }
    }
}
// Store current infinite hunt metadata for tray menu
let infiniteHuntMetadata = null;
// Format duration in human readable format
function formatDuration(seconds) {
    if (seconds < 60)
        return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    if (minutes < 60)
        return `${minutes}m ${secs}s`;
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return `${hours}h ${mins}m`;
}
// Get readable name from template ID (e.g., "linkedin-search" -> "LinkedIn Search")
function getTemplateName(templateId) {
    const nameMap = {
        'linkedin-search': 'LinkedIn Search',
        'linkedin-apply': 'LinkedIn Apply',
        'indeed-search': 'Indeed Search',
        'ziprecruiter-search': 'ZipRecruiter Search',
        'glassdoor-search': 'Glassdoor Search',
        'dice-search': 'Dice Search',
        'autonomous-auto-search': 'Autonomous Search',
    };
    return nameMap[templateId] || templateId;
}
// Show quit confirmation modal in renderer
function showQuitConfirmation() {
    // If no main window, just quit directly
    if (!mainWindow) {
        if (process.platform === 'darwin' && app.dock) {
            try {
                app.dock.show();
            }
            catch {
                // ignore dock errors
            }
        }
        app.quit();
        return;
    }
    // Show the main window first so the modal is visible
    showMainWindow();
    bringMainWindowToFront();
    // Send IPC to renderer to show the quit confirmation modal
    mainWindow.webContents.send('show-quit-confirmation');
}
// Handle force quit (bypasses the confirmation modal)
function forceQuit() {
    hasRequestedQuit = true;
    if (process.platform === 'darwin' && app.dock) {
        try {
            app.dock.show();
        }
        catch {
            // ignore dock errors
        }
    }
    app.quit();
}
function buildTrayMenu() {
    const showInfiniteHuntingPage = () => {
        if (!mainWindow) {
            createWindow();
            return;
        }
        showMainWindow();
        bringMainWindowToFront();
        // Send IPC event to navigate to infinite hunting page
        mainWindow.webContents.send('navigate-to-infinite-hunting');
    };
    const menuItems = [];
    // Add infinite hunt status if available
    if (infiniteHuntMetadata) {
        const isActive = infiniteHuntMetadata.is_running;
        const status = isActive ? 'Active' : 'Idle';
        const stats = infiniteHuntMetadata.cumulative_job_stats;
        menuItems.push({
            label: `Infinite Hunt: ${status}`,
            enabled: true,
            click: showInfiniteHuntingPage,
        });
        // Calculate and show duration
        if (infiniteHuntMetadata.started_at) {
            const startTime = new Date(infiniteHuntMetadata.started_at).getTime();
            let durationSeconds;
            if (isActive) {
                // Active: calculate from start to now
                durationSeconds = Math.floor((Date.now() - startTime) / 1000);
            }
            else if (infiniteHuntMetadata.ended_at) {
                // Idle: calculate from start to end
                const endTime = new Date(infiniteHuntMetadata.ended_at).getTime();
                durationSeconds = Math.floor((endTime - startTime) / 1000);
            }
            else {
                durationSeconds = 0;
            }
            if (durationSeconds > 0) {
                const prefix = isActive ? 'Session' : 'Last session';
                menuItems.push({
                    label: `  ${prefix}: ${formatDuration(durationSeconds)}`,
                    enabled: true,
                    click: showInfiniteHuntingPage,
                });
            }
        }
        // Show runs by template (all selected templates, even with 0 runs)
        const orderedTemplates = infiniteHuntMetadata.ordered_templates || [];
        if (orderedTemplates.length > 0) {
            for (const template of orderedTemplates) {
                const displayName = getTemplateName(template.name);
                menuItems.push({
                    label: `  ${displayName}: ${template.runs} run${template.runs !== 1 ? 's' : ''}`,
                    enabled: true,
                    click: showInfiniteHuntingPage,
                });
            }
        }
        // Show job stats
        if (stats.submitted > 0 || stats.queued > 0 || stats.skipped > 0 || stats.failed > 0) {
            menuItems.push({
                label: `  Submitted: ${stats.submitted} | Queued: ${stats.queued}`,
                enabled: true,
                click: showInfiniteHuntingPage,
            });
            menuItems.push({
                label: `  Skipped: ${stats.skipped} | Failed: ${stats.failed}`,
                enabled: true,
                click: showInfiniteHuntingPage,
            });
        }
        // Show auto-hunt countdown at bottom when idle and enabled
        const autoHunt = infiniteHuntMetadata.auto_hunt_status;
        if (!isActive && autoHunt?.enabled && autoHunt.seconds_until_next_check > 0) {
            menuItems.push({
                label: `  Auto-start in: ${formatDuration(autoHunt.seconds_until_next_check)}`,
                enabled: false,
            });
        }
        menuItems.push({ type: 'separator' });
    }
    menuItems.push({ label: 'Show JobHuntr', click: showInfiniteHuntingPage });
    menuItems.push({ type: 'separator' });
    menuItems.push({
        label: 'Quit JobHuntr',
        click: () => {
            showQuitConfirmation();
        },
    });
    return Menu.buildFromTemplate(menuItems);
}
function updateTrayMenu() {
    if (!tray)
        return;
    const contextMenu = buildTrayMenu();
    tray.setContextMenu(contextMenu);
}
function setupTray() {
    if (tray) {
        return;
    }
    const iconPath = resolveIconPath(process.platform === 'win32'
        ? ['logo.ico', 'logo.png']
        : ['logoTemplate.png', 'logo.png', 'logo.icns']);
    let trayImage = iconPath ? nativeImage.createFromPath(iconPath) : nativeImage.createEmpty();
    if (process.platform === 'darwin' && !trayImage.isEmpty()) {
        trayImage = trayImage.resize({ width: 18, height: 18 });
    }
    tray = new Tray(trayImage);
    tray.setToolTip('JobHuntr');
    const contextMenu = buildTrayMenu();
    tray.setContextMenu(contextMenu);
    const openTrayMenu = () => {
        if (!tray)
            return;
        tray.popUpContextMenu(buildTrayMenu());
    };
    tray.on('click', openTrayMenu);
    tray.on('double-click', openTrayMenu);
    tray.on('right-click', openTrayMenu);
    // IPC handler to update tray with infinite hunt metadata
    ipcMain.on('update-tray-metadata', (_event, metadata) => {
        infiniteHuntMetadata = metadata;
        updateTrayMenu();
    });
    // IPC handler for quit confirmation response from renderer
    ipcMain.on('quit-confirmation-response', (_event, response) => {
        if (response === 'quit') {
            // User chose to quit anyway
            forceQuit();
        }
        else if (response === 'run-invisible') {
            // User chose to run invisible and close window
            // Just hide the window - the renderer will handle starting the infinite hunt
            hideMainWindowToTray();
        }
        // If response is 'cancel', do nothing - modal was dismissed
    });
}
function configureAutoLaunch() {
    if (!app.isPackaged) {
        return;
    }
    if (disableAutoLaunch) {
        return;
    }
    if (process.platform !== 'darwin' && process.platform !== 'win32') {
        return;
    }
    try {
        const existing = typeof app.getLoginItemSettings === 'function' ? app.getLoginItemSettings() : undefined;
        const existingArgs = Array.isArray(existing?.args)
            ? existing?.args
            : [];
        const args = new Set(existingArgs);
        args.add('--hidden-launch');
        const settings = {
            openAtLogin: true,
            args: Array.from(args),
        };
        if (process.platform === 'darwin') {
            settings.openAsHidden = true;
        }
        else if (process.platform === 'win32') {
            settings.path = process.execPath;
        }
        app.setLoginItemSettings(settings);
    }
    catch (error) {
        console.error('Failed to configure auto-launch:', error);
    }
}
function determineShouldLaunchHidden() {
    if (process.argv.some(arg => hiddenLaunchArguments.has(arg))) {
        return true;
    }
    if (process.env['START_MINIMIZED']?.toLowerCase() === 'true') {
        return true;
    }
    if ((process.platform === 'darwin' || process.platform === 'win32') &&
        typeof app.getLoginItemSettings === 'function') {
        try {
            const loginSettings = app.getLoginItemSettings();
            if (loginSettings.wasOpenedAtLogin || loginSettings.openAsHidden) {
                return true;
            }
        }
        catch (error) {
            console.error('Failed to read login item settings:', error);
        }
    }
    return false;
}
// Configure auto-updater
autoUpdater.logger = console;
autoUpdater.autoDownload = false; // We manually trigger downloads for better UX control
autoUpdater.autoInstallOnAppQuit = true;
// Use the release configuration to determine update source
const isLocalEnv = process.env['NODE_ENV'] === 'local' || process.env['APP_ENV'] === 'local';
const rawEnableEnv = process.env['ENABLE_AUTO_UPDATE'];
const isPackaged = app.isPackaged;
// In packaged builds we ignore manual disable flags so users always receive updates.
const enableAutoUpdate = isPackaged || rawEnableEnv === undefined || rawEnableEnv.toLowerCase() !== 'false';
if (isPackaged && rawEnableEnv?.toLowerCase() === 'false') {
    console.warn('[auto-update] ENABLE_AUTO_UPDATE was set to false, but packaged builds always enable updates.');
}
const forceEnabled = false; // Respect environment variables by default
const releaseConfig = ACTIVE_RELEASE_CONFIG;
const isTestingTarget = ACTIVE_RELEASE_TARGET === 'playwright_browser';
const shouldConfigureFeed = enableAutoUpdate || forceEnabled;
if (shouldConfigureFeed) {
    // Set channel to use platform-specific files with generateUpdatesFilesForAllChannels
    // - Windows: channel 'latest-win' → looks for latest-win.yml (no auto-append)
    // - macOS: channel 'latest' → looks for latest-mac.yml (auto-appends -mac)
    // - Linux: channel 'latest' → looks for latest-linux.yml (auto-appends -linux)
    const feedOptions = {
        provider: 'github',
        owner: releaseConfig.owner,
        repo: releaseConfig.repo,
        private: releaseConfig.private,
    };
    // Set channel based on platform
    if (process.platform === 'win32') {
        feedOptions.channel = 'latest-win';
    }
    else {
        // For macOS and Linux, use 'latest' channel
        // electron-updater will append platform suffix (-mac or -linux) to find the file
        feedOptions.channel = 'latest';
    }
    autoUpdater.setFeedURL(feedOptions);
    autoUpdater.allowDowngrade = isTestingTarget;
    // Force dev update config in dev mode OR testing target to enable update checks during development
    if (isTestingTarget || !app.isPackaged) {
        autoUpdater.forceDevUpdateConfig =
            true;
    }
}
else {
    autoUpdater.allowDowngrade = false;
}
// Single instance enforcement
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
    // Another instance is already running, quit this one
    app.quit();
}
else {
    // This is the first instance, continue normally
    app.on('second-instance', (_event, _commandLine, _workingDirectory) => {
        // Someone tried to run a second instance, focus our window instead
        if (!mainWindow) {
            createWindow();
            return;
        }
        if (mainWindow.isMinimized()) {
            mainWindow.restore();
        }
        if (!mainWindow.isVisible()) {
            showMainWindow();
        }
        else {
            mainWindow.focus();
        }
    });
}
function createWindow() {
    // Create the browser window
    const isDev = process.argv.includes('--dev');
    // Find the icon file
    const iconPath = resolveIconPath();
    mainWindow = new BrowserWindow({
        width: 1400,
        height: 900,
        minWidth: 1200,
        minHeight: 800,
        show: false, // Don't show until ready
        icon: iconPath, // Set custom app icon
        title: 'JobHuntr', // Set window title
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.js'),
            webSecurity: !isDev, // Disable web security in development for HMR
            allowRunningInsecureContent: isDev, // Only allow in development
            experimentalFeatures: false,
        },
        titleBarStyle: 'default',
    });
    // Load the renderer - use dev server in development, built files in production
    if (isDev) {
        // In development, load from Vite dev server for HMR
        mainWindow.loadURL('http://localhost:5173');
    }
    else {
        // In production, load from built files
        mainWindow.loadFile(path.join(__dirname, '../../app/index.html'));
    }
    // Filter out harmless DevTools console errors
    mainWindow.webContents.on('console-message', (_event, level, message) => {
        // Suppress known harmless DevTools errors
        const suppressedMessages = ['Autofill.enable', "wasn't found"];
        if (suppressedMessages.some(msg => message.includes(msg))) {
            return;
        }
    });
    // Forward auto-update logs to renderer for debugging
    // Store original console methods before overriding
    const originalConsoleLog = console.log.bind(console);
    const originalConsoleError = console.error.bind(console);
    const originalConsoleWarn = console.warn.bind(console);
    console.log = (...args) => {
        originalConsoleLog(...args);
        if (mainWindow && !mainWindow.isDestroyed() && args.length > 0) {
            const firstArg = String(args[0] || '');
            if (firstArg.includes('[auto-update]')) {
                mainWindow.webContents.send('main-console-log', {
                    type: 'log',
                    args: args.map(a => {
                        if (typeof a === 'object') {
                            try {
                                return JSON.stringify(a, null, 2);
                            }
                            catch {
                                return String(a);
                            }
                        }
                        return String(a);
                    }),
                });
            }
        }
    };
    console.error = (...args) => {
        originalConsoleError(...args);
        if (mainWindow && !mainWindow.isDestroyed() && args.length > 0) {
            const firstArg = String(args[0] || '');
            if (firstArg.includes('[auto-update]')) {
                mainWindow.webContents.send('main-console-log', {
                    type: 'error',
                    args: args.map(a => {
                        if (typeof a === 'object') {
                            try {
                                return JSON.stringify(a, null, 2);
                            }
                            catch {
                                return String(a);
                            }
                        }
                        return String(a);
                    }),
                });
            }
        }
    };
    console.warn = (...args) => {
        originalConsoleWarn(...args);
        if (mainWindow && !mainWindow.isDestroyed() && args.length > 0) {
            const firstArg = String(args[0] || '');
            if (firstArg.includes('[auto-update]')) {
                mainWindow.webContents.send('main-console-log', {
                    type: 'warn',
                    args: args.map(a => {
                        if (typeof a === 'object') {
                            try {
                                return JSON.stringify(a, null, 2);
                            }
                            catch {
                                return String(a);
                            }
                        }
                        return String(a);
                    }),
                });
            }
        }
    };
    // Show window when ready to prevent visual flash
    mainWindow.once('ready-to-show', () => {
        if (!mainWindow) {
            return;
        }
        const launchHidden = shouldStartHidden && !process.argv.includes('--dev');
        if (!launchHidden) {
            mainWindow.show();
            mainWindow.maximize(); // Maximize the window to use full screen space
        }
        else if (process.platform === 'darwin' && app.dock) {
            try {
                app.dock.hide();
            }
            catch {
                // ignore dock errors
            }
        }
        // Trigger update check AFTER window is ready
        // This ensures the renderer can receive the update-available event
        // WINDOWS-SPECIFIC: Check for --squirrel-firstrun flag
        // On Windows, Squirrel.Windows holds a file lock during first run, causing update checks to fail
        const isSquirrelFirstRun = process.platform === 'win32' &&
            process.argv.some(arg => arg === '--squirrel-firstrun' ||
                arg === '--squirrel-install' ||
                arg === '--squirrel-updated');
        // Delay longer on Windows first run to allow Squirrel.Windows to release file lock
        const delay = isSquirrelFirstRun ? 5000 : 2000;
        setTimeout(() => {
            // Skip update check on Windows first run (Squirrel.Windows file lock issue)
            if (isSquirrelFirstRun) {
                console.warn('[auto-update] Skipping update check - Windows first run (Squirrel.Windows file lock active)');
                return;
            }
            // Only check if auto-updater is properly configured
            if (shouldConfigureFeed) {
                autoUpdater.checkForUpdates().catch(error => {
                    console.error('[auto-update] Failed to check for updates:', error);
                });
            }
        }, delay);
        // Open DevTools in development
        if (!launchHidden && process.argv.includes('--dev')) {
            mainWindow.webContents.openDevTools();
        }
    });
    mainWindow.on('close', event => {
        if (isQuittingApp) {
            return;
        }
        event.preventDefault();
        hideMainWindowToTray();
    });
    // Emitted when the window is closed
    mainWindow.on('closed', () => {
        mainWindow = null;
    });
    // Always set up file system handlers for resume management
    setupFileSystemHandlers();
    // Initialize FastAPI coordinator (only if not in standalone mode or no-backend mode)
    const isStandalone = process.argv.includes('--standalone');
    const noBackend = process.argv.includes('--no-backend');
    if (!isStandalone && !noBackend) {
        initializeFastAPI();
    }
}
function setupFileSystemHandlers() {
    if (fileSystemHandlersRegistered) {
        return;
    }
    fileSystemHandlersRegistered = true;
    // Get cross-platform Downloads folder path
    const getDownloadsPath = () => {
        const platform = process.platform;
        const homeDir = os.homedir();
        switch (platform) {
            case 'win32':
                // Windows: Use Downloads folder in user profile
                return path.join(homeDir, 'Downloads');
            case 'darwin':
                // macOS: Use Downloads folder in user home
                return path.join(homeDir, 'Downloads');
            case 'linux':
                // Linux: Use Downloads folder in user home
                return path.join(homeDir, 'Downloads');
            default:
                // Fallback to Downloads in home directory
                return path.join(homeDir, 'Downloads');
        }
    };
    // Check if file exists in Downloads folder
    ipcMain.handle('check-file-exists', async (event, filename) => {
        try {
            const downloadsPath = getDownloadsPath();
            const filePath = path.join(downloadsPath, filename);
            return fs.existsSync(filePath);
        }
        catch (error) {
            console.error('Error checking file existence:', error);
            return false;
        }
    });
    // Get Downloads folder path
    ipcMain.handle('get-downloads-path', async (_event) => {
        try {
            return getDownloadsPath();
        }
        catch (error) {
            console.error('Error getting downloads path:', error);
            return null;
        }
    });
    // Read local file and return as base64 data URL
    ipcMain.handle('read-local-file', async (event, filePath) => {
        try {
            if (!fs.existsSync(filePath)) {
                throw new Error('File does not exist');
            }
            const fileBuffer = fs.readFileSync(filePath);
            const base64Data = fileBuffer.toString('base64');
            return `data:application/pdf;base64,${base64Data}`;
        }
        catch (error) {
            console.error('Error reading local file:', error);
            throw error;
        }
    });
    // Auto-download file to Downloads folder
    ipcMain.handle('auto-download-file', async (event, fileUrl, filename) => {
        try {
            const downloadsPath = getDownloadsPath();
            const filePath = path.join(downloadsPath, filename);
            // Fetch the file from the URL
            const response = await fetch(fileUrl);
            if (!response.ok) {
                throw new Error(`Failed to fetch file: ${response.statusText}`);
            }
            // Get the file as a buffer
            const buffer = await response.arrayBuffer();
            const uint8Array = new Uint8Array(buffer);
            // Write to Downloads folder
            fs.writeFileSync(filePath, uint8Array);
            return { success: true, filePath };
        }
        catch (error) {
            console.error('Error auto-downloading file:', error);
            return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
        }
    });
    // Reveal file in folder
    ipcMain.handle('reveal-in-folder', async (event, filename) => {
        try {
            const downloadsPath = getDownloadsPath();
            const filePath = path.join(downloadsPath, filename);
            // Check if file exists
            if (!fs.existsSync(filePath)) {
                return { success: false, error: 'File not found' };
            }
            // Use shell.showItemInFolder to reveal the file
            shell.showItemInFolder(filePath);
            return { success: true, filePath };
        }
        catch (error) {
            console.error('Error revealing file in folder:', error);
            return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
        }
    });
    // Export HTML to PDF using Electron's printToPDF
    ipcMain.handle('export-html-to-pdf', async (event, htmlContent, filename) => {
        try {
            if (!mainWindow) {
                throw new Error('Main window not available');
            }
            const downloadsPath = getDownloadsPath();
            const filePath = path.join(downloadsPath, filename);
            // Create a new hidden window for PDF generation
            const pdfWindow = new BrowserWindow({
                width: 800,
                height: 1200,
                show: false,
                webPreferences: {
                    nodeIntegration: false,
                    contextIsolation: true,
                },
            });
            // Prepare HTML with proper encoding and meta tags for PDF export
            const processedHtml = `
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="UTF-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <style>
            /* PDF-specific bullet point fixes */
            .bullet {
              display: list-item !important;
              list-style-type: disc !important;
              list-style-position: outside !important;
              margin-left: 20px !important;
              padding-left: 0 !important;
            }

            .bullet:before {
              display: none !important;
            }

            /* Ensure proper font rendering */
            body, * {
              font-family: Arial, sans-serif !important;
              -webkit-print-color-adjust: exact !important;
              color-adjust: exact !important;
            }
          </style>
        </head>
        <body>
          ${htmlContent}
        </body>
        </html>
      `;
            // Load the processed HTML content
            await pdfWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(processedHtml)}`);
            // Wait longer for content and fonts to load
            await new Promise(resolve => setTimeout(resolve, 2000));
            // Generate PDF with Letter size and proper margins for resume content
            const pdfBuffer = await pdfWindow.webContents.printToPDF({
                pageSize: 'Letter',
                margins: {
                    top: 0.5,
                    bottom: 0.5,
                    left: 0.5,
                    right: 0.5,
                },
                printBackground: true,
                landscape: false,
                preferCSSPageSize: false, // Use our specified page size
            });
            // Save PDF to file
            fs.writeFileSync(filePath, pdfBuffer);
            // Close the PDF window
            pdfWindow.close();
            return { success: true, filePath };
        }
        catch (error) {
            console.error('Error exporting HTML to PDF:', error);
            return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
        }
    });
    // Open file with system default application
    ipcMain.handle('open-file', async (event, filePath) => {
        try {
            if (!fs.existsSync(filePath)) {
                throw new Error('File does not exist');
            }
            await shell.openPath(filePath);
            return { success: true };
        }
        catch (error) {
            console.error('Error opening file:', error);
            return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
        }
    });
    // Open external URL in default browser
    ipcMain.handle('open-external-url', async (event, url) => {
        try {
            if (!url || typeof url !== 'string') {
                throw new Error('Invalid URL provided');
            }
            // Validate URL format
            try {
                new URL(url);
            }
            catch {
                throw new Error('Invalid URL format');
            }
            await shell.openExternal(url);
            return { success: true };
        }
        catch (error) {
            console.error('Error opening external URL:', error);
            return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
        }
    });
    // Hide window to tray
    ipcMain.handle('hide-window', async () => {
        try {
            hideMainWindowToTray();
            return { success: true };
        }
        catch (error) {
            console.error('Error hiding window:', error);
            return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
        }
    });
    // Generate PDF blob (legacy method)
    ipcMain.handle('generate-pdf-blob', async (_event, htmlContent, _options) => {
        try {
            if (!mainWindow) {
                throw new Error('Main window not available');
            }
            // Create a new hidden window for PDF generation
            const pdfWindow = new BrowserWindow({
                width: 800,
                height: 1200,
                show: false,
                webPreferences: {
                    nodeIntegration: false,
                    contextIsolation: true,
                },
            });
            // Load the HTML content
            await pdfWindow.loadURL(`data:text/html,${encodeURIComponent(htmlContent)}`);
            // Wait for content to load
            await new Promise(resolve => setTimeout(resolve, 1000));
            // Generate PDF buffer with US Letter settings
            const pdfBuffer = await pdfWindow.webContents.printToPDF({
                pageSize: 'Letter',
                margins: {
                    top: 0.5,
                    bottom: 0.5,
                    left: 0.5,
                    right: 0.5,
                },
                printBackground: true,
                landscape: false,
                preferCSSPageSize: false, // Use our specified page size
            });
            // Close the PDF window
            pdfWindow.close();
            // Convert buffer to base64 data URL
            const base64Data = pdfBuffer.toString('base64');
            const dataUrl = `data:application/pdf;base64,${base64Data}`;
            return dataUrl;
        }
        catch (error) {
            console.error('Error generating PDF blob:', error);
            throw error;
        }
    });
    // Write user auth data to file (backup mechanism)
    ipcMain.handle('write-user-auth', async (event, authData) => {
        try {
            // Determine the correct base directory based on OS
            let baseDir;
            const homeDir = os.homedir();
            if (process.platform === 'darwin') {
                baseDir = path.join(homeDir, 'Library', 'Application Support', 'JobHuntr');
            }
            else if (process.platform === 'win32') {
                baseDir = path.join(homeDir, 'AppData', 'Local', 'jobhuntr');
            }
            else {
                baseDir = path.join(homeDir, '.jobhuntr');
            }
            const tokenFile = path.join(baseDir, 'user_auth.json');
            // Ensure directory exists
            await fs.promises.mkdir(baseDir, { recursive: true });
            // Write auth data to file
            await fs.promises.writeFile(tokenFile, JSON.stringify(authData, null, 2));
            return { success: true, path: tokenFile };
        }
        catch (error) {
            console.error('Error writing user auth data:', error);
            return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
        }
    });
    // Browser setup operations
    ipcMain.handle('get-path', async (event, name) => {
        try {
            return app.getPath(name);
        }
        catch (error) {
            console.error('Error getting path:', error);
            throw error;
        }
    });
    ipcMain.handle('ensure-dir', async (event, dirPath) => {
        try {
            await fs.promises.mkdir(dirPath, { recursive: true });
            return true;
        }
        catch (error) {
            console.error('Error creating directory:', error);
            throw error;
        }
    });
    ipcMain.handle('write-file', async (event, filePath, data) => {
        try {
            await fs.promises.writeFile(filePath, Buffer.from(data));
            return true;
        }
        catch (error) {
            console.error('Error writing file:', error);
            throw error;
        }
    });
    ipcMain.handle('extract-zip', async (event, zipPath, targetDir) => {
        try {
            const execAsync = promisify(exec);
            // Use system unzip command (works on macOS and Linux)
            if (process.platform === 'win32') {
                // On Windows, use PowerShell to extract
                const command = `powershell -command "Expand-Archive -Path '${zipPath}' -DestinationPath '${targetDir}' -Force"`;
                await execAsync(command);
            }
            else {
                // On macOS/Linux, use unzip command
                const command = `unzip -o "${zipPath}" -d "${targetDir}"`;
                await execAsync(command);
            }
            return true;
        }
        catch (error) {
            console.error('Error extracting zip:', error);
            throw error;
        }
    });
    ipcMain.handle('delete-file', async (event, filePath) => {
        try {
            await fs.promises.unlink(filePath);
            return true;
        }
        catch (error) {
            console.error('Error deleting file:', error);
            throw error;
        }
    });
    ipcMain.handle('set-executable-permissions', async (event, filePath) => {
        try {
            const execAsync = promisify(exec);
            if (process.platform === 'win32') {
                // On Windows, files are executable by default
                return true;
            }
            else {
                // On macOS/Linux, use chmod to set executable permissions
                const command = `chmod -R +x "${filePath}"`;
                await execAsync(command);
                return true;
            }
        }
        catch (error) {
            console.error('Error setting executable permissions:', error);
            throw error;
        }
    });
    ipcMain.handle('check-chrome-availability', async () => {
        const chromePath = resolveChromeExecutable();
        return { available: Boolean(chromePath), path: chromePath ?? undefined };
    });
    ipcMain.handle('launch-chrome-for-automation', async (_event, options) => {
        const chromePath = resolveChromeExecutable();
        if (!chromePath) {
            return { success: false, message: 'Google Chrome not found on this system.' };
        }
        const profilePath = getJobhuntrProfilePath();
        try {
            await fs.promises.mkdir(profilePath, { recursive: true });
        }
        catch (error) {
            console.error('Error preparing Chrome profile directory:', error);
            return { success: false, message: 'Unable to prepare JobHuntr Chrome profile.' };
        }
        const port = Number(options?.port) || Number(process.env['JOBHUNTR_CDP_PORT']) || 9222;
        if (chromeAutomationProcess && !chromeAutomationProcess.killed) {
            return { success: true, message: 'Chrome is already running.' };
        }
        const chromeArgs = [
            `--remote-debugging-port=${port}`,
            `--user-data-dir=${profilePath}`,
            '--profile-directory=Default',
            '--remote-allow-origins=*',
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-popup-blocking',
        ];
        try {
            chromeAutomationProcess = spawn(chromePath, chromeArgs, {
                detached: true,
                stdio: 'ignore',
            });
            chromeAutomationProcess.unref();
            return { success: true };
        }
        catch (error) {
            console.error('Failed to launch Chrome:', error);
            chromeAutomationProcess = null;
            return {
                success: false,
                message: error?.message || 'Failed to launch Chrome.',
            };
        }
    });
    ipcMain.handle('launch-chrome-with-profile', async (_event, options) => {
        const chromePath = resolveChromeExecutable();
        if (!chromePath) {
            return { success: false, message: 'Google Chrome not found on this system.' };
        }
        const profilePath = getJobhuntrProfilePath();
        try {
            await fs.promises.mkdir(profilePath, { recursive: true });
        }
        catch (error) {
            console.error('Failed to ensure JobHuntr profile directory:', error);
            return { success: false, message: 'Unable to prepare JobHuntr Chrome profile.' };
        }
        const chromeArgs = [
            `--user-data-dir=${profilePath}`,
            '--profile-directory=Default',
            '--no-default-browser-check',
            '--no-first-run',
        ];
        if (options?.url) {
            chromeArgs.push(options.url);
        }
        try {
            if (process.platform === 'darwin') {
                const appPath = path.resolve(chromePath, '../../..');
                const chromeProcess = spawn('open', ['-na', appPath, '--args', ...chromeArgs], {
                    detached: true,
                    stdio: 'ignore',
                });
                chromeProcess.unref();
            }
            else {
                const chromeProcess = spawn(chromePath, chromeArgs, { detached: true, stdio: 'ignore' });
                chromeProcess.unref();
            }
            return { success: true };
        }
        catch (error) {
            console.error('Failed to launch Chrome with JobHuntr profile:', error);
            return {
                success: false,
                message: error?.message || 'Failed to open Chrome with JobHuntr profile.',
            };
        }
    });
}
function setupAutoUpdater() {
    const isDev = process.argv.includes('--dev');
    // Enable auto-update by default in production, only disable if explicitly set to 'false'
    const enableAutoUpdateEnv = process.env['ENABLE_AUTO_UPDATE'] !== 'false';
    // TEMPORARY: Force enable for testing
    const forceEnabled = false; // Disabled - respect environment variables
    // Skip auto-updater if:
    // 1. In dev mode AND auto-update is not explicitly enabled AND not force enabled
    // BUT: If feed is already configured (shouldConfigureFeed is true), we should still set up handlers
    if (isDev && !enableAutoUpdateEnv && !forceEnabled && !shouldConfigureFeed) {
        return;
    }
    // Also skip if feed wasn't configured at top level
    if (!shouldConfigureFeed) {
        return;
    }
    // Auto-updater event handlers
    autoUpdater.on('checking-for-update', () => {
        if (mainWindow) {
            mainWindow.webContents.send('update-checking');
        }
    });
    autoUpdater.on('update-available', info => {
        if (mainWindow) {
            mainWindow.webContents.send('update-available', {
                version: info.version,
                releaseDate: info.releaseDate,
                releaseName: info.releaseName,
            });
        }
    });
    autoUpdater.on('update-not-available', _info => {
        if (mainWindow) {
            mainWindow.webContents.send('update-not-available');
        }
    });
    autoUpdater.on('download-progress', progress => {
        if (mainWindow) {
            mainWindow.webContents.send('update-download-progress', {
                percent: Math.round(progress.percent),
                transferred: progress.transferred,
                total: progress.total,
                bytesPerSecond: progress.bytesPerSecond,
            });
        }
    });
    autoUpdater.on('update-downloaded', info => {
        if (mainWindow) {
            mainWindow.webContents.send('update-downloaded', {
                version: info.version,
                releaseDate: info.releaseDate,
            });
        }
    });
    autoUpdater.on('error', async (error) => {
        // Ignore 404 errors for platform-specific update files (happens when no releases exist yet)
        const platformUpdateFiles = ['latest-mac.yml', 'latest-win.yml', 'latest-linux.yml'];
        if (error.message?.includes('404') &&
            platformUpdateFiles.some(file => error.message?.includes(file))) {
            return;
        }
        console.error('[auto-update] Update error:', error);
        if (mainWindow) {
            mainWindow.webContents.send('update-error', {
                message: error.message,
            });
        }
    });
    // IPC handler to manually trigger update check
    ipcMain.handle('check-for-updates', async () => {
        try {
            const result = await autoUpdater.checkForUpdates();
            return { success: true, updateInfo: result?.updateInfo };
        }
        catch (error) {
            console.error('Error checking for updates:', error);
            return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
        }
    });
    // IPC handler to manually download update (platform-specific installer)
    ipcMain.handle('download-update', async () => {
        try {
            // Get the latest update info
            const updateCheckResult = await autoUpdater.checkForUpdates();
            if (!updateCheckResult) {
                return { success: false, error: 'No updates available' };
            }
            const updateInfo = updateCheckResult.updateInfo;
            const files = updateInfo.files || [];
            // Find the installer file for the current platform
            let installerFile;
            if (process.platform === 'darwin') {
                // macOS: Look for DMG file
                const arch = process.arch === 'arm64' ? 'arm64' : 'x64';
                installerFile = files.find((file) => file.url.includes('.dmg') && file.url.includes(arch));
                if (!installerFile) {
                    return { success: false, error: 'DMG file not found in release' };
                }
            }
            else if (process.platform === 'win32') {
                // Windows: Look for EXE installer
                installerFile = files.find((file) => file.url.includes('.exe') &&
                    (file.url.includes('JobHuntr') || file.url.includes('JobHuntr-x64.exe')));
                if (!installerFile) {
                    return { success: false, error: 'Windows installer (EXE) not found in release' };
                }
            }
            else {
                // Linux: Look for AppImage or other Linux installer
                installerFile = files.find((file) => file.url.includes('.AppImage') || file.url.includes('.deb') || file.url.includes('.rpm'));
                if (!installerFile) {
                    return { success: false, error: 'Linux installer not found in release' };
                }
            }
            // Download the installer file manually
            const downloadUrl = `https://github.com/${ACTIVE_REPO_SLUG}/releases/download/v${updateInfo.version}/${installerFile.url}`;
            const downloadPath = path.join(app.getPath('downloads'), installerFile.url);
            // Use electron's net module to download (imported at top of file)
            const request = net.request(downloadUrl);
            const fileStream = fs.createWriteStream(downloadPath);
            return new Promise(resolve => {
                request.on('response', (response) => {
                    const totalBytes = parseInt(response.headers['content-length'] || '0', 10);
                    let downloadedBytes = 0;
                    response.on('data', (chunk) => {
                        downloadedBytes += chunk.length;
                        fileStream.write(chunk);
                        // Send progress updates
                        if (mainWindow) {
                            mainWindow.webContents.send('update-download-progress', {
                                percent: (downloadedBytes / totalBytes) * 100,
                                transferred: downloadedBytes,
                                total: totalBytes,
                                bytesPerSecond: 0,
                            });
                        }
                    });
                    response.on('end', () => {
                        fileStream.end();
                        resolve({ success: true, filePath: downloadPath });
                    });
                });
                request.on('error', (error) => {
                    console.error('Download error:', error);
                    fileStream.end();
                    resolve({ success: false, error: error.message });
                });
                request.end();
            });
        }
        catch (error) {
            console.error('Error downloading update:', error);
            const errorMsg = error instanceof Error ? error.message : 'Unknown error';
            return { success: false, error: errorMsg };
        }
    });
    // IPC handler to open downloaded DMG file
    ipcMain.handle('open-dmg', async (_event, filePath) => {
        try {
            if (!fs.existsSync(filePath)) {
                return { success: false, error: 'DMG file not found' };
            }
            // Open the DMG file using the default application (Finder)
            await shell.openPath(filePath);
            return { success: true };
        }
        catch (error) {
            console.error('Error opening DMG:', error);
            return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
        }
    });
    // IPC handler to quit the app (for manual DMG installation)
    ipcMain.handle('quit-app', () => {
        try {
            const tokenPath = path.join(getJobhuntrBaseDir(), 'user_auth.json');
            if (fs.existsSync(tokenPath)) {
                fs.rmSync(tokenPath, { force: true });
            }
        }
        catch (error) {
            console.warn('Failed to remove stored auth before quit:', error);
        }
        finally {
            app.quit();
        }
        return { success: true };
    });
    // NOTE: Initial update check is triggered from window's 'ready-to-show' event
    // This ensures the renderer is ready to receive the update-available event
    // Check for updates every 4 hours
    // Note: checkForUpdates() will NOT auto-download since autoDownload is false
    setInterval(() => {
        autoUpdater.checkForUpdates().catch(error => {
            console.error('Failed to check for updates:', error);
        });
    }, 4 * 60 * 60 * 1000);
}
async function initializeFastAPI() {
    try {
        fastApiCoordinator = new FastAPICoordinator(LOCAL_BACKEND_PORT);
        if (mainWindow) {
            fastApiCoordinator.setMainWindow(mainWindow);
            await fastApiCoordinator.initialize();
        }
        // Set up log entry handler from renderer
        ipcMain.on('log-entries', (event, logEntries) => {
            const logger = getLogger();
            for (const entry of logEntries) {
                logger.log(entry.level, entry.module, entry.message, entry.data, entry.error ? new Error(entry.error) : undefined);
            }
        });
    }
    catch (error) {
        console.error('Failed to initialize FastAPI coordinator:', error);
        const logger = getLogger();
        logger.error('main', 'Failed to initialize FastAPI coordinator', error instanceof Error ? error : new Error(String(error)));
    }
}
// This method will be called when Electron has finished initialization
app.whenReady().then(() => {
    // Set app name and icon for dock/taskbar
    app.setName('JobHuntr');
    // Set dock icon on macOS
    if (process.platform === 'darwin') {
        // Try different possible paths for the PNG icon
        const possiblePaths = [
            path.join(__dirname, '../../frontend/app/public/logo.png'),
            path.join(__dirname, '../../app/public/logo.png'),
            path.join(__dirname, '../../../frontend/app/public/logo.png'),
        ];
        for (const iconPath of possiblePaths) {
            if (fs.existsSync(iconPath)) {
                try {
                    app.dock.setIcon(iconPath);
                    break;
                }
                catch (error) {
                    console.error('Failed to set dock icon:', error);
                    // Continue to next path
                }
            }
        }
    }
    configureAutoLaunch();
    shouldStartHidden = determineShouldLaunchHidden();
    createWindow();
    setupTray();
    // Initialize auto-updater after window is created
    setupAutoUpdater();
});
// Quit when all windows are closed
app.on('window-all-closed', async () => {
    // Cleanup FastAPI coordinator
    await shutdownFastAPI();
    // On macOS, keep app running even when all windows are closed
    if (process.platform !== 'darwin') {
        app.quit();
    }
});
app.on('before-quit', event => {
    // If user already confirmed quit, proceed with cleanup
    if (hasRequestedQuit) {
        isQuittingApp = true;
        if (tray) {
            tray.destroy();
            tray = null;
        }
        if (chromeAutomationProcess) {
            try {
                chromeAutomationProcess.kill();
            }
            catch {
                // ignore
            }
            chromeAutomationProcess = null;
        }
        if (fastApiCoordinator && !isBackendShutdownInProgress) {
            event.preventDefault();
            shutdownFastAPI()
                .catch(error => {
                console.error('Error during pre-quit backend shutdown:', error);
            })
                .finally(() => {
                app.quit();
            });
        }
        return;
    }
    // Intercept quit and show confirmation modal instead
    event.preventDefault();
    showQuitConfirmation();
});
app.on('activate', () => {
    // On macOS, re-create or show window when dock icon is clicked
    // But don't show if user intentionally hid it to tray
    if (!mainWindow) {
        createWindow();
        return;
    }
    // Only show the window if it wasn't intentionally hidden
    if (!isWindowIntentionallyHidden) {
        showMainWindow();
    }
});
// Security: Prevent new window creation
app.on('web-contents-created', (event, contents) => {
    contents.setWindowOpenHandler(() => {
        return { action: 'deny' };
    });
});
// Initialize logging system with BetterStack
const logger = initializeLogger('xohQ7wcxadbDVzC9YpDWLf3M', // BetterStack source token
's1555030.eu-nbg-2.betterstackdata.com' // BetterStack ingesting host
);
logger.info('main', 'Application starting with FastAPI integration');
//# sourceMappingURL=electron-main.js.map