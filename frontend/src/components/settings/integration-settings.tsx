import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Brain,
  Calendar,
  CheckCircle,
  Database,
  Link2,
  Loader2,
  Mail,
  Search,
  Sparkles,
  Trash2,
  XCircle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { toast } from "sonner";
import {
  deleteConnectorAccount,
  listConnectorAccounts,
  listConnectorDocuments,
  listConnectorSyncJobs,
  startGoogleOAuth,
  syncConnectorAccount,
  updateConnectorAccount,
} from "@/api/connectors";
import { api } from "@/api/client";
import { getHealth } from "@/api/monitoring";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { ConnectorAccount, ConnectorSyncJob, HealthServiceState } from "@/types";

interface IntegrationConfig {
  key: string;
  healthKey?: string;
  label: string;
  description: string;
  icon: LucideIcon;
}

const connectorConfigs: IntegrationConfig[] = [
  {
    key: "gmail",
    label: "Gmail",
    description: "Read-only email search, sync, and cited retrieval.",
    icon: Mail,
  },
  {
    key: "google_calendar",
    label: "Google Calendar",
    description: "Read-only calendar events, free-slot detection, and event memory.",
    icon: Calendar,
  },
  {
    key: "google_drive",
    label: "Google Drive",
    description: "Docs, Sheets, Slides, and source-pack ingestion.",
    icon: Database,
  },
];

const serviceConfigs: IntegrationConfig[] = [
  {
    key: "anthropic",
    healthKey: "llm",
    label: "Anthropic",
    description: "Primary reasoning models for agent execution.",
    icon: Sparkles,
  },
  {
    key: "ollama",
    label: "Ollama",
    description: "Local embeddings and offline vector tooling.",
    icon: Brain,
  },
  {
    key: "tavily",
    label: "Tavily",
    description: "Research search and optional proactive background scans.",
    icon: Search,
  },
  {
    key: "posthog",
    label: "PostHog",
    description: "Product analytics and LLM observability.",
    icon: Activity,
  },
  {
    key: "sentry",
    label: "Sentry",
    description: "Error tracking and runtime traces.",
    icon: Activity,
  },
];

function IntegrationSettings() {
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: () => getHealth(),
  });
  const accountsQuery = useQuery({
    queryKey: ["connector-accounts"],
    queryFn: () => listConnectorAccounts(),
  });
  const syncJobsQuery = useQuery({
    queryKey: ["connector-sync-jobs"],
    queryFn: () => listConnectorSyncJobs(),
  });
  const documentsQuery = useQuery({
    queryKey: ["connector-documents"],
    queryFn: () => listConnectorDocuments({ limit: 200 }),
  });

  const accounts = accountsQuery.data ?? [];
  const syncJobs = syncJobsQuery.data ?? [];
  const documents = documentsQuery.data?.items ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">Connectors</h3>
        <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">
          Persisted connector accounts control sync, auto-use, and proactive access.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4">
        {connectorConfigs.map((config) => {
          const account = accounts.find((item) => item.connector_type === config.key);
          const latestJob = syncJobs.find((job) => job.account_id === account?.id);
          const documentCount = documents.filter((doc) => doc.account_id === account?.id).length;
          return (
            <ConnectorCard
              key={config.key}
              config={config}
              account={account}
              latestJob={latestJob}
              documentCount={documentCount}
            />
          );
        })}
      </div>

      <div>
        <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">Platform Services</h3>
        <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">
          Runtime services still expose health checks and connection tests.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4">
        {serviceConfigs.map((config) => {
          const service = healthQuery.data?.services[config.healthKey ?? config.key];
          return (
            <ServiceCard
              key={config.key}
              config={config}
              status={service?.status ?? "unknown"}
              message={service?.message}
            />
          );
        })}
      </div>
    </div>
  );
}

