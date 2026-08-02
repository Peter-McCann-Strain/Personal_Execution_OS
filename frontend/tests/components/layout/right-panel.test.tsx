import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderWithProviders, screen, userEvent, waitFor } from "../../test-utils";
import { RightPanel } from "@/components/layout/right-panel";
import { useAppStore } from "@/stores/app";
import type { AgentRunDetail, Email, Entity, EntityRelationship } from "@/types";

let currentPath = "/dashboard";

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  getAgentRun: vi.fn(),
  approveAgentRunRequest: vi.fn(),
  rejectAgentRunRequest: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("react-router", async () => {
  const actual = await vi.importActual<typeof import("react-router")>("react-router");
  return {
    ...actual,
    useLocation: () => ({ pathname: currentPath }),
    useNavigate: () => mocks.navigate,
  };
});

vi.mock("@/api/agent-runs", () => ({
  getAgentRun: mocks.getAgentRun,
  approveAgentRunRequest: mocks.approveAgentRunRequest,
  rejectAgentRunRequest: mocks.rejectAgentRunRequest,
}));

vi.mock("sonner", () => ({
  toast: {
    success: mocks.toastSuccess,
    error: mocks.toastError,
  },
}));

function resetAppStore() {
  useAppStore.setState({
    sidebarCollapsed: false,
    rightPanelOpen: true,
    rightPanelContent: null,
    inspectedEmail: null,
    inspectedEntity: null,
    inspectedAgentRunId: null,
    theme: "dark",
  });
}

function makeEmail(): Email {
  return {
    id: "email-1",
    threadId: "thread-42",
    snippet: "Fallback message preview",
    headers: {
      From: "Ada Lovelace <ada@example.com>",
      Subject: "Analytical Engine notes",
      Date: "2026-07-31T09:30:00Z",
    },
    body: "The revised notes are ready for review.",
    labelIds: ["UNREAD", "INBOX", "PROJECT"],
    internalDate: String(Date.parse("2026-07-31T09:30:00Z")),
    triage: "ACTION_REQUIRED",
  };
}

function makeEntity(id: string, name: string): Entity {
  return {
    id,
    name,
    entity_type: "PERSON",
    canonical_name: id === "entity-1" ? "Augusta Ada King" : null,
    mention_count: id === "entity-1" ? 12 : 4,
    first_seen: "2026-07-01T09:00:00Z",
    last_seen: "2026-07-31T09:00:00Z",
    metadata: id === "entity-1" ? { role: "Mathematician", empty: "", ignored: null } : {},
    created_at: "2026-07-01T09:00:00Z",
  };
}

function makeRelationship(): EntityRelationship {
  return {
    id: "relationship-1",
    source_entity_id: "entity-1",
    target_entity_id: "entity-2",
    relationship_type: "collaborated_with",
    valid_from: null,
    valid_to: null,
  };
}

function makeAgentRun(): AgentRunDetail {
  return {
    id: "run-1",
    source: "chat",
    status: "waiting_for_approval",
    specialist: "research",
    request_excerpt: "Research a safe deployment approach.",
    pending_approvals: 1,
    created_at: "2026-07-31T09:00:00Z",
    updated_at: "2026-07-31T09:05:00Z",
    trace_id: "trace-1",
    response_id: null,
    metadata: {},
    steps: [
      {
        id: "step-1",
        workflow_id: "run-1",
        step_type: "research",
        title: "Review deployment constraints",
        status: "completed",
        details: {},
        created_at: "2026-07-31T09:00:00Z",
        updated_at: "2026-07-31T09:01:00Z",
      },
    ],
    approvals: [
      {
        id: "approval-1",
        workflow_id: "run-1",
        checkpoint_id: "checkpoint-1",
        request_kind: "external_action",
        title: "Publish the report",
        description: "Review the destination before sending.",
        status: "pending",
        payload: {},
        created_at: "2026-07-31T09:02:00Z",
        resolved_at: null,
        updated_at: "2026-07-31T09:02:00Z",
      },
      {
        id: "approval-resolved",
        workflow_id: "run-1",
        checkpoint_id: null,
        request_kind: "external_action",
        title: "Already reviewed",
        description: null,
        status: "approved",
        payload: {},
        created_at: "2026-07-31T08:00:00Z",
        resolved_at: "2026-07-31T08:05:00Z",
        updated_at: "2026-07-31T08:05:00Z",
      },
    ],
    browser_sessions: [],
    tool_receipts: [
      {
        id: "receipt-1",
        workflow_id: "run-1",
        tool_name: "read_only_search",
        server_name: "search",
        mutation_class: "read",
        status: "completed",
        result_summary: "Three relevant sources found.",
        error_message: null,
        created_at: "2026-07-31T09:01:00Z",
      },
    ],
    artifacts: [
      {
        id: "artifact-1",
        artifact_type: "report",
        scope: "private",
        summary: "Deployment report",
        source_id: "run-1",
        created_at: "2026-07-31T09:03:00Z",
        payload: {},
      },
    ],
  };
}

