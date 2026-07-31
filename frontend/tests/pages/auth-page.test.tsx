import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoginPage } from "@/pages/auth";

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
});
