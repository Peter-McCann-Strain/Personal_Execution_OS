import { memo } from "react";
import { cn } from "@/lib/utils";
import { pickColor } from "@/lib/colors";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { HealthRing } from "./health-ring";
import type { Contact } from "@/types";

interface ContactCardProps {
  contact: Contact;
  onSelect: (contact: Contact) => void;
}

function getInitials(contact: Contact): string {
  const first = contact.first_name?.[0] ?? "";
  const last = contact.last_name?.[0] ?? "";
  return (first + last).toUpperCase();
}

function getDaysSince(dateStr: string | null): number | null {
  if (!dateStr) return null;
  const d = new Date(dateStr);
  const now = new Date();
  return Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24));
}

const ContactCard = memo(function ContactCard({ contact, onSelect }: ContactCardProps) {
  const initials = getInitials(contact);
  const avatarColor = pickColor(contact.id);
  const daysSince = getDaysSince(contact.last_interaction_at);
  const fullName = [contact.first_name, contact.last_name].filter(Boolean).join(" ");

  return (
    <Card hoverable padding="none" className="flex flex-col" onClick={() => onSelect(contact)}>
      <div className="flex items-start gap-3 p-4">
        {/* Avatar */}
        <div
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-sm font-semibold text-white"
          style={{ backgroundColor: avatarColor }}
        >
          {initials}
        </div>

        {/* Score ring + Name area */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between">
            <h3 className="truncate text-sm font-semibold text-[var(--color-fg-primary)]">
              {fullName}
            </h3>
            <HealthRing score={contact.relationship_score} size={36} strokeWidth={3} />
          </div>

          {/* Last interaction */}
          <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">
            {daysSince !== null
              ? `Last interaction: ${daysSince === 0 ? "today" : `${daysSince}d ago`}`
              : "No interactions yet"}
          </p>
        </div>
      </div>

      {/* Tags */}
      {(contact.tags ?? []).length > 0 && (
        <div className="flex flex-wrap gap-1 px-4 pb-2">
          {(contact.tags ?? []).map((tag) => (
            <Badge key={tag} size="sm">
              {tag}
            </Badge>
          ))}
        </div>
      )}

      {/* Frequency info */}
      {contact.interaction_frequency_days && (
        <div className="px-4 pb-2">
          <p className="text-xs text-[var(--color-fg-tertiary)]">
            Target: every {contact.interaction_frequency_days}d
            {daysSince !== null && (
              <span
                className={cn(
                  "ml-2",
                  daysSince > contact.interaction_frequency_days
                    ? "text-[var(--color-error-500)]"
                    : "text-[var(--color-success-500)]",
                )}
              >
                {daysSince > contact.interaction_frequency_days
                  ? `${daysSince - contact.interaction_frequency_days}d overdue`
                  : "On track"}
              </span>
            )}
          </p>
        </div>
      )}
    </Card>
  );
});

export { ContactCard };
export type { ContactCardProps };
