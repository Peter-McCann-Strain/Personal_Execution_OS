import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen, within } from "../../test-utils";
import { ContactDetail } from "@/components/contacts/contact-detail";
import { createContact, createInteraction } from "../../factories";

const mocks = vi.hoisted(() => ({
  getContact: vi.fn(),
  getContactInteractions: vi.fn(),
}));

vi.mock("@/api/contacts", () => ({
  getContact: mocks.getContact,
  getContactInteractions: mocks.getContactInteractions,
}));

describe("ContactDetail", () => {
  beforeEach(() => {
    mocks.getContact.mockReset();
    mocks.getContactInteractions.mockReset();
  });

  it("renders loading skeletons while the contact query is pending", () => {
    mocks.getContact.mockReturnValue(new Promise(() => {}));
    mocks.getContactInteractions.mockReturnValue(new Promise(() => {}));

    const { container } = renderWithProviders(
      <ContactDetail contactId="contact-1" onBack={vi.fn()} />,
    );

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("renders the not-found state when no contact is returned", async () => {
    const onBack = vi.fn();
    mocks.getContact.mockResolvedValue(null);
    mocks.getContactInteractions.mockResolvedValue([]);

    renderWithProviders(<ContactDetail contactId="contact-1" onBack={onBack} />);

    expect(await screen.findByText("Contact not found")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Go back" }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("renders details and filters interactions without unwired mutation controls", async () => {
    const onBack = vi.fn();
    const contact = createContact({
      first_name: "Ada",
      last_name: "Lovelace",
      tags: ["friend", "vip"],
      relationship_score: 91,
    });
    const interactions = [
      createInteraction({
        id: "interaction-1",
        interaction_type: "call",
        direction: "outgoing",
        summary: "Talked through the roadmap",
        topics: ["roadmap"],
      }),
      createInteraction({
        id: "interaction-2",
        interaction_type: "email",
        direction: "incoming",
        summary: "Shared feedback",
        topics: ["feedback"],
      }),
    ];

    mocks.getContact.mockResolvedValue(contact);
    mocks.getContactInteractions.mockResolvedValue(interactions);

    renderWithProviders(<ContactDetail contactId="contact-1" onBack={onBack} />);

    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("Talked through the roadmap")).toBeInTheDocument();
    expect(screen.getByText("Shared feedback")).toBeInTheDocument();
    expect(screen.getByText("roadmap")).toBeInTheDocument();
    expect(screen.getByText("feedback")).toBeInTheDocument();

    const typeTabs = within(screen.getByRole("tablist", { name: "Interaction type" }));
    fireEvent.click(typeTabs.getByRole("tab", { name: "email" }));
    expect(screen.queryByText("Talked through the roadmap")).not.toBeInTheDocument();
    expect(screen.getByText("Shared feedback")).toBeInTheDocument();

    const directionTabs = within(screen.getByRole("tablist", { name: "Interaction direction" }));
    fireEvent.click(directionTabs.getByRole("tab", { name: "outgoing" }));
    expect(await screen.findByText("No interactions found")).toBeInTheDocument();

    fireEvent.click(typeTabs.getByRole("tab", { name: "all" }));
    fireEvent.click(directionTabs.getByRole("tab", { name: "all" }));
    expect(await screen.findByText("Talked through the roadmap")).toBeInTheDocument();

    expect(screen.queryByRole("button", { name: "Send Email" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Schedule Meeting" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Log Interaction" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to contacts" }));

    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("renders the header without optional contact fields while interactions are still loading", async () => {
    mocks.getContact.mockResolvedValue(
      createContact({
        email: null,
        how_we_met: null,
        tags: [],
        last_interaction_at: null,
        interaction_frequency_days: null,
      }),
    );
    mocks.getContactInteractions.mockReturnValue(new Promise(() => {}));

    const { container } = renderWithProviders(
      <ContactDetail contactId="contact-1" onBack={vi.fn()} />,
    );

    expect(await screen.findByText("Alex Morgan")).toBeInTheDocument();
    expect(screen.queryByText("alex@example.com")).not.toBeInTheDocument();
    expect(screen.queryByText("Met through work")).not.toBeInTheDocument();
    expect(screen.queryByText("friend")).not.toBeInTheDocument();
    expect(screen.getAllByText("--", { exact: true }).length).toBeGreaterThanOrEqual(2);
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });
});
