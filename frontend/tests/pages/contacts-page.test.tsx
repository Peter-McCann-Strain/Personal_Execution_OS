import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen, userEvent, waitFor } from "../test-utils";
import { ContactsPage } from "@/pages/contacts";
import { createContact, createPaginatedResponse } from "../factories";
import type { Contact } from "@/types";

const mocks = vi.hoisted(() => ({
  getContacts: vi.fn(),
}));

vi.mock("@/api/contacts", () => ({
  getContacts: mocks.getContacts,
}));

vi.mock("@/components/ui/page-transition", () => ({
  PageTransition: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("@/hooks/use-debounce", () => ({
  useDebounce: (value: string) => value,
}));

vi.mock("@/components/ui/page-header", () => ({
  PageHeader: ({
    children,
    subtitle,
    title,
  }: {
    children?: React.ReactNode;
    subtitle: string;
    title: string;
  }) => (
    <div>
      <h1>{title}</h1>
      <p>{subtitle}</p>
      <div>{children}</div>
    </div>
  ),
}));

vi.mock("@/components/ui/page-error", () => ({
  PageError: ({ message }: { message: string }) => <div>Page Error: {message}</div>,
}));

vi.mock("@/components/ui/empty-state", () => ({
  EmptyState: ({
    title,
    action,
  }: {
    title: string;
    action?: { label: string; onClick: () => void };
  }) => (
    <div>
      <div>{title}</div>
      {action ? (
        <button type="button" onClick={action.onClick}>
          {action.label}
        </button>
      ) : null}
    </div>
  ),
}));

vi.mock("@/components/contacts/contact-card", () => ({
  ContactCard: ({
    contact,
    onSelect,
  }: {
    contact: Contact;
    onSelect: (contact: Contact) => void;
  }) => (
    <button type="button" onClick={() => onSelect(contact)}>
      Open {contact.first_name}
    </button>
  ),
}));

vi.mock("@/components/contacts/contact-detail", () => ({
  ContactDetail: ({ contactId, onBack }: { contactId: string; onBack: () => void }) => (
    <div>
      <div>Detail {contactId}</div>
      <button type="button" onClick={onBack}>
        Back to list
      </button>
    </div>
  ),
}));

describe("ContactsPage", () => {
  beforeEach(() => {
    mocks.getContacts.mockReset();
  });

  it("renders contacts, applies sort and filters, and opens the detail view", async () => {
    const ada = createContact({
      id: "contact-1",
      first_name: "Ada",
      tags: ["friend", "vip"],
      relationship_score: 90,
    });
    const grace = createContact({
      id: "contact-2",
      first_name: "Grace",
      tags: ["work"],
      relationship_score: 40,
    });

    mocks.getContacts.mockResolvedValue(createPaginatedResponse([ada, grace]));

    renderWithProviders(<ContactsPage />);

    expect(await screen.findByRole("heading", { name: "Contacts" })).toBeInTheDocument();
    expect(screen.getByText("Read-only contact and interaction history")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add Contact" })).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Open Ada" })).toBeInTheDocument();
    expect(mocks.getContacts).toHaveBeenCalledWith({
      limit: 50,
      score_max: undefined,
      score_min: undefined,
      search: undefined,
      sort: "score_asc",
      tags: undefined,
    });

    fireEvent.click(screen.getByRole("button", { name: "Sort contacts" }));
    fireEvent.click(screen.getByRole("option", { name: "Name" }));
    await waitFor(() => {
      expect(mocks.getContacts).toHaveBeenLastCalledWith({
        limit: 50,
        score_max: undefined,
        score_min: undefined,
        search: undefined,
        sort: "name",
        tags: undefined,
      });
    });

    fireEvent.click(screen.getByRole("button", { name: /Filters/ }));
    fireEvent.click(screen.getByRole("button", { name: "friend" }));
    await waitFor(() => {
      expect(mocks.getContacts).toHaveBeenLastCalledWith({
        limit: 50,
        score_max: undefined,
        score_min: undefined,
        search: undefined,
        sort: "name",
        tags: ["friend"],
      });
    });
    expect(screen.getByText(/friend\s×/)).toBeInTheDocument();

    fireEvent.click(screen.getByText(/friend\s×/));
    await waitFor(() => {
      expect(mocks.getContacts).toHaveBeenLastCalledWith({
        limit: 50,
        score_max: undefined,
        score_min: undefined,
        search: undefined,
        sort: "name",
        tags: undefined,
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "Clear All" }));
    await waitFor(() => {
      expect(mocks.getContacts).toHaveBeenLastCalledWith({
        limit: 50,
        score_max: undefined,
        score_min: undefined,
        search: undefined,
        sort: "name",
        tags: undefined,
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "Open Ada" }));
    expect(await screen.findByText("Detail contact-1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Back to list" }));
    expect(await screen.findByRole("button", { name: "Open Ada" })).toBeInTheDocument();
  });

  it("renders the empty state when no contacts match", async () => {
    mocks.getContacts.mockResolvedValue(createPaginatedResponse([]));

    renderWithProviders(<ContactsPage />);

    expect(await screen.findByText("No contacts found")).toBeInTheDocument();
  });

  it("renders the loading skeletons while contacts are still loading", () => {
    mocks.getContacts.mockReturnValue(new Promise(() => {}));

    const { container } = renderWithProviders(<ContactsPage />);

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("renders the page error when contact loading fails", async () => {
    mocks.getContacts.mockRejectedValue(new Error("contacts failed"));

    renderWithProviders(<ContactsPage />);

    expect(await screen.findByText("Page Error: contacts failed")).toBeInTheDocument();
  });

  it("falls back to the default error message when the failure has no message", async () => {
    mocks.getContacts.mockRejectedValue({});

    renderWithProviders(<ContactsPage />);

    expect(await screen.findByText("Page Error: Failed to load contacts")).toBeInTheDocument();
  });

  it("shows filter empty states, clamps score range, and exposes the clear search action", async () => {
    const user = userEvent.setup();

    mocks.getContacts.mockResolvedValue(createPaginatedResponse([]));

    renderWithProviders(<ContactsPage />);

    expect(await screen.findByText("No contacts found")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Filters/ }));
    expect(screen.getByText("No tags available")).toBeInTheDocument();

    const ranges = screen.getAllByRole("slider");
    fireEvent.change(ranges[0], { target: { value: "70" } });
    fireEvent.change(ranges[1], { target: { value: "60" } });

    await waitFor(() => {
      expect(mocks.getContacts).toHaveBeenLastCalledWith({
        limit: 50,
        score_max: 70,
        score_min: 70,
        search: undefined,
        sort: "score_asc",
        tags: undefined,
      });
    });

    await user.type(screen.getByPlaceholderText("Search contacts..."), "Ada");
    expect(await screen.findByRole("button", { name: "Clear search" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear search" }));
    await waitFor(() => {
      expect(mocks.getContacts).toHaveBeenLastCalledWith({
        limit: 50,
        score_max: 70,
        score_min: 70,
        search: undefined,
        sort: "score_asc",
        tags: undefined,
      });
    });
  });
});
