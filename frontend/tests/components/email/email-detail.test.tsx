import { describe, expect, it } from "vitest";
import { renderWithProviders, screen, userEvent, waitFor } from "../../test-utils";
import { EmailDetail } from "@/components/email/email-detail";
import type { Email } from "@/types";

function createEmail(overrides: Partial<Email> = {}): Email {
  return {
    id: "email-1",
    threadId: "thread-1",
    snippet: "Snippet",
    headers: {
      From: "Ada Lovelace <ada@example.com>",
      To: "Alex <alex@example.com>",
      Subject: "Project update",
      Date: "2026-04-07T09:30:00Z",
    },
    body: "Main email body",
    labelIds: ["INBOX", "UNREAD", "PROJECT"],
    internalDate: "1775554200000",
    triage: "ACTION_REQUIRED",
    ...overrides,
  };
}

describe("EmailDetail", () => {
  it("renders message details without mailbox mutation controls", () => {
    const email = createEmail();

    renderWithProviders(<EmailDetail email={email} />);

    expect(screen.getByRole("heading", { name: "Project update" })).toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("Alex <alex@example.com>")).toBeInTheDocument();
    expect(screen.getByText("PROJECT")).toBeInTheDocument();
    expect(screen.getByText("Action Required")).toBeInTheDocument();
    expect(screen.getByText("Main email body")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reply" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Label" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mark Read" })).not.toBeInTheDocument();
  });

  it("renders a single read message without triage or mark-read action", () => {
    const email = createEmail({
      body: "Solo body",
      headers: {
        From: "Grace Hopper <grace@example.com>",
        To: "Alex <alex@example.com>",
        Subject: undefined,
      },
      labelIds: ["INBOX"],
      triage: undefined,
    });

    renderWithProviders(<EmailDetail email={email} />);

    expect(screen.getByRole("heading", { name: "(no subject)" })).toBeInTheDocument();
    expect(screen.getByText("Grace Hopper")).toBeInTheDocument();
    expect(screen.getByText("Alex <alex@example.com>")).toBeInTheDocument();
    expect(screen.getByText("Solo body")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mark Read" })).not.toBeInTheDocument();
    expect(screen.queryByText("Action Required")).not.toBeInTheDocument();
  });

  it("handles a message with missing headers gracefully", () => {
    const email = createEmail({
      headers: undefined as unknown as Email["headers"],
      body: "Headerless body",
      labelIds: ["INBOX"],
      triage: undefined,
    });

    renderWithProviders(<EmailDetail email={email} />);

    expect(screen.getByRole("heading", { name: "(no subject)" })).toBeInTheDocument();
    expect(screen.getByText("Headerless body")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mark Read" })).not.toBeInTheDocument();
  });

  it("renders threaded messages and expands collapsed bodies", async () => {
    const user = userEvent.setup();
    const first = createEmail({
      id: "email-1",
      body: "First body",
      headers: {
        From: "Ada Lovelace <ada@example.com>",
        date: "2026-04-07T08:30:00Z",
      },
      labelIds: ["INBOX"],
      triage: undefined,
    });
    const second = createEmail({
      id: "email-2",
      body: "Second body",
      headers: undefined as unknown as Email["headers"],
      labelIds: ["INBOX"],
      triage: undefined,
    });

    renderWithProviders(<EmailDetail email={second} threadEmails={[first, second]} />);

    expect(screen.getByText("Thread (2 messages)")).toBeInTheDocument();
    expect(screen.getByText("Second body")).toBeInTheDocument();
    expect(screen.queryByText("First body")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Ada Lovelace/ }));

    await waitFor(() => {
      expect(screen.getByText("First body")).toBeInTheDocument();
    });
  });
});
