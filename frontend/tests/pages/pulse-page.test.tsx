import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderWithProviders, screen, userEvent, waitFor, within } from "../test-utils";
import { createPaginatedResponse } from "../factories";
import { PulsePage } from "@/pages/pulse";
import { PERMISSION_EVENT } from "@/components/layout/proactive-notification-bridge";
import { useAppStore } from "@/stores/app";
import type {
  AgentRunSummary,
  Notification as AppNotification,
  ScheduledAction,
  ScheduledActionRun,
  WebPushSubscription,
} from "@/types";

const mocks = vi.hoisted(() => ({
  createScheduledAction: vi.fn(),
  deleteScheduledAction: vi.fn(),
  disconnectWebPushSubscription: vi.fn(),
  getAgentRuns: vi.fn(),
  getNotifications: vi.fn(),
  getWebPushConfig: vi.fn(),
  listScheduledActionRuns: vi.fn(),
  listScheduledActions: vi.fn(),
  listWebPushSubscriptions: vi.fn(),
  requestPermission: vi.fn(),
  runScheduledActionNow: vi.fn(),
  updateScheduledAction: vi.fn(),
}));

const originalNotificationDescriptor = Object.getOwnPropertyDescriptor(globalThis, "Notification");

vi.mock("@/api/agent-runs", () => ({
  getAgentRuns: mocks.getAgentRuns,
}));

vi.mock("@/api/notifications", () => ({
  getNotifications: mocks.getNotifications,
  getWebPushConfig: mocks.getWebPushConfig,
  listWebPushSubscriptions: mocks.listWebPushSubscriptions,
}));

vi.mock("@/api/scheduled-actions", () => ({
  createScheduledAction: mocks.createScheduledAction,
  deleteScheduledAction: mocks.deleteScheduledAction,
  listScheduledActionRuns: mocks.listScheduledActionRuns,
  listScheduledActions: mocks.listScheduledActions,
  runScheduledActionNow: mocks.runScheduledActionNow,
  updateScheduledAction: mocks.updateScheduledAction,
}));

vi.mock("@/lib/web-push", () => ({
  disconnectWebPushSubscription: mocks.disconnectWebPushSubscription,
}));

