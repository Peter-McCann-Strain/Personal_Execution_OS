import { useMemo } from "react";
import { useLocation, useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Calendar,
  CornerDownRight,
  ExternalLink,
  Hash,
  KeyRound,
  Mail,
  MessageSquareText,
  Network,
  Package,
  PanelRightClose,
  PanelsTopLeft,
  Sparkles,
  Tag,
  UserRound,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getAgentRun, approveAgentRunRequest, rejectAgentRunRequest } from "@/api/agent-runs";
import { getSender, getSubject, isUnread, triageMap } from "@/components/email/email-list.utils";
import { isAuthConfigured, isLegacyDevAuthEnabled } from "@/lib/auth-mode";
import { formatShortcut } from "@/lib/platform";
import { formatRelativeTime } from "@/lib/utils";
import { useAppStore } from "@/stores/app";
import { getRouteMeta } from "./route-metadata";
import { toast } from "sonner";

const GLOBAL_SHORTCUTS = [
  { combo: formatShortcut("Mod+K"), label: "Open command palette" },
  { combo: formatShortcut("Mod+B"), label: "Toggle sidebar" },
  { combo: formatShortcut("Mod+1"), label: "Go to dashboard" },
  { combo: formatShortcut("Mod+2"), label: "Go to chat" },
  { combo: formatShortcut("Mod+6"), label: "Go to calendar" },
  { combo: formatShortcut("Mod+7"), label: "Go to email" },
];

const PANEL_COPY = {
  workspace: {
    title: "Workspace Panel",
    description: "A route-aware control surface for navigation, state, and operating context.",
  },
  email: {
    title: "Email Inspector",
    description: "Live message context for the email currently selected in the inbox.",
  },
  entity: {
    title: "Entity Inspector",
    description: "Live knowledge-graph context for the entity currently selected on the graph.",
  },
  artifact: {
    title: "Artifact Inspector",
    description: "Reserved for recent outputs, saved artifacts, and generated work products.",
  },
  "agent-run": {
    title: "Agent Run",
    description:
      "Live execution timeline, approvals, tool receipts, and artifacts for one workflow run.",
  },
} as const;

const ENTITY_TYPE_CONFIG = {
  PERSON: { label: "Person", accent: "var(--color-agent-memory)" },
  ORG: { label: "Organization", accent: "var(--color-agent-comms)" },
  PLACE: { label: "Place", accent: "var(--color-success-500)" },
  CONCEPT: { label: "Concept", accent: "var(--color-agent-research)" },
} as const;

function StatusRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-2">
      <span className="text-xs text-[var(--color-fg-secondary)]">{label}</span>
      <span className="text-xs font-medium text-[var(--color-fg-primary)]">{value}</span>
    </div>
  );
}

