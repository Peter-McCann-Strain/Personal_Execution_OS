import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { DataSettings } from "@/components/settings/data-settings";
import { act, renderWithProviders, screen, waitFor } from "../../test-utils";

const mocks = vi.hoisted(() => ({
  clearThisDevice: vi.fn(),
  createCoreDataExport: vi.fn(),
  downloadCoreDataExport: vi.fn(),
  listCoreDataExports: vi.fn(),
  navigate: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
  toastWarning: vi.fn(),
}));

vi.mock("@/api/account-data", () => ({
  createCoreDataExport: mocks.createCoreDataExport,
  downloadCoreDataExport: mocks.downloadCoreDataExport,
  listCoreDataExports: mocks.listCoreDataExports,
}));

vi.mock("@/lib/device-data", () => ({
  clearThisDevice: mocks.clearThisDevice,
}));

vi.mock("react-router", async (importOriginal) => {
  const original = await importOriginal<typeof import("react-router")>();
  return {
    ...original,
    useNavigate: () => mocks.navigate,
  };
});

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
    success: mocks.toastSuccess,
    warning: mocks.toastWarning,
  },
}));

describe("DataSettings", () => {
  beforeEach(() => {
    mocks.clearThisDevice.mockReset().mockResolvedValue({ warnings: [] });
    mocks.createCoreDataExport.mockReset();
    mocks.downloadCoreDataExport.mockReset();
    mocks.listCoreDataExports.mockReset().mockResolvedValue([]);
    mocks.navigate.mockReset();
    mocks.toastError.mockReset();
    mocks.toastSuccess.mockReset();
    mocks.toastWarning.mockReset();
  });

  it("describes the core export as a subset rather than a full backup", async () => {
    renderWithProviders(<DataSettings />);

    expect(await screen.findByRole("heading", { name: "Core-data export" })).toBeInTheDocument();
    expect(screen.getByText(/documented subset/i)).toBeInTheDocument();
    expect(screen.getByText(/not a full account backup/i)).toBeInTheDocument();
    expect(screen.queryByText(/delete account/i)).not.toBeInTheDocument();
  });

  it("requires confirmation and clearly preserves server-side core records", async () => {
    renderWithProviders(<DataSettings />);

    fireEvent.click(await screen.findByRole("button", { name: "Clear this device" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Server-side goals, notes, projects");
    expect(mocks.clearThisDevice).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Clear local data and sign out" }));

    await waitFor(() => {
      expect(mocks.clearThisDevice).toHaveBeenCalledWith(expect.anything(), {
        unregisterServiceWorker: false,
      });
    });
    expect(mocks.navigate).toHaveBeenCalledWith("/login", { replace: true });
  });

  it("passes the optional service-worker removal choice and surfaces partial cleanup", async () => {
    mocks.clearThisDevice.mockResolvedValue({
      warnings: ["The server session cookie could not be revoked."],
    });
    renderWithProviders(<DataSettings />);

    fireEvent.click(await screen.findByRole("button", { name: "Clear this device" }));
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Clear local data and sign out" }));

    await waitFor(() => {
      expect(mocks.clearThisDevice).toHaveBeenCalledWith(expect.anything(), {
        unregisterServiceWorker: true,
      });
    });
    expect(mocks.toastWarning).toHaveBeenCalledWith("Device data cleared with warnings", {
      description: "The server session cookie could not be revoked.",
    });
  });

  it("queues exports and reports provider failures without claiming success", async () => {
    mocks.createCoreDataExport
      .mockResolvedValueOnce({
        id: "export-1",
        status: "pending",
        storage_url: null,
        expires_at: null,
        created_at: "2026-08-02T10:00:00Z",
        completed_at: null,
      })
      .mockRejectedValueOnce(new Error("export service unavailable"));

    renderWithProviders(<DataSettings />);

    const requestButton = await screen.findByRole("button", {
      name: "Request core-data export",
    });
    fireEvent.click(requestButton);

    await waitFor(() => {
      expect(mocks.createCoreDataExport).toHaveBeenCalledTimes(1);
      expect(mocks.toastSuccess).toHaveBeenCalledWith("Core-data export queued");
    });

    fireEvent.click(requestButton);
    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("export service unavailable");
    });
  });

  it("uses a safe export error when a dependency rejects without an Error", async () => {
    mocks.createCoreDataExport.mockRejectedValue({ provider_payload: "do not expose" });
    renderWithProviders(<DataSettings />);

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Request core-data export",
      }),
    );

    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("Unable to request export");
    });
  });

  it("renders export lifecycle rows and downloads completed payloads", async () => {
    const createObjectUrl = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:core-data-export");
    const revokeObjectUrl = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    mocks.listCoreDataExports.mockResolvedValue([
      {
        id: "completed-export",
        status: "completed",
        storage_url: null,
        expires_at: "2026-08-09T10:00:00Z",
        created_at: "2026-08-02T10:00:00Z",
        completed_at: "2026-08-02T10:05:00Z",
      },
      {
        id: "pending-export",
        status: "pending",
        storage_url: null,
        expires_at: null,
        created_at: "2026-08-01T10:00:00Z",
        completed_at: null,
      },
    ]);
    mocks.downloadCoreDataExport.mockResolvedValue({
      schema_version: "1",
      goals: [{ id: "goal-1" }],
    });

    renderWithProviders(<DataSettings />);

    expect(await screen.findByText("completed")).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Download Again" }));

    await waitFor(() => {
      expect(mocks.downloadCoreDataExport).toHaveBeenCalledWith(
        "completed-export",
        expect.anything(),
      );
    });
    expect(createObjectUrl).toHaveBeenCalledWith(expect.any(Blob));
    expect(anchorClick).toHaveBeenCalledOnce();
    expect(revokeObjectUrl).toHaveBeenCalledWith("blob:core-data-export");
  });

  it("reports download failures and leaves the export available to retry", async () => {
    mocks.listCoreDataExports.mockResolvedValue([
      {
        id: "completed-export",
        status: "completed",
        storage_url: null,
        expires_at: null,
        created_at: "2026-08-02T10:00:00Z",
        completed_at: "2026-08-02T10:05:00Z",
      },
    ]);
    mocks.downloadCoreDataExport.mockRejectedValue(new Error("download expired"));

    renderWithProviders(<DataSettings />);
    fireEvent.click(await screen.findByRole("button", { name: "Download Again" }));

    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("download expired");
    });
    expect(screen.getByRole("button", { name: "Download Again" })).toBeEnabled();
  });

  it("uses a safe download error for a non-Error rejection", async () => {
    mocks.listCoreDataExports.mockResolvedValue([
      {
        id: "completed-export",
        status: "completed",
        storage_url: null,
        expires_at: null,
        created_at: "2026-08-02T10:00:00Z",
        completed_at: "2026-08-02T10:05:00Z",
      },
    ]);
    mocks.downloadCoreDataExport.mockRejectedValue({ provider_payload: "do not expose" });

    renderWithProviders(<DataSettings />);
    fireEvent.click(await screen.findByRole("button", { name: "Download Again" }));

    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith("Unable to download export");
    });
  });

  it("shows export-list errors and retries the read without exposing controls", async () => {
    mocks.listCoreDataExports
      .mockRejectedValueOnce(new Error("database unavailable"))
      .mockResolvedValueOnce([]);

    renderWithProviders(<DataSettings />);

    expect(await screen.findByText("database unavailable")).toBeInTheDocument();
    expect(screen.getByText("Couldn't load data controls.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear this device" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("button", { name: "Clear this device" })).toBeInTheDocument();
    expect(mocks.listCoreDataExports).toHaveBeenCalledTimes(2);
  });

  it("keeps the destructive dialog open and signed-in state intact when cleanup fails", async () => {
    mocks.clearThisDevice.mockRejectedValue(new Error("session revocation failed"));
    renderWithProviders(<DataSettings />);

    fireEvent.click(await screen.findByRole("button", { name: "Clear this device" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear local data and sign out" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("session revocation failed");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(mocks.navigate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("uses a safe cleanup error for non-Error rejections", async () => {
    mocks.clearThisDevice.mockRejectedValue({ provider_payload: "do not expose" });
    renderWithProviders(<DataSettings />);

    fireEvent.click(await screen.findByRole("button", { name: "Clear this device" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear local data and sign out" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to clear this device");
    expect(screen.getByRole("alert")).not.toHaveTextContent("do not expose");
    expect(mocks.navigate).not.toHaveBeenCalled();

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("cannot dismiss the cleanup confirmation while destructive work is pending", async () => {
    let resolveCleanup!: (value: { warnings: string[] }) => void;
    mocks.clearThisDevice.mockReturnValue(
      new Promise((resolve) => {
        resolveCleanup = resolve;
      }),
    );
    renderWithProviders(<DataSettings />);

    fireEvent.click(await screen.findByRole("button", { name: "Clear this device" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear local data and sign out" }));
    await waitFor(() => expect(mocks.clearThisDevice).toHaveBeenCalledOnce());

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await act(async () => {
      resolveCleanup({ warnings: [] });
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });
});
