import { useState, useCallback } from "react";

/**
 * Manages expand/collapse state for tree views.
 * Used by ProjectTree, GoalTree, and similar hierarchical components.
 */
function useTreeExpansion(initialIds: string[] = []) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(initialIds));

  const toggleNode = useCallback((id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const expandAll = useCallback((ids: string[]) => {
    setExpanded(new Set(ids));
  }, []);

  const collapseAll = useCallback(() => {
    setExpanded(new Set());
  }, []);

  const isExpanded = useCallback((id: string) => expanded.has(id), [expanded]);

  return { expanded, toggleNode, expandAll, collapseAll, isExpanded };
}

export { useTreeExpansion };
