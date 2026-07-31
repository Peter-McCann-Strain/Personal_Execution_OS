import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Badge, AgentBadge, PriorityBadge, ParaBadge } from "@/components/ui/badge";
import { badgeVariants } from "@/components/ui/badge-variants";
import { Progress } from "@/components/ui/progress";
import { Pagination } from "@/components/ui/pagination";
import { Input } from "@/components/ui/input";

describe("UI primitives", () => {
  describe("Button", () => {
    it("renders default button styling and supports loading", () => {
      renderWithProviders(<Button loading>Save changes</Button>);

      const button = screen.getByRole("button", { name: /save changes/i });
      expect(button).toBeDisabled();
      expect(button).toHaveClass("bg-[var(--color-info-500)]");
      expect(button).toHaveClass("text-[var(--color-fg-on-accent)]");
      expect(button).toHaveClass("h-9");
      expect(button).toHaveClass("px-4");
      expect(button.querySelector("svg")).toHaveClass("animate-spin");
    });

    it("applies variant and size classes and supports asChild rendering", () => {
      renderWithProviders(
        <Button asChild variant="outline" size="sm">
          <a href="/settings">Settings</a>
        </Button>,
      );

      const link = screen.getByRole("link", { name: "Settings" });
      expect(link).toHaveAttribute("href", "/settings");
      expect(link).toHaveClass("border");
      expect(link).toHaveClass("h-8");
      expect(link).toHaveClass("px-3");
      expect(buttonVariants({ variant: "destructive", size: "icon" })).toContain(
        "bg-[var(--color-error-500)]",
      );
    });
  });

  describe("Badge family", () => {
    it("renders base badge variants", () => {
      renderWithProviders(
        <Badge variant="success" size="sm" data-testid="badge">
          Synced
        </Badge>,
      );

      const badge = screen.getByTestId("badge");
      expect(badge).toHaveClass("bg-[var(--color-success-50)]");
      expect(badge).toHaveClass("text-[10px]");
      expect(badgeVariants({ variant: "warning", size: "md" })).toContain(
        "bg-[var(--color-warning-50)]",
      );
    });

    it("renders agent, priority, and PARA badges with mapped styling", () => {
      renderWithProviders(
        <div>
          <AgentBadge agent="diary" size="sm" data-testid="agent-badge" />
          <AgentBadge agent="memory" data-testid="agent-badge-md" />
          <PriorityBadge priority="P0" data-testid="priority-badge" />
          <ParaBadge category="resource" data-testid="para-badge" />
        </div>,
      );

      const agentBadge = screen.getByTestId("agent-badge");
      expect(agentBadge).toHaveTextContent("diary");
      expect(agentBadge).toHaveStyle({
        color: "var(--color-agent-diary)",
      });
      expect(agentBadge.querySelector("span")).toHaveStyle({
        backgroundColor: "var(--color-agent-diary)",
      });
      expect(agentBadge).toHaveClass("px-1.5");

      const agentBadgeMd = screen.getByTestId("agent-badge-md");
      expect(agentBadgeMd).toHaveClass("px-2");
      expect(agentBadgeMd).toHaveTextContent("memory");

      expect(screen.getByTestId("priority-badge")).toHaveTextContent("P0");
      expect(screen.getByTestId("priority-badge")).toHaveClass("bg-[var(--color-error-50)]");

      const paraBadge = screen.getByTestId("para-badge");
      expect(paraBadge).toHaveTextContent("resource");
      expect(paraBadge).toHaveClass("capitalize");
      expect(paraBadge).toHaveClass("bg-[var(--color-warning-50)]");
    });
  });

  describe("Progress", () => {
    it("defaults to zero width and uses the default color variant", () => {
      const { container } = renderWithProviders(<Progress />);

      const progressbar = screen.getByRole("progressbar");
      const indicator = container.querySelector('[style*="width: 0%"]') as HTMLElement | null;
      expect(progressbar).toBeInTheDocument();
      expect(indicator).toBeInTheDocument();
      expect(indicator).toHaveClass("bg-[var(--color-info-500)]");
    });

    it("supports agent colors and custom values", () => {
      const { container } = renderWithProviders(
        <Progress value={72} colorVariant="memory" data-testid="progress" />,
      );

      expect(screen.getByTestId("progress")).toBeInTheDocument();
      const indicator = container.querySelector('[style*="width: 72%"]') as HTMLElement | null;
      expect(indicator).toBeInTheDocument();
      expect(indicator).toHaveClass("bg-[var(--color-agent-memory)]");
    });

    it("falls back to the default fill color for unknown variants", () => {
      const { container } = renderWithProviders(
        <Progress colorVariant={"unknown" as never} value={15} />,
      );

      const indicator = container.querySelector('[style*="width: 15%"]') as HTMLElement | null;
      expect(indicator).toBeInTheDocument();
      expect(indicator).toHaveClass("bg-[var(--color-info-500)]");
    });
  });

  describe("Pagination", () => {
    it("hides itself when there is only one page", () => {
      const { container } = renderWithProviders(
        <Pagination page={1} totalPages={1} onPageChange={vi.fn()} />,
      );

      expect(container).toBeEmptyDOMElement();
    });

    it("disables edge controls and calls page changes", async () => {
      const onPageChange = vi.fn();
      const user = userEvent.setup();
      renderWithProviders(<Pagination page={3} totalPages={5} onPageChange={onPageChange} />);

      expect(screen.getByText("Page 3 of 5")).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: /first page/i }));
      await user.click(screen.getByRole("button", { name: /previous page/i }));
      await user.click(screen.getByRole("button", { name: /next page/i }));
      await user.click(screen.getByRole("button", { name: /last page/i }));
      expect(onPageChange).toHaveBeenNthCalledWith(1, 1);
      expect(onPageChange).toHaveBeenNthCalledWith(2, 2);
      expect(onPageChange).toHaveBeenNthCalledWith(3, 4);
      expect(onPageChange).toHaveBeenNthCalledWith(4, 5);
    });

    it("disables the first controls on the first page", () => {
      renderWithProviders(<Pagination page={1} totalPages={4} onPageChange={vi.fn()} />);

      expect(screen.getByRole("button", { name: /first page/i })).toBeDisabled();
      expect(screen.getByRole("button", { name: /previous page/i })).toBeDisabled();
    });

    it("disables the last controls on the last page", () => {
      renderWithProviders(<Pagination page={4} totalPages={4} onPageChange={vi.fn()} />);

      expect(screen.getByRole("button", { name: /next page/i })).toBeDisabled();
      expect(screen.getByRole("button", { name: /last page/i })).toBeDisabled();
    });
  });

  describe("Input", () => {
    it("uses the default text type and base styles", () => {
      renderWithProviders(<Input aria-label="Title" placeholder="Enter title" />);

      const input = screen.getByRole("textbox", { name: "Title" });
      expect(input).toHaveAttribute("type", "text");
      expect(input).toHaveClass("border-[var(--color-border-default)]");
      expect(input).toHaveClass("placeholder:text-[var(--color-fg-tertiary)]");
    });

    it("applies the error variant and forwards custom props", () => {
      renderWithProviders(
        <Input aria-label="Email" type="email" error disabled className="mt-2" />,
      );

      const input = screen.getByRole("textbox", { name: "Email" });
      expect(input).toHaveAttribute("type", "email");
      expect(input).toBeDisabled();
      expect(input).toHaveClass("border-[var(--color-error-500)]");
      expect(input).toHaveClass("mt-2");
    });
  });
});