function formatEmailDate(rawDate: string | null, headers: Record<string, string>) {
  if (rawDate) {
    const timestamp = Number(rawDate);
    if (!Number.isNaN(timestamp)) {
      const date = timestamp > 1e12 ? new Date(timestamp) : new Date(timestamp * 1000);
      return date.toLocaleString("en-GB", {
        weekday: "short",
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
    }
  }

  const headerDate = headers.Date || headers.date;
  if (!headerDate) {
    return "Unknown";
  }

  return new Date(headerDate).toLocaleString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ShortcutList() {
  return (
    <div className="space-y-2">
      {GLOBAL_SHORTCUTS.map((shortcut) => (
        <div
          key={shortcut.combo}
          className="flex items-center justify-between gap-3 rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-2"
        >
          <span className="text-xs text-[var(--color-fg-secondary)]">{shortcut.label}</span>
          <kbd className="rounded-[var(--radius-sm)] border border-[var(--color-border-strong)] bg-[var(--color-bg-overlay)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-fg-primary)]">
            {shortcut.combo}
          </kbd>
        </div>
      ))}
    </div>
  );
}

function SectionHeading({ icon: Icon, label }: { icon: typeof PanelsTopLeft; label: string }) {
  return (
    <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.16em] text-[var(--color-fg-tertiary)]">
      <Icon className="h-3.5 w-3.5" />
      {label}
    </div>
  );
}

function EmailInspector() {
  const navigate = useNavigate();
  const email = useAppStore((s) => s.inspectedEmail);

  if (!email) {
    return (
      <section className="rounded-[var(--radius-lg)] border border-dashed border-[var(--color-border-default)] px-3 py-4">
        <p className="text-sm font-medium text-[var(--color-fg-primary)]">No email selected</p>
        <p className="mt-1 text-xs leading-relaxed text-[var(--color-fg-secondary)]">
          Select a message from the inbox to inspect its live metadata here.
        </p>
      </section>
    );
  }

  const sender = getSender(email);
  const subject = getSubject(email);
  const unread = isUnread(email);
  const date = formatEmailDate(email.internalDate, email.headers ?? {});
  const triage = email.triage ? triageMap[email.triage] : null;
  const preview = email.body?.trim() || email.snippet || "No preview available.";
  const labels = email.labelIds.filter((label) => label !== "UNREAD");

  return (
    <>
      <section className="space-y-2">
        <SectionHeading icon={Mail} label="Selected Message" />
        <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-3">
          <p className="text-sm font-semibold text-[var(--color-fg-primary)]">{subject}</p>
          <div className="mt-2 space-y-2 text-xs text-[var(--color-fg-secondary)]">
            <div className="flex items-start gap-2">
              <UserRound className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--color-fg-tertiary)]" />
              <span>{sender}</span>
            </div>
            <div className="flex items-start gap-2">
              <Calendar className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--color-fg-tertiary)]" />
              <span>{date}</span>
            </div>
            <div className="flex items-start gap-2">
              <Hash className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--color-fg-tertiary)]" />
              <span>{email.threadId ?? "Standalone message"}</span>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            {triage && (
              <span
                className={`${triage.bgClass} ${triage.textClass} inline-flex items-center rounded-[var(--radius-full)] px-2 py-0.5 text-[10px] font-medium`}
              >
                {triage.label}
              </span>
            )}
            {unread && <Badge size="sm">Unread</Badge>}
            {labels.map((label) => (
              <Badge key={label} size="sm">
                {label}
              </Badge>
            ))}
          </div>
        </div>
      </section>

      <section className="space-y-2">
        <SectionHeading icon={MessageSquareText} label="Preview" />
        <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-3">
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-[var(--color-fg-primary)]">
            {preview}
          </p>
        </div>
      </section>

      <Button variant="outline" className="w-full" onClick={() => navigate("/email")}>
        <ExternalLink className="h-4 w-4" />
        Open Inbox Workspace
      </Button>
    </>
  );
}

