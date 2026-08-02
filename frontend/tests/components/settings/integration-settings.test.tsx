import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { act, renderWithProviders, screen, waitFor, within } from "../../test-utils";
import { IntegrationSettings } from "@/components/settings/integration-settings";

const mocks = vi.hoisted(() => ({
  apiPost: vi.fn(),
  deleteConnectorAccount: vi.fn(),
  getHealth: vi.fn(),
  listConnectorAccounts: vi.fn(),
  listConnectorDocuments: vi.fn(),
  listConnectorSyncJobs: vi.fn(),
  startGoogleOAuth: vi.fn(),
  syncConnectorAccount: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
  updateConnectorAccount: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  api: {
    post: mocks.apiPost,
  },
}));

vi.mock("@/api/monitoring", () => ({
  getHealth: mocks.getHealth,
}));

vi.mock("@/api/connectors", () => ({
  deleteConnectorAccount: mocks.deleteConnectorAccount,
  listConnectorAccounts: mocks.listConnectorAccounts,
  listConnectorDocuments: mocks.listConnectorDocuments,
  listConnectorSyncJobs: mocks.listConnectorSyncJobs,
  startGoogleOAuth: mocks.startGoogleOAuth,
  syncConnectorAccount: mocks.syncConnectorAccount,
  updateConnectorAccount: mocks.updateConnectorAccount,
}));

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
    success: mocks.toastSuccess,
  },
}));

function makeHealthStatus() {
  return {
    status: "degraded",
    services: {
      llm: { status: "ok", message: "Connected" },
      ollama: { status: "down", message: "Local runtime unavailable" },
      gmail: { status: "unknown" },
      tavily: { status: "ok" },
    },
  };
}

