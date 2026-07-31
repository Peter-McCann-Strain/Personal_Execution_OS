import { useQuery } from "@tanstack/react-query";
import { ShieldCheck, AlertTriangle, FileText } from "lucide-react";
import {
  getAssistantNativeEvalSummary,
  getAssistantNativeMetrics,
  getPreflightReport,
  getPromptVersions,
  type PreflightCheck,
} from "@/api/monitoring";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatRelativeTime } from "@/lib/utils";

function statusVariant(
  status: "ok" | "warn" | "fail" | "skipped" | "degraded" | "down",
): "success" | "warning" | "error" | "default" {
  if (status === "ok") return "success";
  if (status === "warn" || status === "degraded") return "warning";
  if (status === "fail" || status === "down") return "error";
  return "default";
}

function ReleaseReadiness() {
  const preflight = useQuery({
    queryKey: ["preflight"],
    queryFn: () => getPreflightReport(),
    refetchInterval: 120_000,
  });

  const prompts = useQuery({
    queryKey: ["prompt-versions"],
    queryFn: () => getPromptVersions(),
    staleTime: 300_000,
  });

  const assistantNative = useQuery({
    queryKey: ["assistant-native-metrics"],
    queryFn: () => getAssistantNativeMetrics(),
    staleTime: 120_000,
  });

  const assistantNativeEval = useQuery({
    queryKey: ["assistant-native-evals"],
    queryFn: () => getAssistantNativeEvalSummary(),
    staleTime: 120_000,
  });

  const promptRecords = prompts.data ?? [];
  const versionedCount = promptRecords.filter((record) => record.prompt_version).length;
  const runtimeGovernedCount = promptRecords.filter(
    (record) =>
      record.allowed_tool_patterns.length > 0 ||
      record.confirmation_policy === "on_mutation" ||
      record.confirmation_policy === "always",
  ).length;

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-5">
        <Card>
          <div className="flex items-center gap-3">
            <ShieldCheck className="h-5 w-5 text-[var(--color-success-500)]" />
            <div>
              <p className="text-xs uppercase tracking-wide text-[var(--color-fg-tertiary)]">
                Startup Readiness
              </p>
              {preflight.isLoading ? (
                <Skeleton className="mt-2 h-7 w-20" />
              ) : preflight.data ? (
                <>
                  <div className="mt-1">
                    <Badge variant={statusVariant(preflight.data.status)} size="md">
                      {preflight.data.status}
                    </Badge>
                  </div>
                  <p className="mt-1 text-xs text-[var(--color-fg-secondary)]">
                    {formatRelativeTime(new Date(preflight.data.generated_at))}
                  </p>
                </>
              ) : (
                <p className="mt-1 text-sm text-[var(--color-error-500)]">Unavailable</p>
              )}
            </div>
          </div>
        </Card>

        <Card>
          <div className="flex items-center gap-3">
            <FileText className="h-5 w-5 text-[var(--color-info-500)]" />
            <div>
              <p className="text-xs uppercase tracking-wide text-[var(--color-fg-tertiary)]">
                Versioned Prompts
              </p>
              {prompts.isLoading ? (
                <Skeleton className="mt-2 h-7 w-24" />
              ) : (
                <>
                  <p className="text-2xl font-semibold text-[var(--color-fg-primary)]">
                    {versionedCount}
                  </p>
                  <p className="text-xs text-[var(--color-fg-secondary)]">
                    {promptRecords.length - versionedCount} runtime surfaces still unversioned
                  </p>
                </>
              )}
            </div>
          </div>
        </Card>

        <Card>
          <div className="flex items-center gap-3">
            <AlertTriangle className="h-5 w-5 text-[var(--color-warning-500)]" />
            <div>
              <p className="text-xs uppercase tracking-wide text-[var(--color-fg-tertiary)]">
                Governed Runtimes
              </p>
              {prompts.isLoading ? (
                <Skeleton className="mt-2 h-7 w-24" />
              ) : (
                <>
                  <p className="text-2xl font-semibold text-[var(--color-fg-primary)]">
                    {runtimeGovernedCount}
                  </p>
                  <p className="text-xs text-[var(--color-fg-secondary)]">
                    Agents with tool or confirmation policy boundaries
                  </p>
                </>
              )}
            </div>
          </div>
        </Card>

        <Card>
          <div className="flex items-center gap-3">
            <ShieldCheck className="h-5 w-5 text-[var(--color-info-500)]" />
            <div>
              <p className="text-xs uppercase tracking-wide text-[var(--color-fg-tertiary)]">
                Assistant Receipts
              </p>
              {assistantNative.isLoading ? (
                <Skeleton className="mt-2 h-7 w-24" />
              ) : assistantNative.data ? (
                <>
                  <p className="text-2xl font-semibold text-[var(--color-fg-primary)]">
                    {assistantNative.data.assistant_receipt_count}
                  </p>
                  <p className="text-xs text-[var(--color-fg-secondary)]">
                    from {assistantNative.data.interaction_sample_size} recent interactions
                  </p>
                </>
              ) : (
                <p className="mt-1 text-sm text-[var(--color-error-500)]">Unavailable</p>
              )}
            </div>
          </div>
        </Card>

        <Card>
          <div className="flex items-center gap-3">
            <ShieldCheck className="h-5 w-5 text-[var(--color-success-500)]" />
            <div>
              <p className="text-xs uppercase tracking-wide text-[var(--color-fg-tertiary)]">
                Continuity Replays
              </p>
              {assistantNativeEval.isLoading ? (
                <Skeleton className="mt-2 h-7 w-24" />
              ) : assistantNativeEval.data ? (
                <>
                  <p className="text-2xl font-semibold text-[var(--color-fg-primary)]">
                    {assistantNativeEval.data.pass_count}/{assistantNativeEval.data.case_count}
                  </p>
                  <p className="text-xs text-[var(--color-fg-secondary)]">
                    baseline lift {Math.round(assistantNativeEval.data.baseline_lift * 100)}%
                  </p>
                </>
              ) : (
                <p className="mt-1 text-sm text-[var(--color-error-500)]">Unavailable</p>
              )}
            </div>
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <OperationalMetricCard
          title="Continuity Runtime"
          loading={assistantNative.isLoading}
          error={assistantNative.isError ? (assistantNative.error as Error).message : null}
          stats={
            assistantNative.data
              ? [
                  { label: "Resolutions", value: assistantNative.data.continuity_resolution_count },
                  {
                    label: "Retries replayed",
                    value: assistantNative.data.continuity_retry_replayed_count,
                  },
                  {
                    label: "Duplicates prevented",
                    value: assistantNative.data.continuity_duplicate_prevented_count,
                  },
                ]
              : []
          }
        />
        <OperationalMetricCard
          title="Knowledge System"
          loading={assistantNative.isLoading}
          error={assistantNative.isError ? (assistantNative.error as Error).message : null}
          stats={
            assistantNative.data
              ? [
                  { label: "Notes", value: assistantNative.data.notes_total },
                  { label: "Memories", value: assistantNative.data.saved_memories_total },
                  { label: "Canvases", value: assistantNative.data.canvases_total },
                  { label: "Semantic links", value: assistantNative.data.semantic_links_total },
                ]
              : []
          }
        />
        <OperationalMetricCard
          title="Content Factory"
          loading={assistantNative.isLoading}
          error={assistantNative.isError ? (assistantNative.error as Error).message : null}
          stats={
            assistantNative.data
              ? [
                  { label: "Drafts applied", value: assistantNative.data.project_drafts_applied },
                  {
                    label: "Actions active",
                    value: assistantNative.data.scheduled_actions_active_total,
                  },
                  {
                    label: "Needs review",
                    value: assistantNative.data.content_assets_needs_review_total,
                  },
                  {
                    label: "NotebookLM queued",
                    value: assistantNative.data.notebooklm_podcast_total,
                  },
                ]
              : []
          }
        />
        <OperationalMetricCard
          title="Control Plane"
          loading={assistantNative.isLoading}
          error={assistantNative.isError ? (assistantNative.error as Error).message : null}
          stats={
            assistantNative.data
              ? [
                  { label: "Connectors", value: assistantNative.data.connector_accounts_total },
                  {
                    label: "Connector docs",
                    value: assistantNative.data.connector_documents_total,
                  },
                  {
                    label: "Approvals pending",
                    value: assistantNative.data.approval_requests_pending_total,
                  },
                ]
              : []
          }
        />
        <OperationalMetricCard
          title="Continuity Replays"
          loading={assistantNativeEval.isLoading}
          error={assistantNativeEval.isError ? (assistantNativeEval.error as Error).message : null}
          stats={
            assistantNativeEval.data
              ? [
                  {
                    label: "Pass rate",
                    value: Math.round(assistantNativeEval.data.pass_rate * 100),
                  },
                  {
                    label: "Baseline lift",
                    value: Math.round(assistantNativeEval.data.baseline_lift * 100),
                  },
                  {
                    label: "Failing cases",
                    value: assistantNativeEval.data.failing_case_ids.length,
                  },
                ]
              : []
          }
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <Card padding="none">
          <CardHeader>
            <CardTitle>Preflight Checks</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {preflight.isLoading ? (
              Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-16" />)
            ) : preflight.isError ? (
              <p className="text-sm text-[var(--color-error-500)]">
                {(preflight.error as Error).message}
              </p>
            ) : (
              preflight.data?.checks.map((check) => (
                <PreflightCheckCard key={check.name} check={check} />
              ))
            )}
          </CardContent>
        </Card>

        <Card padding="none">
          <CardHeader>
            <CardTitle>Prompt Governance</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {prompts.isLoading ? (
              Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-24" />)
            ) : prompts.isError ? (
              <p className="text-sm text-[var(--color-error-500)]">
                {(prompts.error as Error).message}
              </p>
            ) : (
              promptRecords.map((record) => (
                <div
                  key={record.agent}
                  className="rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-base)] px-3 py-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-semibold text-[var(--color-fg-primary)]">
                      {record.agent}
                    </p>
                    <Badge variant={record.prompt_version ? "success" : "warning"} size="sm">
                      {record.prompt_version ?? "unversioned"}
                    </Badge>
                    <Badge variant="default" size="sm">
                      {record.kind}
                    </Badge>
                  </div>
                  <div className="mt-2 grid grid-cols-1 gap-2 text-xs text-[var(--color-fg-secondary)] md:grid-cols-2">
                    <p>Model: {record.model_policy}</p>
                    <p>Rubric: {record.eval_rubric_id ?? "n/a"}</p>
                    <p>Memory: {record.memory_namespace ?? "n/a"}</p>
                    <p>Confirm: {record.confirmation_policy ?? "n/a"}</p>
                    <p className="md:col-span-2">Prompt: {record.prompt_source}</p>
                    <p className="md:col-span-2">
                      Tools:{" "}
                      {record.allowed_tool_patterns.length > 0
                        ? record.allowed_tool_patterns.join(", ")
                        : "no runtime tool patterns"}
                    </p>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function OperationalMetricCard({
  title,
  loading,
  error,
  stats,
}: {
  title: string;
  loading: boolean;
  error: string | null;
  stats: Array<{ label: string; value: number }>;
}) {
  return (
    <Card padding="none">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading ? (
          Array.from({ length: 3 }).map((_, index) => <Skeleton key={index} className="h-12" />)
        ) : error ? (
          <p className="text-sm text-[var(--color-error-500)]">{error}</p>
        ) : (
          stats.map((item) => (
            <div
              key={item.label}
              className="rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-base)] px-3 py-3"
            >
              <p className="text-xs uppercase tracking-wide text-[var(--color-fg-tertiary)]">
                {item.label}
              </p>
              <p className="mt-1 text-2xl font-semibold text-[var(--color-fg-primary)]">
                {item.value}
              </p>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}

interface ProviderConfigurationDetails extends Record<string, unknown> {
  required?: Record<string, boolean>;
  optional?: Record<string, boolean>;
  missing_required?: string[];
  missing_optional?: string[];
}

function isProviderConfigurationDetails(
  details: Record<string, unknown>,
): details is ProviderConfigurationDetails {
  return "required" in details || "optional" in details;
}

function PreflightCheckCard({ check }: { check: PreflightCheck }) {
  const detailKeys = Object.keys(check.details ?? {});
  const providerDetails =
    check.name === "provider_configuration" && isProviderConfigurationDetails(check.details)
      ? check.details
      : null;
  const requiredEntries = providerDetails ? Object.entries(providerDetails.required ?? {}) : [];
  const optionalEntries = providerDetails ? Object.entries(providerDetails.optional ?? {}) : [];

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-base)] px-3 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-semibold text-[var(--color-fg-primary)]">
          {check.name.replaceAll("_", " ")}
        </p>
        <Badge variant={statusVariant(check.status)} size="sm">
          {check.status}
        </Badge>
        {!check.required && (
          <Badge variant="default" size="sm">
            optional
          </Badge>
        )}
      </div>
      <p className="mt-2 text-sm text-[var(--color-fg-secondary)]">{check.message}</p>
      {providerDetails && (
        <div className="mt-3 grid grid-cols-1 gap-3 text-xs md:grid-cols-2">
          <div className="space-y-2">
            <p className="font-semibold uppercase tracking-wide text-[var(--color-fg-tertiary)]">
              Required Providers
            </p>
            <div className="flex flex-wrap gap-2">
              {requiredEntries.map(([name, configured]) => (
                <Badge key={name} variant={configured ? "success" : "error"} size="sm">
                  {name.replaceAll("_", " ")}: {configured ? "configured" : "missing"}
                </Badge>
              ))}
            </div>
          </div>
          <div className="space-y-2">
            <p className="font-semibold uppercase tracking-wide text-[var(--color-fg-tertiary)]">
              Optional Integrations
            </p>
            <div className="flex flex-wrap gap-2">
              {optionalEntries.map(([name, configured]) => (
                <Badge key={name} variant={configured ? "success" : "default"} size="sm">
                  {name.replaceAll("_", " ")}: {configured ? "enabled" : "not attached"}
                </Badge>
              ))}
            </div>
          </div>
        </div>
      )}
      {detailKeys.length > 0 && (
        <p className="mt-2 text-xs text-[var(--color-fg-tertiary)]">
          Details: {detailKeys.join(", ")}
        </p>
      )}
    </div>
  );
}

export { ReleaseReadiness };
