import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useTreeExpansion } from "@/hooks/use-tree-expansion";

describe("useTreeExpansion", () => {
  it("returns an empty set initially when no IDs are provided", () => {
    const { result } = renderHook(() => useTreeExpansion());
    expect(result.current.expanded.size).toBe(0);
  });

  it("initializes with provided IDs", () => {
    const { result } = renderHook(() => useTreeExpansion(["node-1", "node-2"]));
    expect(result.current.expanded.size).toBe(2);
    expect(result.current.isExpanded("node-1")).toBe(true);
    expect(result.current.isExpanded("node-2")).toBe(true);
  });

  it("toggleNode adds an item that is not expanded", () => {
    const { result } = renderHook(() => useTreeExpansion());

    act(() => {
      result.current.toggleNode("node-a");
    });

    expect(result.current.isExpanded("node-a")).toBe(true);
    expect(result.current.expanded.size).toBe(1);
  });

  it("toggleNode removes an already-expanded item", () => {
    const { result } = renderHook(() => useTreeExpansion(["node-a"]));

    expect(result.current.isExpanded("node-a")).toBe(true);

    act(() => {
      result.current.toggleNode("node-a");
    });

    expect(result.current.isExpanded("node-a")).toBe(false);
    expect(result.current.expanded.size).toBe(0);
  });

  it("toggleNode works correctly across multiple operations", () => {
    const { result } = renderHook(() => useTreeExpansion());

    // Expand two nodes
    act(() => {
      result.current.toggleNode("a");
    });
    act(() => {
      result.current.toggleNode("b");
    });

    expect(result.current.expanded.size).toBe(2);
    expect(result.current.isExpanded("a")).toBe(true);
    expect(result.current.isExpanded("b")).toBe(true);

    // Collapse one
    act(() => {
      result.current.toggleNode("a");
    });

    expect(result.current.expanded.size).toBe(1);
    expect(result.current.isExpanded("a")).toBe(false);
    expect(result.current.isExpanded("b")).toBe(true);
  });

  it("expandAll sets the expanded set to all provided IDs", () => {
    const { result } = renderHook(() => useTreeExpansion());

    act(() => {
      result.current.expandAll(["x", "y", "z"]);
    });

    expect(result.current.expanded.size).toBe(3);
    expect(result.current.isExpanded("x")).toBe(true);
    expect(result.current.isExpanded("y")).toBe(true);
    expect(result.current.isExpanded("z")).toBe(true);
  });

  it("expandAll replaces existing expanded set", () => {
    const { result } = renderHook(() => useTreeExpansion(["old-1", "old-2"]));

    act(() => {
      result.current.expandAll(["new-1"]);
    });

    expect(result.current.expanded.size).toBe(1);
    expect(result.current.isExpanded("old-1")).toBe(false);
    expect(result.current.isExpanded("new-1")).toBe(true);
  });

  it("collapseAll clears all expanded nodes", () => {
    const { result } = renderHook(() => useTreeExpansion(["a", "b", "c"]));

    expect(result.current.expanded.size).toBe(3);

    act(() => {
      result.current.collapseAll();
    });

    expect(result.current.expanded.size).toBe(0);
    expect(result.current.isExpanded("a")).toBe(false);
    expect(result.current.isExpanded("b")).toBe(false);
    expect(result.current.isExpanded("c")).toBe(false);
  });

  it("isExpanded returns false for unknown IDs", () => {
    const { result } = renderHook(() => useTreeExpansion(["known"]));
    expect(result.current.isExpanded("unknown")).toBe(false);
  });
});
