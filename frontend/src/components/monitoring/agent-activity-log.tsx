import { useState } from "react";
import { Activity, ChevronDown, ChevronRight, ExternalLink, Copy } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { cn, formatRelativeTime, formatCurrency, formatTokens, truncate } from "@/lib/utils";
import { AGENT_OPTIONS, MODEL_OPTIONS, SORT_OPTIONS } from "@/lib/monitoring";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AgentBadge, Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { Pagination } from "@/components/ui/pagination";
import { getAgentActions, type AgentActionQueryParams } from "@/api/monitoring";
import type { AgentName, AgentAction } from "@/types";

// ─── Model Badge Colors ─────────────────────────────────────

function modelBadgeColor(model: string): "success" | "info" | "warning" | "default" {
  const lower = model.toLowerCase();
  if (lower.includes("haiku")) return "success";
  if (lower.includes("sonnet")) return "info";
  if (lower.includes("opus")) return "warning";
  return "default";
}

// ─── AgentActivityLog Component ─────────────────────────────

function AgentActivityLog() {
  const [agentFilter, setAgentFilter] = useState<AgentName | "all">("all");
  const [modelFilter, setModelFilter] = useState("all");
  const [sort, setSort] = useState<AgentActionQueryParams["sort"]>("newest");
  const [page, setPage] = useState(1);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const pageSize = 25;

  const queryParams: AgentActionQueryParams = {
    limit: pageSize,
    offset: (page - 1) * pageSize,
    agent: agentFilter !== "all" ? agentFilter : undefined,
    model: modelFilter !== "all" ? modelFilter : undefined,
    sort,
  };

  const { data, isLoading } = useQuery({
    queryKey: ["agent-actions", queryParams],
    queryFn: () => getAgentActions(queryParams),
  });

  const actions = data?.items ?? [];
  const totalPages = data ? Math.ceil(data.total / pageSize) : 0;

  const toggleExpand = (id: string) => {
    setExpandedRow((prev) => (prev === id ? null : id));
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    toast.success("Copied to clipboard");
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-[var(--color-fg-primary)]">Agent Activity Log</h2>
        {data && (
          <span className="text-xs text-[var(--color-fg-tertiary)]">
            Showing {(page - 1) * pageSize + 1}-{Math.min(page * pageSize, data.total)} of{" "}
            {data.total.toLocaleString()}
          </span>
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={agentFilter}
          onChange={(e) => {
            setAgentFilter(e.target.value as AgentName | "all");
            setPage(1);
          }}
          className="h-8 rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-2 text-xs text-[var(--color-fg-primary)]"
        >
          {AGENT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        <select
          value={modelFilter}
          onChange={(e) => {
            setModelFilter(e.target.value);
            setPage(1);
          }}
          className="h-8 rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-2 text-xs text-[var(--color-fg-primary)]"
        >
          {MODEL_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-[var(--color-fg-tertiary)]">Sort:</span>
          <select
            value={sort}
            onChange={(e) => {
              setSort(e.target.value as AgentActionQueryParams["sort"]);
              setPage(1);
            }}
            className="h-8 rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-2 text-xs text-[var(--color-fg-primary)]"
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Table */}
      <Card padding="none" className="overflow-hidden">
        {isLoading ? (
          <div className="p-4 flex flex-col gap-3">
            {Array.from({ length: 10 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : actions.length === 0 ? (
          <EmptyState icon={Activity} title="No activity found" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border-subtle)] bg-[var(--color-bg-elevated)]">
                  <th className="w-8 px-3 py-2" />
                  <th className="px-3 py-2 text-left text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider">
                    Time
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider">
                    Agent
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider">
                    Action
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider">
                    Model
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider">
                    Tokens
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider">
                    Cost
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider">
                    Duration
                  </th>
                  <th className="px-3 py-2 text-center text-xs font-medium text-[var(--color-fg-tertiary)] uppercase tracking-wider">
                    Trace
                  </th>
                </tr>
              </thead>
              <tbody>
                {actions.map((action) => (
                  <ActivityRow
                    key={action.id}
                    action={action}
                    isExpanded={expandedRow === action.id}
                    onToggle={() => toggleExpand(action.id)}
                    onCopy={copyToClipboard}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Pagination */}
      <Pagination page={page} totalPages={totalPages} onPageChange={setPage} />
    </div>
  );
}

// ─── ActivityRow ────────────────────────────────────────────

interface ActivityRowProps {
  action: AgentAction;
  isExpanded: boolean;
  onToggle: () => void;
  onCopy: (text: string) => void;
}

function ActivityRow({ action, isExpanded, onToggle, onCopy }: ActivityRowProps) {
  const modelUsed = action.model_used ?? "Unknown";
  const tokensIn = action.tokens_in ?? 0;
  const tokensOut = action.tokens_out ?? 0;
  const costUsd = action.cost_usd ?? 0;
  const durationMs = action.duration_ms ?? 0;
  const traceId = action.trace_id ?? null;
  const costColor =
    costUsd > 0.1
      ? "text-[var(--color-error-500)]"
      : costUsd > 0.05
        ? "text-[var(--color-warning-500)]"
        : "text-[var(--color-fg-secondary)]";

  const durationColor =
    durationMs > 5000
      ? "text-[var(--color-error-500)]"
      : durationMs > 3000
        ? "text-[var(--color-warning-500)]"
        : "text-[var(--color-fg-secondary)]";

  return (
    <>
      <tr
        className="border-b border-[var(--color-border-subtle)] hover:bg-[var(--color-bg-overlay)] transition-colors cursor-pointer"
        onClick={onToggle}
      >
        <td className="px-3 py-2.5">
          {isExpanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-[var(--color-fg-tertiary)]" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-[var(--color-fg-tertiary)]" />
          )}
        </td>
        <td className="px-3 py-2.5 text-xs text-[var(--color-fg-secondary)] whitespace-nowrap">
          {formatRelativeTime(action.created_at)}
        </td>
        <td className="px-3 py-2.5">
          <AgentBadge agent={action.agent_name} size="sm" />
        </td>
        <td className="px-3 py-2.5 text-xs text-[var(--color-fg-secondary)]">
          {action.action_type}
        </td>
        <td className="px-3 py-2.5">
          <Badge variant={modelBadgeColor(modelUsed)} size="sm">
            {extractModelShortName(modelUsed)}
          </Badge>
        </td>
        <td className="px-3 py-2.5 text-right text-xs text-[var(--color-fg-tertiary)] font-mono whitespace-nowrap">
          {formatTokens(tokensIn)}/{formatTokens(tokensOut)}
        </td>
        <td className={cn("px-3 py-2.5 text-right text-xs font-mono whitespace-nowrap", costColor)}>
          {formatCurrency(costUsd)}
        </td>
        <td
          className={cn(
            "px-3 py-2.5 text-right text-xs font-mono whitespace-nowrap",
            durationColor,
          )}
        >
          {durationMs.toLocaleString()}ms
        </td>
        <td className="px-3 py-2.5 text-center">
          {traceId ? (
            <a
              href={`#trace-${traceId}`}
              onClick={(e) => e.stopPropagation()}
              className="text-[var(--color-info-500)] hover:underline"
              title={traceId}
            >
              <ExternalLink className="h-3.5 w-3.5 inline" />
            </a>
          ) : (
            <span className="text-[var(--color-fg-disabled)]">-</span>
          )}
        </td>
      </tr>

      {/* Expanded Row */}
      {isExpanded && (
        <tr className="bg-[var(--color-bg-elevated)]">
          <td colSpan={9} className="px-6 py-4">
            <div className="flex flex-col gap-4">
              {/* Input Summary */}
              {action.input_summary && (
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-semibold text-[var(--color-fg-tertiary)] uppercase tracking-wider">
                      Input ({formatTokens(tokensIn)} tokens)
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        onCopy(action.input_summary ?? "");
                      }}
                    >
                      <Copy className="h-3 w-3" />
                      Copy
                    </Button>
                  </div>
                  <pre className="max-h-40 overflow-auto rounded-[var(--radius-md)] bg-[var(--color-bg-base)] p-3 text-xs text-[var(--color-fg-secondary)] font-mono whitespace-pre-wrap">
                    {action.input_summary}
                  </pre>
                </div>
              )}

              {/* Output Summary */}
              {action.output_summary && (
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-semibold text-[var(--color-fg-tertiary)] uppercase tracking-wider">
                      Output ({formatTokens(tokensOut)} tokens)
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        onCopy(action.output_summary ?? "");
                      }}
                    >
                      <Copy className="h-3 w-3" />
                      Copy
                    </Button>
                  </div>
                  <pre className="max-h-40 overflow-auto rounded-[var(--radius-md)] bg-[var(--color-bg-base)] p-3 text-xs text-[var(--color-fg-secondary)] font-mono whitespace-pre-wrap">
                    {action.output_summary}
                  </pre>
                </div>
              )}

              {/* Trace ID */}
              {traceId && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-[var(--color-fg-tertiary)]">Trace ID:</span>
                  <code className="font-mono text-[var(--color-fg-secondary)]">{traceId}</code>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ─── Helpers ────────────────────────────────────────────────

function extractModelShortName(model: string): string {
  const lower = model.toLowerCase();
  if (lower.includes("haiku")) return "Haiku";
  if (lower.includes("sonnet")) return "Sonnet";
  if (lower.includes("opus")) return "Opus";
  return truncate(model, 12);
}

export { AgentActivityLog };
