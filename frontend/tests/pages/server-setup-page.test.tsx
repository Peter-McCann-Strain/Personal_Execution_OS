import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    await user.click(await screen.findByRole("button", { name: "Create owner and continue" }));

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

  it("surfaces setup-status failures and still renders recovery context", async () => {
    mocks.getSetupStatus.mockRejectedValue(new Error("backend unavailable"));
    const { SetupPage } = await import("@/pages/setup");

    render(
      <MemoryRouter initialEntries={["/setup"]}>
        <Routes>
          <Route path="/setup" element={<SetupPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not check setup status. Confirm the backend is running.",
    );
    expect(
      screen.getByText(/unique password stored in your password manager/i),
    ).toBeInTheDocument();
  });

  it("validates minimum length and confirmation before owner creation", async () => {
    const user = userEvent.setup();
    const { SetupPage } = await import("@/pages/setup");
    render(
      <MemoryRouter initialEntries={["/setup"]}>
        <SetupPage />
      </MemoryRouter>,
    );

    const password = await screen.findByLabelText("Owner password");
    const confirmation = screen.getByLabelText("Confirm password");
    const form = (await screen.findByRole("button", { name: "Create owner and continue" })).closest(
      "form",
    );
    expect(form).not.toBeNull();

    await user.type(password, "too short");
    await user.type(confirmation, "too short");
    fireEvent.submit(form!);
    expect(await screen.findByRole("alert")).toHaveTextContent("at least 12 characters");

    await user.clear(password);
    await user.clear(confirmation);
    await user.type(password, "a unique long password");
    await user.type(confirmation, "a different password");
    fireEvent.submit(form!);
    expect(await screen.findByRole("alert")).toHaveTextContent("passwords do not match");
    expect(mocks.initializeOwner).not.toHaveBeenCalled();
  });

  it("toggles visibility for both password fields", async () => {
    const user = userEvent.setup();
    const { SetupPage } = await import("@/pages/setup");
    render(
      <MemoryRouter initialEntries={["/setup"]}>
        <SetupPage />
      </MemoryRouter>,
    );

    const password = (await screen.findByLabelText("Owner password")) as HTMLInputElement;
    const confirmation = screen.getByLabelText("Confirm password") as HTMLInputElement;
    expect(password.type).toBe("password");
    expect(confirmation.type).toBe("password");

    await user.click(screen.getByRole("button", { name: "Reveal passwords" }));
    expect(password.type).toBe("text");
    expect(confirmation.type).toBe("text");

    await user.click(screen.getByRole("button", { name: "Hide passwords" }));
    expect(password.type).toBe("password");
    expect(confirmation.type).toBe("password");
  });

  it.each([
    ["conflict", "Setup is already complete. Go to sign in."],
    ["generic", "database unavailable"],
    ["opaque", "Setup failed. Please try again."],
  ])("keeps setup state intact when owner creation fails", async (failureKind, message) => {
    const user = userEvent.setup();
    const { ApiError: CurrentApiError } = await import("@/api/client");
    mocks.initializeOwner.mockRejectedValue(
      failureKind === "conflict"
        ? new CurrentApiError(409, "already initialized")
        : failureKind === "generic"
          ? new Error("database unavailable")
          : { provider_payload: "do not expose" },
    );
    const { SetupPage } = await import("@/pages/setup");
    render(
      <MemoryRouter initialEntries={["/setup"]}>
        <SetupPage />
      </MemoryRouter>,
    );

    await user.type(await screen.findByLabelText("Owner password"), "a unique long password");
    await user.type(screen.getByLabelText("Confirm password"), "a unique long password");
    await user.click(await screen.findByRole("button", { name: "Create owner and continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("heading", { name: "Create the owner account" })).toBeInTheDocument();
  });
});
