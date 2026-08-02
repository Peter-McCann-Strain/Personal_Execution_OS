# ADR-0009: Use revocable server-side browser sessions with CSRF protection

- **Status:** Accepted (retrospective)
- **Date:** 2026-07-31

## Context

The supported product has one local owner and no hosted identity or email
recovery service. The browser needs convenient same-origin authentication
without storing a durable API credential in JavaScript-accessible storage.
The owner must be able to change the password and revoke sessions immediately.

Cookie authentication also creates a cross-site request-forgery boundary that
the application must handle.

## Decision drivers

- Keep browser credentials out of local storage and application JavaScript.
- Hash the owner password with a memory-hard password function.
- Support individual logout and revoke-all behavior.
- Expire and validate sessions on the server.
- Protect unsafe cookie-authenticated requests against cross-origin submission.
- Preserve a separate server-to-server API credential path where required.

## Considered options

1. Store the backend API key or bearer token in browser storage.
2. Use long-lived stateless JWTs with no server-side revocation record.
3. Require an external identity provider for every local installation.
4. Use a local password, signed opaque cookie, server-side session record, and
   CSRF token.

## Decision

One-time local setup creates a singleton owner credential. Passwords use
Argon2id. Login creates a random session token and CSRF token; only hashes are
stored in PostgreSQL. The browser receives an HTTP-only signed session cookie
and a separate readable CSRF cookie. Unsafe requests must send the matching
CSRF value in a header and pass exact-origin validation.

Sessions expire and can be revoked. Password changes and revoke-all operations
rotate the session-signing secret and invalidate every device. API key or
equivalent bearer authentication remains available for non-browser
server-to-server access and is not the production PWA credential.

## Consequences

### Positive

- JavaScript cannot directly read the session credential cookie.
- Server records permit immediate revocation and expiry checks.
- CSRF and origin checks protect cookie-authenticated mutations.
- Password change can invalidate every existing session.

### Negative

- Authenticated requests require database session validation and last-seen
  maintenance.
- There is no email password-recovery workflow.
- Cookie security depends on correct HTTPS, origin, proxy, and host settings.
- First-run setup has no authentication until the local owner claims it.

### Neutral

- The client can read the CSRF cookie because it must copy the value to the
  request header. That cookie is not the authentication secret.
- API-key authentication has a different threat model and must not be exposed
  to the production browser build.

## Security, privacy, and operations

Remote access requires `AUTH_COOKIE_SECURE=true`, a trusted HTTPS origin, exact
host validation, and a maintained TLS access layer. An uninitialized remotely
reachable installation can be claimed by another person, so setup must be
completed before exposure.

Session records include operational IP-address and user-agent metadata and
therefore participate in privacy, retention, backup, and deletion decisions.
The proxy overwrites forwarded client-address headers instead of trusting
arbitrary browser input.

Revoking sessions does not revoke provider OAuth tokens; those are a separate
credential lifecycle.

## Verification in code and tests

- [`src/app/core/local_auth.py`](../../src/app/core/local_auth.py) implements
  password hashing, random tokens, cookie signing, and parsing.
- [`src/app/api/routes/auth.py`](../../src/app/api/routes/auth.py) implements
  setup, login, logout, password change, and revoke-all workflows.
- [`src/app/api/deps.py`](../../src/app/api/deps.py) validates signed cookies,
  server-side token hashes, expiry, origin, and CSRF state.
- [`src/app/persistence/models.py`](../../src/app/persistence/models.py) defines
  `LocalOwnerCredential` and `LocalAuthSession`.
- [`frontend/src/api/auth.ts`](../../frontend/src/api/auth.ts) and
  [`frontend/src/components/auth/auth-gate.tsx`](../../frontend/src/components/auth/auth-gate.tsx)
  implement the browser-side session flow.
- [`tests/unit/api/test_auth.py`](../../tests/unit/api/test_auth.py) checks
  setup, session cookies, CSRF, cross-origin rejection, rate limiting,
  password change, and revocation.
- [`frontend/tests/components/auth/auth-gate.test.tsx`](../../frontend/tests/components/auth/auth-gate.test.tsx)
  checks browser setup and authentication routing.
- [`tests/unit/test_self_hosted_compose.py`](../../tests/unit/test_self_hosted_compose.py)
  checks proxy host and forwarded-address controls.

## Revisit when

- The supported product becomes multi-user or needs delegated identity.
- Operators need a separately secured password-reset or recovery mechanism.
- Session volume makes per-request database validation impractical.
- A native client requires a different public authentication protocol.
- An external identity provider becomes optional without weakening the local
  owner path.
