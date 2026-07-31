# Integration data guide

Personal Execution OS runs locally by default. Its optional integrations can
send data to third parties. This guide explains what each integration receives
and how to turn it off.

Adding an API key means accepting that provider's terms, retention policy, and
account settings. Those policies can change. Check the linked provider
documentation before using an integration with sensitive material.

## Local copies

Connector syncs create local copies in PostgreSQL and the application data
volume. Revoking a provider token stops future access but does not remove those
local records. Disconnect a connector in Settings to revoke its token and purge
its connector records. To remove all application data, stop the stack and
delete its Docker volumes as described in [SETUP.md](SETUP.md).

Browser data is separate. Use **Clear this device** in Settings on every browser
that has used the application.

## Provider summary

| Provider         | What is sent                                                 | Why                                       | Default |
| ---------------- | ------------------------------------------------------------ | ----------------------------------------- | ------- |
| Anthropic        | Prompts, selected context, and model parameters              | Optional model-backed chat and analysis   | Off     |
| Google Workspace | OAuth credentials and Google API requests                    | Read-only Calendar, Gmail, and Drive sync | Off     |
| Telegram         | Messages, attachments, chat metadata, and delivery requests  | Optional bot capture and notifications    | Off     |
| Tavily           | Search queries and search options                            | Optional web research                     | Off     |
| Sentry           | Errors and configured diagnostic context                     | Optional error monitoring                 | Off     |
| PostHog          | Pseudonymous product events and configured properties        | Optional local-install analytics          | Off     |
| OpenTelemetry    | Traces, metrics, and configured attributes                   | Optional operator observability           | Off     |
| Web Push         | Push subscription details and a generic notification payload | Optional browser notifications            | Off     |

## Configuration checklist

Configure one provider at a time with disposable data. Put values in the
private root `.env`, run `docker compose up --build --detach --wait`, and use
**Settings → Integrations** or the relevant feature page to test it. A key being
accepted proves connectivity, not an approved privacy or cost policy.

| Feature               | Required private values                                                                              | Additional setup                                                                              |
| --------------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Anthropic models      | `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`                                                        | Create a dedicated key and set a project spending limit in the provider console.              |
| Local embeddings      | `OLLAMA_HOST`, optional `OLLAMA_EMBED_MODEL`                                                         | Run Ollama on the Docker host and pull the configured embedding model.                        |
| Google read-only sync | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URL`                              | Enable Calendar, Gmail, and Drive APIs; create a Web OAuth client; connect from Settings.     |
| Telegram              | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS`, `TELEGRAM_WEBHOOK_URL`, `TELEGRAM_WEBHOOK_SECRET` | Requires an externally reachable HTTPS webhook; startup registers the configured URL.         |
| Tavily research       | `TAVILY_API_KEY`                                                                                     | Create a dedicated key and review plan or pay-as-you-go limits.                               |
| Browser push          | `WEB_PUSH_PUBLIC_KEY`, `WEB_PUSH_PRIVATE_KEY`, `WEB_PUSH_SUBJECT`                                    | Supply a VAPID key pair and subscribe each browser from Settings.                             |
| Sentry                | `SENTRY_DSN`, keep `SENTRY_SEND_DEFAULT_PII=false`                                                   | Use a dedicated project and review event scrubbing and retention.                             |
| PostHog               | `POSTHOG_API_KEY`, `POSTHOG_HOST`                                                                    | Use a dedicated project and review captured properties and retention.                         |
| OpenTelemetry         | `OTEL_ENABLED=true`, `OTEL_EXPORTER_OTLP_ENDPOINT`, optional headers                                 | Approve the collector and keep `OTEL_EXPORT_CONTENT=false` unless content export is intended. |

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
and Drive. It sends OAuth credentials and ordinary Google API requests. Synced
calendar and email records are stored locally. Drive sync can read file
metadata and supported Docs, Sheets, Slides, or file content, then store
searchable source-pack copies in PostgreSQL.

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

Disconnecting Google in Settings attempts to revoke the provider token, then
purges the locally stored token and connector data. If Google is unavailable,
verify revocation in your Google Account before treating access as closed.

- [Google Workspace API user data policy](https://developers.google.com/workspace/workspace-api-user-data-developer-policy)
- [OAuth security practices](https://developers.google.com/identity/protocols/oauth2/resources/best-practices)
- [Gmail OAuth flow](https://developers.google.com/workspace/gmail/api/auth/web-server)
- [Gmail OAuth scope classifications](https://developers.google.com/workspace/gmail/api/auth/scopes)
- [Drive OAuth scope classifications](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)

Remove all `GOOGLE_*` values and `CONNECTOR_TOKEN_ENCRYPTION_KEY` from `.env`
after disconnecting if the integration will not be used again.

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
header are rejected. Do not expose the webhook from an uninitialized
installation.

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

PostHog is disabled when `POSTHOG_API_KEY` is blank. If enabled, the application
sends product events under an installation-scoped pseudonymous identifier. It
does not need an email address or display name. Event retention depends on the
PostHog deployment and plan.

- [PostHog privacy policy](https://posthog.com/privacy)
- [PostHog data collection controls](https://posthog.com/docs/privacy/data-collection)

Remove `POSTHOG_API_KEY` and `POSTHOG_HOST`, restart the stack, and delete the
PostHog project or events when they are no longer required.

## OpenTelemetry

OpenTelemetry is disabled unless an exporter endpoint is configured. The
operator controls that destination. Traces and metrics can contain route names,
timings, identifiers, and other attributes added by instrumentation.

Content export is separately controlled by `OTEL_EXPORT_CONTENT` and is off by
default. Keep it off unless the telemetry destination is approved to receive
application content.

- [OpenTelemetry guidance for sensitive data](https://opentelemetry.io/docs/security/handling-sensitive-data/)
- [OTLP exporter specification](https://opentelemetry.io/docs/specs/otel/protocol/exporter/)

Remove the `OTEL_*` values and restart the stack to disable export. Delete data
at the configured telemetry destination separately.

## Web Push

Web Push stores a browser subscription locally and sends a generic notification
payload through the browser vendor's push service. The push service can observe
delivery metadata even when payload content is encrypted.

- [W3C Push API](https://www.w3.org/TR/push-api/)

Unsubscribe in Settings before removing `WEB_PUSH_PUBLIC_KEY`,
`WEB_PUSH_PRIVATE_KEY`, and `WEB_PUSH_SUBJECT`. Restart the stack after changing
the keys. Use **Clear this device** to remove the browser-side subscription and
cached local data.
