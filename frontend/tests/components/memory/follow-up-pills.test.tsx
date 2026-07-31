import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { FollowUpPills } from "@/components/memory/follow-up-pills";

describe("FollowUpPills", () => {
  it("returns nothing when there are no suggestions", () => {
    const { container } = renderWithProviders(
      <FollowUpPills suggestions={[]} onSelect={vi.fn()} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("renders suggestions and forwards the selected follow-up", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();

    renderWithProviders(
      <FollowUpPills
        suggestions={["What changed this week?", "What should I read next?"]}
        onSelect={onSelect}
      />,
    );

    expect(screen.getByText("Follow-up questions")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "What changed this week?" }));
    expect(onSelect).toHaveBeenCalledWith("What changed this week?");
  });
});
