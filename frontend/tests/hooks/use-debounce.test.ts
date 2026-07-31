import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useDebounce } from "@/hooks/use-debounce";

describe("useDebounce", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns the initial value immediately", () => {
    const { result } = renderHook(() => useDebounce("hello", 500));
    expect(result.current).toBe("hello");
  });

  it("does not update the debounced value before the delay", () => {
    const { result, rerender } = renderHook(({ value, delay }) => useDebounce(value, delay), {
      initialProps: { value: "initial", delay: 500 },
    });

    // Change the value
    rerender({ value: "updated", delay: 500 });

    // Advance time but not enough to trigger the debounce
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(result.current).toBe("initial");
  });

  it("updates the debounced value after the delay expires", () => {
    const { result, rerender } = renderHook(({ value, delay }) => useDebounce(value, delay), {
      initialProps: { value: "initial", delay: 500 },
    });

    rerender({ value: "updated", delay: 500 });

    act(() => {
      vi.advanceTimersByTime(500);
    });

    expect(result.current).toBe("updated");
  });

  it("returns the latest value when multiple updates happen within the delay", () => {
    const { result, rerender } = renderHook(({ value, delay }) => useDebounce(value, delay), {
      initialProps: { value: "first", delay: 300 },
    });

    rerender({ value: "second", delay: 300 });

    act(() => {
      vi.advanceTimersByTime(100);
    });

    // Another update before the first debounce fires
    rerender({ value: "third", delay: 300 });

    act(() => {
      vi.advanceTimersByTime(300);
    });

    // Should be the latest value, not "second"
    expect(result.current).toBe("third");
  });

  it("respects different delay values", () => {
    const { result, rerender } = renderHook(({ value, delay }) => useDebounce(value, delay), {
      initialProps: { value: "start", delay: 1000 },
    });

    rerender({ value: "end", delay: 1000 });

    act(() => {
      vi.advanceTimersByTime(500);
    });

    expect(result.current).toBe("start");

    act(() => {
      vi.advanceTimersByTime(500);
    });

    expect(result.current).toBe("end");
  });

  it("works with non-string types", () => {
    const { result, rerender } = renderHook(({ value, delay }) => useDebounce(value, delay), {
      initialProps: { value: 42, delay: 200 },
    });

    expect(result.current).toBe(42);

    rerender({ value: 99, delay: 200 });

    act(() => {
      vi.advanceTimersByTime(200);
    });

    expect(result.current).toBe(99);
  });
});