function ConnectorCard({
  config,
  account,
  latestJob,
  documentCount,
}: {
  config: IntegrationConfig;
  account?: ConnectorAccount;
  latestJob?: ConnectorSyncJob;
  documentCount: number;
}) {
  const Icon = config.icon;
  const queryClient = useQueryClient();
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [disconnectError, setDisconnectError] = useState<string | null>(null);

  const connectMutation = useMutation({
    mutationFn: async () => {
      const response = await startGoogleOAuth(config.key);
      window.location.assign(response.auth_url);
      return {
        id: account?.id ?? config.key,
        status: "redirecting",
      } as ConnectorAccount;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connector-accounts"] });
      toast.success(`${config.label} connected`);
    },
    onError: (error) => {
      toast.error(`Unable to update ${config.label}`, {
        description: error instanceof Error ? error.message : "Unknown error",
      });
    },
  });

  const pauseMutation = useMutation({
    mutationFn: async () => {
      if (!account) {
        throw new Error("Connect this service first");
      }
      return updateConnectorAccount(account.id, {
        sync_enabled: !account.sync_enabled,
      });
    },
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["connector-accounts"] });
      toast.success(
        updated.sync_enabled ? `${config.label} sync resumed` : `${config.label} sync paused`,
      );
    },
    onError: (error) => {
      toast.error(`Unable to update ${config.label} sync`, {
        description: error instanceof Error ? error.message : "Unknown error",
      });
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: async () => {
      if (!account) {
        throw new Error("Connector account no longer exists");
      }
      return deleteConnectorAccount(account.id);
    },
    onSuccess: () => {
      setDisconnectOpen(false);
      setDisconnectError(null);
      queryClient.invalidateQueries({ queryKey: ["connector-accounts"] });
      queryClient.invalidateQueries({ queryKey: ["connector-sync-jobs"] });
      queryClient.invalidateQueries({ queryKey: ["connector-documents"] });
      toast.success(`${config.label} disconnected and local data deleted`);
    },
    onError: (error) => {
      const reason = error instanceof Error ? error.message : "Provider revocation failed";
      setDisconnectError(reason);
      toast.error(`${config.label} was not disconnected`, {
        description:
          "Nothing was deleted. Retry, or revoke access in the provider account before requesting a verified local purge from the installation administrator.",
      });
    },
  });

  const toggleMutation = useMutation({
    mutationFn: async (data: {
      auto_use?: boolean;
      background_access?: boolean;
      sync_enabled?: boolean;
    }) => {
      if (!account) {
        throw new Error("Connect this service first");
      }
      return updateConnectorAccount(account.id, data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connector-accounts"] });
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Update failed");
    },
  });

  const syncMutation = useMutation({
    mutationFn: async (syncType: "incremental" | "reindex") => {
      if (!account) {
        throw new Error("Connect this service first");
      }
      return syncConnectorAccount(account.id, {
        sync_type: syncType === "reindex" ? "full" : "incremental",
        max_items: syncType === "reindex" ? 100 : 25,
      });
    },
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: ["connector-sync-jobs"] });
      queryClient.invalidateQueries({ queryKey: ["connector-documents"] });
      queryClient.invalidateQueries({ queryKey: ["connector-accounts"] });
      if (job.status === "failed") {
        toast.error(`${config.label} sync failed`, {
          description: job.error_message ?? "Unknown error",
        });
        return;
      }
      toast.success(`${config.label} synced`, {
        description: `${job.document_count} documents indexed`,
      });
    },
    onError: (error) => {
      toast.error(`${config.label} sync failed`, {
        description: error instanceof Error ? error.message : "Unknown error",
      });
    },
  });

  return (
    <Card padding="lg" className="gap-4">
      <div className="flex items-start gap-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--color-bg-overlay)]">
          <Icon className="h-5 w-5 text-[var(--color-fg-secondary)]" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-[var(--color-fg-primary)]">
              {config.label}
            </span>
            <Badge
              size="sm"
              variant={
                account?.status === "connected"
                  ? "success"
                  : account?.status === "error"
                    ? "error"
                    : "default"
              }
            >
              {account?.status ?? "not_connected"}
            </Badge>
            {account?.sync_enabled ? <Badge size="sm">sync on</Badge> : null}
            {account?.has_refresh_token ? <Badge size="sm">token vaulted</Badge> : null}
          </div>
          <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">{config.description}</p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <Badge size="sm" variant="default">
              {documentCount} docs
            </Badge>
            <Badge size="sm" variant="default">
              auto-use {account?.auto_use ? "on" : "off"}
            </Badge>
            <Badge size="sm" variant="default">
              background {account?.background_access ? "on" : "off"}
            </Badge>
            {account?.last_sync_at ? (
              <Badge size="sm" variant="default">
                last sync {new Date(account.last_sync_at).toLocaleDateString("en-GB")}
              </Badge>
            ) : null}
            {latestJob ? (
              <Badge
                size="sm"
                variant={
                  latestJob.status === "failed"
                    ? "error"
                    : latestJob.status === "completed"
                      ? "success"
                      : "warning"
                }
              >
                {latestJob.sync_type} {latestJob.status}
              </Badge>
            ) : null}
          </div>
          {latestJob?.error_message ? (
            <p className="mt-2 text-xs text-[var(--color-error-500)]">{latestJob.error_message}</p>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {account?.status === "connected" ? (
          <Button
            size="sm"
            variant="outline"
            loading={pauseMutation.isPending}
            onClick={() => pauseMutation.mutate()}
          >
            {account.sync_enabled ? "Pause sync" : "Resume sync"}
          </Button>
        ) : (
          <Button
            size="sm"
            variant="default"
            loading={connectMutation.isPending}
            onClick={() => connectMutation.mutate()}
          >
            <Link2 className="h-3.5 w-3.5" />
            Connect
          </Button>
        )}
        <Button
          size="sm"
          variant="outline"
          disabled={!account}
          loading={syncMutation.isPending && syncMutation.variables === "incremental"}
          onClick={() => syncMutation.mutate("incremental")}
        >
          Sync now
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={!account}
          loading={syncMutation.isPending && syncMutation.variables === "reindex"}
          onClick={() => syncMutation.mutate("reindex")}
        >
          Reindex
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={!account}
          loading={toggleMutation.isPending}
          onClick={() => toggleMutation.mutate({ auto_use: !account?.auto_use })}
        >
          Auto-use {account?.auto_use ? "off" : "on"}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={!account}
          loading={toggleMutation.isPending}
          onClick={() => toggleMutation.mutate({ background_access: !account?.background_access })}
        >
          Background {account?.background_access ? "off" : "on"}
        </Button>
        {account ? (
          <Button
            size="sm"
            variant="destructive"
            onClick={() => {
              setDisconnectError(null);
              setDisconnectOpen(true);
            }}
          >
            <Trash2 className="h-3.5 w-3.5" />
            Disconnect and delete local data
          </Button>
        ) : null}
      </div>

      <Dialog.Root
        open={disconnectOpen}
        onOpenChange={(open) => {
          if (!disconnectMutation.isPending) {
            setDisconnectOpen(open);
            if (!open) setDisconnectError(null);
          }
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60" />
          <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-[var(--radius-xl)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-6 shadow-2xl focus:outline-none">
            <Dialog.Title className="text-base font-semibold text-[var(--color-fg-primary)]">
              Disconnect {config.label}?
            </Dialog.Title>
            <Dialog.Description className="mt-2 text-sm text-[var(--color-fg-secondary)]">
              This revokes provider access and permanently deletes this connector&apos;s local
              documents, sync history, jobs, and stored token. This cannot be undone.
            </Dialog.Description>
            {disconnectError ? (
              <div
                role="alert"
                className="mt-4 rounded-[var(--radius-md)] border border-[var(--color-error-500)]/40 bg-[var(--color-error-500)]/10 p-3 text-xs text-[var(--color-fg-secondary)]"
              >
                <p className="font-medium text-[var(--color-error-500)]">
                  Disconnect did not complete
                </p>
                <p className="mt-1">{disconnectError}</p>
                <p className="mt-2">
                  Nothing was deleted. Retry first. If the provider remains unavailable, revoke
                  Execution OS in the provider account, then ask the installation administrator for
                  a verified local purge.
                </p>
              </div>
            ) : null}
            <div className="mt-6 flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={disconnectMutation.isPending}
                onClick={() => setDisconnectOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="destructive"
                loading={disconnectMutation.isPending}
                onClick={() => disconnectMutation.mutate()}
              >
                Disconnect and permanently delete
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </Card>
  );
}

function ServiceCard({
  config,
  status,
  message,
}: {
  config: IntegrationConfig;
  status: HealthServiceState;
  message?: string;
}) {
  const Icon = config.icon;
  const statusVariant =
    status === "ok"
      ? "success"
      : status === "degraded" || status === "lagging"
        ? "warning"
        : status === "down"
          ? "error"
          : "default";

  const testMutation = useMutation({
    mutationFn: () => api.post<{ status: string }>(`/settings/integrations/${config.key}/test`),
    onSuccess: () => {
      toast.success(`${config.label} connection successful`);
    },
    onError: (error) => {
      toast.error(`${config.label} connection failed`, {
        description: error instanceof Error ? error.message : "Unknown error",
      });
    },
  });

  return (
    <Card padding="lg" className="flex items-start gap-4">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--color-bg-overlay)]">
        <Icon className="h-5 w-5 text-[var(--color-fg-secondary)]" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-[var(--color-fg-primary)]">
            {config.label}
          </span>
          <Badge size="sm" variant={statusVariant}>
            {status}
          </Badge>
        </div>
        <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">{config.description}</p>
        {message ? (
          <p className="mt-2 text-xs text-[var(--color-fg-secondary)]">{message}</p>
        ) : null}
      </div>
      <div className="flex items-center gap-2">
        {testMutation.isSuccess ? (
          <CheckCircle className="h-4 w-4 text-[var(--color-success-500)]" />
        ) : null}
        {testMutation.isError ? (
          <XCircle className="h-4 w-4 text-[var(--color-error-500)]" />
        ) : null}
        <Button
          size="sm"
          variant="outline"
          disabled={testMutation.isPending}
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
    </Card>
  );
}

export { IntegrationSettings };
