# Integration data guide

Personal Execution OS runs locally by default. Its optional integrations can
send data to third parties. This guide explains what each integration receives
and how to turn it off.

When you add an API key, the provider's terms, retention policy, and account
settings apply. Those policies can change, so check the linked provider
documentation before sending sensitive material.

Provider-policy links and retention claims were last reviewed on 2026-07-31.
Re-check the linked primary sources before enabling a provider.

## Local copies

Connector syncs create local copies in PostgreSQL. Revoking a provider token
stops future access but does not remove those local records. A successful
disconnect in Settings revokes the token before purging its connector records.
If provider revocation fails, the endpoint returns an error and keeps the local
token and records so you can retry. Revoke access in the provider account
before treating the connection as closed. To remove all application data,
follow the retirement procedure in [SETUP.md](SETUP.md).

Browser data is separate. Use **Clear this device** in Settings on every browser
that has used the application.

## Provider summary

All external providers are off by default unless the entry says "on demand."

- **Anthropic:** prompts, selected context, and model parameters for optional
  model-backed work.
- **Google Workspace:** OAuth credentials and requests for read-only Calendar,
  Gmail, and Drive sync.
- **Telegram:** messages, attachments, chat metadata, and delivery requests
  for optional capture and notifications.
- **Tavily:** search queries and options for optional model-backed research.
- **Sentry:** errors and operator-approved diagnostic context.
- **PostHog:** configured product events. The default distinct ID is the
  literal `anonymous`; an advanced installation salt makes it pseudonymous.
- **OpenTelemetry:** spans and configured attributes sent to an
  operator-chosen collector.
- **Web Push:** subscription details and a generic encrypted notification
  payload.
- **GitHub:** quality issue text, labels, comments, and state for an explicitly
  enabled issue filer.
- **Healthchecks:** a request to the configured check URL for an optional
  worker heartbeat.
- **Supplied URL (on demand):** HTTP request and host metadata; returned page
  content is parsed locally for user-directed extraction.
- **RSS source (dormant):** feed-fetching code exists, but this release has no
  supported configuration, schedule, enqueue path, or UI.

## Configuration checklist

Configure one provider at a time and test it with disposable data. Put values
in the private root `.env`, run
`docker compose up --build --detach --wait`, then use
**Settings > Integrations** or the relevant feature page. An accepted key
proves connectivity. It says nothing about whether the privacy or cost policy
is suitable for your installation.

- **Anthropic models:** set `LLM_PROVIDER=anthropic` and
  `ANTHROPIC_API_KEY`; use a dedicated key and a provider-side spending limit.
- **Advanced embedding compatibility:** set `OLLAMA_HOST` and optionally
  `OLLAMA_EMBED_MODEL`; run Ollama on the Docker host and pull that model.
  This supports compatible query-time code and dataset curation, not a
  fresh-install record-indexing workflow.
- **Google read-only sync:** set the Google client ID, secret, redirect URL,
  and `CONNECTOR_TOKEN_ENCRYPTION_KEY`; enable the three APIs and create a Web
  OAuth client before connecting in Settings.
- **Telegram capture:** set the bot token, user allowlist, HTTPS webhook URL,
  and webhook secret, and enable Anthropic. Delivery-only worker alerts need
  the token and allowlist but not a model.
- **Tavily research:** set `TAVILY_API_KEY` and enable Anthropic; search feeds
  a model-backed synthesis path.
- **Browser push:** set the three `WEB_PUSH_*` values and subscribe each
  browser in Settings.
- **Sentry:** set `SENTRY_DSN`, keep `SENTRY_SEND_DEFAULT_PII=false`, and
  review provider-side scrubbing and retention.
- **PostHog:** set both `POSTHOG_API_KEY` and `POSTHOG_HOST`; review captured
  properties and retention.
- **OpenTelemetry:** set `OTEL_ENABLED=true`, the OTLP endpoint, and optional
  headers. Keep content export off unless it is explicitly approved.
- **GitHub issue filing:** set a token, exact repository, and
  `GITHUB_ISSUE_FILER_ENABLED=true`. Restrict a fine-grained token to that
  repository and Issues write access.
- **Worker heartbeat:** set `HEALTHCHECKS_HEARTBEAT_URL`; the destination can
  observe worker timing and the host request.

The application does not manage provider subscriptions, invoices, retention,
or account deletion. Remove credentials locally and revoke them at the provider
when an integration is retired.

## Anthropic