describe("RightPanel", () => {
  beforeEach(() => {
    currentPath = "/dashboard";
    mocks.navigate.mockReset();
    mocks.getAgentRun.mockReset();
    mocks.approveAgentRunRequest.mockReset();
    mocks.rejectAgentRunRequest.mockReset();
    mocks.toastSuccess.mockReset();
    mocks.toastError.mockReset();
    act(() => {
      resetAppStore();
    });
  });

  it("renders route-aware workspace status and closes the panel", async () => {
    currentPath = "/settings";
    act(() => {
      useAppStore.setState({ sidebarCollapsed: true, theme: "light" });
    });
    const user = userEvent.setup();

    renderWithProviders(<RightPanel />);

    expect(screen.getByRole("heading", { name: "Workspace Panel" })).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(
      screen.getByText("Profile, integrations, data controls, and account configuration."),
    ).toBeInTheDocument();
    expect(screen.getByText("Light")).toBeInTheDocument();
    expect(screen.getByText("Dev mode")).toBeInTheDocument();
    expect(screen.getByText("Collapsed")).toBeInTheDocument();
    expect(screen.getByText("Open command palette")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close workspace panel" }));

    expect(useAppStore.getState().rightPanelOpen).toBe(false);
    expect(useAppStore.getState().rightPanelContent).toBeNull();
  });

  it("shows the reserved artifact mode and returns to workspace tools", async () => {
    act(() => {
      useAppStore.setState({ rightPanelContent: "artifact" });
    });
    const user = userEvent.setup();

    renderWithProviders(<RightPanel />);

    expect(screen.getByRole("heading", { name: "Artifact Inspector" })).toBeInTheDocument();
    expect(screen.getByText(/reserved for a future saved-output flow/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Return To Workspace Tools" }));

    expect(useAppStore.getState().rightPanelContent).toBe("workspace");
  });

  it("moves from the empty email state to live message details and opens the inbox", async () => {
    act(() => {
      useAppStore.setState({ rightPanelContent: "email" });
    });
    const user = userEvent.setup();

    renderWithProviders(<RightPanel />);

    expect(screen.getByText("No email selected")).toBeInTheDocument();

    act(() => {
      useAppStore.setState({ inspectedEmail: makeEmail() });
    });

    expect(await screen.findByText("Analytical Engine notes")).toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("Action Required")).toBeInTheDocument();
    expect(screen.getByText("Unread")).toBeInTheDocument();
    expect(screen.getByText("PROJECT")).toBeInTheDocument();
    expect(screen.getByText("The revised notes are ready for review.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open Inbox Workspace" }));

    expect(mocks.navigate).toHaveBeenCalledWith("/email");
  });

  it("moves from the empty entity state to relationship context and graph navigation", async () => {
    act(() => {
      useAppStore.setState({ rightPanelContent: "entity" });
    });
    const user = userEvent.setup();

    renderWithProviders(<RightPanel />);

    expect(screen.getByText("No entity selected")).toBeInTheDocument();

    act(() => {
      useAppStore.setState({
        inspectedEntity: {
          entity: makeEntity("entity-1", "Ada Lovelace"),
          relationships: [
            {
              relationship: makeRelationship(),
              relatedEntity: makeEntity("entity-2", "Charles Babbage"),
            },
          ],
        },
      });
    });

    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("Canonical name: Augusta Ada King")).toBeInTheDocument();
    expect(screen.getByText("12 mentions")).toBeInTheDocument();
    expect(screen.getByText("Mathematician")).toBeInTheDocument();
    expect(screen.getByText("collaborated_with")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Charles Babbage/i }));
    expect(mocks.navigate).toHaveBeenCalledWith("/knowledge-graph?entity=entity-2");

    await user.click(screen.getByRole("button", { name: "Open Graph Focus" }));
    expect(mocks.navigate).toHaveBeenLastCalledWith("/knowledge-graph?entity=entity-1");
  });

  it("shows an empty run state before a workflow is selected", () => {
    act(() => {
      useAppStore.setState({ rightPanelContent: "agent-run" });
    });

    renderWithProviders(<RightPanel />);

    expect(screen.getByText("No run selected")).toBeInTheDocument();
    expect(mocks.getAgentRun).not.toHaveBeenCalled();
  });

  it("loads a run and supports its approval and rejection actions", async () => {
    const run = makeAgentRun();
    mocks.getAgentRun.mockResolvedValue(run);
    mocks.approveAgentRunRequest.mockResolvedValue({
      status: "approved",
      response_content: "The approved request was queued.",
      workflow_status: "running",
    });
    mocks.rejectAgentRunRequest.mockResolvedValue({
      status: "rejected",
      response_content: "The request was rejected.",
      workflow_status: "cancelled",
    });
    act(() => {
      useAppStore.setState({
        rightPanelContent: "agent-run",
        inspectedAgentRunId: run.id,
      });
    });
    const user = userEvent.setup();

    renderWithProviders(<RightPanel />);

    expect(screen.getByText("Loading run details…")).toBeInTheDocument();
    expect(await screen.findByText("research workflow")).toBeInTheDocument();
    expect(screen.getByText("Research a safe deployment approach.")).toBeInTheDocument();
    expect(screen.getByText("Review deployment constraints")).toBeInTheDocument();
    expect(screen.getByText("read_only_search")).toBeInTheDocument();
    expect(screen.getByText("Three relevant sources found.")).toBeInTheDocument();
    expect(screen.getByText("Publish the report")).toBeInTheDocument();
    expect(screen.queryByText("Already reviewed")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => {
      expect(mocks.approveAgentRunRequest).toHaveBeenCalledWith("run-1", "approval-1");
      expect(mocks.toastSuccess).toHaveBeenCalledWith(
        "Approval sent",
        expect.objectContaining({ description: "The approved request was queued." }),
      );
    });

    await user.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() => {
      expect(mocks.rejectAgentRunRequest).toHaveBeenCalledWith("run-1", "approval-1");
      expect(mocks.toastSuccess).toHaveBeenCalledWith(
        "Request rejected",
        expect.objectContaining({ description: "The request was rejected." }),
      );
    });
  });

  it("reports run loading and mutation failures without losing the inspector", async () => {
    mocks.getAgentRun.mockRejectedValueOnce(new Error("Run lookup failed"));
    act(() => {
      useAppStore.setState({
        rightPanelContent: "agent-run",
        inspectedAgentRunId: "missing-run",
      });
    });

    const { unmount } = renderWithProviders(<RightPanel />);

    expect(await screen.findByText("Run unavailable")).toBeInTheDocument();
    expect(screen.getByText("Run lookup failed")).toBeInTheDocument();
    unmount();

    mocks.getAgentRun.mockResolvedValue(makeAgentRun());
    mocks.approveAgentRunRequest.mockRejectedValue(new Error("Approval service unavailable"));
    act(() => {
      useAppStore.setState({ inspectedAgentRunId: "run-1" });
    });
    const user = userEvent.setup();

    renderWithProviders(<RightPanel />);

    await user.click(await screen.findByRole("button", { name: "Approve" }));
    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith(
        "Approval failed",
        expect.objectContaining({ description: "Approval service unavailable" }),
      );
    });
  });
});
