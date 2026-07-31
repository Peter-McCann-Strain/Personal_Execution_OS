import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import {
  AlertCircle,
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  ShieldCheck,
} from "lucide-react";
import { getSetupStatus, initializeOwner } from "@/api/auth";
import { ApiError, api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { defaultAppPath, isLegacyDevAuthEnabled, safeReturnTo } from "@/lib/auth-mode";
import { useAppStore } from "@/stores/app";

// The endpoint we hit to validate a freshly-pasted key. It is auth-required
// and returns 401 on bad credentials, 200 on good ones, so it gives us a
// clean signal without performing any side-effects.
const VALIDATION_PATH = "/dashboard/stats";
const API_KEY_STORAGE_KEY = ["api", "key"].join("_");

function LegacyApiKeySetupPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const setApiKey = useAppStore((s) => s.setApiKey);

  const [keyInput, setKeyInput] = useState("");
  const [reveal, setReveal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [success, setSuccess] = useState(false);

  const returnToParam = searchParams.get("returnTo");
  const returnTo = safeReturnTo(returnToParam, defaultAppPath);

  // If the user lands on /setup but already has a working key in
  // sessionStorage, don't strand them here — bounce to the destination.
  useEffect(() => {
    const existing = sessionStorage.getItem(API_KEY_STORAGE_KEY);
    if (existing) {
      navigate(returnTo, { replace: true });
    }
  }, [navigate, returnTo]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = keyInput.trim();
    if (!trimmed) {
      setErrorStatus(null);
      setErrorMessage("Paste your API key first.");
      return;
    }

    setSubmitting(true);
    setErrorMessage(null);
    setErrorStatus(null);
    setSuccess(false);

    // Stash the key briefly so the api client picks it up for the probe.
    // If the probe fails we restore the previous value to keep the
    // session unchanged.
    const previousKey = sessionStorage.getItem(API_KEY_STORAGE_KEY);
    sessionStorage.setItem(API_KEY_STORAGE_KEY, trimmed);

    try {
      await api.get(VALIDATION_PATH);
      // Persist via the store so React state stays in sync.
      setApiKey(trimmed);
      setSuccess(true);
      navigate(returnTo, { replace: true });
    } catch (err) {
      // Restore whatever was there (or remove the bad key) so subsequent
      // /api/* requests don't keep echoing 401s.
      if (previousKey === null) {
        sessionStorage.removeItem(API_KEY_STORAGE_KEY);
      } else {
        sessionStorage.setItem(API_KEY_STORAGE_KEY, previousKey);
      }

      if (err instanceof ApiError) {
        setErrorStatus(err.status);
        if (err.status === 401) {
          setErrorMessage(
            "That key was rejected by the API. Double-check the value of CHAT_API_KEY in your backend .env.",
          );
        } else if (err.status === 0) {
          setErrorMessage("Could not reach the API. Is the backend running?");
        } else {
          setErrorMessage(err.message || `Validation failed (HTTP ${err.status}).`);
        }
      } else {
        setErrorStatus(null);
        setErrorMessage(err instanceof Error ? err.message : "Validation failed.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-[var(--color-bg-base)] px-4 py-12">
      <Card padding="lg" className="flex w-full max-w-md flex-col gap-6">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--color-bg-overlay)]">
            <KeyRound className="h-5 w-5 text-[var(--color-fg-secondary)]" />
          </div>
          <div className="flex flex-col gap-1">
            <h1 className="text-base font-semibold text-[var(--color-fg-primary)]">
              Connect your workspace
            </h1>
            <p className="text-xs text-[var(--color-fg-tertiary)]">
              Paste the API key the backend is expecting so this dashboard can talk to it.
            </p>
          </div>
        </div>

        <div className="rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-overlay)] p-3 text-xs text-[var(--color-fg-tertiary)]">
          The key is the value of{" "}
          <code className="rounded bg-[var(--color-bg-base)] px-1 py-0.5 font-mono text-[var(--color-fg-secondary)]">
            CHAT_API_KEY
          </code>{" "}
          in your backend{" "}
          <code className="rounded bg-[var(--color-bg-base)] px-1 py-0.5 font-mono text-[var(--color-fg-secondary)]">
            .env
          </code>{" "}
          file. It is stored in this browser tab only (sessionStorage) and never sent anywhere
          except to your own API.
        </div>

        <form className="flex flex-col gap-3" onSubmit={handleSubmit} noValidate>
          <label
            htmlFor="api-key-input"
            className="text-xs font-medium text-[var(--color-fg-secondary)]"
          >
            API key
          </label>
          <div className="flex gap-2">
            <Input
              id="api-key-input"
              type={reveal ? "text" : "password"}
              autoComplete="off"
              autoFocus
              spellCheck={false}
              value={keyInput}
              onChange={(event) => setKeyInput(event.target.value)}
              placeholder="Paste CHAT_API_KEY..."
              error={errorMessage !== null}
              aria-invalid={errorMessage !== null}
              aria-describedby={errorMessage ? "api-key-error" : undefined}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => setReveal((value) => !value)}
              aria-label={reveal ? "Hide API key" : "Reveal API key"}
            >
              {reveal ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </Button>
          </div>

          {errorMessage ? (
            <div
              id="api-key-error"
              role="alert"
              className="flex items-start gap-2 rounded-[var(--radius-md)] border border-[var(--color-error-500)]/40 bg-[var(--color-error-500)]/10 p-3 text-xs text-[var(--color-error-500)]"
            >
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <div className="flex flex-col gap-0.5">
                {errorStatus !== null ? (
                  <span className="font-medium">HTTP {errorStatus}</span>
                ) : null}
                <span>{errorMessage}</span>
              </div>
            </div>
          ) : null}

          {success ? (
            <div
              role="status"
              className="flex items-center gap-2 rounded-[var(--radius-md)] border border-[var(--color-success-500)]/40 bg-[var(--color-success-500)]/10 p-3 text-xs text-[var(--color-success-500)]"
            >
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <span>Key accepted — redirecting...</span>
            </div>
          ) : null}

          <Button type="submit" disabled={submitting || keyInput.trim().length === 0}>
            {submitting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Validating...
              </>
            ) : (
              "Save and continue"
            )}
          </Button>
        </form>

        <p className="text-[11px] text-[var(--color-fg-tertiary)]">
          Need to update an existing key later? Open{" "}
          <a className="underline" href="/settings">
            Settings → API Keys
          </a>
          .
        </p>
      </Card>
    </div>
  );
}

function ServerSetupPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [reveal, setReveal] = useState(false);
  const [checkingSetup, setCheckingSetup] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const returnTo = safeReturnTo(searchParams.get("returnTo"), defaultAppPath);

  useEffect(() => {
    let active = true;
    getSetupStatus()
      .then((status) => {
        if (active && status.initialized) {
          navigate(`/login?returnTo=${encodeURIComponent(returnTo)}`, { replace: true });
        }
      })
      .catch(() => {
        if (active) {
          setErrorMessage("Could not check setup status. Confirm the backend is running.");
        }
      })
      .finally(() => {
        if (active) setCheckingSetup(false);
      });
    return () => {
      active = false;
    };
  }, [navigate, returnTo]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password.length < 12) {
      setErrorMessage("Use at least 12 characters.");
      return;
    }
    if (password !== confirmation) {
      setErrorMessage("The passwords do not match.");
      return;
    }
    setSubmitting(true);
    setErrorMessage(null);
    try {
      await initializeOwner(password);
      navigate(returnTo, { replace: true });
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setErrorMessage("Setup is already complete. Go to sign in.");
      } else {
        setErrorMessage(error instanceof Error ? error.message : "Setup failed. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-[var(--color-bg-base)] px-4 py-12">
      <Card padding="lg" className="flex w-full max-w-md flex-col gap-5">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--color-bg-overlay)]">
            <ShieldCheck className="h-5 w-5 text-[var(--color-fg-secondary)]" />
          </div>
          <div className="flex flex-col gap-1">
            <h1 className="text-base font-semibold text-[var(--color-fg-primary)]">
              Create the owner account
            </h1>
            <p className="text-sm text-[var(--color-fg-secondary)]">
              This one-time setup creates the password for this self-hosted installation.
            </p>
          </div>
        </div>

        <form className="flex flex-col gap-3" onSubmit={handleSubmit} noValidate>
          <label
            htmlFor="setup-password"
            className="text-xs font-medium text-[var(--color-fg-secondary)]"
          >
            Owner password
          </label>
          <div className="flex gap-2">
            <Input
              id="setup-password"
              type={reveal ? "text" : "password"}
              autoComplete="new-password"
              autoFocus
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              aria-describedby="password-requirements"
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => setReveal((value) => !value)}
              aria-label={reveal ? "Hide passwords" : "Reveal passwords"}
            >
              {reveal ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </Button>
          </div>
          <p id="password-requirements" className="text-xs text-[var(--color-fg-tertiary)]">
            At least 12 characters. Use a unique password stored in your password manager.
          </p>

          <label
            htmlFor="setup-password-confirmation"
            className="text-xs font-medium text-[var(--color-fg-secondary)]"
          >
            Confirm password
          </label>
          <Input
            id="setup-password-confirmation"
            type={reveal ? "text" : "password"}
            autoComplete="new-password"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            error={errorMessage !== null}
            aria-invalid={errorMessage !== null}
            aria-describedby={errorMessage ? "setup-error" : undefined}
          />

          {errorMessage ? (
            <div
              id="setup-error"
              role="alert"
              className="flex items-start gap-2 rounded-[var(--radius-md)] border border-[var(--color-error-500)]/40 bg-[var(--color-error-500)]/10 p-3 text-xs text-[var(--color-error-500)]"
            >
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{errorMessage}</span>
            </div>
          ) : null}

          <Button
            type="submit"
            disabled={
              checkingSetup || submitting || password.length < 12 || confirmation.length === 0
            }
          >
            {checkingSetup || submitting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {checkingSetup ? "Checking server..." : "Creating owner..."}
              </>
            ) : (
              "Create owner and continue"
            )}
          </Button>
        </form>
      </Card>
    </div>
  );
}

function SetupPage() {
  return isLegacyDevAuthEnabled ? <LegacyApiKeySetupPage /> : <ServerSetupPage />;
}

export { SetupPage };
