import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen, waitFor } from "../../test-utils";
import { ProfileSettings } from "@/components/settings/profile-settings";
import { useAppStore } from "@/stores/app";
import { mockMatchMedia, resetSettingsState } from "../../settings-test-utils";

const mocks = vi.hoisted(() => ({
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
    success: mocks.toastSuccess,
  },
}));

describe("ProfileSettings", () => {
  beforeEach(() => {
    resetSettingsState();
    mocks.toastError.mockReset();
    mocks.toastSuccess.mockReset();
  });

  it("switches appearance settings and saves profile fields", async () => {
    renderWithProviders(<ProfileSettings />);

    expect(screen.getByRole("button", { name: "Dark" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Light" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "System" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("Owner")).toBeInTheDocument();
    expect(screen.getByDisplayValue("UTC")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Light" }));
    expect(useAppStore.getState().theme).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");

    vi.mocked(window.matchMedia).mockReturnValueOnce(mockMatchMedia(true));
    fireEvent.click(screen.getByRole("button", { name: "System" }));
    expect(useAppStore.getState().theme).toBe("system");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");

    fireEvent.change(screen.getByPlaceholderText("Your name"), {
      target: { value: "Ada" },
    });
    fireEvent.change(screen.getByDisplayValue("UTC"), {
      target: { value: "America/New_York" },
    });
    fireEvent.change(screen.getByDisplayValue("09:00"), {
      target: { value: "08:30" },
    });
    fireEvent.change(screen.getByDisplayValue("17:30"), {
      target: { value: "16:00" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));

    await waitFor(() =>
      expect(useAppStore.getState().profileSettings).toEqual({
        displayName: "Ada",
        timezone: "America/New_York",
        workStart: "08:30",
        workEnd: "16:00",
      }),
    );
    expect(mocks.toastSuccess).toHaveBeenCalledWith("Profile settings saved");
  });
});
