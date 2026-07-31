import { describe, expect, it, vi } from "vitest";
import { act, renderWithProviders, screen, waitFor } from "../../test-utils";
import { HealthRing } from "@/components/contacts/health-ring";
import { getHealthColor } from "@/components/contacts/health-ring.utils";

describe("HealthRing", () => {
  it("renders a label by default and supports hiding it", () => {
    const { rerender } = renderWithProviders(<HealthRing score={82} />);

    expect(screen.getByText("82")).toBeInTheDocument();

    rerender(<HealthRing score={82} showLabel={false} />);
    expect(screen.queryByText("82")).not.toBeInTheDocument();
  });

  it("maps score bands to the expected health colors", () => {
    expect(getHealthColor(85)).toBe("var(--color-success-500)");
    expect(getHealthColor(60)).toBe("var(--color-warning-500)");
    expect(getHealthColor(30)).toBe("oklch(0.65 0.18 55)");
    expect(getHealthColor(10)).toBe("var(--color-error-500)");
  });

  it("animates and clamps score bounds", async () => {
    const callbacks: FrameRequestCallback[] = [];
    const requestAnimationFrameSpy = vi
      .spyOn(window, "requestAnimationFrame")
      .mockImplementation((cb: FrameRequestCallback) => {
        callbacks.push(cb);
        return callbacks.length;
      });
    const cancelAnimationFrameSpy = vi
      .spyOn(window, "cancelAnimationFrame")
      .mockImplementation(vi.fn());

    const { rerender, unmount } = renderWithProviders(
      <HealthRing score={150} size={32} strokeWidth={2} />,
    );

    expect(callbacks).toHaveLength(1);

    await act(async () => {
      callbacks.shift()?.(0);
    });

    expect(callbacks).toHaveLength(1);

    await act(async () => {
      callbacks.shift()?.(600);
    });

    await waitFor(() => {
      expect(screen.getByText("100")).toBeInTheDocument();
    });

    rerender(<HealthRing score={-5} size={32} strokeWidth={2} />);

    expect(callbacks).toHaveLength(1);

    await act(async () => {
      callbacks.shift()?.(0);
    });

    expect(callbacks).toHaveLength(1);

    await act(async () => {
      callbacks.shift()?.(600);
    });

    await waitFor(() => {
      expect(screen.getByText("0")).toBeInTheDocument();
    });

    unmount();

    expect(requestAnimationFrameSpy).toHaveBeenCalled();
    expect(cancelAnimationFrameSpy).toHaveBeenCalled();

    requestAnimationFrameSpy.mockRestore();
    cancelAnimationFrameSpy.mockRestore();
  });
});
