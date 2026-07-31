import { describe, it, expect, vi } from "vitest";
import { renderWithProviders, screen } from "../../test-utils";
import { EmptyState } from "@/components/ui/empty-state";
import { StickyNote } from "lucide-react";

describe("EmptyState", () => {
  it("renders title and icon", () => {
    renderWithProviders(<EmptyState icon={StickyNote} title="No notes yet" />);
    expect(screen.getByText("No notes yet")).toBeInTheDocument();
  });

  it("renders optional description", () => {
    renderWithProviders(
      <EmptyState
        icon={StickyNote}
        title="No notes"
        description="Create your first note to get started."
      />,
    );
    expect(screen.getByText("Create your first note to get started.")).toBeInTheDocument();
  });

  it("renders primary action button", () => {
    const onClick = vi.fn();
    renderWithProviders(
      <EmptyState icon={StickyNote} title="No notes" action={{ label: "Create Note", onClick }} />,
    );
    const btn = screen.getByRole("button", { name: "Create Note" });
    expect(btn).toBeInTheDocument();
    btn.click();
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("renders secondary action button when provided", () => {
    const primary = vi.fn();
    const secondary = vi.fn();
    renderWithProviders(
      <EmptyState
        icon={StickyNote}
        title="No notes"
        action={{ label: "Create", onClick: primary }}
        secondaryAction={{ label: "Learn more", onClick: secondary }}
      />,
    );
    expect(screen.getByRole("button", { name: "Create" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Learn more" })).toBeInTheDocument();
  });

  it("does not render action buttons when not provided", () => {
    renderWithProviders(<EmptyState icon={StickyNote} title="Empty" />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
