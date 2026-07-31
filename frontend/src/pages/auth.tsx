import { useEffect, useState, type FormEvent } from "react";
import { AlertCircle, ArrowRight, Eye, EyeOff, KeyRound, Loader2, LogIn } from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { getSetupStatus, loginWithPassword } from "@/api/auth";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  buildSetupPath,
  defaultAppPath,
  isLegacyDevAuthEnabled,
  safeReturnTo,
} from "@/lib/auth-mode";

function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [password, setPassword] = useState("");
  const [reveal, setReveal] = useState(false);
  const [checkingSetup, setCheckingSetup] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const returnTo = safeReturnTo(
    searchParams.get("returnTo") ?? searchParams.get("redirect_url"),
    defaultAppPath,
  );

  useEffect(() => {
    let active = true;
    getSetupStatus()
      .then((status) => {
        if (active && !status.initialized) {
          navigate(buildSetupPath(returnTo), { replace: true });
        }
      })
      .catch(() => {
        if (active) {
          setErrorMessage(
            "Could not check the server setup status. Confirm the backend is running.",
          );
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
    if (!password) return;
    setSubmitting(true);
    setErrorMessage(null);
    try {
      await loginWithPassword(password);
      navigate(returnTo, { replace: true });
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        navigate(buildSetupPath(returnTo), { replace: true });
        return;
      }
      if (error instanceof ApiError && error.status === 401) {
        setErrorMessage("The password was not accepted.");
      } else if (error instanceof ApiError && error.status === 429) {
        setErrorMessage("Too many attempts. Wait a moment before trying again.");
      } else {
        setErrorMessage(
          error instanceof Error ? error.message : "Sign in failed. Please try again.",
        );
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
            <LogIn className="h-5 w-5 text-[var(--color-fg-secondary)]" />
          </div>
          <div className="flex flex-col gap-1">
            <h1 className="text-base font-semibold text-[var(--color-fg-primary)]">Sign in</h1>
            <p className="text-sm text-[var(--color-fg-secondary)]">
              Sign in to your self-hosted workspace. Your session is stored in a secure, same-origin
              cookie.
            </p>
          </div>
        </div>

        <form className="flex flex-col gap-3" onSubmit={handleSubmit} noValidate>
          <label
            htmlFor="owner-password"
            className="text-xs font-medium text-[var(--color-fg-secondary)]"
          >
            Owner password
          </label>
          <div className="flex gap-2">
            <Input
              id="owner-password"
              type={reveal ? "text" : "password"}
              autoComplete="current-password"
              autoFocus
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              error={errorMessage !== null}
              aria-invalid={errorMessage !== null}
              aria-describedby={errorMessage ? "login-error" : undefined}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => setReveal((value) => !value)}
              aria-label={reveal ? "Hide password" : "Reveal password"}
            >
              {reveal ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </Button>
          </div>

          {errorMessage ? (
            <div
              id="login-error"
              role="alert"
              className="flex items-start gap-2 rounded-[var(--radius-md)] border border-[var(--color-error-500)]/40 bg-[var(--color-error-500)]/10 p-3 text-xs text-[var(--color-error-500)]"
            >
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{errorMessage}</span>
            </div>
          ) : null}

          <Button type="submit" disabled={checkingSetup || submitting || password.length === 0}>
            {checkingSetup || submitting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                {checkingSetup ? "Checking server..." : "Signing in..."}
              </>
            ) : (
              <>
                Sign in
                <ArrowRight className="h-4 w-4" />
              </>
            )}
          </Button>
        </form>

        {isLegacyDevAuthEnabled ? (
          <Link
            to={buildSetupPath(returnTo)}
            className="inline-flex items-center justify-center gap-2 text-xs text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-secondary)]"
          >
            <KeyRound className="h-3.5 w-3.5" />
            Use a local development API key
          </Link>
        ) : null}
      </Card>
    </div>
  );
}

export { LoginPage };
