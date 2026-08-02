import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { SetupPage } from "@/pages/setup";
import { ApiError } from "@/api/client";
import { useAppStore } from "@/stores/app";
import { resetSettingsState } from "../settings-test-utils";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
}));

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return {
    ...actual,
    api: {
      get: mocks.apiGet,
    },
  };
});

function renderSetup(initialEntry: string = "/setup") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/setup" element={<SetupPage />} />
          <Route path="/dashboard" element={<div>Dashboard landing</div>} />
          <Route path="/email" element={<div>Email landing</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SetupPage", () => {
  beforeEach(() => {
    resetSettingsState();
    mocks.apiGet.mockReset();
  });

  afterEach(() => {
    sessionStorage.clear();
  });

  it("renders the setup form with instructions and a hidden input", () => {
    renderSetup();

    expect(screen.getByRole("heading", { name: "Connect your workspace" })).toBeInTheDocument();
    expect(screen.getByText(/CHAT_API_KEY/)).toBeInTheDocument();
    const input = screen.getByLabelText("API key") as HTMLInputElement;
    expect(input.type).toBe("password");
    expect(screen.getByRole("button", { name: "Save and continue" })).toBeDisabled();
  });

  it("toggles visibility when the show/hide button is clicked", () => {
    renderSetup();

    const input = screen.getByLabelText("API key") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "secret-key-value" } });
    expect(input.type).toBe("password");

    fireEvent.click(screen.getByRole("button", { name: "Reveal API key" }));
    expect(input.type).toBe("text");

    fireEvent.click(screen.getByRole("button", { name: "Hide API key" }));
    expect(input.type).toBe("password");
  });

  it("validates the key, persists it, and redirects to the returnTo path on success", async () => {
    mocks.apiGet.mockResolvedValueOnce({ ok: true });

    renderSetup("/setup?returnTo=%2Femail");

    fireEvent.change(screen.getByLabelText("API key"), {
      target: { value: "sk-good-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));

    await waitFor(() => {
      expect(mocks.apiGet).toHaveBeenCalledWith("/dashboard/stats");
    });
    expect(sessionStorage.getItem("api_key")).toBe("sk-good-key");
    expect(useAppStore.getState().apiKey).toBe("sk-good-key");
    expect(await screen.findByText("Email landing")).toBeInTheDocument();
  });

  it("falls back to /dashboard when no returnTo is provided", async () => {
    mocks.apiGet.mockResolvedValueOnce({ ok: true });

    renderSetup("/setup");

    fireEvent.change(screen.getByLabelText("API key"), {
      target: { value: "sk-good-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));

    expect(await screen.findByText("Dashboard landing")).toBeInTheDocument();
  });

  it("ignores returnTo values that escape the same-origin app", async () => {
    mocks.apiGet.mockResolvedValueOnce({ ok: true });

    renderSetup("/setup?returnTo=https%3A%2F%2Fevil.example.com%2F");

    fireEvent.change(screen.getByLabelText("API key"), {
      target: { value: "sk-good-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));

    expect(await screen.findByText("Dashboard landing")).toBeInTheDocument();
  });

  it("surfaces the HTTP status and message and does not save on 401", async () => {
    mocks.apiGet.mockRejectedValueOnce(new ApiError(401, "Invalid or missing credentials"));

    renderSetup();

    fireEvent.change(screen.getByLabelText("API key"), {
      target: { value: "sk-bad-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("HTTP 401");
    expect(alert).toHaveTextContent(/CHAT_API_KEY/);
    expect(sessionStorage.getItem("api_key")).toBeNull();
    expect(useAppStore.getState().apiKey).toBe("");
    expect(screen.queryByText("Dashboard landing")).not.toBeInTheDocument();
  });

  it("surfaces a network error message when the API is unreachable", async () => {
    mocks.apiGet.mockRejectedValueOnce(new ApiError(0, "Network error"));

    renderSetup();

    fireEvent.change(screen.getByLabelText("API key"), {
      target: { value: "sk-bad-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not reach the API");
    expect(sessionStorage.getItem("api_key")).toBeNull();
  });

  it("restores the previous key when validation fails", async () => {
    // Start with no key so the auto-redirect useEffect does not fire.
    mocks.apiGet.mockRejectedValueOnce(new ApiError(403, "forbidden"));

    renderSetup();

    // Simulate the "user already had a key, navigated back to /setup to
    // change it" case by writing the previous key *after* mount, before
    // the submit grabs it as `previousKey`.
    sessionStorage.setItem("api_key", "previous-key");

    fireEvent.change(screen.getByLabelText("API key"), {
      target: { value: "sk-bad-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));

    await screen.findByRole("alert");
    expect(sessionStorage.getItem("api_key")).toBe("previous-key");
  });

  it("redirects away from /setup if a key is already configured", async () => {
    sessionStorage.setItem("api_key", "already-here");

    renderSetup("/setup?returnTo=%2Femail");

    expect(await screen.findByText("Email landing")).toBeInTheDocument();
  });

  it("rejects whitespace-only credentials even when the form is submitted directly", async () => {
    renderSetup();
    fireEvent.change(screen.getByLabelText("API key"), {
      target: { value: "   " },
    });
    const form = screen.getByRole("button", { name: "Save and continue" }).closest("form");

    fireEvent.submit(form!);

    expect(await screen.findByRole("alert")).toHaveTextContent("Paste your API key first.");
    expect(mocks.apiGet).not.toHaveBeenCalled();
  });

  it("uses a safe generic validation error for non-Error failures", async () => {
    mocks.apiGet.mockRejectedValueOnce({ provider_payload: "do not expose" });
    renderSetup();

    fireEvent.change(screen.getByLabelText("API key"), {
      target: { value: "candidate-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Validation failed.");
    expect(screen.getByRole("alert")).not.toHaveTextContent("do not expose");
    expect(sessionStorage.getItem("api_key")).toBeNull();
  });
});
