/**
 * Frontend Configuration
 * Centralized config for the entire frontend application
 *
 * Note: This file is deprecated in favor of app/src/config/constants.ts
 * Use constants.ts for environment-aware configuration.
 */
// Get environment from Vite
const APP_ENV = import.meta.env?.VITE_APP_ENV || 'production';
const IS_LOCAL_ENV = APP_ENV === 'local' || APP_ENV === 'test';
// Service gateway URL: can be overridden via VITE_SERVICE_GATEWAY_URL in .env
// Falls back to hardcoded URLs based on APP_ENV
const SERVICE_GATEWAY_URL = import.meta.env?.VITE_SERVICE_GATEWAY_URL ||
    (IS_LOCAL_ENV
        ? 'http://localhost:8001'
        : 'https://democratized-service-gateway-production.up.railway.app');
// Local backend (FastAPI) configuration used by Electron processes
export const LOCAL_BACKEND_PORT = Number(process.env.LOCAL_BACKEND_PORT || 58273);
export const LOCAL_BACKEND_URL = `http://localhost:${LOCAL_BACKEND_PORT}`;
export const LOCAL_BACKEND_WS_URL = `ws://localhost:${LOCAL_BACKEND_PORT}`;
export const config = {
    // Analytics Configuration (PostHog)
    analytics: {
        posthog: {
            apiKey: 'phc_Lmpw09moMXPCinm0qGGBWIMPWsrsxp9nY9isjd348Z0',
            apiHost: 'https://us.i.posthog.com',
            enabled: true, // Set to false to disable analytics
            options: {
                person_profiles: 'identified_only',
                capture_pageview: false, // Disable auto pageview for Electron
                capture_pageleave: false, // Not useful in desktop apps
                autocapture: true, // Auto-capture clicks
                session_recording: {
                    recordCrossOriginIframes: false,
                },
            },
        },
    },
    // API Endpoints
    api: {
        backend: {
            url: LOCAL_BACKEND_URL, // Always use local backend in Electron runtime
        },
        serviceGateway: {
            url: SERVICE_GATEWAY_URL,
        },
    },
    // Application Settings
    app: {
        name: 'JobHuntr',
        version: '0.0.3',
        isDevelopment: IS_LOCAL_ENV,
        environment: APP_ENV,
    },
    // Feature Flags
    features: {
        enableCoachMode: true,
        enableJobTracker: true,
        enableATSTemplates: true,
        enableCoverLetterGenerator: true,
        enableLinkedInBot: true,
    },
    // Add your other settings here...
};
//# sourceMappingURL=config.js.map