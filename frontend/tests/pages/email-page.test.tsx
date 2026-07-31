import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../test-utils";
import { EmailPage } from "@/pages/email";
import { useAppStore } from "@/stores/app";
import type { Email } from "@/types";

const mocks = vi.hoisted(() => ({
  getEmails: vi.fn(),
}));

vi.mock("@/api/email", () => ({
  getEmails: mocks.getEmails,
}));

vi.mock("@/components/ui/page-transition", () => ({
  PageTransition: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("@/components/email/email-list", () => ({
  EmailList: ({
    emails,
    onSelectEmail,
    selectedId,
  }: {
    emails: Email[];
    onSelectEmail: (email: Email) => void;
    selectedId: string | null;
  }) => (
    <div>
      <div>List count {emails.length}</div>
      <div>Selected {selectedId ?? "none"}</div>
      {emails.map((email) => (
        <button key={email.id} type="button" onClick={() => onSelectEmail(email)}>
          Open {email.id}
        </button>
      ))}
    </div>
  ),
}));

vi.mock("@/components/email/email-detail", () => ({
  EmailDetail: ({ email }: { email: Email }) => (
    <div>
      <div>Detail {email.id}</div>
    </div>
  ),
}));

vi.mock("@/components/ui/page-error", () => ({
  PageError: ({ message, onRetry }: { message: string; onRetry?: () => void }) => (
    <div>
      <div>Page Error: {message}</div>
      {onRetry && (
        <button type="button" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  ),
}));

function createEmail(overrides: Partial<Email> = {}): Email {
  return {
    id: "email-1",
    threadId: "thread-1",
    snippet: "First email snippet",
    headers: {
      From: "Ada Lovelace <ada@example.com>",
      To: "alex@example.com",
      Subject: "Project update",
      Date: "2026-04-07T09:00:00Z",
    },
    body: "Email body",
    labelIds: ["INBOX", "UNREAD"],
    internalDate: "1775552400000",
    triage: "ACTION_REQUIRED",
    ...overrides,
  };
}

function createResponse(items: Email[]) {
  return {
    items,
    total: items.length,
    limit: 50,
    offset: 0,
  };
}

describe("EmailPage", () => {
  beforeEach(() => {
    mocks.getEmails.mockReset();
    useAppStore.setState({
      rightPanelOpen: false,
      rightPanelContent: null,
      inspectedEmail: null,
    });
  });

  it("renders a read-only inbox, updates filters, and opens message details", async () => {
    const user = userEvent.setup();
    const actionEmail = createEmail({
      id: "email-1",
      snippet: "Action needed",
      triage: "ACTION_REQUIRED",
    });
    const fyiEmail = createEmail({
      id: "email-2",
      snippet: "FYI only",
      labelIds: ["INBOX"],
      triage: "FYI",
    });
    const lowerCaseEmail = createEmail({
      id: "email-3",
      snippet: "Lower-case headers",
      headers: {
        from: "Lower Case <lower@example.com>",
        subject: "Lower-case reply",
        Date: "2026-04-07T11:00:00Z",
      },
      threadId: undefined,
      labelIds: ["INBOX"],
      triage: undefined,
    });

    mocks.getEmails.mockImplementation((params: Record<string, unknown> = {}) => {
      if (params.search === "fyi") {
        return Promise.resolve(createResponse([fyiEmail]));
      }
      if (params.triage === "ACTION_REQUIRED") {
        return Promise.resolve(createResponse([actionEmail, lowerCaseEmail]));
      }
      if (params.unread_only) {
        return Promise.resolve(createResponse([actionEmail, lowerCaseEmail]));
      }
      return Promise.resolve(createResponse([actionEmail, fyiEmail, lowerCaseEmail]));
    });

    renderWithProviders(<EmailPage />);

    expect(await screen.findByRole("heading", { name: "Email" })).toBeInTheDocument();
    expect(screen.getByText("Read-only inbox")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Compose" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reply/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /send/i })).not.toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("List count 3")).toBeInTheDocument();
    });
    expect(mocks.getEmails).toHaveBeenCalledWith({
      limit: 50,
      search: undefined,
      triage: undefined,
      unread_only: undefined,
    });

    await user.click(screen.getByRole("tab", { name: "Action" }));
    await waitFor(() => {
      expect(mocks.getEmails).toHaveBeenLastCalledWith({
        limit: 50,
        search: undefined,
        triage: "ACTION_REQUIRED",
        unread_only: undefined,
      });
    });

    await user.click(screen.getByRole("button", { name: "Show unread emails only" }));
    await waitFor(() => {
      expect(mocks.getEmails).toHaveBeenLastCalledWith({
        limit: 50,
        search: undefined,
        triage: "ACTION_REQUIRED",
        unread_only: true,
      });
    });

    await user.click(screen.getByRole("button", { name: "Open email-1" }));
    expect(screen.getByText("Detail email-1")).toBeInTheDocument();
    expect(screen.getByText("Selected email-1")).toBeInTheDocument();
    expect(useAppStore.getState().rightPanelContent).toBe("email");
    expect(useAppStore.getState().inspectedEmail?.id).toBe("email-1");

    await user.click(screen.getByRole("button", { name: "Open email-3" }));
    expect(screen.getByText("Detail email-3")).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("Search emails..."), "fyi");
    await waitFor(() => {
      expect(mocks.getEmails).toHaveBeenLastCalledWith({
        limit: 50,
        search: "fyi",
        triage: "ACTION_REQUIRED",
        unread_only: true,
      });
    });
  });

  it("renders an empty inbox state", async () => {
    mocks.getEmails.mockResolvedValue(createResponse([]));

    renderWithProviders(<EmailPage />);

    expect(await screen.findByText("List count 0")).toBeInTheDocument();
  });

  it("renders the page error when loading fails", async () => {
    const user = userEvent.setup();
    mocks.getEmails
      .mockRejectedValueOnce(new Error("email inbox failed"))
      .mockResolvedValue(createResponse([createEmail()]));

    renderWithProviders(<EmailPage />);

    expect(await screen.findByText("Page Error: email inbox failed")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() => {
      expect(mocks.getEmails).toHaveBeenCalledTimes(2);
      expect(screen.getByText("List count 1")).toBeInTheDocument();
    });
  });

  it("falls back to the generic email error message when the failure has no message", async () => {
    const user = userEvent.setup();
    mocks.getEmails.mockRejectedValueOnce({}).mockResolvedValue(createResponse([createEmail()]));

    renderWithProviders(<EmailPage />);

    expect(await screen.findByText("Page Error: Failed to load emails")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() => {
      expect(mocks.getEmails).toHaveBeenCalledTimes(2);
      expect(screen.getByText("List count 1")).toBeInTheDocument();
    });
  });

  it("shows headerless messages without exposing mutation actions", async () => {
    const user = userEvent.setup();
    const headerlessEmail = createEmail({
      id: "email-blank",
      headers: undefined,
      threadId: undefined,
      labelIds: ["INBOX"],
      triage: undefined,
    });

    mocks.getEmails.mockResolvedValue(createResponse([headerlessEmail]));

    renderWithProviders(<EmailPage />);

    expect(await screen.findByText("List count 1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open email-blank" }));
    expect(screen.getByText("Detail email-blank")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reply/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /send/i })).not.toBeInTheDocument();
  });
});
