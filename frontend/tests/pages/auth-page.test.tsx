import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoginPage } from "@/pages/auth";
import { ApiError } from "@/api/client";

const mocks = vi.hoisted(() => ({
  getSetupStatus: vi.fn(),
  loginWithPassword: vi.fn(),
}));

vi.mock("@/api/auth", () => ({
  getSetupStatus: mocks.getSetupStatus,
  loginWithPassword: mocks.loginWithPassword,
}));

function renderLogin(initialEntry = "/login") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/setup" element={<div>First-run setup</div>} />
        <Route path="/dashboard" element={<div>Dashboard landing</div>} />
        <Route path="/email" element={<div>Email landing</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    mocks.getSetupStatus.mockReset();
    mocks.loginWithPassword.mockReset();
    mocks.getSetupStatus.mockResolvedValue({ initialized: true, auth_mode: "local_owner" });
  });

  it("signs in with the owner password and preserves the return target", async () => {
    const user = userEvent.setup();
    mocks.loginWithPassword.mockResolvedValue({
      authenticated: true,
      subject: "owner",
      role: "owner",
      expires_at: null,
    });
    renderLogin("/login?returnTo=%2Femail");

    const password = await screen.findByLabelText("Owner password");
    await user.type(password, "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      expect(mocks.loginWithPassword).toHaveBeenCalledWith("correct horse battery staple");
    });
    expect(await screen.findByText("Email landing")).toBeInTheDocument();
  });

  it("redirects an uninitialized installation to one-time setup", async () => {
    mocks.getSetupStatus.mockResolvedValue({ initialized: false, auth_mode: "local_owner" });
    renderLogin();

    expect(await screen.findByText("First-run setup")).toBeInTheDocument();
  });

  it("surfaces setup-status failures and allows password visibility control", async () => {
    const user = userEvent.setup();
    mocks.getSetupStatus.mockRejectedValue(new Error("backend unavailable"));
    renderLogin();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not check the server setup status",
    );
    const password = screen.getByLabelText("Owner password") as HTMLInputElement;
    await user.type(password, "owner-password");
    await user.click(screen.getByRole("button", { name: "Reveal password" }));
    expect(password.type).toBe("text");
    await user.click(screen.getByRole("button", { name: "Hide password" }));
    expect(password.type).toBe("password");
  });

  it.each([
    [401, "The password was not accepted."],
    [429, "Too many attempts. Wait a moment before trying again."],
  ])("maps HTTP %s authentication failures to safe guidance", async (status, message) => {
    const user = userEvent.setup();
    mocks.loginWithPassword.mockRejectedValue(new ApiError(status, "sensitive provider detail"));
    renderLogin();

    await user.type(await screen.findByLabelText("Owner password"), "wrong password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("alert")).not.toHaveTextContent("sensitive provider detail");
  });

  it("returns an installation race to setup instead of showing a login error", async () => {
    const user = userEvent.setup();
    mocks.loginWithPassword.mockRejectedValue(new ApiError(409, "not initialized"));
    renderLogin("/login?returnTo=%2Femail");

    await user.type(await screen.findByLabelText("Owner password"), "owner password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("First-run setup")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("surfaces an unexpected login failure without navigating", async () => {
    const user = userEvent.setup();
    mocks.loginWithPassword.mockRejectedValue(new Error("identity service unavailable"));
    renderLogin();

    await user.type(await screen.findByLabelText("Owner password"), "owner password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("identity service unavailable");
    expect(screen.queryByText("Dashboard landing")).not.toBeInTheDocument();
  });

  it("uses a safe generic message for non-Error authentication failures", async () => {
    const user = userEvent.setup();
    mocks.loginWithPassword.mockRejectedValue({ provider_payload: "do not expose" });
    renderLogin();

    await user.type(await screen.findByLabelText("Owner password"), "owner password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Sign in failed. Please try again.");
    expect(screen.getByRole("alert")).not.toHaveTextContent("do not expose");
  });

  it("does not invoke authentication when an empty form is submitted", async () => {
    renderLogin();
    await screen.findByRole("button", { name: "Sign in" });
    const form = screen.getByRole("button", { name: "Sign in" }).closest("form");

    fireEvent.submit(form!);

    expect(mocks.loginWithPassword).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
