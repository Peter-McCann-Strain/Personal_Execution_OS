import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { ContactCard } from "@/components/contacts/contact-card";
import { createContact } from "../../factories";

describe("ContactCard", () => {
  it("renders contact metadata and opens the read-only detail view", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();

    renderWithProviders(
      <ContactCard
        contact={createContact({
          tags: ["friend", "work"],
          interaction_frequency_days: 7,
          last_interaction_at: "2000-01-01T12:00:00Z",
        })}
        onSelect={onSelect}
      />,
    );

    expect(screen.getByText("Alex Morgan")).toBeInTheDocument();
    expect(screen.getByText(/Last interaction: \d+d ago/)).toBeInTheDocument();
    expect(screen.getByText("friend")).toBeInTheDocument();
    expect(screen.getByText("work")).toBeInTheDocument();
    expect(screen.getByText("Target: every 7d", { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/overdue/)).toBeInTheDocument();

    expect(screen.queryByRole("button", { name: "Log" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Email" })).not.toBeInTheDocument();

    await user.click(screen.getByText("Alex Morgan"));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "contact-1" }));
  });

  it("renders fallback copy for contacts without interaction history or tags", () => {
    renderWithProviders(
      <ContactCard
        contact={createContact({
          first_name: "Ada",
          last_name: null,
          tags: [],
          interaction_frequency_days: null,
          last_interaction_at: null,
        })}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("Ada")).toBeInTheDocument();
    expect(screen.getByText("No interactions yet")).toBeInTheDocument();
    expect(screen.queryByText("Target: every", { exact: false })).not.toBeInTheDocument();
  });

  it("renders the on-track state when the interaction cadence is current", () => {
    renderWithProviders(
      <ContactCard
        contact={createContact({
          interaction_frequency_days: 7,
          last_interaction_at: new Date().toISOString(),
        })}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("Target: every 7d", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("On track")).toBeInTheDocument();
    expect(screen.queryByText(/overdue/)).not.toBeInTheDocument();
  });
});
