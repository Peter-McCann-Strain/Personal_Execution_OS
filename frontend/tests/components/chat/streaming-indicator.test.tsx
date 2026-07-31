import { describe, expect, it } from "vitest";
import { renderWithProviders, screen } from "../../test-utils";
import { StreamingIndicator } from "@/components/chat/streaming-indicator";

describe("StreamingIndicator", () => {
  it("renders the processing label and merges custom classes", () => {
    const { container } = renderWithProviders(<StreamingIndicator className="text-red-500" />);

    const indicator = screen.getByLabelText("Processing");
    expect(indicator).toHaveClass("inline-flex", "items-center", "gap-1", "text-red-500");
    expect(container.querySelectorAll('[aria-label="Processing"] span')).toHaveLength(3);
  });
});