function EntityInspector() {
  const navigate = useNavigate();
  const inspectedEntity = useAppStore((s) => s.inspectedEntity);

  if (!inspectedEntity) {
    return (
      <section className="rounded-[var(--radius-lg)] border border-dashed border-[var(--color-border-default)] px-3 py-4">
        <p className="text-sm font-medium text-[var(--color-fg-primary)]">No entity selected</p>
        <p className="mt-1 text-xs leading-relaxed text-[var(--color-fg-secondary)]">
          Select an entity on the graph to inspect live relationship context here.
        </p>
      </section>
    );
  }

  const { entity, relationships } = inspectedEntity;
  const config = ENTITY_TYPE_CONFIG[entity.entity_type] ?? ENTITY_TYPE_CONFIG.CONCEPT;
  const metadataEntries = Object.entries(entity.metadata).filter(
    ([, value]) => value !== null && value !== undefined && value !== "",
  );

  return (
    <>
      <section className="space-y-2">
        <SectionHeading icon={Network} label="Selected Entity" />
        <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-[var(--color-fg-primary)]">{entity.name}</p>
              <div className="mt-2 flex items-center gap-1.5">
                <Badge size="sm">{config.label}</Badge>
                <span className="text-[11px] text-[var(--color-fg-tertiary)]">
                  {entity.mention_count} mentions
                </span>
              </div>
            </div>
            <span
              className="mt-0.5 h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: config.accent }}
            />
          </div>

          {entity.canonical_name && entity.canonical_name !== entity.name && (
            <p className="mt-3 text-xs text-[var(--color-fg-secondary)]">
              Canonical name: {entity.canonical_name}
            </p>
          )}

          <div className="mt-3 grid gap-2 text-xs text-[var(--color-fg-secondary)]">
            <div className="flex items-center justify-between gap-3">
              <span>First seen</span>
              <span className="text-[var(--color-fg-primary)]">
                {entity.first_seen
                  ? new Date(entity.first_seen).toLocaleDateString("en-GB")
                  : "Unknown"}
              </span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span>Last seen</span>
              <span className="text-[var(--color-fg-primary)]">
                {entity.last_seen ? formatRelativeTime(entity.last_seen) : "Unknown"}
              </span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span>Relationships</span>
              <span className="text-[var(--color-fg-primary)]">{relationships.length}</span>
            </div>
          </div>
        </div>
      </section>

      {relationships.length > 0 && (
        <section className="space-y-2">
          <SectionHeading icon={CornerDownRight} label="Related Entities" />
          <div className="space-y-2">
            {relationships.slice(0, 6).map(({ relationship, relatedEntity }) => (
              <button
                key={relationship.id}
                type="button"
                onClick={() => navigate(`/knowledge-graph?entity=${relatedEntity.id}`)}
                className="w-full rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-2 text-left transition-colors hover:border-[var(--color-border-strong)]"
              >
                <p className="text-sm font-medium text-[var(--color-fg-primary)]">
                  {relatedEntity.name}
                </p>
                <p className="mt-1 text-xs text-[var(--color-fg-secondary)]">
                  {relationship.relationship_type}
                </p>
              </button>
            ))}
          </div>
        </section>
      )}

      {metadataEntries.length > 0 && (
        <section className="space-y-2">
          <SectionHeading icon={Tag} label="Metadata" />
          <div className="space-y-2 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-3">
            {metadataEntries.slice(0, 5).map(([key, value]) => (
              <div key={key} className="flex items-start justify-between gap-3 text-xs">
                <span className="text-[var(--color-fg-tertiary)]">{key}</span>
                <span className="max-w-[60%] text-right text-[var(--color-fg-primary)]">
                  {String(value)}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      <Button
        variant="outline"
        className="w-full"
        onClick={() => navigate(`/knowledge-graph?entity=${entity.id}`)}
      >
        <ExternalLink className="h-4 w-4" />
        Open Graph Focus
      </Button>
    </>
  );
}

function AgentRunInspector() {
  const queryClient = useQueryClient();
  const runId = useAppStore((s) => s.inspectedAgentRunId);

  const runQuery = useQuery({
    queryKey: ["agent-run", runId],
    queryFn: () => getAgentRun(runId!),
    enabled: Boolean(runId),
  });

  const approveMutation = useMutation({
    mutationFn: ({ workflowId, approvalId }: { workflowId: string; approvalId: string }) =>
      approveAgentRunRequest(workflowId, approvalId),
    onSuccess: (result, variables) => {
      toast.success("Approval sent", {
        description: result.response_content.slice(0, 180),
      });
      queryClient.invalidateQueries({ queryKey: ["agent-run", variables.workflowId] });
    },
    onError: (error) => {
      toast.error("Approval failed", {
        description: error instanceof Error ? error.message : "Unknown error",
      });
    },
  });

  const rejectMutation = useMutation({
    mutationFn: ({ workflowId, approvalId }: { workflowId: string; approvalId: string }) =>
      rejectAgentRunRequest(workflowId, approvalId),
    onSuccess: (result, variables) => {
      toast.success("Request rejected", {
        description: result.response_content.slice(0, 180),
      });
      queryClient.invalidateQueries({ queryKey: ["agent-run", variables.workflowId] });
    },
    onError: (error) => {
      toast.error("Rejection failed", {
        description: error instanceof Error ? error.message : "Unknown error",
      });
    },
  });

  if (!runId) {
    return (
      <section className="rounded-[var(--radius-lg)] border border-dashed border-[var(--color-border-default)] px-3 py-4">
        <p className="text-sm font-medium text-[var(--color-fg-primary)]">No run selected</p>
        <p className="mt-1 text-xs leading-relaxed text-[var(--color-fg-secondary)]">
          Open a workflow from chat to inspect its steps, approvals, and artifacts here.
        </p>
      </section>
    );
  }

  if (runQuery.isLoading) {
    return (
      <section className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-4">
        <p className="text-sm text-[var(--color-fg-secondary)]">Loading run details…</p>
      </section>
    );
  }

  if (runQuery.isError || !runQuery.data) {
    return (
      <section className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-4">
        <p className="text-sm font-medium text-[var(--color-fg-primary)]">Run unavailable</p>
        <p className="mt-1 text-xs leading-relaxed text-[var(--color-fg-secondary)]">
          {runQuery.error instanceof Error ? runQuery.error.message : "Unable to load this run."}
        </p>
      </section>
    );
  }

  const run = runQuery.data;
  const pendingApprovals = run.approvals.filter((approval) => approval.status === "pending");

  return (
    <>
      <section className="space-y-2">
        <SectionHeading icon={Sparkles} label="Run Status" />
        <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-[var(--color-fg-primary)]">
                {run.specialist ? `${run.specialist} workflow` : "Assistant workflow"}
              </p>
              <p className="mt-1 text-xs text-[var(--color-fg-secondary)]">
                {run.request_excerpt || "No request excerpt stored."}
              </p>
            </div>
            <Badge size="sm">{run.status}</Badge>
          </div>
          <div className="mt-3 grid gap-2 text-xs text-[var(--color-fg-secondary)]">
            <div className="flex items-center justify-between gap-3">
              <span>Created</span>
              <span className="text-[var(--color-fg-primary)]">
                {formatRelativeTime(run.created_at)}
              </span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span>Pending approvals</span>
              <span className="text-[var(--color-fg-primary)]">{pendingApprovals.length}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span>Artifacts</span>
              <span className="text-[var(--color-fg-primary)]">{run.artifacts.length}</span>
            </div>
          </div>
        </div>
      </section>

      {pendingApprovals.length > 0 && (
        <section className="space-y-2">
          <SectionHeading icon={CheckCircle2} label="Approvals" />
          <div className="space-y-2">
            {pendingApprovals.map((approval) => (
              <div
                key={approval.id}
                className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-3"
              >
                <p className="text-sm font-medium text-[var(--color-fg-primary)]">
                  {approval.title}
                </p>
                {approval.description && (
                  <p className="mt-1 text-xs leading-relaxed text-[var(--color-fg-secondary)]">
                    {approval.description}
                  </p>
                )}
                <div className="mt-3 flex items-center gap-2">
                  <Button
                    size="sm"
                    onClick={() =>
                      approveMutation.mutate({ workflowId: run.id, approvalId: approval.id })
                    }
                    disabled={approveMutation.isPending || rejectMutation.isPending}
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    Approve
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      rejectMutation.mutate({ workflowId: run.id, approvalId: approval.id })
                    }
                    disabled={approveMutation.isPending || rejectMutation.isPending}
                  >
                    <XCircle className="h-4 w-4" />
                    Reject
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="space-y-2">
        <SectionHeading icon={MessageSquareText} label="Timeline" />
        <div className="space-y-2">
          {run.steps.map((step) => (
            <div
              key={step.id}
              className="rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-2"
            >
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-[var(--color-fg-primary)]">{step.title}</p>
                <Badge size="sm">{step.status}</Badge>
              </div>
              <p className="mt-1 text-[11px] text-[var(--color-fg-tertiary)]">{step.step_type}</p>
            </div>
          ))}
        </div>
      </section>

      {run.tool_receipts.length > 0 && (
        <section className="space-y-2">
          <SectionHeading icon={Package} label="Tools" />
          <div className="space-y-2">
            {run.tool_receipts.slice(0, 6).map((receipt) => (
              <div
                key={receipt.id}
                className="rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-2"
              >
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-medium text-[var(--color-fg-primary)]">
                    {receipt.tool_name}
                  </p>
                  <Badge size="sm">{receipt.status}</Badge>
                </div>
                {receipt.result_summary && (
                  <p className="mt-1 text-xs text-[var(--color-fg-secondary)]">
                    {receipt.result_summary}
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  );
}

export function RightPanel() {
  const location = useLocation();
  const sidebarCollapsed = useAppStore((s) => s.sidebarCollapsed);
  const theme = useAppStore((s) => s.theme);
  const rightPanelContent = useAppStore((s) => s.rightPanelContent);
  const closeRightPanel = useAppStore((s) => s.closeRightPanel);
  const openRightPanel = useAppStore((s) => s.openRightPanel);

  const routeMeta = getRouteMeta(location.pathname);
  const panelMode = rightPanelContent ?? "workspace";
  const panelCopy = PANEL_COPY[panelMode];

  const statusSummary = useMemo(
    () => ({
      theme: theme === "system" ? "System" : theme === "dark" ? "Dark" : "Light",
      auth: isAuthConfigured
        ? isLegacyDevAuthEnabled
          ? "Dev mode"
          : "Server session"
        : "Disabled",
      sidebar: sidebarCollapsed ? "Collapsed" : "Expanded",
    }),
    [sidebarCollapsed, theme],
  );

  return (
    <div className="flex h-full flex-col" aria-label="Workspace panel">
      <div className="flex items-start justify-between gap-3 border-b border-[var(--color-border-subtle)] px-4 py-4">
        <div className="space-y-1">
          <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-[var(--color-fg-tertiary)]">
            {panelMode === "workspace" ? "Workspace" : "Inspector"}
          </p>
          <h2 className="text-sm font-semibold text-[var(--color-fg-primary)]">
            {panelCopy.title}
          </h2>
          <p className="text-xs leading-relaxed text-[var(--color-fg-secondary)]">
            {panelCopy.description}
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Close workspace panel"
          title="Close workspace panel"
          onClick={closeRightPanel}
          className="shrink-0"
        >
          <PanelRightClose className="h-4 w-4" />
        </Button>
      </div>

      <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4">
        {panelMode === "workspace" ? (
          <>
            <section className="space-y-2">
              <SectionHeading icon={PanelsTopLeft} label="Current View" />
              <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-3">
                <p className="text-sm font-medium text-[var(--color-fg-primary)]">
                  {routeMeta.label}
                </p>
                <p className="mt-1 text-xs leading-relaxed text-[var(--color-fg-secondary)]">
                  {routeMeta.description}
                </p>
              </div>
            </section>

            <section className="space-y-2">
              <SectionHeading icon={Sparkles} label="Workspace Status" />
              <div className="space-y-2">
                <StatusRow label="Theme" value={statusSummary.theme} />
                <StatusRow label="Auth" value={statusSummary.auth} />
                <StatusRow label="Sidebar" value={statusSummary.sidebar} />
              </div>
            </section>

            <section className="space-y-2">
              <SectionHeading icon={KeyRound} label="Global Shortcuts" />
              <ShortcutList />
            </section>
          </>
        ) : panelMode === "email" ? (
          <EmailInspector />
        ) : panelMode === "entity" ? (
          <EntityInspector />
        ) : panelMode === "agent-run" ? (
          <AgentRunInspector />
        ) : (
          <section className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-3">
            <div className="flex items-start gap-2">
              <Package className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-agent-tools)]" />
              <div className="space-y-1">
                <p className="text-sm font-medium text-[var(--color-fg-primary)]">
                  Artifact Inspector
                </p>
                <p className="text-xs leading-relaxed text-[var(--color-fg-secondary)]">
                  Artifact inspection is still reserved for a future saved-output flow.
                </p>
              </div>
            </div>
          </section>
        )}

        {panelMode !== "workspace" && (
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            onClick={() => openRightPanel("workspace")}
          >
            Return To Workspace Tools
          </Button>
        )}
      </div>
    </div>
  );
}
