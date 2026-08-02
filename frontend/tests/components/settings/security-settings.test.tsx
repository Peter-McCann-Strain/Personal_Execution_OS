import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { SecuritySettings } from "@/components/settings/security-settings";
import { act, renderWithProviders, screen, waitFor } from "../../test-utils";

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

  it.each([
    ["short", "a-new-owner-password"],
    ["current-owner-password", "short"],
  ])(
    "rejects short credentials before calling the password endpoint",
    async (currentPassword, newPassword) => {
      renderWithProviders(<SecuritySettings />);

      fireEvent.change(screen.getByLabelText("Current password"), {
        target: { value: currentPassword },
      });
      fireEvent.change(screen.getByLabelText("New password"), {
        target: { value: newPassword },
      });
      fireEvent.change(screen.getByLabelText("Confirm new password"), {
        target: { value: newPassword },
      });
      fireEvent.click(
        screen.getByRole("button", {
          name: "Change password and sign out all devices",
        }),
      );

      expect(await screen.findByRole("alert")).toHaveTextContent("at least 12 characters");
      expect(mocks.changeOwnerPassword).not.toHaveBeenCalled();
    },
  );

  it("shows a password-change failure without clearing state or navigating", async () => {
    mocks.changeOwnerPassword.mockRejectedValue(new Error("current password rejected"));
    renderWithProviders(<SecuritySettings />);

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

    expect(await screen.findByRole("alert")).toHaveTextContent("current password rejected");
    expect(mocks.navigate).not.toHaveBeenCalled();
  });

  it("uses a safe password-change error for non-Error failures", async () => {
    mocks.changeOwnerPassword.mockRejectedValue({ provider_payload: "do not expose" });
    renderWithProviders(<SecuritySettings />);

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

    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to change password");
    expect(screen.getByRole("alert")).not.toHaveTextContent("do not expose");
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

  it("keeps the revoke dialog open when session revocation fails", async () => {
    mocks.revokeAllOwnerSessions.mockRejectedValue(new Error("password was not accepted"));
    renderWithProviders(<SecuritySettings />);

    fireEvent.click(screen.getByRole("button", { name: "Sign out every device" }));
    fireEvent.change(screen.getAllByLabelText("Current password")[1], {
      target: { value: "current-owner-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Revoke sessions and sign out" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("password was not accepted");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(mocks.navigate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("uses a safe revocation error for non-Error failures", async () => {
    mocks.revokeAllOwnerSessions.mockRejectedValue({ provider_payload: "do not expose" });
    renderWithProviders(<SecuritySettings />);

    fireEvent.click(screen.getByRole("button", { name: "Sign out every device" }));
    fireEvent.change(screen.getAllByLabelText("Current password")[1], {
      target: { value: "current-owner-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Revoke sessions and sign out" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to revoke sessions");
    expect(screen.getByRole("alert")).not.toHaveTextContent("do not expose");

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("cannot dismiss the revocation dialog while the request is pending", async () => {
    let resolveRevocation!: () => void;
    mocks.revokeAllOwnerSessions.mockReturnValue(
      new Promise<void>((resolve) => {
        resolveRevocation = resolve;
      }),
    );
    renderWithProviders(<SecuritySettings />);

    fireEvent.click(screen.getByRole("button", { name: "Sign out every device" }));
    fireEvent.change(screen.getAllByLabelText("Current password")[1], {
      target: { value: "current-owner-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Revoke sessions and sign out" }));
    await waitFor(() => expect(mocks.revokeAllOwnerSessions).toHaveBeenCalledOnce());

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await act(async () => {
      resolveRevocation();
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });
});