describe("IntegrationSettings", () => {
  beforeEach(() => {
    mocks.apiPost.mockReset();
    mocks.deleteConnectorAccount.mockReset();
    mocks.getHealth.mockReset();
    mocks.listConnectorAccounts.mockReset();
    mocks.listConnectorDocuments.mockReset();
    mocks.listConnectorSyncJobs.mockReset();
    mocks.startGoogleOAuth.mockReset();
    mocks.syncConnectorAccount.mockReset();
    mocks.toastError.mockReset();
    mocks.toastSuccess.mockReset();
    mocks.updateConnectorAccount.mockReset();
    mocks.listConnectorAccounts.mockResolvedValue([]);
    mocks.listConnectorSyncJobs.mockResolvedValue([]);
    mocks.listConnectorDocuments.mockResolvedValue({ items: [], total: 0 });
    mocks.deleteConnectorAccount.mockResolvedValue(undefined);
  });

  it("renders integration health and tests a successful connection", async () => {
    mocks.getHealth.mockResolvedValue(makeHealthStatus());
    mocks.apiPost.mockResolvedValue({ status: "ok" });

    renderWithProviders(<IntegrationSettings />);

    expect(await screen.findByText("Anthropic")).toBeInTheDocument();
    expect(screen.getAllByText("not_connected").length).toBeGreaterThan(0);

    const buttons = screen.getAllByRole("button", { name: "Test Connection" });
    await waitFor(() => {
      expect(buttons[0]).toBeEnabled();
      expect(buttons[1]).toBeEnabled();
    });
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("Local runtime unavailable")).toBeInTheDocument();

    fireEvent.click(buttons[0]);

    await waitFor(() => {
      expect(mocks.apiPost).toHaveBeenCalledWith("/settings/integrations/anthropic/test");
    });
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Anthropic connection successful");
  });

  it("surfaces failed connection tests", async () => {
    mocks.getHealth.mockResolvedValue(makeHealthStatus());
    mocks.apiPost.mockRejectedValueOnce(new Error("ollama failed"));

    renderWithProviders(<IntegrationSettings />);

    const buttons = await screen.findAllByRole("button", { name: "Test Connection" });
    await waitFor(() => {
      expect(buttons[1]).toBeEnabled();
    });
    fireEvent.click(buttons[1]);

    await waitFor(() => {
      expect(mocks.apiPost).toHaveBeenCalledWith("/settings/integrations/ollama/test");
    });

    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("Ollama connection failed", {
        description: "ollama failed",
      });
    });
  });

  it("pauses sync without deleting the connector account or local data", async () => {
    mocks.getHealth.mockResolvedValue(makeHealthStatus());
    mocks.listConnectorAccounts.mockResolvedValue([makeConnectedGmailAccount()]);
    mocks.updateConnectorAccount.mockResolvedValue({
      ...makeConnectedGmailAccount(),
      sync_enabled: false,
    });

    renderWithProviders(<IntegrationSettings />);

    fireEvent.click(await screen.findByRole("button", { name: "Pause sync" }));

    await waitFor(() => {
      expect(mocks.updateConnectorAccount).toHaveBeenCalledWith("gmail-account", {
        sync_enabled: false,
      });
    });
    expect(mocks.deleteConnectorAccount).not.toHaveBeenCalled();
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Gmail sync paused");
  });

  it("requires confirmation before revoking access and deleting local connector data", async () => {
    mocks.getHealth.mockResolvedValue(makeHealthStatus());
    mocks.listConnectorAccounts.mockResolvedValue([makeConnectedGmailAccount()]);

    renderWithProviders(<IntegrationSettings />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Disconnect and delete local data" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("This cannot be undone");
    expect(mocks.deleteConnectorAccount).not.toHaveBeenCalled();

    fireEvent.click(
      within(dialog).getByRole("button", { name: "Disconnect and permanently delete" }),
    );

    await waitFor(() => {
      expect(mocks.deleteConnectorAccount).toHaveBeenCalledWith("gmail-account");
    });
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Gmail disconnected and local data deleted");
  });

  it("does not claim deletion when provider revocation fails and shows recovery guidance", async () => {
    mocks.getHealth.mockResolvedValue(makeHealthStatus());
    mocks.listConnectorAccounts.mockResolvedValue([makeConnectedGmailAccount()]);
    mocks.deleteConnectorAccount.mockRejectedValue(new Error("Google token revocation failed"));

    renderWithProviders(<IntegrationSettings />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Disconnect and delete local data" }),
    );
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Disconnect and permanently delete",
      }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nothing was deleted");
    expect(alert).toHaveTextContent("revoke Execution OS in the provider account");
    expect(mocks.toastSuccess).not.toHaveBeenCalledWith(
      "Gmail disconnected and local data deleted",
    );

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("cannot dismiss disconnect confirmation while provider revocation is pending", async () => {
    let resolveDisconnect!: () => void;
    mocks.getHealth.mockResolvedValue(makeHealthStatus());
    mocks.listConnectorAccounts.mockResolvedValue([makeConnectedGmailAccount()]);
    mocks.deleteConnectorAccount.mockReturnValue(
      new Promise<void>((resolve) => {
        resolveDisconnect = resolve;
      }),
    );

    renderWithProviders(<IntegrationSettings />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Disconnect and delete local data" }),
    );
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Disconnect and permanently delete",
      }),
    );
    await waitFor(() => expect(mocks.deleteConnectorAccount).toHaveBeenCalledOnce());

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await act(async () => {
      resolveDisconnect();
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("starts Google OAuth and reports authorization-start failures", async () => {
    mocks.getHealth.mockResolvedValue(makeHealthStatus());
    mocks.startGoogleOAuth.mockRejectedValue(new Error("OAuth configuration missing"));

    renderWithProviders(<IntegrationSettings />);
    const connectButtons = await screen.findAllByRole("button", { name: "Connect" });
    fireEvent.click(connectButtons[0]);

    await waitFor(() => {
      expect(mocks.startGoogleOAuth).toHaveBeenCalledWith("gmail");
      expect(mocks.toastError).toHaveBeenCalledWith("Unable to update Gmail", {
        description: "OAuth configuration missing",
      });
    });
  });

  it("updates connector permissions independently", async () => {
    const account = makeConnectedGmailAccount();
    mocks.getHealth.mockResolvedValue(makeHealthStatus());
    mocks.listConnectorAccounts.mockResolvedValue([account]);
    mocks.updateConnectorAccount.mockResolvedValue(account);

    renderWithProviders(<IntegrationSettings />);

    await screen.findByRole("button", { name: "Pause sync" });
    fireEvent.click(await screen.findByRole("button", { name: "Auto-use off" }));
    await waitFor(() => {
      expect(mocks.updateConnectorAccount).toHaveBeenCalledWith("gmail-account", {
        auto_use: false,
      });
    });

    fireEvent.click(
      screen
        .getAllByRole("button", { name: "Background on" })
        .find((button) => !button.hasAttribute("disabled"))!,
    );
    await waitFor(() => {
      expect(mocks.updateConnectorAccount).toHaveBeenCalledWith("gmail-account", {
        background_access: true,
      });
    });
  });

  it("resumes a paused connector and reports the resulting state", async () => {
    const paused = makeConnectorAccount({ sync_enabled: false });
    mocks.getHealth.mockResolvedValue(makeHealthStatus());
    mocks.listConnectorAccounts.mockResolvedValue([paused]);
    mocks.updateConnectorAccount.mockResolvedValue({ ...paused, sync_enabled: true });

    renderWithProviders(<IntegrationSettings />);
    fireEvent.click(await screen.findByRole("button", { name: "Resume sync" }));

    await waitFor(() => {
      expect(mocks.updateConnectorAccount).toHaveBeenCalledWith("gmail-account", {
        sync_enabled: true,
      });
    });
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Gmail sync resumed");
  });

  it("reports a sync-pause failure without changing the destructive state", async () => {
    mocks.getHealth.mockResolvedValue(makeHealthStatus());
    mocks.listConnectorAccounts.mockResolvedValue([makeConnectedGmailAccount()]);
    mocks.updateConnectorAccount.mockRejectedValue(new Error("write unavailable"));

    renderWithProviders(<IntegrationSettings />);
    fireEvent.click(await screen.findByRole("button", { name: "Pause sync" }));

    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("Unable to update Gmail sync", {
        description: "write unavailable",
      });
    });
    expect(screen.getByRole("button", { name: "Disconnect and delete local data" })).toBeEnabled();
  });

  it("runs incremental and full syncs with honest success and failure feedback", async () => {
    mocks.getHealth.mockResolvedValue(makeHealthStatus());
    mocks.listConnectorAccounts.mockResolvedValue([makeConnectedGmailAccount()]);
    mocks.syncConnectorAccount
      .mockResolvedValueOnce({
        id: "sync-1",
        account_id: "gmail-account",
        sync_type: "incremental",
        status: "completed",
        document_count: 3,
        error_message: null,
      })
      .mockResolvedValueOnce({
        id: "sync-2",
        account_id: "gmail-account",
        sync_type: "full",
        status: "failed",
        document_count: 0,
        error_message: null,
      });

    renderWithProviders(<IntegrationSettings />);
    await screen.findByRole("button", { name: "Pause sync" });
    const enabledSyncButton = screen
      .getAllByRole("button", { name: "Sync now" })
      .find((button) => !button.hasAttribute("disabled"));
    expect(enabledSyncButton).toBeDefined();
    fireEvent.click(enabledSyncButton!);

    await waitFor(() => {
      expect(mocks.syncConnectorAccount).toHaveBeenCalledWith("gmail-account", {
        sync_type: "incremental",
        max_items: 25,
      });
      expect(mocks.toastSuccess).toHaveBeenCalledWith("Gmail synced", {
        description: "3 documents indexed",
      });
    });

    fireEvent.click(
      screen
        .getAllByRole("button", { name: "Reindex" })
        .find((button) => !button.hasAttribute("disabled"))!,
    );
    await waitFor(() => {
      expect(mocks.syncConnectorAccount).toHaveBeenCalledWith("gmail-account", {
        sync_type: "full",
        max_items: 100,
      });
      expect(mocks.toastError).toHaveBeenCalledWith("Gmail sync failed", {
        description: "Unknown error",
      });
    });
  });

  it("reports update and sync transport failures without changing connector labels", async () => {
    mocks.getHealth.mockResolvedValue(makeHealthStatus());
    mocks.listConnectorAccounts.mockResolvedValue([makeConnectedGmailAccount()]);
    mocks.updateConnectorAccount.mockRejectedValue("non-error update failure");
    mocks.syncConnectorAccount.mockRejectedValue("non-error sync failure");

    renderWithProviders(<IntegrationSettings />);
    await screen.findByRole("button", { name: "Pause sync" });
    fireEvent.click(await screen.findByRole("button", { name: "Auto-use off" }));
    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("Update failed");
    });

    const enabledSyncButton = screen
      .getAllByRole("button", { name: "Sync now" })
      .find((button) => !button.hasAttribute("disabled"));
    expect(enabledSyncButton).toBeDefined();
    fireEvent.click(enabledSyncButton!);
    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("Gmail sync failed", {
        description: "Unknown error",
      });
    });
    expect(screen.getByRole("button", { name: "Pause sync" })).toBeInTheDocument();
  });

  it("renders indexed-document and latest-job evidence for a failed sync", async () => {
    mocks.getHealth.mockResolvedValue({
      status: "degraded",
      services: {
        llm: { status: "degraded", message: "Rate limited" },
        ollama: { status: "lagging" },
        posthog: { status: "unknown" },
        sentry: { status: "down" },
      },
    });
    mocks.listConnectorAccounts.mockResolvedValue([
      makeConnectorAccount({ last_sync_at: "2026-08-01T10:00:00Z" }),
    ]);
    mocks.listConnectorDocuments.mockResolvedValue({
      items: [
        { id: "doc-1", account_id: "gmail-account" },
        { id: "doc-2", account_id: "gmail-account" },
      ],
      total: 2,
    });
    mocks.listConnectorSyncJobs.mockResolvedValue([
      {
        id: "job-1",
        account_id: "gmail-account",
        sync_type: "full",
        status: "failed",
        error_message: "Provider quota exhausted",
      },
    ]);

    renderWithProviders(<IntegrationSettings />);

    expect(await screen.findByText("2 docs")).toBeInTheDocument();
    expect(screen.getByText("full failed")).toBeInTheDocument();
    expect(screen.getByText("Provider quota exhausted")).toBeInTheDocument();
    expect(screen.getByText("Rate limited")).toBeInTheDocument();
  });

  it("renders completed and in-progress latest-job states", async () => {
    mocks.getHealth.mockResolvedValue(makeHealthStatus());
    mocks.listConnectorAccounts.mockResolvedValue([
      makeConnectedGmailAccount(),
      makeConnectorAccount({
        id: "calendar-account",
        connector_type: "google_calendar",
        display_name: "Google Calendar",
      }),
    ]);
    mocks.listConnectorSyncJobs.mockResolvedValue([
      {
        id: "job-1",
        account_id: "gmail-account",
        sync_type: "incremental",
        status: "completed",
        error_message: null,
      },
      {
        id: "job-2",
        account_id: "calendar-account",
        sync_type: "full",
        status: "running",
        error_message: null,
      },
    ]);

    renderWithProviders(<IntegrationSettings />);

    expect(await screen.findByText("incremental completed")).toBeInTheDocument();
    expect(screen.getByText("full running")).toBeInTheDocument();
  });

  it("uses safe service-test feedback for non-Error failures", async () => {
    mocks.getHealth.mockResolvedValue(makeHealthStatus());
    mocks.apiPost.mockRejectedValue({ provider_payload: "do not expose" });

    renderWithProviders(<IntegrationSettings />);
    const buttons = await screen.findAllByRole("button", { name: "Test Connection" });
    await waitFor(() => expect(buttons[0]).toBeEnabled());
    fireEvent.click(buttons[0]);

    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("Anthropic connection failed", {
        description: "Unknown error",
      });
    });
  });
});

function makeConnectorAccount(overrides: Record<string, unknown> = {}) {
  return {
    ...makeConnectedGmailAccount(),
    ...overrides,
  };
}

function makeConnectedGmailAccount() {
  return {
    id: "gmail-account",
    user_id: "owner",
    connector_type: "gmail",
    display_name: "Gmail",
    status: "connected",
    scopes: ["https://www.googleapis.com/auth/gmail.readonly"],
    has_refresh_token: true,
    token_last_rotated_at: "2026-07-31T00:00:00Z",
    auto_use: true,
    background_access: false,
    sync_enabled: true,
    last_sync_at: null,
    metadata: {},
    created_at: "2026-07-31T00:00:00Z",
    updated_at: "2026-07-31T00:00:00Z",
  };
}
