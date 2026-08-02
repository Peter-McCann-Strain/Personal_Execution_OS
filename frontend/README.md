# Personal Execution OS Web

This directory contains the installable React PWA for Personal Execution OS.

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
URL. For local Vite development, set it in the shell:

```bash
VITE_SOURCE_REPOSITORY_URL=https://github.com/your-org/your-repository
```

For the supported Compose build, set the same value in the root `.env` and
rebuild the `web` image. Compose forwards it only as a public build argument;
the web container never receives the backend `.env` file.

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
npm run test:e2e:install
npm run test:e2e
```

`test:e2e` is the CI-gated browser acceptance, PWA, responsive interaction,
and accessibility suite. It runs desktop Chromium, Firefox, and WebKit plus
Pixel 7 Chromium and iPhone 15 WebKit emulation. The emulated mobile projects
do not replace physical-device and assistive-technology review. `test:visual`
is a separate snapshot-development command and is not currently a release gate.
`capture:showcase` regenerates the reviewed, fixture-only mobile image used in
the root README.

The frontend expects the API under `/api`. Vite proxies `/api` to the local
backend on port 8001 during development. Streaming uses server-sent events;
the repository has no supported WebSocket endpoint.
