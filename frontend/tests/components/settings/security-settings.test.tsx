import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { SecuritySettings } from "@/components/settings/security-settings";
import { renderWithProviders, screen, waitFor } from "../../test-utils";

const mocks = vi.hoisted(() => ({
  changeOwnerPassword: vi.fn(),
  navigate: vi.fn(),
  revokeAllOwnerSessions: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("@/api/auth", () => ({
  changeOwnerPassword: mocks.changeOwnerPassword,
  revokeAllOwnerSessions: mocks.revokeAllOwnerSessions,
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
    success: mocks.toastSuccess,
  },
}));

describe("SecuritySettings", () => {
  beforeEach(() => {
    mocks.changeOwnerPassword.mockReset().mockResolvedValue(undefined);
    mocks.navigate.mockReset();
    mocks.revokeAllOwnerSessions.mockReset().mockResolvedValue(undefined);
    mocks.toastSuccess.mockReset();
  });

  it("warns that a password change signs out every device and performs it", async () => {
    renderWithProviders(<SecuritySettings />);

    expect(screen.getByText(/immediately signs out every browser and device/i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Current password"), {
      target: { value: "current-owner-password" },
    });
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "a-new-owner-password" },
    });
    fireEvent.change(screen.getByLabelText("Confirm new password"), {
      target: { value: "a-new-owner-password" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Change password and sign out all devices" }),
    );

    await waitFor(() => {
      expect(mocks.changeOwnerPassword).toHaveBeenCalledWith(
        "current-owner-password",
        "a-new-owner-password",
      );
    });
    expect(mocks.navigate).toHaveBeenCalledWith("/login", { replace: true });
  });

  it("does not submit mismatched passwords", async () => {
    renderWithProviders(<SecuritySettings />);

    fireEvent.change(screen.getByLabelText("Current password"), {
      target: { value: "current-owner-password" },
    });
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "a-new-owner-password" },
    });
    fireEvent.change(screen.getByLabelText("Confirm new password"), {
      target: { value: "a-different-password" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Change password and sign out all devices" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("do not match");
    expect(mocks.changeOwnerPassword).not.toHaveBeenCalled();
  });

  it("requires confirmation and the current password before revoking every session", async () => {
    renderWithProviders(<SecuritySettings />);

    fireEvent.click(screen.getByRole("button", { name: "Sign out every device" }));
    expect(mocks.revokeAllOwnerSessions).not.toHaveBeenCalled();

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("device you are using now");
    const confirmButton = screen.getByRole("button", { name: "Revoke sessions and sign out" });
    expect(confirmButton).toBeDisabled();

    fireEvent.change(screen.getAllByLabelText("Current password")[1], {
      target: { value: "current-owner-password" },
    });
    fireEvent.click(confirmButton);

    await waitFor(() => {
      expect(mocks.revokeAllOwnerSessions).toHaveBeenCalledWith("current-owner-password");
    });
    expect(mocks.navigate).toHaveBeenCalledWith("/login", { replace: true });
  });
});
