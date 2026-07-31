import { Component } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { ErrorBoundary } from "@/components/ui/error-boundary";

class Bomb extends Component<{ shouldThrow?: boolean }> {
  render() {
    if (this.props.shouldThrow) {
      throw new Error("render failed");
    }
    return <div>Healthy child</div>;
  }
}

describe("ErrorBoundary", () => {
  it("renders children when no error is thrown", () => {
    renderWithProviders(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );

    expect(screen.getByText("Healthy child")).toBeInTheDocument();
  });

  it("renders the default fallback and resets after retry", async () => {
    const user = userEvent.setup();
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    let shouldThrow = true;

    function MaybeBomb() {
      return <Bomb shouldThrow={shouldThrow} />;
    }

    renderWithProviders(
      <ErrorBoundary>
        <MaybeBomb />
      </ErrorBoundary>,
    );

    expect(await screen.findByText("Interface crashed")).toBeInTheDocument();
    expect(screen.getByText("render failed")).toBeInTheDocument();

    shouldThrow = false;
    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Healthy child")).toBeInTheDocument();
    consoleError.mockRestore();
  });

  it("renders a custom fallback when provided", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);

    renderWithProviders(
      <ErrorBoundary fallback={<div>Custom fallback</div>}>
        <Bomb shouldThrow />
      </ErrorBoundary>,
    );

    expect(await screen.findByText("Custom fallback")).toBeInTheDocument();
    consoleError.mockRestore();
  });

  it("falls back to the default message when the thrown error has no message", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);

    function SilentBomb() {
      throw Object.assign(new Error("hidden"), { message: undefined });
    }

    renderWithProviders(
      <ErrorBoundary>
        <SilentBomb />
      </ErrorBoundary>,
    );

    expect(
      await screen.findByText("The interface crashed without an error message."),
    ).toBeInTheDocument();
    consoleError.mockRestore();
  });

  describe("route-level recovery actions", () => {
    let consoleError: ReturnType<typeof vi.spyOn>;
    let originalLocation: Location;

    beforeEach(() => {
      consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
      originalLocation = window.location;
      sessionStorage.setItem("api_key", "sk-test-123");
      // Mock window.location.assign via a replaceable stub.
      Object.defineProperty(window, "location", {
        configurable: true,
        value: {
          ...originalLocation,
          assign: vi.fn(),
        },
      });
    });

    afterEach(() => {
      consoleError.mockRestore();
      sessionStorage.removeItem("api_key");
      Object.defineProperty(window, "location", {
        configurable: true,
        value: originalLocation,
      });
    });

    it("exposes a Home link that targets the dashboard", async () => {
      renderWithProviders(
        <ErrorBoundary>
          <Bomb shouldThrow />
        </ErrorBoundary>,
      );

      const home = await screen.findByRole("link", { name: "Home" });
      expect(home).toHaveAttribute("href", "/dashboard");
    });

    it("clears session auth and redirects to setup on Clear auth and re-login", async () => {
      const user = userEvent.setup();
      const onClearAuth = vi.fn();

      renderWithProviders(
        <ErrorBoundary onClearAuth={onClearAuth}>
          <Bomb shouldThrow />
        </ErrorBoundary>,
      );

      await user.click(await screen.findByRole("button", { name: "Clear auth and re-login" }));

      expect(sessionStorage.getItem("api_key")).toBeNull();
      expect(onClearAuth).toHaveBeenCalledTimes(1);
      expect(window.location.assign).toHaveBeenCalledWith("/setup?returnTo=%2F");
    });

    it("still proceeds with redirect when sessionStorage access throws", async () => {
      const user = userEvent.setup();
      const removeItem = vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
        throw new Error("storage unavailable");
      });

      renderWithProviders(
        <ErrorBoundary>
          <Bomb shouldThrow />
        </ErrorBoundary>,
      );

      await user.click(await screen.findByRole("button", { name: "Clear auth and re-login" }));

      expect(window.location.assign).toHaveBeenCalledWith("/setup?returnTo=%2F");
      removeItem.mockRestore();
    });
  });
});
