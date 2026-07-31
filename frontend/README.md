# Personal Execution OS Web

Installable, responsive React PWA for the self-hosted Personal Execution OS.

## Authentication

Production uses the backend's local-owner password flow and a same-origin
server session. The browser sends the secure session cookie automatically,
reads the non-secret CSRF cookie for mutation headers, and does not store API
keys or bearer tokens. On a new installation, open `/setup` once to create the
owner password. Later visits use `/login`.

The legacy API-key setup screen is available only for local development and
tests:

```bash
VITE_ALLOW_INSECURE_DEV_AUTH=true npm run dev
```

That flag is ignored by production builds, so `X-API-Key` and `sessionStorage`
credentials are never enabled in the production app. Server-to-server API keys
remain a backend/admin concern.

An optional public source link can be added to the landing page with an HTTPS
URL:

```bash
VITE_SOURCE_REPOSITORY_URL=https://github.com/your-org/your-repository
```

The service worker caches only versioned static assets and icons. It never
caches navigation responses, API calls, authentication routes, setup routes, or
settings pages.

## Commands

Use Node.js 22 LTS (22.22 or newer) or Node.js 24 and newer.

```bash
npm ci
npm run dev
npm run test
npm run lint
npm run build
```

The frontend expects the API under `/api`. Vite proxies `/api` and `/ws` to the local backend during development.
