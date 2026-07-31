import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@/api/client";
import { AuthGate } from "@/components/auth/auth-gate";

const mocks = vi.hoisted(() => ({
  getCurrentSession: vi.fn(),
  getSetupStatus: vi.fn(),
}));

vi.mock("@/api/auth", () => ({
  getCurrentSession: mocks.getCurrentSession,
  getSetupStatus: mocks.getSetupStatus,
}));

vi.mock("@/lib/auth-mode", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth-mode")>("@/lib/auth-mode");
  return {
    ...actual,
    isLegacyDevAuthEnabled: false,
  };
});

function LocationProbe() {
  const location = useLocation();
  return <div>{`${location.pathname}${location.search}`}</div>;
}

function renderGate() {
  return render(
    <MemoryRouter initialEntries={["/settings?tab=privacy"]}>
      <Routes>
        <Route
          path="/settings"
          element={
            <AuthGate>
              <div>Protected settings</div>
            </AuthGate>
          }
        />
        <Route path="/setup" element={<LocationProbe />} />
        <Route path="/login" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AuthGate server session", () => {
  beforeEach(() => {
    mocks.getCurrentSession.mockReset();
    mocks.getSetupStatus.mockReset();
    mocks.getSetupStatus.mockResolvedValue({
      initialized: true,
      auth_mode: "local_owner",
    });
    mocks.getCurrentSession.mockResolvedValue({
      authenticated: true,
      subject: "owner",
      role: "owner",
      expires_at: null,
    });
  });

  it("does not reveal protected content until the server session is verified", async () => {
    let resolveSession: ((value: unknown) => void) | undefined;
    mocks.getCurrentSession.mockReturnValue(
      new Promise((resolve) => {
        resolveSession = resolve;
      }),
    );

    renderGate();

    expect(screen.getByLabelText("Checking session")).toBeInTheDocument();
    expect(screen.queryByText("Protected settings")).not.toBeInTheDocument();
    resolveSession?.({
      authenticated: true,
      subject: "owner",
      role: "owner",
      expires_at: null,
    });
    expect(await screen.findByText("Protected settings")).toBeInTheDocument();
  });

  it("redirects an uninitialized installation to setup with a safe return path", async () => {
    mocks.getSetupStatus.mockResolvedValue({
      initialized: false,
      auth_mode: "local_owner",
    });

    renderGate();

    expect(
      await screen.findByText("/setup?returnTo=%2Fsettings%3Ftab%3Dprivacy"),
    ).toBeInTheDocument();
    expect(mocks.getCurrentSession).not.toHaveBeenCalled();
  });

  it("redirects an expired session to login with a safe return path", async () => {
    mocks.getCurrentSession.mockRejectedValue(new ApiError(401, "expired"));

    renderGate();

    expect(
      await screen.findByText("/login?returnTo=%2Fsettings%3Ftab%3Dprivacy"),
    ).toBeInTheDocument();
  });

  it("shows a recoverable error for network failure and retries the probe", async () => {
    const user = userEvent.setup();
    mocks.getSetupStatus
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValueOnce({ initialized: true, auth_mode: "local_owner" });

    renderGate();

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not verify your session");
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => {
      expect(mocks.getSetupStatus).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText("Protected settings")).toBeInTheDocument();
  });
});
