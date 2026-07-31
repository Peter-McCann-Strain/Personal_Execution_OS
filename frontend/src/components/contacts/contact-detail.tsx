import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Phone,
  Mail,
  Coffee,
  MessageSquare,
  ArrowRight,
  ArrowLeft,
  ChevronLeft,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Button } from "@/components/ui/button";
import { formatInteractionDateTime } from "@/lib/date";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { HealthRing } from "./health-ring";
import { getContact, getContactInteractions } from "@/api/contacts";
import type { Contact, Interaction, InteractionType, InteractionDirection } from "@/types";

// ─── Type Icons ──────────────────────────────────────────────

const typeIconMap: Record<InteractionType, LucideIcon> = {
  call: Phone,
  email: Mail,
  coffee: Coffee,
  message: MessageSquare,
};

const typeColorMap: Record<InteractionType, string> = {
  call: "var(--color-info-500)",
  email: "oklch(0.58 0.18 290)",
  coffee: "var(--color-warning-500)",
  message: "var(--color-success-500)",
};

// ─── Sub-Components ──────────────────────────────────────────

interface InteractionItemProps {
  interaction: Interaction;
  isLast: boolean;
}

function InteractionItem({ interaction, isLast }: InteractionItemProps) {
  const Icon = typeIconMap[interaction.interaction_type];
  const color = typeColorMap[interaction.interaction_type];
  const DirectionIcon = interaction.direction === "outgoing" ? ArrowRight : ArrowLeft;
  const { date: formattedDate, time: formattedTime } = formatInteractionDateTime(
    interaction.interaction_at,
  );

  return (
    <div className="flex gap-3">
      {/* Timeline line + dot */}
      <div className="flex flex-col items-center">
        <div
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
          style={{ backgroundColor: `color-mix(in oklch, ${color} 15%, transparent)` }}
        >
          <Icon className="h-4 w-4" style={{ color }} />
        </div>
        {!isLast && <div className="w-px flex-1 bg-[var(--color-border-subtle)]" />}
      </div>

      {/* Content */}
      <div className="flex-1 pb-6">
        <div className="flex items-center gap-2 text-xs text-[var(--color-fg-tertiary)]">
          <span className="font-medium uppercase text-[var(--color-fg-secondary)]">
            {interaction.interaction_type}
          </span>
          <DirectionIcon className="h-3 w-3" />
          <span>{formattedDate}</span>
          <span>{formattedTime}</span>
        </div>
        {interaction.summary && (
          <p className="mt-1 text-sm text-[var(--color-fg-primary)]">{interaction.summary}</p>
        )}
        {interaction.topics.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {interaction.topics.map((topic) => (
              <Badge key={topic} size="sm">
                {topic}
              </Badge>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Detail Header ───────────────────────────────────────────

interface DetailHeaderProps {
  contact: Contact;
}

function DetailHeader({ contact }: DetailHeaderProps) {
  const fullName = [contact.first_name, contact.last_name].filter(Boolean).join(" ");
  const initials = ((contact.first_name?.[0] ?? "") + (contact.last_name?.[0] ?? "")).toUpperCase();

  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:gap-6">
      {/* Avatar + name */}
      <div className="flex items-center gap-4">
        <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-[var(--color-info-500)] text-lg font-bold text-white">
          {initials}
        </div>
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-[var(--color-fg-primary)]">{fullName}</h2>
          {contact.email && (
            <p className="text-sm text-[var(--color-fg-secondary)]">{contact.email}</p>
          )}
          {contact.how_we_met && (
            <p className="mt-0.5 text-xs italic text-[var(--color-fg-tertiary)]">
              {contact.how_we_met}
            </p>
          )}
        </div>
      </div>

      {/* Score ring */}
      <div className="sm:ml-auto">
        <HealthRing score={contact.relationship_score} size={80} strokeWidth={5} />
      </div>
    </div>
  );
}

// ─── Main Component ──────────────────────────────────────────

interface ContactDetailProps {
  contactId: string;
  onBack: () => void;
}

function ContactDetail({ contactId, onBack }: ContactDetailProps) {
  const [typeFilter, setTypeFilter] = useState<InteractionType | "all">("all");
  const [dirFilter, setDirFilter] = useState<InteractionDirection | "all">("all");
  const [nowMs] = useState(Date.now);

  const contactQuery = useQuery({
    queryKey: ["contact", contactId],
    queryFn: () => getContact(contactId),
  });

  const interactionsQuery = useQuery({
    queryKey: ["contact-interactions", contactId],
    queryFn: () => getContactInteractions(contactId),
  });

  const contact = contactQuery.data;
  const interactions = interactionsQuery.data ?? [];

  const filteredInteractions = interactions.filter((i) => {
    if (typeFilter !== "all" && i.interaction_type !== typeFilter) return false;
    if (dirFilter !== "all" && i.direction !== dirFilter) return false;
    return true;
  });

  if (contactQuery.isLoading) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-60 w-full" />
      </div>
    );
  }

  if (!contact) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 p-12 text-[var(--color-fg-tertiary)]">
        <p>Contact not found</p>
        <Button variant="ghost" onClick={onBack}>
          Go back
        </Button>
      </div>
    );
  }

  const daysSince = contact.last_interaction_at
    ? Math.floor((nowMs - new Date(contact.last_interaction_at).getTime()) / (1000 * 60 * 60 * 24))
    : null;

  return (
    <div className="flex flex-col gap-6 p-6">
      {/* Back button */}
      <Button variant="ghost" size="sm" className="w-fit gap-1.5" onClick={onBack}>
        <ChevronLeft className="h-4 w-4" />
        Back to contacts
      </Button>

      {/* Header */}
      <Card padding="lg">
        <DetailHeader contact={contact} />

        {/* Tags */}
        {(contact.tags ?? []).length > 0 && (
          <div className="mt-4 flex flex-wrap gap-1.5">
            {(contact.tags ?? []).map((tag) => (
              <Badge key={tag}>{tag}</Badge>
            ))}
          </div>
        )}

        {/* Quick stats */}
        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div className="rounded-[var(--radius-md)] bg-[var(--color-bg-elevated)] p-3">
            <p className="text-xs text-[var(--color-fg-tertiary)]">Score</p>
            <p className="text-lg font-semibold text-[var(--color-fg-primary)]">
              {Math.round(contact.relationship_score ?? 0)}
            </p>
          </div>
          <div className="rounded-[var(--radius-md)] bg-[var(--color-bg-elevated)] p-3">
            <p className="text-xs text-[var(--color-fg-tertiary)]">Last Contact</p>
            <p className="text-lg font-semibold text-[var(--color-fg-primary)]">
              {daysSince !== null ? `${daysSince}d` : "--"}
            </p>
          </div>
          <div className="rounded-[var(--radius-md)] bg-[var(--color-bg-elevated)] p-3">
            <p className="text-xs text-[var(--color-fg-tertiary)]">Target Freq</p>
            <p className="text-lg font-semibold text-[var(--color-fg-primary)]">
              {contact.interaction_frequency_days ? `${contact.interaction_frequency_days}d` : "--"}
            </p>
          </div>
          <div className="rounded-[var(--radius-md)] bg-[var(--color-bg-elevated)] p-3">
            <p className="text-xs text-[var(--color-fg-tertiary)]">Interactions</p>
            <p className="text-lg font-semibold text-[var(--color-fg-primary)]">
              {interactions.length}
            </p>
          </div>
        </div>
      </Card>

      {/* Interaction Timeline */}
      <Card padding="lg">
        <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">
          Interaction Timeline
        </h3>

        {/* Filters */}
        <div className="mt-3 flex flex-wrap gap-2">
          {/* Type filter */}
          <SegmentedControl
            value={typeFilter}
            onChange={setTypeFilter}
            options={["all", "call", "email", "coffee", "message"] as const}
            label="Interaction type"
          />

          {/* Direction filter */}
          <SegmentedControl
            value={dirFilter}
            onChange={setDirFilter}
            options={["all", "incoming", "outgoing"] as const}
            label="Interaction direction"
          />
        </div>

        {/* Timeline */}
        <div className="mt-4">
          {interactionsQuery.isLoading ? (
            <div className="flex flex-col gap-4">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : filteredInteractions.length === 0 ? (
            <p className="py-8 text-center text-sm text-[var(--color-fg-tertiary)]">
              No interactions found
            </p>
          ) : (
            filteredInteractions.map((interaction, idx) => (
              <InteractionItem
                key={interaction.id}
                interaction={interaction}
                isLast={idx === filteredInteractions.length - 1}
              />
            ))
          )}
        </div>
      </Card>
    </div>
  );
}

export { ContactDetail };
export type { ContactDetailProps };
