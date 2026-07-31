import { useState, useMemo, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Calendar as CalendarIcon } from "lucide-react";
import {
  startOfMonth,
  endOfMonth,
  startOfWeek,
  endOfWeek,
  addMonths,
  subMonths,
  addWeeks,
  subWeeks,
  addDays,
  subDays,
  eachDayOfInterval,
  isSameDay,
  isSameMonth,
  isToday,
  format,
} from "date-fns";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Skeleton } from "@/components/ui/skeleton";
import { PageError } from "@/components/ui/page-error";
import { PageTransition } from "@/components/ui/page-transition";
import { MonthView } from "@/components/calendar/month-view";
import { WeekView } from "@/components/calendar/week-view";
import { DayView } from "@/components/calendar/day-view";
import { EventCard } from "@/components/calendar/event-card";
import { getEvents } from "@/api/calendar";
import type { CalendarEvent } from "@/types";

// ─── Types ───────────────────────────────────────────────────

type CalendarViewMode = "month" | "week" | "day";

// ─── Mini Calendar ───────────────────────────────────────────

interface MiniCalendarProps {
  currentDate: Date;
  selectedDate: Date;
  onSelectDate: (date: Date) => void;
  onNavigateMonth: (date: Date) => void;
}

function MiniCalendar({
  currentDate,
  selectedDate,
  onSelectDate,
  onNavigateMonth,
}: MiniCalendarProps) {
  const days = useMemo(() => {
    const monthStart = startOfMonth(currentDate);
    const monthEnd = endOfMonth(currentDate);
    const calStart = startOfWeek(monthStart, { weekStartsOn: 1 });
    const calEnd = endOfWeek(monthEnd, { weekStartsOn: 1 });
    return eachDayOfInterval({ start: calStart, end: calEnd });
  }, [currentDate]);

  return (
    <div>
      <div className="flex items-center justify-between">
        <button
          onClick={() => onNavigateMonth(subMonths(currentDate, 1))}
          className="p-1 text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)]"
          aria-label="Previous month"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <span className="text-xs font-medium text-[var(--color-fg-secondary)]">
          {format(currentDate, "MMMM yyyy")}
        </span>
        <button
          onClick={() => onNavigateMonth(addMonths(currentDate, 1))}
          className="p-1 text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)]"
          aria-label="Next month"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-2 grid grid-cols-7 gap-0">
        {["M", "T", "W", "T", "F", "S", "S"].map((d, i) => (
          <div
            key={i}
            className="pb-1 text-center text-[10px] font-medium text-[var(--color-fg-tertiary)]"
          >
            {d}
          </div>
        ))}
        {days.map((day) => {
          const inMonth = isSameMonth(day, currentDate);
          const today = isToday(day);
          const selected = isSameDay(day, selectedDate);

          return (
            <button
              key={day.toISOString()}
              onClick={() => onSelectDate(day)}
              className={cn(
                "flex h-6 w-6 items-center justify-center rounded-full text-[10px] transition-colors mx-auto",
                today &&
                  !selected &&
                  "bg-[var(--color-info-500)]/20 text-[var(--color-info-500)] font-semibold",
                selected && "bg-[var(--color-info-500)] text-white font-semibold",
                !today &&
                  !selected &&
                  (inMonth
                    ? "text-[var(--color-fg-secondary)] hover:bg-[var(--color-bg-overlay)]"
                    : "text-[var(--color-fg-tertiary)] hover:bg-[var(--color-bg-overlay)]"),
              )}
            >
              {format(day, "d")}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────

function CalendarPage() {
  const [view, setView] = useState<CalendarViewMode>("week");
  const [currentDate, setCurrentDate] = useState(new Date());
  const [miniCalMonth, setMiniCalMonth] = useState(new Date());
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);

  // Compute date range for query
  const { rangeStart, rangeEnd } = useMemo(() => {
    const start =
      view === "month"
        ? startOfMonth(subMonths(currentDate, 1))
        : view === "week"
          ? startOfWeek(currentDate, { weekStartsOn: 1 })
          : new Date(new Date(currentDate).setHours(0, 0, 0, 0));
    const end =
      view === "month"
        ? endOfMonth(addMonths(currentDate, 1))
        : view === "week"
          ? endOfWeek(currentDate, { weekStartsOn: 1 })
          : new Date(new Date(currentDate).setHours(23, 59, 59, 999));
    return {
      rangeStart: start.toISOString(),
      rangeEnd: end.toISOString(),
    };
  }, [currentDate, view]);

  const eventsQuery = useQuery({
    queryKey: ["calendar-events", rangeStart, rangeEnd],
    queryFn: () => getEvents(rangeStart, rangeEnd),
  });

  const events = useMemo(() => eventsQuery.data ?? [], [eventsQuery.data]);

  // Upcoming events for sidebar
  const upcomingEvents = useMemo(() => {
    const now = new Date();
    return events
      .filter((e) => new Date(e.start) >= now)
      .sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime())
      .slice(0, 5);
  }, [events]);

  // Navigation
  const goBack = useCallback(() => {
    setCurrentDate((d) =>
      view === "month" ? subMonths(d, 1) : view === "week" ? subWeeks(d, 1) : subDays(d, 1),
    );
  }, [view]);

  const goForward = useCallback(() => {
    setCurrentDate((d) =>
      view === "month" ? addMonths(d, 1) : view === "week" ? addWeeks(d, 1) : addDays(d, 1),
    );
  }, [view]);

  const goToday = useCallback(() => {
    setCurrentDate(new Date());
    setMiniCalMonth(new Date());
  }, []);

  const handleSelectDay = useCallback((date: Date) => {
    setCurrentDate(date);
    setView("day");
  }, []);

  const handleSelectEvent = useCallback((event: CalendarEvent) => {
    setSelectedEvent(event);
  }, []);

  // Title
  const title = useMemo(() => {
    if (view === "month") return format(currentDate, "MMMM yyyy");
    if (view === "week") {
      const ws = startOfWeek(currentDate, { weekStartsOn: 1 });
      const we = endOfWeek(currentDate, { weekStartsOn: 1 });
      return `${format(ws, "MMM d")} - ${format(we, "MMM d, yyyy")}`;
    }
    return format(currentDate, "EEEE, MMMM d, yyyy");
  }, [currentDate, view]);

  return (
    <PageTransition>
      <div className="flex h-full flex-col">
        {/* Toolbar */}
        <div className="flex flex-col gap-2 border-b border-[var(--color-border-subtle)] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="icon" onClick={goBack} aria-label="Navigate back">
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="sm" onClick={goToday}>
              Today
            </Button>
            <Button variant="ghost" size="icon" onClick={goForward} aria-label="Navigate forward">
              <ChevronRight className="h-4 w-4" />
            </Button>
            <h1 className="ml-2 text-base font-semibold text-[var(--color-fg-primary)]">{title}</h1>
          </div>

          <div className="flex items-center gap-2">
            {/* View toggle */}
            <SegmentedControl
              value={view}
              onChange={setView}
              options={["month", "week", "day"] as const}
              label="Calendar view"
            />
            <span className="hidden text-xs text-[var(--color-fg-tertiary)] sm:inline">
              Read-only calendar
            </span>
          </div>
        </div>

        {/* Main content */}
        <div className="flex flex-1 overflow-hidden">
          {/* Sidebar */}
          <aside className="hidden w-56 shrink-0 flex-col gap-4 overflow-y-auto border-r border-[var(--color-border-subtle)] p-4 lg:flex">
            <MiniCalendar
              currentDate={miniCalMonth}
              selectedDate={currentDate}
              onSelectDate={(d) => {
                setCurrentDate(d);
                if (view === "month") setView("day");
              }}
              onNavigateMonth={setMiniCalMonth}
            />

            <Button variant="ghost" size="sm" className="w-full" onClick={goToday}>
              <CalendarIcon className="mr-1.5 h-3.5 w-3.5" />
              Today
            </Button>

            {/* Upcoming events */}
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--color-fg-tertiary)]">
                Upcoming
              </h3>
              {upcomingEvents.length === 0 ? (
                <p className="text-xs text-[var(--color-fg-tertiary)]">No upcoming events</p>
              ) : (
                <div className="flex flex-col gap-1.5">
                  {upcomingEvents.map((event) => (
                    <EventCard key={event.id} event={event} compact onClick={handleSelectEvent} />
                  ))}
                </div>
              )}
            </div>
          </aside>

          {/* Calendar view */}
          <main className="flex-1 overflow-auto">
            {eventsQuery.isError ? (
              <PageError
                message={eventsQuery.error?.message ?? "Failed to load calendar events"}
                onRetry={() => eventsQuery.refetch()}
                context="your calendar"
                icon={CalendarIcon}
              />
            ) : eventsQuery.isLoading ? (
              <div className="flex flex-col gap-2 p-4">
                <Skeleton className="h-8 w-48" />
                <Skeleton className="h-[400px] w-full" />
              </div>
            ) : view === "month" ? (
              <MonthView
                currentDate={currentDate}
                events={events}
                onSelectDay={handleSelectDay}
                onSelectEvent={handleSelectEvent}
              />
            ) : view === "week" ? (
              <WeekView
                currentDate={currentDate}
                events={events}
                onSelectEvent={handleSelectEvent}
              />
            ) : (
              <DayView
                currentDate={currentDate}
                events={events}
                onSelectEvent={handleSelectEvent}
              />
            )}
          </main>
        </div>

        {/* Event detail popover */}
        {selectedEvent && (
          <>
            <div
              className="fixed inset-0 z-40 bg-black/30"
              onClick={() => setSelectedEvent(null)}
              role="presentation"
            />
            <div
              className="fixed right-4 top-1/4 z-50 w-80 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4 shadow-xl"
              role="dialog"
              aria-label="Event details"
              onKeyDown={(e) => {
                if (e.key === "Escape") setSelectedEvent(null);
              }}
            >
              <div className="flex items-start justify-between">
                <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">
                  {selectedEvent.summary}
                </h3>
                <button
                  onClick={() => setSelectedEvent(null)}
                  className="text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)]"
                  aria-label="Close event details"
                >
                  &times;
                </button>
              </div>
              <div className="mt-3 flex flex-col gap-2 text-xs">
                <div>
                  <span className="font-medium text-[var(--color-fg-tertiary)]">Time</span>
                  <p className="text-[var(--color-fg-secondary)]">
                    {new Date(selectedEvent.start).toLocaleString("en-GB", {
                      weekday: "short",
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}{" "}
                    -{" "}
                    {new Date(selectedEvent.end).toLocaleTimeString("en-GB", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </p>
                </div>
                {selectedEvent.location && (
                  <div>
                    <span className="font-medium text-[var(--color-fg-tertiary)]">Location</span>
                    <p className="text-[var(--color-fg-secondary)]">{selectedEvent.location}</p>
                  </div>
                )}
                {selectedEvent.description && (
                  <div>
                    <span className="font-medium text-[var(--color-fg-tertiary)]">Description</span>
                    <p className="text-[var(--color-fg-secondary)]">{selectedEvent.description}</p>
                  </div>
                )}
                {selectedEvent.attendees.length > 0 && (
                  <div>
                    <span className="font-medium text-[var(--color-fg-tertiary)]">Attendees</span>
                    <ul className="mt-0.5">
                      {selectedEvent.attendees.map((a) => (
                        <li key={a} className="text-[var(--color-fg-secondary)]">
                          {a}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </PageTransition>
  );
}

export { CalendarPage };
