import { useMemo, useEffect, useState } from "react";
import { isSameDay, isToday, format } from "date-fns";
import { MapPin, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { tintedBg } from "@/lib/colors";
import { formatTime } from "@/lib/date";
import { getEventColor } from "./event-card.utils";
import type { CalendarEvent } from "@/types";

interface DayViewProps {
  currentDate: Date;
  events: CalendarEvent[];
  onSelectEvent: (event: CalendarEvent) => void;
  startHour?: number;
  endHour?: number;
}

const HOUR_HEIGHT = 60;

function DayView({
  currentDate,
  events,
  onSelectEvent,
  startHour = 8,
  endHour = 20,
}: DayViewProps) {
  const [currentTimeOffset, setCurrentTimeOffset] = useState<number | null>(null);

  const hours = useMemo(
    () => Array.from({ length: endHour - startHour }, (_, i) => startHour + i),
    [startHour, endHour],
  );

  const dayEvents = useMemo(
    () =>
      events
        .filter((e) => isSameDay(new Date(e.start), currentDate))
        .sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime()),
    [events, currentDate],
  );

  // Current time indicator
  useEffect(() => {
    function update() {
      if (!isToday(currentDate)) {
        setCurrentTimeOffset(null);
        return;
      }
      const now = new Date();
      const minutes = now.getHours() * 60 + now.getMinutes();
      const offset = ((minutes - startHour * 60) / 60) * HOUR_HEIGHT;
      setCurrentTimeOffset(
        offset >= 0 && offset <= (endHour - startHour) * HOUR_HEIGHT ? offset : null,
      );
    }
    const initial = window.setTimeout(update, 0);
    const interval = setInterval(update, 60_000);
    return () => {
      clearTimeout(initial);
      clearInterval(interval);
    };
  }, [currentDate, startHour, endHour]);

  return (
    <div className="flex gap-6 overflow-auto">
      {/* Time column */}
      <div className="flex flex-col">
        {/* Date header */}
        <div className="sticky top-0 z-10 border-b border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] pb-2 pt-2 text-center">
          <p className="text-xs text-[var(--color-fg-tertiary)]">{format(currentDate, "EEEE")}</p>
          <p
            className={cn(
              "mx-auto mt-0.5 text-xl font-semibold",
              isToday(currentDate)
                ? "flex h-9 w-9 items-center justify-center rounded-full bg-[var(--color-info-500)] text-white"
                : "text-[var(--color-fg-primary)]",
            )}
          >
            {format(currentDate, "d")}
          </p>
        </div>

        {/* Time grid */}
        <div className="relative min-w-[300px] flex-1">
          {hours.map((hour) => (
            <div
              key={hour}
              className="flex border-b border-[var(--color-border-subtle)]"
              style={{ height: HOUR_HEIGHT }}
            >
              <div className="w-14 shrink-0 pr-2 pt-0 text-right text-[10px] text-[var(--color-fg-tertiary)]">
                <span className="-translate-y-1.5 inline-block">
                  {hour.toString().padStart(2, "0")}:00
                </span>
              </div>
              <div className="relative flex-1" />
            </div>
          ))}

          {/* Events overlay */}
          <div
            className="absolute left-14 right-0 top-0"
            style={{ height: hours.length * HOUR_HEIGHT }}
          >
            {dayEvents.map((event) => {
              const start = new Date(event.start);
              const end = new Date(event.end);
              const startMin = start.getHours() * 60 + start.getMinutes();
              const endMin = end.getHours() * 60 + end.getMinutes();
              const top = ((startMin - startHour * 60) / 60) * HOUR_HEIGHT;
              const height = Math.max(((endMin - startMin) / 60) * HOUR_HEIGHT, 28);
              const color = getEventColor(event.summary);

              return (
                <button
                  key={event.id}
                  onClick={() => onSelectEvent(event)}
                  className="absolute left-1 right-1 overflow-hidden rounded-[var(--radius-md)] px-2.5 py-1 text-left transition-opacity hover:opacity-80"
                  style={{
                    top,
                    height,
                    backgroundColor: tintedBg(color),
                    borderLeft: `3px solid ${color}`,
                  }}
                >
                  <p className="truncate text-sm font-medium text-[var(--color-fg-primary)]">
                    {event.summary}
                  </p>
                  <p className="text-xs text-[var(--color-fg-secondary)]">
                    {formatTime(event.start)} - {formatTime(event.end)}
                  </p>
                  {event.location && (
                    <div className="mt-0.5 flex items-center gap-1 text-xs text-[var(--color-fg-tertiary)]">
                      <MapPin className="h-3 w-3 shrink-0" />
                      <span className="truncate">{event.location}</span>
                    </div>
                  )}
                </button>
              );
            })}
          </div>

          {/* Current time line */}
          {currentTimeOffset !== null && (
            <div
              className="absolute left-14 right-0 z-10 flex items-center"
              style={{ top: currentTimeOffset }}
            >
              <div className="h-2.5 w-2.5 rounded-full bg-[var(--color-error-500)]" />
              <div className="h-[2px] flex-1 bg-[var(--color-error-500)]" />
            </div>
          )}
        </div>
      </div>

      {/* Agenda sidebar */}
      <div className="hidden w-72 shrink-0 flex-col gap-3 lg:flex">
        <div className="sticky top-0 z-10 border-b border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] pb-2 pt-2">
          <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">Today's Events</h3>
        </div>

        {dayEvents.length === 0 ? (
          <p className="py-8 text-center text-sm text-[var(--color-fg-tertiary)]">
            No events scheduled
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {dayEvents.map((event, idx) => {
              const color = getEventColor(event.summary);
              return (
                <button
                  key={event.id}
                  onClick={() => onSelectEvent(event)}
                  className="flex flex-col gap-1 rounded-[var(--radius-md)] border-l-3 bg-[var(--color-bg-elevated)] p-3 text-left transition-colors hover:bg-[var(--color-bg-overlay)]"
                  style={{ borderLeftColor: color }}
                >
                  <div className="flex items-baseline gap-2">
                    <span className="text-xs font-medium text-[var(--color-fg-tertiary)]">
                      {idx + 1}.
                    </span>
                    <span className="text-xs text-[var(--color-fg-secondary)]">
                      {formatTime(event.start)} - {formatTime(event.end)}
                    </span>
                  </div>
                  <p className="text-sm font-medium text-[var(--color-fg-primary)]">
                    {event.summary}
                  </p>
                  {event.location && (
                    <div className="flex items-center gap-1 text-xs text-[var(--color-fg-tertiary)]">
                      <MapPin className="h-3 w-3" />
                      {event.location}
                    </div>
                  )}
                  {event.attendees.length > 0 && (
                    <div className="flex items-center gap-1 text-xs text-[var(--color-fg-tertiary)]">
                      <Users className="h-3 w-3" />
                      {event.attendees.slice(0, 2).join(", ")}
                      {event.attendees.length > 2 && ` +${event.attendees.length - 2}`}
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export { DayView };
export type { DayViewProps };
