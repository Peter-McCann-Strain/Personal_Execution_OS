import { MapPin, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatTime } from "@/lib/date";
import { getEventColor } from "./event-card.utils";
import type { CalendarEvent } from "@/types";

interface EventCardProps {
  event: CalendarEvent;
  compact?: boolean;
  onClick?: (event: CalendarEvent) => void;
  className?: string;
  style?: React.CSSProperties;
}

function EventCard({ event, compact = false, onClick, className, style }: EventCardProps) {
  const color = getEventColor(event.summary);
  const startTime = formatTime(event.start);
  const endTime = formatTime(event.end);

  if (compact) {
    return (
      <button
        onClick={() => onClick?.(event)}
        className={cn(
          "w-full truncate rounded-[var(--radius-sm)] px-1.5 py-0.5 text-left text-[10px] font-medium text-white transition-opacity hover:opacity-80",
          className,
        )}
        style={{ backgroundColor: color, ...style }}
        title={`${event.summary} (${startTime}-${endTime})`}
      >
        {event.summary}
      </button>
    );
  }

  return (
    <button
      onClick={() => onClick?.(event)}
      className={cn(
        "flex w-full flex-col gap-0.5 rounded-[var(--radius-md)] border-l-3 bg-[var(--color-bg-elevated)] p-2 text-left transition-colors hover:bg-[var(--color-bg-overlay)]",
        className,
      )}
      style={{ borderLeftColor: color, ...style }}
    >
      <p
        className="truncate text-sm font-medium text-[var(--color-fg-primary)]"
        title={event.summary}
      >
        {event.summary}
      </p>
      <p className="text-xs text-[var(--color-fg-secondary)]">
        {startTime} - {endTime}
      </p>
      {event.location && (
        <div className="flex items-center gap-1 text-xs text-[var(--color-fg-tertiary)]">
          <MapPin className="h-3 w-3" />
          <span className="truncate">{event.location}</span>
        </div>
      )}
      {event.attendees.length > 0 && (
        <div className="flex items-center gap-1 text-xs text-[var(--color-fg-tertiary)]">
          <Users className="h-3 w-3" />
          <span>
            {event.attendees.length} attendee{event.attendees.length !== 1 ? "s" : ""}
          </span>
        </div>
      )}
    </button>
  );
}

export { EventCard };
export type { EventCardProps };
