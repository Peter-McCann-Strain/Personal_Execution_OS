import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { DayView } from "@/components/calendar/day-view";
import type { CalendarEvent } from "@/types";

function createEvent(overrides: Partial<CalendarEvent> = {}): CalendarEvent {
  return {
    id: "event-1",
    summary: "Planning sync",
    start: new Date(2026, 3, 8, 9, 0, 0).toISOString(),
    end: new Date(2026, 3, 8, 10, 0, 0).toISOString(),
    location: "Room 1",
    description: null,
    attendees: ["a@example.com", "b@example.com", "c@example.com"],
    ...overrides,
  };
}

describe("DayView", () => {
  it("renders the day agenda and forwards clicks", async () => {
    const user = userEvent.setup();
    const onSelectEvent = vi.fn();
    const currentDate = new Date("2026-04-08T12:00:00.000Z");

    renderWithProviders(
      <DayView
        currentDate={currentDate}
        events={[
          createEvent(),
          createEvent({
            id: "event-2",
            summary: "Later sync",
            start: new Date(2026, 3, 8, 11, 0, 0).toISOString(),
            end: new Date(2026, 3, 8, 12, 0, 0).toISOString(),
            location: null,
            attendees: [],
          }),
        ]}
        onSelectEvent={onSelectEvent}
      />,
    );

    expect(screen.getByText("Wednesday")).toBeInTheDocument();
    expect(screen.getByText("Today's Events")).toBeInTheDocument();
    expect(screen.getAllByText("Planning sync").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Room 1").length).toBeGreaterThan(0);
    expect(screen.getByText("a@example.com, b@example.com +1")).toBeInTheDocument();

    await user.click(screen.getAllByRole("button", { name: /Planning sync/ })[0]);
    expect(onSelectEvent).toHaveBeenCalledWith(
      expect.objectContaining({ summary: "Planning sync" }),
    );
  });

  it("renders the empty agenda state when there are no events", () => {
    renderWithProviders(
      <DayView
        currentDate={new Date("2026-04-08T12:00:00.000Z")}
        events={[]}
        onSelectEvent={vi.fn()}
      />,
    );

    expect(screen.getByText("No events scheduled")).toBeInTheDocument();
  });

  it("hides the current-time indicator on a non-today date and handles single-attendee events", async () => {
    const user = userEvent.setup();
    const onSelectEvent = vi.fn();
    const { container } = renderWithProviders(
      <DayView
        currentDate={new Date("2026-04-07T12:00:00.000Z")}
        events={[
          createEvent({
            id: "event-3",
            summary: "Solo sync",
            start: new Date(2026, 3, 7, 9, 0, 0).toISOString(),
            end: new Date(2026, 3, 7, 10, 0, 0).toISOString(),
            attendees: ["solo@example.com"],
            location: null,
          }),
        ]}
        onSelectEvent={onSelectEvent}
      />,
    );

    expect(screen.getByText("Tuesday")).toBeInTheDocument();
    expect(screen.queryByText("No events scheduled")).not.toBeInTheDocument();
    expect(screen.getAllByText("Solo sync").length).toBeGreaterThan(0);

    await user.click(screen.getAllByRole("button", { name: /Solo sync/ })[0]);
    expect(onSelectEvent).toHaveBeenCalledWith(expect.objectContaining({ summary: "Solo sync" }));
    expect(container).toBeTruthy();
  });

  it("omits the current-time marker when the current time is outside the visible window", async () => {
    const user = userEvent.setup();
    const onSelectEvent = vi.fn();

    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-04-08T23:30:00.000Z"));

    renderWithProviders(
      <DayView
        currentDate={new Date("2026-04-08T12:00:00.000Z")}
        events={[
          createEvent({
            id: "event-4",
            summary: "Late sync",
            start: new Date(2026, 3, 8, 9, 30, 0).toISOString(),
            end: new Date(2026, 3, 8, 10, 30, 0).toISOString(),
          }),
        ]}
        onSelectEvent={onSelectEvent}
      />,
    );

    expect(screen.getByText("Wednesday")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Late sync/ }).length).toBe(2);

    await user.click(screen.getAllByRole("button", { name: /Late sync/ })[1]);
    expect(onSelectEvent).toHaveBeenCalledWith(expect.objectContaining({ summary: "Late sync" }));

    vi.useRealTimers();
  });
});
