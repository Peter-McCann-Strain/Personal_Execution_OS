import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { render, screen } from "@testing-library/react";
import { AuthGate } from "@/components/auth/auth-gate";
import { useAppStore } from "@/stores/app";

vi.mock("@/lib/auth-mode", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth-mode")>("@/lib/auth-mode");
  return {
    ...actual,
    isLegacyDevAuthEnabled: true,
  };
});

function LocationProbe() {
  const location = useLocation();
  return <div>{`${location.pathname}${location.search}`}</div>;
}

function renderLegacyGate() {
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
      </Routes>
    </MemoryRouter>,
  );
}

describe("AuthGate legacy development mode", () => {
  beforeEach(() => {
    useAppStore.setState({ apiKey: "" });
  });

  it("redirects a missing development key without losing the return target", async () => {
    renderLegacyGate();

    expect(
      await screen.findByText("/setup?returnTo=%2Fsettings%3Ftab%3Dprivacy"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Protected settings")).not.toBeInTheDocument();
  });

  it("renders protected content only when a development key exists", () => {
    useAppStore.setState({ apiKey: "development-key" });

    renderLegacyGate();

    expect(screen.getByText("Protected settings")).toBeInTheDocument();
  });
});
