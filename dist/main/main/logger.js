/**
 * @file purpose: Frontend logging system for Electron main process
 * This module provides unified logging for the main process that forwards
 * logs to the backend Python logger and BetterStack integration.
 */
import { app } from 'electron';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import axios from 'axios';
import { LOCAL_BACKEND_URL } from '../config.js';
export var LogLevel;
(function (LogLevel) {
    LogLevel["DEBUG"] = "DEBUG";
    LogLevel["INFO"] = "INFO";
    LogLevel["WARN"] = "WARN";
    LogLevel["ERROR"] = "ERROR";
})(LogLevel || (LogLevel = {}));
class DemocratizedFrontendLogger {
    logFilePath;
    betterStackToken;
    betterStackHost;
    logQueue = [];
    flushInterval;
    userEmail = 'Unknown';
    constructor(logFilePath, betterStackToken, betterStackHost) {
        // Set up log file path
        if (!logFilePath) {
            const userDataPath = app.getPath('userData');
            const logDir = path.join(userDataPath, 'logs');
            // Ensure log directory exists
            if (!fs.existsSync(logDir)) {
                fs.mkdirSync(logDir, { recursive: true });
            }
            this.logFilePath = path.join(logDir, 'jobhuntr.log');
        }
        else {
            this.logFilePath = logFilePath;
        }
        this.betterStackToken = betterStackToken;
        this.betterStackHost = betterStackHost;
        // Set up periodic log flushing
        this.flushInterval = setInterval(() => {
            this.flushLogs();
        }, 5000); // Flush every 5 seconds
        // Log startup
        this.log(LogLevel.INFO, 'main', '='.repeat(80));
        this.log(LogLevel.INFO, 'main', 'Democratized Frontend Logger Initialized');
        this.log(LogLevel.INFO, 'main', `Log file: ${this.logFilePath}`);
        this.log(LogLevel.INFO, 'main', `Electron version: ${process.versions.electron}`);
        this.log(LogLevel.INFO, 'main', `Node version: ${process.versions.node}`);
        this.log(LogLevel.INFO, 'main', `Platform: ${os.platform()} ${os.arch()}`);
        this.log(LogLevel.INFO, 'main', '='.repeat(80));
        // Try to load user email from JWT auth file
        this.loadUserEmailFromAuthFile();
    }
    loadUserEmailFromAuthFile() {
        try {
            const homeDir = os.homedir();
            let authFilePath;
            // Determine auth file location based on OS
            if (os.platform() === 'darwin') {
                authFilePath = path.join(homeDir, 'Library', 'Application Support', 'jobhuntr', 'user_auth.json');
            }
            else if (os.platform() === 'win32') {
                authFilePath = path.join(homeDir, 'AppData', 'Local', 'jobhuntr', 'user_auth.json');
            }
            else {
                authFilePath = path.join(homeDir, '.jobhuntr', 'user_auth.json');
            }
            if (fs.existsSync(authFilePath)) {
                const authData = JSON.parse(fs.readFileSync(authFilePath, 'utf8'));
                const userInfo = authData.user_info || {};
                const email = userInfo.email || userInfo.user_metadata?.email;
                if (email) {
                    this.userEmail = email;
                    this.log(LogLevel.INFO, 'main', `Loaded user email from auth file: ${email}`);
                }
            }
        }
        catch (error) {
            // Silently fail - email is not critical
            console.debug('Could not load user email from auth file:', error);
        }
    }
    updateUserEmail(email) {
        this.userEmail = email;
    }
    log(level, module, message, data, error) {
        const timestamp = new Date().toISOString();
        const logEntry = {
            timestamp,
            level,
            process: 'frontend',
            module,
            message,
            data: data ? this.serializeData(data) : undefined,
            error: error?.message,
            stack: error?.stack,
            user_email: this.userEmail,
        };
        // Add to queue
        this.logQueue.push(logEntry);
        // Also log to console
        const consoleMessage = `${timestamp} | ${level.padEnd(5)} | ${module.padEnd(15)} | ${message}`;
        switch (level) {
            case LogLevel.DEBUG:
                console.debug(consoleMessage, data || '');
                break;
            case LogLevel.INFO:
                console.info(consoleMessage, data || '');
                break;
            case LogLevel.WARN:
                console.warn(consoleMessage, data || '');
                break;
            case LogLevel.ERROR:
                console.error(consoleMessage, data || '', error || '');
                break;
        }
    }
    debug(module, message, data) {
        this.log(LogLevel.DEBUG, module, message, data);
    }
    info(module, message, data) {
        this.log(LogLevel.INFO, module, message, data);
    }
    warn(module, message, data) {
        this.log(LogLevel.WARN, module, message, data);
    }
    error(module, message, error, data) {
        this.log(LogLevel.ERROR, module, message, data, error);
    }
    logException(module, error, context) {
        const message = context ? `Exception in ${context}` : 'Exception occurred';
        this.error(module, message, error);
    }
    serializeData(data) {
        try {
            return JSON.parse(JSON.stringify(data));
        }
        catch {
            return String(data);
        }
    }
    async flushLogs() {
        if (this.logQueue.length === 0)
            return;
        const logsToFlush = [...this.logQueue];
        this.logQueue = [];
        try {
            // Write to file
            await this.writeToFile(logsToFlush);
            // Send to BetterStack if configured (frontend has its own source)
            if (this.betterStackToken && this.betterStackHost) {
                await this.sendToBetterStack(logsToFlush);
            }
            // NOTE: Not sending to backend - frontend has its own BetterStack source
            // If you want to send to backend for unified logging, uncomment:
            // await this.sendToBackend(logsToFlush);
        }
        catch (error) {
            console.error('Failed to flush logs:', error);
            // Put logs back in queue
            this.logQueue.unshift(...logsToFlush);
        }
    }
    async writeToFile(logs) {
        const logLines = logs.map(log => this.formatLogEntry(log)).join('\n') + '\n';
        return new Promise((resolve, reject) => {
            fs.appendFile(this.logFilePath, logLines, 'utf8', err => {
                if (err)
                    reject(err);
                else
                    resolve();
            });
        });
    }
    formatLogEntry(log) {
        let formatted = `${log.timestamp} | ${log.level.padEnd(8)} | ${log.process.padEnd(10)} | ${log.module.padEnd(15)} | ${log.message}`;
        if (log.data) {
            formatted += ` | Data: ${JSON.stringify(log.data)}`;
        }
        if (log.error) {
            formatted += ` | Error: ${log.error}`;
        }
        if (log.stack) {
            formatted += `\nStack: ${log.stack}`;
        }
        return formatted;
    }
    async sendToBetterStack(logs) {
        if (!this.betterStackToken || !this.betterStackHost)
            return;
        try {
            for (const log of logs) {
                // Format log to match BetterStack expected format
                const betterStackLog = {
                    timestamp: log.timestamp,
                    level: log.level,
                    logger: log.module,
                    message: log.message,
                    module: log.module,
                    process: log.process,
                    app: 'jobhuntr-frontend', // Different app name to distinguish from backend
                    user_email: log.user_email || this.userEmail, // Include user email
                    ...(log.data && { data: log.data }),
                    ...(log.error && { error: log.error }),
                    ...(log.stack && { stack: log.stack }),
                };
                await axios.post(`https://${this.betterStackHost}/logs`, betterStackLog, {
                    headers: {
                        Authorization: `Bearer ${this.betterStackToken}`,
                        'Content-Type': 'application/json',
                    },
                    timeout: 5000,
                });
            }
        }
        catch (error) {
            console.error('Failed to send logs to BetterStack:', error);
            if (axios.isAxiosError(error) && error.response) {
                console.error('Response status:', error.response.status);
                console.error('Response data:', error.response.data);
            }
        }
    }
    async sendToBackend(logs) {
        if (logs.length === 0)
            return;
        try {
            // Send logs to backend Python FastAPI server
            const response = await axios.post(`${LOCAL_BACKEND_URL}/api/logs/frontend`, { logs }, {
                headers: {
                    'Content-Type': 'application/json',
                },
                timeout: 5000,
            });
            if (response.status !== 200) {
                console.error(`Failed to send logs to backend: ${response.status}`);
            }
        }
        catch (error) {
            // Silently fail - don't want logging failures to break the app
            // Only log to console for debugging
            if (axios.isAxiosError(error)) {
                if (error.code === 'ECONNREFUSED') {
                    // Backend not running - this is expected in some scenarios
                    console.debug('Backend not available for log forwarding');
                }
                else {
                    console.error('Failed to send logs to backend:', error.message);
                }
            }
            else {
                console.error('Failed to send logs to backend:', error);
            }
        }
    }
    destroy() {
        if (this.flushInterval) {
            clearInterval(this.flushInterval);
        }
        // Final flush
        this.flushLogs();
    }
}
// Global logger instance
let globalLogger = null;
export function initializeLogger(betterStackToken, betterStackHost) {
    if (!globalLogger) {
        globalLogger = new DemocratizedFrontendLogger(undefined, betterStackToken, betterStackHost);
    }
    return globalLogger;
}
export function getLogger() {
    if (!globalLogger) {
        globalLogger = new DemocratizedFrontendLogger();
    }
    return globalLogger;
}
// Convenience functions
export function debug(module, message, data) {
    getLogger().debug(module, message, data);
}
export function info(module, message, data) {
    getLogger().info(module, message, data);
}
export function warn(module, message, data) {
    getLogger().warn(module, message, data);
}
export function error(module, message, error, data) {
    getLogger().error(module, message, error, data);
}
export function updateUserEmail(email) {
    getLogger().updateUserEmail(email);
}
export function logException(module, error, context) {
    getLogger().logException(module, error, context);
}
//# sourceMappingURL=logger.js.map