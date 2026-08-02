# ADR-0004: Provide an installable progressive web app rather than native clients

- **Status:** Accepted (retrospective)
- **Date:** 2026-07-31

## Context

The product needs a useful desktop and phone interface while remaining
self-hosted. Separate iOS, Android, and desktop clients would multiply release,
security, accessibility, and synchronization work. A normal responsive website
would reduce that cost but would not provide an installable app shell.

The application contains sensitive records, so an offline-first cache of API
responses would create another data store and a difficult invalidation and
deletion boundary.

## Decision drivers

- Maintain one interaction client across desktop and phone viewports.
- Allow supported browsers to install an app-like shell.
- Keep authentication and API calls same-origin.
- Avoid caching personal records or authentication state for offline use.
- Preserve web accessibility and browser testing as release gates.

## Considered options

1. Build separate native iOS and Android clients.
2. Ship a responsive website with no installable metadata or service worker.
3. Build an offline-first PWA that caches API data and page navigations.
4. Build an installable responsive PWA that caches versioned static assets
   only.

## Decision

React and Vite produce a responsive PWA. Its manifest and service worker make
the static shell installable. The service worker may cache reviewed static
assets but excludes API requests, authentication routes, settings, navigation
responses, and personal records.

The PWA is the supported phone experience. It is not a native mobile binary,
does not provide a background native service, and does not promise personal
records offline. A phone accessing a different host needs a trusted HTTPS
origin that can reach the self-hosted installation.

## Consequences

### Positive

- One client and design system serve desktop and phone layouts.
- Browser accessibility, responsive behavior, and critical paths can share
  automated tests.
- Same-origin cookies and CSRF controls apply consistently.
- Clearing browser data does not need to reconcile an intended offline record
  database.

### Negative

- Native platform capabilities and background execution are limited.
- Installation behavior varies across browser and operating-system versions.
- Remote phone use requires HTTPS and operator-managed network access.
- The app cannot provide useful personal-record access when the host is
  unavailable.

### Neutral

- Browser push remains an optional external delivery path rather than proof of
  native application support.
- Static asset caching still leaves browser storage and push subscriptions as
  privacy-relevant copies.

## Security, privacy, and operations

The narrow cache policy reduces local data persistence but does not make the
browser stateless. Operators must clear caches, unregister service workers, and
remove push subscriptions when retiring a device. HTTPS is required for remote
installation and secure cookies; a private network by itself does not satisfy
the browser secure-context requirement.

The PWA has not been validated on every supported iOS and Android release.
Screenshots and viewport tests are evidence of responsive design, not a claim
of complete device certification.

## Verification in code and tests

- [`frontend/public/manifest.webmanifest`](../../frontend/public/manifest.webmanifest)
  defines installable application metadata.
- [`frontend/public/sw.js`](../../frontend/public/sw.js) implements the
  static-only cache policy.
- [`frontend/src/main.tsx`](../../frontend/src/main.tsx) registers the service
  worker.
- [`frontend/src/lib/device-data.ts`](../../frontend/src/lib/device-data.ts)
  clears browser-side application data.
- [`frontend/tests/service-worker-policy.test.ts`](../../frontend/tests/service-worker-policy.test.ts)
  checks the cache exclusions and manifest.
- [`frontend/e2e/pwa.spec.ts`](../../frontend/e2e/pwa.spec.ts) exercises PWA
  behavior.
- [`frontend/e2e/a11y.spec.ts`](../../frontend/e2e/a11y.spec.ts) and
  [`frontend/e2e/critical-path.spec.ts`](../../frontend/e2e/critical-path.spec.ts)
  exercise accessibility and responsive user paths.

## Revisit when

- Users require offline access with an explicit encryption, synchronization,
  conflict, deletion, and recovery design.
- A native-only capability becomes essential to the execution loop.
- Device testing shows the PWA cannot meet supported phone requirements.
- Separate native clients have clear maintainers and sustainable release
  processes.
