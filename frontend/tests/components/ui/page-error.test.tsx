import { describe, it, expect, vi } from "vitest";
import { renderWithProviders, screen } from "../../test-utils";
import { PageError } from "@/components/ui/page-error";
import { classifyError } from "@/components/ui/page-error.utils";
import { Flame } from "lucide-react";

describe("PageError", () => {
  it("renders with default message", () => {
    renderWithProviders(<PageError />);
    expect(screen.getByText("Request failed")).toBeInTheDocument();
    expect(screen.getByText("An unexpected error occurred.")).toBeInTheDocument();
  });

  it("renders retry button when onRetry provided", () => {
    const onRetry = vi.fn();
    renderWithProviders(<PageError onRetry={onRetry} />);
    const btn = screen.getByRole("button", { name: /try again/i });
    expect(btn).toBeInTheDocument();
    btn.click();
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("does not render retry button when onRetry is not provided", () => {
    renderWithProviders(<PageError />);
    expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
  });

  it("shows context message when context prop provided", () => {
    renderWithProviders(<PageError context="your habits" />);
    expect(screen.getByText("Couldn't load your habits.")).toBeInTheDocument();
  });

  it("renders page icon badge when icon provided", () => {
    const { container } = renderWithProviders(<PageError icon={Flame} />);
    // The page icon is rendered inside a small badge overlay
    const svgs = container.querySelectorAll("svg");
    expect(svgs.length).toBeGreaterThanOrEqual(2); // error icon + page icon
  });
});

describe("classifyError", () => {
  it("classifies network errors as connection failed", () => {
    const result = classifyError("Failed to fetch");
    expect(result.title).toBe("Connection failed");
    expect(result.hint).toBe("The backend server isn't reachable.");
  });

  it("classifies 500 errors as server error", () => {
    const result = classifyError("Request failed with status 500");
    expect(result.title).toBe("Server error");
  });

  it("classifies 404 errors as not found", () => {
    const result = classifyError("404 Not Found");
    expect(result.title).toBe("Not found");
  });

  it("classifies 401/403 errors as access denied", () => {
    const result = classifyError("401 Unauthorized");
    expect(result.title).toBe("Access denied");
  });

  it("returns generic error for unknown messages", () => {
    const result = classifyError("Some random error");
    expect(result.title).toBe("Request failed");
    expect(result.hint).toBeUndefined();
  });

  it("handles undefined message", () => {
    const result = classifyError(undefined);
    expect(result.title).toBe("Request failed");
  });

  it("renders the raw backend message and contextual hint", () => {
    renderWithProviders(<PageError message="Failed to fetch /api/memory" />);
    expect(screen.getByText("Failed to fetch /api/memory")).toBeInTheDocument();
    expect(screen.getByText("The backend server isn't reachable.")).toBeInTheDocument();
  });
});
