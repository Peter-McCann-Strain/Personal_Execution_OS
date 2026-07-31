import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { DataSettings } from "@/components/settings/data-settings";
import { renderWithProviders, screen, waitFor } from "../../test-utils";

const mocks = vi.hoisted(() => ({
  clearThisDevice: vi.fn(),
  createCoreDataExport: vi.fn(),
  downloadCoreDataExport: vi.fn(),
  listCoreDataExports: vi.fn(),
  navigate: vi.fn(),
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
    error: vi.fn(),
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
});
