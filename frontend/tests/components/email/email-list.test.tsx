import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { EmailList } from "@/components/email/email-list";
import { getSender, getSubject, isUnread, triageMap } from "@/components/email/email-list.utils";
import type { Email } from "@/types";

vi.mock("@/lib/utils", async () => {
  const actual = await vi.importActual<typeof import("@/lib/utils")>("@/lib/utils");
  return {
    ...actual,
    formatRelativeTime: () => "2h ago",
  };
});

function createEmail(overrides: Partial<Email> = {}): Email {
  return {
    id: "email-1",
    threadId: "thread-1",
    snippet: "Follow up on the launch plan",
    headers: {
      From: "Ada Lovelace <ada@example.com>",
      Subject: "Launch plan",
      Date: "2026-04-07T09:00:00Z",
    },
    body: "Email body",
    labelIds: ["INBOX", "UNREAD"],
    internalDate: "1775552400000",
    triage: "URGENT",
    ...overrides,
  };
}

describe("EmailList", () => {
  it("renders emails, helpers, and triage badges", async () => {
    const user = userEvent.setup();
    const onSelectEmail = vi.fn();
    const email = createEmail();
    const unreadEmail = createEmail({
      labelIds: ["INBOX", "UNREAD", "PROJECT"],
    });

    expect(getSender(email)).toBe("Ada Lovelace");
    expect(getSubject(email)).toBe("Launch plan");
    expect(isUnread(email)).toBe(true);
    expect(triageMap.URGENT.label).toBe("Urgent");

    renderWithProviders(
      <EmailList emails={[unreadEmail]} selectedId={null} onSelectEmail={onSelectEmail} />,
    );

    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("Launch plan")).toBeInTheDocument();
    expect(screen.getByText("Follow up on the launch plan")).toBeInTheDocument();
    expect(screen.getByText("2h ago")).toBeInTheDocument();
    expect(screen.getByText("Urgent")).toBeInTheDocument();
    expect(screen.getByText("PROJECT")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Ada Lovelace/ }));
    expect(onSelectEmail).toHaveBeenCalledWith(unreadEmail);
  });

  it("renders the empty state when there are no emails", () => {
    renderWithProviders(<EmailList emails={[]} selectedId={null} onSelectEmail={vi.fn()} />);

    expect(screen.getByText("No emails found")).toBeInTheDocument();
  });

  it("handles sender, subject, unread, date, and selected-state fallbacks", async () => {
    const user = userEvent.setup();
    const onSelectEmail = vi.fn();
    const secondsEmail = createEmail({
      id: "email-seconds",
      headers: {
        from: "Grace Hopper",
        subject: "Seconds date",
      },
      internalDate: "1775552400",
      labelIds: ["INBOX"],
      triage: undefined,
    });
    const headerEmail = createEmail({
      id: "email-header",
      headers: {
        From: "Alan Turing <alan@example.com>",
        Subject: "Header date",
        Date: "2026-04-07T10:00:00Z",
      },
      labelIds: ["INBOX", "SENT"],
      triage: undefined,
    });
    const lowerDateEmail = createEmail({
      id: "email-lower-date",
      headers: {
        From: "Jane Doe <jane@example.com>",
        Subject: "Lower date",
        date: "2026-04-07T10:30:00Z",
      },
      internalDate: undefined,
      labelIds: ["INBOX"],
      triage: undefined,
    });
    const fallbackEmail = createEmail({
      id: "email-fallback",
      headers: undefined as unknown as Email["headers"],
      internalDate: undefined,
      labelIds: ["SENT"],
      triage: undefined,
    });

    expect(getSender(secondsEmail)).toBe("Grace Hopper");
    expect(getSubject(fallbackEmail)).toBe("(no subject)");
    expect(isUnread(fallbackEmail)).toBe(false);
    expect(
      isUnread(
        createEmail({
          id: "email-unlabeled",
          labelIds: undefined as unknown as Email["labelIds"],
          triage: undefined,
        }),
      ),
    ).toBe(false);

    renderWithProviders(
      <EmailList
        emails={[secondsEmail, headerEmail, lowerDateEmail, fallbackEmail]}
        selectedId="email-header"
        onSelectEmail={onSelectEmail}
      />,
    );

    expect(screen.getByText("Grace Hopper")).toBeInTheDocument();
    expect(screen.getByText("Header date")).toBeInTheDocument();
    expect(screen.getByText("Lower date")).toBeInTheDocument();
    expect(screen.getByText("(no subject)")).toBeInTheDocument();
    expect(screen.getAllByText("2h ago")).toHaveLength(3);

    await user.click(screen.getByRole("button", { name: /Alan Turing/ }));
    expect(onSelectEmail).toHaveBeenCalledWith(headerEmail);
  });

  it("falls back when headers omit sender and subject", () => {
    const email = createEmail({
      headers: {},
      labelIds: ["INBOX"],
      triage: undefined,
    });

    expect(getSender(email)).toBe("");
    expect(getSubject(email)).toBe("(no subject)");
    expect(isUnread(email)).toBe(false);
  });
});
