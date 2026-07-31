import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { triageMap, getSender, getSubject } from "./email-list.utils";
import type { Email } from "@/types";

// ─── Thread Message ──────────────────────────────────────────

interface ThreadMessageProps {
  email: Email;
  index: number;
  total: number;
  defaultExpanded: boolean;
}

function ThreadMessage({ email, index, total, defaultExpanded }: ThreadMessageProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const sender = getSender(email);
  const hdr = email.headers ?? {};
  const dateHeader = hdr["Date"] || hdr["date"] || "";
  const date = dateHeader
    ? new Date(dateHeader).toLocaleString("en-GB", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--color-border-subtle)]">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-4 py-3 text-left transition-colors hover:bg-[var(--color-bg-elevated)]"
      >
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-[var(--color-fg-tertiary)]">
            [{index + 1}/{total}]
          </span>
          <span className="text-sm font-medium text-[var(--color-fg-primary)]">{sender}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-[var(--color-fg-tertiary)]">{date}</span>
          {expanded ? (
            <ChevronUp className="h-3.5 w-3.5 text-[var(--color-fg-tertiary)]" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5 text-[var(--color-fg-tertiary)]" />
          )}
        </div>
      </button>
      {expanded && (
        <div className="border-t border-[var(--color-border-subtle)] px-4 py-3">
          <pre className="whitespace-pre-wrap text-sm leading-relaxed text-[var(--color-fg-primary)] font-[inherit]">
            {email.body}
          </pre>
        </div>
      )}
    </div>
  );
}

// ─── Email Detail ────────────────────────────────────────────

interface EmailDetailProps {
  email: Email;
  threadEmails?: Email[];
}

function EmailDetail({ email, threadEmails }: EmailDetailProps) {
  const sender = getSender(email);
  const subject = getSubject(email);
  const triage = email.triage ? triageMap[email.triage] : null;
  const h = email.headers ?? {};
  const to = h["To"] || h["to"] || "";
  const dateHeader = h["Date"] || h["date"] || "";
  const date = dateHeader
    ? new Date(dateHeader).toLocaleString("en-GB", {
        weekday: "short",
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";

  const hasThread = threadEmails && threadEmails.length > 1;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-[var(--color-border-subtle)] px-6 py-4">
        <h2 className="text-base font-semibold text-[var(--color-fg-primary)]">{subject}</h2>
        <div className="mt-2 flex flex-col gap-1 text-xs">
          <div className="flex gap-2">
            <span className="font-medium text-[var(--color-fg-tertiary)]">From:</span>
            <span className="text-[var(--color-fg-secondary)]">{sender}</span>
          </div>
          <div className="flex gap-2">
            <span className="font-medium text-[var(--color-fg-tertiary)]">To:</span>
            <span className="text-[var(--color-fg-secondary)]">{to}</span>
          </div>
          <div className="flex gap-2">
            <span className="font-medium text-[var(--color-fg-tertiary)]">Date:</span>
            <span className="text-[var(--color-fg-secondary)]">{date}</span>
          </div>
        </div>

        {/* Labels and triage */}
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {email.labelIds
            .filter((l) => l !== "UNREAD")
            .map((label) => (
              <Badge key={label} size="sm">
                {label}
              </Badge>
            ))}
          {triage && (
            <span
              className={cn(
                "inline-flex items-center rounded-[var(--radius-full)] px-2 py-0.5 text-[10px] font-medium",
                triage.bgClass,
                triage.textClass,
              )}
            >
              {triage.label}
            </span>
          )}
        </div>
      </div>

      {/* Body / Thread */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {hasThread ? (
          <div className="flex flex-col gap-3">
            <p className="text-xs font-medium text-[var(--color-fg-tertiary)]">
              Thread ({threadEmails.length} messages)
            </p>
            {threadEmails.map((msg, idx) => (
              <ThreadMessage
                key={msg.id}
                email={msg}
                index={idx}
                total={threadEmails.length}
                defaultExpanded={idx === threadEmails.length - 1}
              />
            ))}
          </div>
        ) : (
          <pre className="whitespace-pre-wrap text-sm leading-relaxed text-[var(--color-fg-primary)] font-[inherit]">
            {email.body}
          </pre>
        )}
      </div>
    </div>
  );
}

export { EmailDetail };
export type { EmailDetailProps };
