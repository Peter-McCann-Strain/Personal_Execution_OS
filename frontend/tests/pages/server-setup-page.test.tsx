import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mocks = vi.hoisted(() => ({
  getSetupStatus: vi.fn(),
  initializeOwner: vi.fn(),
}));

vi.mock("@/api/auth", () => ({
  getSetupStatus: mocks.getSetupStatus,
  initializeOwner: mocks.initializeOwner,
}));

describe("server owner setup", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_ALLOW_INSECURE_DEV_AUTH", "");
    mocks.getSetupStatus.mockReset();
    mocks.initializeOwner.mockReset();
    mocks.getSetupStatus.mockResolvedValue({ initialized: false, auth_mode: "local_owner" });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("creates the owner and continues with the new cookie session", async () => {
    const user = userEvent.setup();
    mocks.initializeOwner.mockResolvedValue({
      authenticated: true,
      subject: "owner",
      role: "owner",
      expires_at: null,
    });
    const { SetupPage } = await import("@/pages/setup");

    render(
      <MemoryRouter initialEntries={["/setup?returnTo=%2Fdashboard"]}>
        <Routes>
          <Route path="/setup" element={<SetupPage />} />
          <Route path="/dashboard" element={<div>Dashboard landing</div>} />
          <Route path="/login" element={<div>Login landing</div>} />
        </Routes>
      </MemoryRouter>,
    );

    await user.type(await screen.findByLabelText("Owner password"), "a unique long password");
    await user.type(screen.getByLabelText("Confirm password"), "a unique long password");
    await user.click(screen.getByRole("button", { name: "Create owner and continue" }));

    await waitFor(() => {
      expect(mocks.initializeOwner).toHaveBeenCalledWith("a unique long password");
    });
    expect(await screen.findByText("Dashboard landing")).toBeInTheDocument();
  });

  it("sends initialized installations to login", async () => {
    mocks.getSetupStatus.mockResolvedValue({ initialized: true, auth_mode: "local_owner" });
    const { SetupPage } = await import("@/pages/setup");

    render(
      <MemoryRouter initialEntries={["/setup"]}>
        <Routes>
          <Route path="/setup" element={<SetupPage />} />
          <Route path="/login" element={<div>Login landing</div>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Login landing")).toBeInTheDocument();
  });
});
