import { useState } from "react";
import { CheckCircle, Eye, EyeOff, Key, Loader2, XCircle } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAppStore } from "@/stores/app";

function mask(value: string): string {
  if (!value) return "";
  if (value.length < 20) return "*".repeat(value.length);
  return `${value.slice(0, 4)}${"*".repeat(value.length - 8)}${value.slice(-4)}`;
}

function ApiKeySettings() {
  const apiKey = useAppStore((state) => state.apiKey);
  const setApiKey = useAppStore((state) => state.setApiKey);

  const [apiKeyInput, setApiKeyInput] = useState(apiKey);
  const [revealApiKey, setRevealApiKey] = useState(false);

  const testMutation = useMutation({
    mutationFn: () => api.get("/dashboard/stats"),
    onSuccess: () => toast.success("Connection successful"),
    onError: () => toast.error("Connection test failed"),
  });

  const testResult = testMutation.isSuccess ? "success" : testMutation.isError ? "error" : null;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">Access Credentials</h3>
        <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">
          Local development only. Production browser sessions use secure same-origin cookies.
        </p>
      </div>

      <CredentialCard
        icon={Key}
        title="API Key"
        description="Legacy internal credential sent as X-API-Key."
        active={apiKey.length > 0}
        revealed={revealApiKey}
        onToggleReveal={() => setRevealApiKey((value) => !value)}
        value={apiKey}
        inputValue={apiKeyInput}
        onInputChange={setApiKeyInput}
        onSave={() => {
          setApiKey(apiKeyInput);
          testMutation.reset();
          toast.success("API key saved");
        }}
      />

      <Card padding="lg">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-sm font-medium text-[var(--color-fg-primary)]">
              Connection Test
            </div>
            <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">
              Verifies whichever credential is currently configured against an authenticated
              dashboard endpoint.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {testResult === "success" ? (
              <CheckCircle className="h-4 w-4 text-[var(--color-success-500)]" />
            ) : null}
            {testResult === "error" ? (
              <XCircle className="h-4 w-4 text-[var(--color-error-500)]" />
            ) : null}
            <Button
              variant="outline"
              disabled={testMutation.isPending || !apiKey}
              onClick={() => testMutation.mutate()}
            >
              {testMutation.isPending ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Testing...
                </>
              ) : (
                "Test Connection"
              )}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

function CredentialCard({
  icon: Icon,
  title,
  description,
  active,
  revealed,
  onToggleReveal,
  value,
  inputValue,
  onInputChange,
  onSave,
}: {
  icon: typeof Key;
  title: string;
  description: string;
  active: boolean;
  revealed: boolean;
  onToggleReveal: () => void;
  value: string;
  inputValue: string;
  onInputChange: (value: string) => void;
  onSave: () => void;
}) {
  return (
    <Card padding="lg" className="gap-4">
      <div className="flex items-center gap-3">
        <Icon className="h-5 w-5 text-[var(--color-fg-secondary)]" />
        <div>
          <div className="text-sm font-medium text-[var(--color-fg-primary)]">{title}</div>
          <p className="text-xs text-[var(--color-fg-tertiary)]">{description}</p>
        </div>
        <Badge size="sm" variant={active ? "success" : "default"}>
          {active ? "Active" : "Not set"}
        </Badge>
      </div>

      {active ? (
        <div className="flex items-center gap-2">
          <code className="flex-1 rounded-[var(--radius-md)] bg-[var(--color-bg-base)] px-3 py-2 text-xs font-mono text-[var(--color-fg-secondary)]">
            {revealed ? value : mask(value)}
          </code>
          <Button
            variant="ghost"
            size="icon"
            onClick={onToggleReveal}
            aria-label={`${revealed ? "Hide" : "Reveal"} ${title}`}
          >
            {revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </Button>
        </div>
      ) : null}

      <div className="flex gap-2">
        <Input
          type="password"
          value={inputValue}
          onChange={(event) => onInputChange(event.target.value)}
          placeholder={`Paste ${title.toLowerCase()}...`}
        />
        <Button disabled={inputValue.length === 0 || inputValue === value} onClick={onSave}>
          Save
        </Button>
      </div>
    </Card>
  );
}

export { ApiKeySettings };
