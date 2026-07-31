import { memo } from "react";
import { Mail } from "lucide-react";
import { cn, formatRelativeTime } from "@/lib/utils";
import { pickColor } from "@/lib/colors";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { getSender, getSubject, isUnread, triageMap } from "./email-list.utils";
import type { Email } from "@/types";

function getDate(email: Email): string {
  if (email.internalDate) {
    const ts = Number(email.internalDate);
    const d = ts > 1e12 ? new Date(ts) : new Date(ts * 1000);
    return formatRelativeTime(d);
  }
  const hdr = email.headers ?? {};
  const dateHeader = hdr["Date"] || hdr["date"];
  if (dateHeader) return formatRelativeTime(new Date(dateHeader));
  return "";
}

// ─── Email List Item ─────────────────────────────────────────

interface EmailListItemProps {
  email: Email;
  selected: boolean;
  onSelect: (email: Email) => void;
}

const EmailListItem = memo(function EmailListItem({
  email,
  selected,
  onSelect,
}: EmailListItemProps) {
  const sender = getSender(email);
  const subject = getSubject(email);
  const unread = isUnread(email);
  const date = getDate(email);
  const triage = email.triage ? triageMap[email.triage] : null;
  const initials = sender
    .split(" ")
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <button
      onClick={() => onSelect(email)}
      className={cn(
        "flex w-full gap-3 border-b border-[var(--color-border-subtle)] px-4 py-3 text-left transition-colors",
        selected ? "bg-[var(--color-bg-overlay)]" : "hover:bg-[var(--color-bg-elevated)]",
        unread && "border-l-3 border-l-[var(--color-info-500)]",
      )}
    >
      {/* Avatar */}
      <div
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white"
        style={{ backgroundColor: pickColor(sender) }}
      >
        {initials || "?"}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span
            className={cn(
              "truncate text-sm",
              unread
                ? "font-semibold text-[var(--color-fg-primary)]"
                : "text-[var(--color-fg-secondary)]",
            )}
          >
            {sender}
          </span>
          <span className="shrink-0 text-[10px] text-[var(--color-fg-tertiary)]">{date}</span>
        </div>

        <p
          className={cn(
            "truncate text-sm",
            unread
              ? "font-semibold text-[var(--color-fg-primary)]"
              : "text-[var(--color-fg-secondary)]",
          )}
        >
          {subject}
        </p>

        <p className="mt-0.5 truncate text-xs text-[var(--color-fg-tertiary)]">{email.snippet}</p>

        {/* Badges */}
        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          {triage && (
            <span
              className={cn(
                "inline-flex items-center rounded-[var(--radius-full)] px-1.5 py-0.5 text-[10px] font-medium",
                triage.bgClass,
                triage.textClass,
                triage.pulse && "animate-pulse",
              )}
            >
              {triage.label}
            </span>
          )}
          {email.labelIds
            .filter((l) => l !== "UNREAD" && l !== "INBOX" && l !== "SENT" && l !== "DRAFT")
            .slice(0, 3)
            .map((label) => (
              <Badge key={label} size="sm">
                {label}
              </Badge>
            ))}
        </div>
      </div>
    </button>
  );
});

// ─── Email List ──────────────────────────────────────────────

interface EmailListProps {
  emails: Email[];
  selectedId: string | null;
  onSelectEmail: (email: Email) => void;
}

function EmailList({ emails, selectedId, onSelectEmail }: EmailListProps) {
  if (emails.length === 0) {
    return <EmptyState icon={Mail} title="No emails found" />;
  }

  return (
    <div className="flex flex-col overflow-y-auto">
      {emails.map((email) => (
        <EmailListItem
          key={email.id}
          email={email}
          selected={email.id === selectedId}
          onSelect={onSelectEmail}
        />
      ))}
    </div>
  );
}

export { EmailList, EmailListItem };
export type { EmailListProps, EmailListItemProps };
