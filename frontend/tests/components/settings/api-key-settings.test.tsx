import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen, waitFor } from "../../test-utils";
import { ApiKeySettings } from "@/components/settings/api-key-settings";
import { useAppStore } from "@/stores/app";
import { resetSettingsState } from "../../settings-test-utils";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  api: {
    get: mocks.apiGet,
  },
}));

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
    success: mocks.toastSuccess,
  },
}));

describe("ApiKeySettings", () => {
  beforeEach(() => {
    resetSettingsState();
    mocks.apiGet.mockReset();
    mocks.toastError.mockReset();
    mocks.toastSuccess.mockReset();
  });

  it("renders the empty state when no key is configured", () => {
    renderWithProviders(<ApiKeySettings />);

    expect(screen.getByText("Access Credentials")).toBeInTheDocument();
    expect(screen.getAllByText("Not set").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "Save" })[0]).toBeDisabled();
    expect(screen.getByRole("button", { name: "Test Connection" })).toBeDisabled();
  });

  it("reveals, saves, and tests the api key", async () => {
    useAppStore.getState().setApiKey("abcd-1234567890-uvwxyz");
    mocks.apiGet.mockRejectedValueOnce(new Error("bad key"));

    renderWithProviders(<ApiKeySettings />);

    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("abcd**************wxyz")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Reveal API Key" }));
    expect(screen.getByText("abcd-1234567890-uvwxyz")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Hide API Key" }));
    expect(screen.getByText("abcd**************wxyz")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Paste api key..."), {
      target: { value: "sk-test-new-key-9999" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Save" })[0]);

    await waitFor(() => {
      expect(useAppStore.getState().apiKey).toBe("sk-test-new-key-9999");
      expect(sessionStorage.getItem("api_key")).toBe("sk-test-new-key-9999");
      expect(localStorage.getItem("api_key")).toBeNull();
    });
    expect(mocks.toastSuccess).toHaveBeenCalledWith("API key saved");

    fireEvent.click(screen.getByRole("button", { name: "Test Connection" }));

    await waitFor(() => {
      expect(mocks.apiGet).toHaveBeenCalledWith("/dashboard/stats");
    });
    expect(mocks.toastError).toHaveBeenCalledWith("Connection test failed");
  });

  it("never exposes a complete short credential until the user reveals it", () => {
    useAppStore.getState().setApiKey("tiny-key");

    renderWithProviders(<ApiKeySettings />);

    expect(screen.getByText("********")).toBeInTheDocument();
    expect(screen.queryByText("tiny-key")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Reveal API Key" }));
    expect(screen.getByText("tiny-key")).toBeInTheDocument();
  });

  it.each([
    ["1234567890123456789", "*******************"],
    ["12345678901234567890", "1234************7890"],
  ])("enforces the masking policy at the 20-character boundary", (apiKey, masked) => {
    useAppStore.getState().setApiKey(apiKey);

    renderWithProviders(<ApiKeySettings />);

    expect(screen.getByText(masked)).toBeInTheDocument();
    expect(screen.queryByText(apiKey)).not.toBeInTheDocument();
  });

  it("shows successful connection feedback for the currently saved key", async () => {
    useAppStore.getState().setApiKey("sk-test-1234567890");
    mocks.apiGet.mockResolvedValue({ status: "ok" });

    renderWithProviders(<ApiKeySettings />);
    fireEvent.click(screen.getByRole("button", { name: "Test Connection" }));

    await waitFor(() => {
      expect(mocks.apiGet).toHaveBeenCalledWith("/dashboard/stats");
      expect(mocks.toastSuccess).toHaveBeenCalledWith("Connection successful");
    });
  });
});
