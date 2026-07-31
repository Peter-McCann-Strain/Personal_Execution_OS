import { useMemo, useEffect, useState } from "react";
import { startOfWeek, addDays, isSameDay, isToday, format } from "date-fns";
import { cn } from "@/lib/utils";
import { tintedBg } from "@/lib/colors";
import { formatTime } from "@/lib/date";
import { getEventColor } from "./event-card.utils";
import type { CalendarEvent } from "@/types";

interface WeekViewProps {
  currentDate: Date;
  events: CalendarEvent[];
  onSelectEvent: (event: CalendarEvent) => void;
  startHour?: number;
  endHour?: number;
}

const HOUR_HEIGHT = 60; // px per hour

function getEventsForDay(events: CalendarEvent[], day: Date): CalendarEvent[] {
  return events.filter((e) => {
    const start = new Date(e.start);
    return isSameDay(start, day);
  });
}

function getEventPosition(
  event: CalendarEvent,
  startHour: number,
): { top: number; height: number } {
  const start = new Date(event.start);
  const end = new Date(event.end);
  const startMinutes = start.getHours() * 60 + start.getMinutes();
  const endMinutes = end.getHours() * 60 + end.getMinutes();
  const top = ((startMinutes - startHour * 60) / 60) * HOUR_HEIGHT;
  const height = Math.max(((endMinutes - startMinutes) / 60) * HOUR_HEIGHT, 20);
  return { top, height };
}

function WeekView({
  currentDate,
  events,
  onSelectEvent,
  startHour = 8,
  endHour = 20,
}: WeekViewProps) {
  const [currentTimeOffset, setCurrentTimeOffset] = useState<number | null>(null);

  const weekStart = useMemo(() => startOfWeek(currentDate, { weekStartsOn: 1 }), [currentDate]);

  const weekDays = useMemo(
    () => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)),
    [weekStart],
  );

  const hours = useMemo(
    () => Array.from({ length: endHour - startHour }, (_, i) => startHour + i),
    [startHour, endHour],
  );

  // Update current time indicator every 60s
  useEffect(() => {
    function update() {
      const now = new Date();
      const minutes = now.getHours() * 60 + now.getMinutes();
      const offset = ((minutes - startHour * 60) / 60) * HOUR_HEIGHT;
      setCurrentTimeOffset(
        offset >= 0 && offset <= (endHour - startHour) * HOUR_HEIGHT ? offset : null,
      );
    }
    update();
    const interval = setInterval(update, 60_000);
    return () => clearInterval(interval);
  }, [startHour, endHour]);

  const todayIndex = weekDays.findIndex((d) => isToday(d));

  return (
    <div className="flex flex-col overflow-auto">
      {/* Day headers */}
      <div className="sticky top-0 z-10 grid grid-cols-[60px_repeat(7,1fr)] border-b border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)]">
        <div className="border-r border-[var(--color-border-subtle)]" />
        {weekDays.map((day, i) => (
          <div
            key={day.toISOString()}
            className={cn(
              "border-r border-[var(--color-border-subtle)] px-2 py-2 text-center",
              i >= 5 && "bg-[var(--color-bg-elevated)]/30",
            )}
          >
            <p className="text-xs text-[var(--color-fg-tertiary)]">{format(day, "EEE")}</p>
            <p
              className={cn(
                "text-sm font-medium",
                isToday(day)
                  ? "inline-flex h-7 w-7 items-center justify-center rounded-full bg-[var(--color-info-500)] text-white"
                  : "text-[var(--color-fg-primary)]",
              )}
            >
              {format(day, "d")}
            </p>
          </div>
        ))}
      </div>

      {/* Time grid */}
      <div className="relative grid grid-cols-[60px_repeat(7,1fr)]">
        {/* Hour labels */}
        <div className="border-r border-[var(--color-border-subtle)]">
          {hours.map((hour) => (
            <div
              key={hour}
              className="flex items-start justify-end pr-2 text-[10px] text-[var(--color-fg-tertiary)]"
              style={{ height: HOUR_HEIGHT }}
            >
              <span className="-translate-y-1.5">{hour.toString().padStart(2, "0")}:00</span>
            </div>
          ))}
        </div>

        {/* Day columns */}
        {weekDays.map((day, dayIdx) => {
          const dayEvents = getEventsForDay(events, day);
          return (
            <div
              key={day.toISOString()}
              className={cn(
                "relative border-r border-[var(--color-border-subtle)]",
                dayIdx >= 5 && "bg-[var(--color-bg-elevated)]/30",
              )}
              style={{ height: hours.length * HOUR_HEIGHT }}
            >
              {/* Hour lines */}
              {hours.map((hour) => (
                <div
                  key={hour}
                  className="border-b border-[var(--color-border-subtle)]"
                  style={{ height: HOUR_HEIGHT }}
                />
              ))}

              {/* Events */}
              {dayEvents.map((event) => {
                const { top, height } = getEventPosition(event, startHour);
                const color = getEventColor(event.summary);
                return (
                  <button
                    key={event.id}
                    onClick={() => onSelectEvent(event)}
                    className="absolute left-0.5 right-0.5 overflow-hidden rounded-[var(--radius-sm)] px-1.5 py-0.5 text-left transition-opacity hover:opacity-80"
                    style={{
                      top,
                      height,
                      backgroundColor: tintedBg(color),
                      borderLeft: `3px solid ${color}`,
                    }}
                  >
                    <p className="truncate text-[11px] font-medium text-[var(--color-fg-primary)]">
                      {event.summary}
                    </p>
                    <p className="text-[10px] text-[var(--color-fg-secondary)]">
                      {formatTime(event.start)}
                    </p>
                  </button>
                );
              })}

              {/* Current time line */}
              {dayIdx === todayIndex && currentTimeOffset !== null && (
                <div
                  className="absolute left-0 right-0 z-10 flex items-center"
                  style={{ top: currentTimeOffset }}
                >
                  <div className="h-2.5 w-2.5 rounded-full bg-[var(--color-error-500)]" />
                  <div className="h-[2px] flex-1 bg-[var(--color-error-500)]" />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export { WeekView };
export type { WeekViewProps };
