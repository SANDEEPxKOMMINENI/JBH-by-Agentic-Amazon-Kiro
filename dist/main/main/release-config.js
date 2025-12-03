import { readFileSync, existsSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const releaseTargetsPath = path.join(__dirname, '../../config/release-targets.json');
const selectionPath = path.join(__dirname, '../../config/release-target-selected.json');
const releaseTargetsRaw = JSON.parse(readFileSync(releaseTargetsPath, 'utf-8'));
export const RELEASE_TARGETS = releaseTargetsRaw;
const FALLBACK_RELEASE_TARGET = 'job-application-bot-by-ollama-ai';
const normalizeTarget = (source, value) => {
    if (!value) {
        return undefined;
    }
    if (value === 'playwright_browser' || value === 'job-application-bot-by-ollama-ai') {
        return value;
    }
    console.warn(`[release-config] Ignoring invalid ${source} release target "${value}".`);
    return undefined;
};
const envRaw = process.env['JOBHUNTR_RELEASE_REPO'];
const envTarget = normalizeTarget('environment', envRaw);
let fileTarget;
if (existsSync(selectionPath)) {
    try {
        const selectionRaw = JSON.parse(readFileSync(selectionPath, 'utf-8'));
        fileTarget = normalizeTarget('selection file', selectionRaw.target ?? undefined);
    }
    catch (error) {
        console.warn('[release-config] Failed to read release target selection file:', error);
    }
}
export const ACTIVE_RELEASE_TARGET = envTarget ?? fileTarget ?? FALLBACK_RELEASE_TARGET;
export const ACTIVE_RELEASE_CONFIG = RELEASE_TARGETS[ACTIVE_RELEASE_TARGET];
export const getRepoSlug = (config) => `${config.owner}/${config.repo}`;
export const ACTIVE_REPO_SLUG = getRepoSlug(ACTIVE_RELEASE_CONFIG);
//# sourceMappingURL=release-config.js.map