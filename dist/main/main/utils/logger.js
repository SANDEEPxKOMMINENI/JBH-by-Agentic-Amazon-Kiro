export class Logger {
    static instance;
    prefix;
    constructor(prefix) {
        this.prefix = prefix;
    }
    static frontend() {
        if (!Logger.instance) {
            Logger.instance = new Logger('🖥️  [FRONTEND]');
        }
        return Logger.instance;
    }
    static python() {
        return new Logger('🐍 [PYTHON]');
    }
    log(...args) {
        console.log(this.prefix, ...args);
    }
    info(...args) {
        console.info(this.prefix, ...args);
    }
    warn(...args) {
        console.warn(this.prefix, ...args);
    }
    error(...args) {
        console.error(this.prefix, ...args);
    }
    debug(...args) {
        console.debug(this.prefix, ...args);
    }
}
// Export convenience instances
export const frontendLogger = Logger.frontend();
export const pythonLogger = Logger.python();
//# sourceMappingURL=logger.js.map