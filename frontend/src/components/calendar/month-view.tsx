import { useMemo } from "react";
import {
  startOfMonth,
  endOfMonth,
  startOfWeek,
  endOfWeek,
  eachDayOfInterval,
  isSameMonth,
  isToday,
  format,
} from "date-fns";
import { cn } from "@/lib/utils";
import { EventCard } from "./event-card";
import type { CalendarEvent } from "@/types";

interface MonthViewProps {
  currentDate: Date;
  events: CalendarEvent[];
  onSelectDay: (date: Date) => void;
  onSelectEvent: (event: CalendarEvent) => void;
}

function getEventsForDay(events: CalendarEvent[], day: Date): CalendarEvent[] {
  return events.filter((e) => {
    const start = new Date(e.start);
    const end = new Date(e.end);
    const dayStart = new Date(day);
    dayStart.setHours(0, 0, 0, 0);
    const dayEnd = new Date(day);
    dayEnd.setHours(23, 59, 59, 999);
    return start <= dayEnd && end >= dayStart;
  });
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MAX_VISIBLE_EVENTS = 3;

function MonthView({ currentDate, events, onSelectDay, onSelectEvent }: MonthViewProps) {
  const days = useMemo(() => {
    const monthStart = startOfMonth(currentDate);
    const monthEnd = endOfMonth(currentDate);
    const calStart = startOfWeek(monthStart, { weekStartsOn: 1 });
    const calEnd = endOfWeek(monthEnd, { weekStartsOn: 1 });
    return eachDayOfInterval({ start: calStart, end: calEnd });
  }, [currentDate]);

  return (
    <div className="flex flex-col">
      {/* Weekday headers */}
      <div className="grid grid-cols-7 border-b border-[var(--color-border-subtle)]">
        {WEEKDAYS.map((day) => (
          <div
            key={day}
            className="px-2 py-2 text-center text-xs font-medium text-[var(--color-fg-tertiary)]"
          >
            {day}
          </div>
        ))}
      </div>

      {/* Day grid */}
      <div className="grid grid-cols-7 flex-1">
        {days.map((day) => {
          const inMonth = isSameMonth(day, currentDate);
          const today = isToday(day);
          const dayEvents = getEventsForDay(events, day);
          const visibleEvents = dayEvents.slice(0, MAX_VISIBLE_EVENTS);
          const overflowCount = dayEvents.length - MAX_VISIBLE_EVENTS;

          return (
            <div
              role="button"
              tabIndex={0}
              key={day.toISOString()}
              onClick={() => onSelectDay(day)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelectDay(day);
                }
              }}
              className={cn(
                "flex min-h-[100px] flex-col border-b border-r border-[var(--color-border-subtle)] p-1.5 text-left transition-colors hover:bg-[var(--color-bg-elevated)]",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-border-focus)] focus-visible:ring-inset",
                !inMonth && "opacity-40",
              )}
            >
              {/* Day number */}
              <span
                className={cn(
                  "mb-1 inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-medium",
                  today
                    ? "bg-[var(--color-info-500)] text-white font-semibold"
                    : "text-[var(--color-fg-secondary)]",
                )}
              >
                {format(day, "d")}
              </span>

              {/* Events */}
              <div className="flex flex-col gap-0.5">
                {visibleEvents.map((event) => (
                  <EventCard
                    key={event.id}
                    event={event}
                    compact
                    onClick={(e) => {
                      onSelectEvent(e);
                    }}
                  />
                ))}
                {overflowCount > 0 && (
                  <span className="px-1 text-[10px] font-medium text-[var(--color-fg-tertiary)]">
                    +{overflowCount} more
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export { MonthView };
export type { MonthViewProps };