Set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` to enable Anthropic. The
application can send a prompt, selected workspace context, and model settings
to the Anthropic API. Leave `LLM_PROVIDER=disabled` to prevent model calls.

Anthropic states that standard API inputs and outputs are normally deleted from
its backend within 30 days, subject to policy and legal exceptions. Zero data
retention applies only when Anthropic has approved it for the relevant product
and account. Anthropic also documents how API data is treated for model
training:

- [API data retention](https://privacy.anthropic.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data)
- [Model training policy](https://privacy.anthropic.com/en/articles/7996868-is-my-data-used-for-model-training)
- [Zero data retention scope](https://privacy.anthropic.com/en/articles/8956058-i-have-a-zero-data-retention-agreement-with-anthropic-what-products-does-it-apply-to)

Remove the API key from `.env` and restart the stack to disable the
integration. Delete provider-side data through the controls available for your
Anthropic account.

## Google Workspace

Google integration uses OAuth and requests read-only access to Calendar, Gmail,
and Drive. It sends OAuth credentials and Google API requests. Synced calendar
and email records are stored locally. Drive sync can read file metadata and
supported Docs, Sheets, Slides, or file content, then store searchable
source-pack copies in PostgreSQL.

For a local install, register this exact redirect URI in the Google OAuth Web
client and set the same value in `.env`:

```dotenv
GOOGLE_OAUTH_REDIRECT_URL=http://localhost:8080/api/connectors/oauth/google/callback
```

For remote access, replace the scheme and host with the exact trusted HTTPS
origin. Enable the Calendar, Gmail, and Drive APIs in the same Google Cloud
project. The Gmail and Drive read-only scopes used here are classified by
Google as restricted scopes; external or broadly distributed OAuth clients may
require additional verification and security assessment. A personal testing
client should remain limited to explicitly approved test users.

Disconnecting Google in Settings revokes the provider token first and purges
the local token and connector records only after revocation succeeds. If
Google returns an error, the API returns `502` and keeps the local connection
so the operation can be retried. Revoke access directly in the Google account
when necessary, then retry or retire the whole local installation.

- [Google Workspace API user data policy](https://developers.google.com/workspace/workspace-api-user-data-developer-policy)
- [OAuth security practices](https://developers.google.com/identity/protocols/oauth2/resources/best-practices)
- [Gmail OAuth flow](https://developers.google.com/workspace/gmail/api/auth/web-server)
- [Gmail OAuth scope classifications](https://developers.google.com/workspace/gmail/api/auth/scopes)
- [Drive OAuth scope classifications](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)

Remove all `GOOGLE_*` values and `CONNECTOR_TOKEN_ENCRYPTION_KEY` from `.env`
after disconnecting if the integration will not be used again.

The retired `scripts/google_oauth.py` helper is not a supported path. It now
fails closed because its former write-capable scopes and terminal token output
contradicted the reviewed connector boundary.

## Telegram

The optional bot receives messages and attachments that a user sends to it.
The application may also ask Telegram to deliver replies and notifications.
Telegram receives bot and chat identifiers as part of those API calls.

Set `TELEGRAM_WEBHOOK_URL` to the externally reachable HTTPS route:

```dotenv
TELEGRAM_WEBHOOK_URL=https://assistant.example.com/webhook/telegram
```

Set `TELEGRAM_ALLOWED_USER_IDS` to the explicit numeric user IDs allowed to
interact with the bot. Startup registers the webhook with
`TELEGRAM_WEBHOOK_SECRET`; requests without the matching Telegram secret-token
header are rejected. API capture and replies initialize only when an Anthropic
model provider is also configured. The worker can initialize Telegram for
enabled notification delivery without a model, although briefings and reviews
remain model/proactive-automation dependent. Do not expose the webhook from an
uninitialized installation.

Enabling a Telegram notification or alert job gives that job standing
permission to send messages. It does not request confirmation for each event.

- [Telegram privacy policy](https://www.telegram.org/privacy)
- [Telegram Bot API documentation](https://core.telegram.org/bots)

Delete the webhook, revoke the bot token with BotFather, remove the Telegram
values from `.env`, and restart the stack to disable access. Purge locally
stored messages separately.

## Tavily

Tavily receives search queries and request options. Search results can then be
stored in local workspace records or included in a later model prompt. Tavily's
privacy policy and FAQ describe its data handling. Do not assume zero data
retention unless your account agreement says so.

- [Tavily privacy policy](https://www.tavily.com/privacy)
- [Tavily FAQ](https://docs.tavily.com/faq/faq)

Remove `TAVILY_API_KEY` and restart the stack to disable Tavily. Use Tavily's
account controls for provider-side deletion.

The supported research pipeline also requires an enabled model provider.
Supplying only the Tavily key does not make the feature ready.

## Sentry

Sentry is disabled when `SENTRY_DSN` is blank. If enabled, errors and diagnostic
context are sent to the configured Sentry project. Keep
`SENTRY_SEND_DEFAULT_PII=false`. Retention depends on the Sentry plan and
project settings.

- [Sentry privacy policy](https://sentry.io/privacy/)
- [Sentry security information](https://sentry.io/security/)

Remove `SENTRY_DSN`, restart the stack, and delete the Sentry project or its
stored events when it is no longer required.

## PostHog

PostHog is disabled unless both `POSTHOG_API_KEY` and `POSTHOG_HOST` are set. If
enabled, the application sends product events with the literal identifier
`anonymous` by default. An advanced `TELEMETRY_INSTALLATION_SALT` changes that
to a stable installation-scoped pseudonymous identifier. It does not send an
email address or display name. Event retention depends on the destination.

- [PostHog privacy policy](https://posthog.com/privacy)
- [PostHog data collection controls](https://posthog.com/docs/privacy/data-collection)

Remove `POSTHOG_API_KEY` and `POSTHOG_HOST`, restart the stack, and delete the
PostHog project or events when they are no longer required.

## OpenTelemetry

OpenTelemetry is disabled unless an exporter endpoint is configured. The
operator controls that destination. The implementation exports traces, not an
OpenTelemetry metrics pipeline. Spans can contain route names, timings,
identifiers, and other attributes added by instrumentation.

Content export is separately controlled by `OTEL_EXPORT_CONTENT` and is off by
default. Keep it off unless the telemetry destination is approved to receive
application content.

- [OpenTelemetry guidance for sensitive data](https://opentelemetry.io/docs/security/handling-sensitive-data/)
- [OTLP exporter specification](https://opentelemetry.io/docs/specs/otel/protocol/exporter/)

Remove the `OTEL_*` values and restart the stack to disable export. Delete data
at the configured telemetry destination separately.

## GitHub issue filing

The optional issue filer can create, comment on, label, and close issues for
quality signals. It is not a general-purpose GitHub tool. Setting
`GITHUB_ISSUE_FILER_ENABLED=true` with a token and exact repository gives the
worker standing permission to perform those actions. It does not ask for
confirmation before each issue.

Use a dedicated fine-grained token limited to the intended repository and the
minimum Issues permission. GitHub documents endpoint permissions in its
[fine-grained token permission reference](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens).

Disable the feature, restart the worker, revoke the token at GitHub, and review
or remove filed issues separately. Removing the local token does not delete
provider-side issues or comments.

## Healthchecks-compatible heartbeat

When `HEALTHCHECKS_HEARTBEAT_URL` is configured, the worker periodically sends
a request to that exact URL. The endpoint observes request timing and source
network metadata. Treat the full check URL as a secret because it contains the
check identifier.

Healthchecks documents its
[ping API](https://healthchecks.io/docs/http_api/) and
[privacy policy](https://healthchecks.io/privacy/). The supported heartbeat
path does not send a diagnostic body. Remove the URL and restart the worker to
disable future pings.

`HEALTHCHECKS_BACKUP_URL` exists as an inherited setting but is not used by the
supported database backup script.

## User-supplied URL fetching

The save handler can fetch a URL the user explicitly supplies. The remote
server sees a request from the installation's network and can return tracking,
malformed, or prompt-injection content.

The fetcher permits HTTP(S), rejects unsafe destination classes, checks every
redirect, and limits request time and response size. These controls reduce
server-side-request-forgery risk, but remote content remains untrusted.
Extracted text is data. It cannot change policy or authorize a provider write.

Avoid private, authenticated, one-time, or uniquely identifying URLs. There is
no provider account to revoke; remove any saved local copy through the
application and follow the remote site's deletion process if applicable.

## Dormant RSS curation code

The repository contains an RSS curation handler, but the public runtime has no
supported UI, schedule, or enqueue path for it. It is dormant code, not an
operator capability.

If a future release enables it, each feed request will disclose host network
metadata and returned content will be untrusted. The current handler uses
`feedparser` directly and does not share the supplied-URL fetcher's complete
destination validation. It must receive an SSRF review, an explicit opt-in
gate, source management, deletion behavior, and tests before promotion.

## Web Push

Web Push stores a browser subscription locally and sends a generic notification
payload through the browser vendor's push service. The push service can observe
delivery metadata even when payload content is encrypted.

- [W3C Push API](https://www.w3.org/TR/push-api/)

Unsubscribe in Settings before removing `WEB_PUSH_PUBLIC_KEY`,
`WEB_PUSH_PRIVATE_KEY`, and `WEB_PUSH_SUBJECT`. Restart the stack after changing
the keys. Use **Clear this device** to remove the browser-side subscription and
cached local data.