vi.mock("@/components/ui/page-transition", () => ({
  PageTransition: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("@/components/ui/page-header", () => ({
  PageHeader: ({ subtitle, title }: { subtitle: string; title: string }) => (
    <div>
      <h1>{title}</h1>
      <p>{subtitle}</p>
    </div>
  ),
}));

vi.mock("@/components/ui/page-error", () => ({
  PageError: ({ message, onRetry }: { message: string; onRetry: () => void }) => (
    <div>
      <p>Page Error: {message}</p>
      <button type="button" onClick={onRetry}>
        Retry
      </button>
    </div>
  ),
}));

vi.mock("@/components/ui/empty-state", () => ({
  EmptyState: ({ description, title }: { description?: string; title: string }) => (
    <div>
      <p>{title}</p>
      {description ? <p>{description}</p> : null}
    </div>
  ),
}));

function createScheduledAction(overrides: Partial<ScheduledAction> = {}): ScheduledAction {
  return {
    id: "action-1",
    user_id: "user-1",
    title: "Morning scan",
    prompt: "Review overnight changes",
    schedule_type: "daily",
    schedule_config: { hour: 8, minute: 30 },
    timezone: "Europe/London",
    status: "active",
    delivery_channel: "web",
    next_run_at: "2026-08-03T08:30:00Z",
    last_run_at: "2026-08-02T08:30:00Z",
    last_result_summary: "No urgent changes",
    metadata: {},
    created_at: "2026-08-01T10:00:00Z",
    updated_at: "2026-08-02T08:30:00Z",
    ...overrides,
  };
}

function createScheduledRun(overrides: Partial<ScheduledActionRun> = {}): ScheduledActionRun {
  return {
    id: "run-1",
    action_id: "action-1",
    workflow_id: "workflow-1",
    status: "completed",
    result_summary: "Run completed",
    error_message: null,
    payload: {},
    triggered_at: "2026-08-02T08:30:00Z",
    completed_at: "2026-08-02T08:31:00Z",
    created_at: "2026-08-02T08:30:00Z",
    ...overrides,
  };
}

function createNotification(overrides: Partial<AppNotification> = {}): AppNotification {
  return {
    id: "notification-1",
    message: "Morning scan is ready",
    priority: "P1",
    category: "proactive",
    created_at: "2026-08-02T08:31:00Z",
    dismissed: false,
    ...overrides,
  };
}

function createAgentRun(overrides: Partial<AgentRunSummary> = {}): AgentRunSummary {
  return {
    id: "agent-run-1",
    source: "scheduled_action",
    status: "waiting_for_approval",
    specialist: "research",
    request_excerpt: "Review changes",
    pending_approvals: 1,
    created_at: "2026-08-02T08:30:00Z",
    updated_at: "2026-08-02T08:31:00Z",
    ...overrides,
  };
}

function createPushSubscription(overrides: Partial<WebPushSubscription> = {}): WebPushSubscription {
  return {
    id: "push-1",
    status: "active",
    endpoint_preview: "https://push.example/subscription",
    endpoint_host: "push.example",
    expiration_time: null,
    user_agent: "Test browser",
    failure_count: 0,
    last_seen_at: "2026-08-02T08:00:00Z",
    last_success_at: "2026-08-02T08:01:00Z",
    last_failure_at: null,
    last_error: null,
    created_at: "2026-08-01T08:00:00Z",
    updated_at: "2026-08-02T08:01:00Z",
    ...overrides,
  };
}

function setNotificationApi(
  permission: NotificationPermission = "default",
  requestPermission = mocks.requestPermission,
): void {
  Object.defineProperty(globalThis, "Notification", {
    configurable: true,
    value: {
      permission,
      requestPermission,
    },
    writable: true,
  });
}

function createDeferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
} {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

describe("PulsePage", () => {
  beforeEach(() => {
    for (const mock of Object.values(mocks)) {
      mock.mockReset();
    }

    mocks.listScheduledActions.mockResolvedValue(createPaginatedResponse([]));
    mocks.listScheduledActionRuns.mockResolvedValue([]);
    mocks.getNotifications.mockResolvedValue(createPaginatedResponse([]));
    mocks.getWebPushConfig.mockResolvedValue({
      enabled: false,
      public_key: null,
      active_subscription_count: 0,
    });
    mocks.listWebPushSubscriptions.mockResolvedValue([]);
    mocks.getAgentRuns.mockResolvedValue(createPaginatedResponse([]));
    mocks.createScheduledAction.mockResolvedValue(createScheduledAction());
    mocks.updateScheduledAction.mockResolvedValue(createScheduledAction());
    mocks.deleteScheduledAction.mockResolvedValue(undefined);
    mocks.runScheduledActionNow.mockResolvedValue(createScheduledRun());
    mocks.disconnectWebPushSubscription.mockResolvedValue(undefined);
    mocks.requestPermission.mockResolvedValue("granted");
    setNotificationApi();

    useAppStore.setState({
      inspectedAgentRunId: null,
      rightPanelContent: null,
      rightPanelOpen: false,
      runtimeStreamStatus: "idle",
    });
  });

  afterEach(() => {
    if (originalNotificationDescriptor) {
      Object.defineProperty(globalThis, "Notification", originalNotificationDescriptor);
      return;
    }
    Reflect.deleteProperty(globalThis, "Notification");
  });

  it("renders the independent loading states", () => {
    const pending = new Promise(() => {});
    mocks.listScheduledActions.mockReturnValue(pending);
    mocks.listScheduledActionRuns.mockReturnValue(pending);
    mocks.getNotifications.mockReturnValue(pending);
    mocks.getWebPushConfig.mockReturnValue(pending);
    mocks.listWebPushSubscriptions.mockReturnValue(pending);
    mocks.getAgentRuns.mockReturnValue(pending);
    useAppStore.setState({ runtimeStreamStatus: "live" });

    const { container } = renderWithProviders(<PulsePage />);

    expect(screen.getByRole("heading", { name: "Pulse" })).toBeInTheDocument();
    expect(screen.getByText("Runtime stream live")).toBeInTheDocument();
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThanOrEqual(6);
  });

  it("shows the scheduled-action error, retries it, and renders all empty states", async () => {
    const user = userEvent.setup();
    mocks.listScheduledActions
      .mockRejectedValueOnce(new Error("scheduled actions unavailable"))
      .mockResolvedValueOnce(createPaginatedResponse([]));
    useAppStore.setState({ runtimeStreamStatus: "error" });

    renderWithProviders(<PulsePage />);

    expect(
      await screen.findByText("Page Error: scheduled actions unavailable"),
    ).toBeInTheDocument();
    expect(screen.getByText("Runtime stream error")).toBeInTheDocument();
    expect(await screen.findByText("No runs recorded yet.")).toBeInTheDocument();
    expect(screen.getByText("No proactive notifications yet.")).toBeInTheDocument();
    expect(screen.getByText("No pending run approvals right now.")).toBeInTheDocument();
    expect(
      screen.getByText("No browser has completed server push registration yet."),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("No scheduled actions yet")).toBeInTheDocument();
    expect(mocks.listScheduledActions).toHaveBeenCalledTimes(2);
  });

  it("renders operational data and drives action, approval, push, and permission controls", async () => {
    const user = userEvent.setup();
    const activeAction = createScheduledAction();
    const pausedAction = createScheduledAction({
      id: "action-2",
      title: "Weekly briefing",
      schedule_type: "weekly",
      schedule_config: { hour: 7, minute: 5, weekday: 2 },
      status: "paused",
      delivery_channel: "telegram",
      next_run_at: null,
      last_result_summary: null,
    });
    const archivedAction = createScheduledAction({
      id: "action-3",
      title: "Archived scan",
      status: "archived",
    });
    const subscriptions = [
      createPushSubscription(),
      createPushSubscription({
        id: "push-2",
        endpoint_host: null,
        last_success_at: null,
        status: "error",
      }),
    ];

    mocks.listScheduledActions.mockResolvedValue(
      createPaginatedResponse([activeAction, pausedAction, archivedAction]),
    );
    mocks.listScheduledActionRuns.mockResolvedValue([
      createScheduledRun(),
      createScheduledRun({
        id: "run-2",
        status: "failed",
        result_summary: null,
        error_message: "Provider timed out",
      }),
      createScheduledRun({
        id: "run-3",
        status: "running",
        result_summary: null,
        error_message: null,
      }),
    ]);
    mocks.getNotifications.mockResolvedValue(
      createPaginatedResponse([createNotification({ priority: "P0" })]),
    );
    mocks.getWebPushConfig.mockResolvedValue({
      enabled: true,
      public_key: "public-key",
      active_subscription_count: 2,
    });
    mocks.listWebPushSubscriptions.mockResolvedValue(subscriptions);
    mocks.getAgentRuns.mockResolvedValue(
      createPaginatedResponse([
        createAgentRun(),
        createAgentRun({
          id: "agent-run-2",
          specialist: null,
          pending_approvals: 2,
        }),
        createAgentRun({
          id: "agent-run-complete",
          pending_approvals: 0,
          status: "completed",
        }),
      ]),
    );

    const permissionListener = vi.fn();
    window.addEventListener(PERMISSION_EVENT, permissionListener);

    renderWithProviders(<PulsePage />);

    expect(await screen.findByText("Morning scan")).toBeInTheDocument();
    expect(screen.getByText("Weekly briefing")).toBeInTheDocument();
    expect(screen.getByText("Archived scan")).toBeInTheDocument();
    expect(screen.getAllByText("No urgent changes")).toHaveLength(2);
    expect(screen.getAllByText(/daily · web · next/)).toHaveLength(2);
    expect(screen.getByText(/weekly · telegram · next not scheduled/)).toBeInTheDocument();
    expect(screen.getByText("Run completed")).toBeInTheDocument();
    expect(screen.getByText("Provider timed out")).toBeInTheDocument();
    expect(screen.getByText("No summary available")).toBeInTheDocument();
    expect(screen.getByText("Morning scan is ready")).toBeInTheDocument();
    expect(screen.getByText("Server push ready")).toBeInTheDocument();
    expect(screen.getByText("2 browsers")).toBeInTheDocument();
    expect(screen.getByText("push.example")).toBeInTheDocument();
    expect(screen.getByText("Browser subscription")).toBeInTheDocument();
    expect(screen.getByText(/last ok/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^research run/ }));
    expect(useAppStore.getState().inspectedAgentRunId).toBe("agent-run-1");
    expect(useAppStore.getState().rightPanelContent).toBe("agent-run");
    expect(useAppStore.getState().rightPanelOpen).toBe(true);

    await user.click(screen.getAllByRole("button", { name: "Run now" })[0]);
    await waitFor(() => {
      expect(mocks.runScheduledActionNow).toHaveBeenCalledWith("action-1");
    });

    await user.click(screen.getByRole("button", { name: "Pause" }));
    await user.click(screen.getAllByRole("button", { name: "Resume" })[0]);
    await waitFor(() => {
      expect(mocks.updateScheduledAction).toHaveBeenCalledWith("action-1", { status: "paused" });
      expect(mocks.updateScheduledAction).toHaveBeenCalledWith("action-2", { status: "active" });
    });

    await user.click(screen.getAllByRole("button", { name: "Delete" })[2]);
    await waitFor(() => {
      expect(mocks.deleteScheduledAction).toHaveBeenCalledWith("action-3");
    });

    await user.click(screen.getAllByRole("button", { name: "Disconnect" })[0]);
    await waitFor(() => {
      expect(mocks.disconnectWebPushSubscription).toHaveBeenCalledWith(
        subscriptions[0],
        expect.anything(),
      );
    });

    await user.click(
      screen.getByRole("checkbox", {
        name: /I understand the lock-screen and push-provider metadata exposure/,
      }),
    );
    await user.click(screen.getByRole("button", { name: "Request permission" }));

    await waitFor(() => {
      expect(mocks.requestPermission).toHaveBeenCalledTimes(1);
      expect(permissionListener).toHaveBeenCalledTimes(1);
    });
    expect(screen.getByText("granted")).toBeInTheDocument();

    window.removeEventListener(PERMISSION_EVENT, permissionListener);
  });

  it("creates each schedule shape and resets the composer after success", async () => {
    const user = userEvent.setup();
    renderWithProviders(<PulsePage />);

    await screen.findByText("No scheduled actions yet");

    const title = screen.getByLabelText("Scheduled action title");
    const prompt = screen.getByLabelText("Scheduled action prompt");
    const frequency = screen.getByLabelText("Scheduled action frequency");
    const delivery = screen.getByLabelText("Scheduled action delivery channel");

    await user.type(title, "Weekly research");
    await user.type(prompt, "Review the weekly sources");
    await user.selectOptions(frequency, "weekly");
    await user.selectOptions(delivery, "telegram");
    await user.clear(screen.getByLabelText("Scheduled action hour"));
    await user.type(screen.getByLabelText("Scheduled action hour"), "06");
    await user.clear(screen.getByLabelText("Scheduled action minute"));
    await user.type(screen.getByLabelText("Scheduled action minute"), "15");
    await user.selectOptions(screen.getByLabelText("Scheduled action weekday"), "1");
    await user.click(screen.getByRole("button", { name: "Create action" }));

    await waitFor(() => {
      expect(mocks.createScheduledAction).toHaveBeenLastCalledWith({
        delivery_channel: "telegram",
        prompt: "Review the weekly sources",
        schedule_config: { hour: 6, minute: 15, weekday: 1 },
        schedule_type: "weekly",
        timezone: expect.any(String),
        title: "Weekly research",
      });
    });
    await waitFor(() => {
      expect(title).toHaveValue("");
      expect(frequency).toHaveValue("daily");
      expect(delivery).toHaveValue("web");
    });

    await user.type(title, "Monthly review");
    await user.type(prompt, "Prepare the monthly review");
    await user.selectOptions(frequency, "monthly");
    await user.clear(screen.getByLabelText("Scheduled action day of month"));
    await user.clear(screen.getByLabelText("Scheduled action hour"));
    await user.clear(screen.getByLabelText("Scheduled action minute"));
    await user.click(screen.getByRole("button", { name: "Create action" }));

    await waitFor(() => {
      expect(mocks.createScheduledAction).toHaveBeenLastCalledWith(
        expect.objectContaining({
          schedule_config: { day: 1, hour: 8, minute: 0 },
          schedule_type: "monthly",
        }),
      );
    });

    await user.type(title, "One-off check");
    await user.type(prompt, "Run this once");
    await user.selectOptions(frequency, "once");
    await user.click(screen.getByRole("button", { name: "Create action" }));

    await waitFor(() => {
      expect(mocks.createScheduledAction).toHaveBeenLastCalledWith(
        expect.objectContaining({
          schedule_config: { run_at: undefined },
          schedule_type: "once",
        }),
      );
    });

    await user.type(title, "Dated check");
    await user.type(prompt, "Run at the selected time");
    await user.selectOptions(frequency, "once");
    const runAt = screen.getByLabelText("Scheduled action run time");
    await user.type(runAt, "2026-08-05T09:45");
    await user.click(screen.getByRole("button", { name: "Create action" }));

    await waitFor(() => {
      expect(mocks.createScheduledAction).toHaveBeenLastCalledWith(
        expect.objectContaining({
          schedule_config: { run_at: new Date("2026-08-05T09:45").toISOString() },
          schedule_type: "once",
        }),
      );
    });
  }, 30_000);

  it("loads an action into the composer, updates it, and supports cancel and delete reset", async () => {
    const user = userEvent.setup();
    const weeklyAction = createScheduledAction({
      id: "action-weekly",
      title: "Wednesday scan",
      prompt: "Inspect midweek status",
      schedule_type: "weekly",
      schedule_config: { hour: 5, minute: 7, weekday: 2 },
      delivery_channel: "email",
    });
    const onceAction = createScheduledAction({
      id: "action-once",
      title: "One-off scan",
      prompt: "Inspect one time",
      schedule_type: "once",
      schedule_config: { run_at: "2026-08-06T10:20:00Z" },
    });
    mocks.listScheduledActions.mockResolvedValue(
      createPaginatedResponse([weeklyAction, onceAction]),
    );

    renderWithProviders(<PulsePage />);

    await screen.findByText("Wednesday scan");
    await user.click(screen.getAllByRole("button", { name: "Edit" })[0]);

    expect(screen.getByLabelText("Scheduled action title")).toHaveValue("Wednesday scan");
    expect(screen.getByLabelText("Scheduled action prompt")).toHaveValue("Inspect midweek status");
    expect(screen.getByLabelText("Scheduled action frequency")).toHaveValue("weekly");
    expect(screen.getByLabelText("Scheduled action delivery channel")).toHaveValue("email");
    expect(screen.getByLabelText("Scheduled action hour")).toHaveValue("05");
    expect(screen.getByLabelText("Scheduled action minute")).toHaveValue("07");
    expect(screen.getByLabelText("Scheduled action weekday")).toHaveValue("2");

    await user.clear(screen.getByLabelText("Scheduled action prompt"));
    await user.type(screen.getByLabelText("Scheduled action prompt"), "Updated midweek status");
    await user.click(screen.getByRole("button", { name: "Update action" }));

    await waitFor(() => {
      expect(mocks.updateScheduledAction).toHaveBeenCalledWith(
        "action-weekly",
        expect.objectContaining({
          delivery_channel: "email",
          prompt: "Updated midweek status",
          schedule_config: { hour: 5, minute: 7, weekday: 2 },
          schedule_type: "weekly",
          title: "Wednesday scan",
        }),
      );
    });
    expect(await screen.findByRole("button", { name: "Create action" })).toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: "Edit" })[1]);
    expect(screen.getByLabelText("Scheduled action run time")).toHaveValue("2026-08-06T10:20");
    await user.click(screen.getByRole("button", { name: "Cancel edit" }));
    expect(screen.getByLabelText("Scheduled action frequency")).toHaveValue("daily");

    await user.click(screen.getAllByRole("button", { name: "Edit" })[0]);
    await user.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    await waitFor(() => {
      expect(mocks.deleteScheduledAction).toHaveBeenCalledWith("action-weekly");
    });
    expect(await screen.findByRole("button", { name: "Create action" })).toBeInTheDocument();
  }, 30_000);

  it("shows operation-specific pending states and tolerates missing schedule configuration", async () => {
    const user = userEvent.setup();
    const action = createScheduledAction({
      schedule_config: undefined as unknown as Record<string, unknown>,
    });
    const subscription = createPushSubscription();
    const runDeferred = createDeferred<ScheduledActionRun>();
    const statusDeferred = createDeferred<ScheduledAction>();
    const editDeferred = createDeferred<ScheduledAction>();
    const deleteDeferred = createDeferred<void>();
    const disconnectDeferred = createDeferred<void>();

    mocks.listScheduledActions.mockResolvedValue(createPaginatedResponse([action]));
    mocks.listWebPushSubscriptions.mockResolvedValue([subscription]);
    mocks.runScheduledActionNow.mockReturnValueOnce(runDeferred.promise);
    mocks.updateScheduledAction
      .mockReturnValueOnce(statusDeferred.promise)
      .mockReturnValueOnce(editDeferred.promise);
    mocks.deleteScheduledAction.mockReturnValueOnce(deleteDeferred.promise);
    mocks.disconnectWebPushSubscription.mockReturnValueOnce(disconnectDeferred.promise);

    renderWithProviders(<PulsePage />);

    expect(await screen.findByText("1 browser")).toBeInTheDocument();

    const runNowButton = screen.getByRole("button", { name: "Run now" });
    await user.click(runNowButton);
    await waitFor(() => {
      expect(runNowButton).toBeDisabled();
    });
    act(() => runDeferred.resolve(createScheduledRun()));
    await waitFor(() => {
      expect(runNowButton).toBeEnabled();
    });

    const pauseButton = screen.getByRole("button", { name: "Pause" });
    await user.click(pauseButton);
    await waitFor(() => {
      expect(pauseButton).toBeDisabled();
    });
    act(() => statusDeferred.resolve(createScheduledAction({ status: "paused" })));
    await waitFor(() => {
      expect(pauseButton).toBeEnabled();
    });

    await user.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByLabelText("Scheduled action hour")).toHaveValue("08");
    expect(screen.getByLabelText("Scheduled action minute")).toHaveValue("00");
    const updateButton = screen.getByRole("button", { name: "Update action" });
    await user.click(updateButton);
    await waitFor(() => {
      expect(updateButton).toBeDisabled();
    });
    act(() => editDeferred.resolve(action));
    expect(await screen.findByRole("button", { name: "Create action" })).toBeInTheDocument();

    const deleteButton = screen.getByRole("button", { name: "Delete" });
    await user.click(deleteButton);
    await waitFor(() => {
      expect(deleteButton).toBeDisabled();
    });
    act(() => deleteDeferred.resolve());
    await waitFor(() => {
      expect(deleteButton).toBeEnabled();
    });

    const disconnectButton = screen.getByRole("button", { name: "Disconnect" });
    await user.click(disconnectButton);
    await waitFor(() => {
      expect(disconnectButton).toBeDisabled();
    });
    act(() => disconnectDeferred.resolve());
    await waitFor(() => {
      expect(disconnectButton).toBeEnabled();
    });
  });

  it("handles denied and disappearing browser notification APIs", async () => {
    const user = userEvent.setup();
    mocks.requestPermission.mockResolvedValueOnce("denied");
    renderWithProviders(<PulsePage />);

    const riskCheckbox = screen.getByRole("checkbox", {
      name: /I understand the lock-screen and push-provider metadata exposure/,
    });
    await user.click(riskCheckbox);
    await user.click(screen.getByRole("button", { name: "Request permission" }));

    expect(await screen.findByText("denied")).toBeInTheDocument();

    setNotificationApi("default");
    const secondRender = renderWithProviders(<PulsePage />);
    const secondCheckbox = within(secondRender.container).getByRole("checkbox", {
      name: /I understand the lock-screen and push-provider metadata exposure/,
    });
    await user.click(secondCheckbox);
    Reflect.deleteProperty(globalThis, "Notification");
    await user.click(
      within(secondRender.container).getByRole("button", { name: "Request permission" }),
    );

    expect(await within(secondRender.container).findByText("unsupported")).toBeInTheDocument();
  });
});
