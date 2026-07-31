import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { WeekView } from "@/components/calendar/week-view";
import { formatTime } from "@/lib/date";
import type { CalendarEvent } from "@/types";

function createEvent(overrides: Partial<CalendarEvent> = {}): CalendarEvent {
  return {
    id: "event-1",
    summary: "Planning sync",
    start: new Date(2026, 3, 8, 9, 30, 0).toISOString(),
    end: new Date(2026, 3, 8, 10, 30, 0).toISOString(),
    location: "Room 1",
    description: null,
    attendees: [],
    ...overrides,
  };
}

describe("WeekView", () => {
  it("renders a weekly timeline and forwards event clicks", async () => {
    const user = userEvent.setup();
    const onSelectEvent = vi.fn();
    const currentDate = new Date("2026-04-08T12:00:00.000Z");

    renderWithProviders(
      <WeekView
        currentDate={currentDate}
        events={[
          createEvent(),
          createEvent({
            id: "event-2",
            summary: "Friday sync",
            start: "2026-04-10T11:00:00.000Z",
            end: "2026-04-10T12:00:00.000Z",
          }),
        ]}
        onSelectEvent={onSelectEvent}
      />,
    );

    expect(screen.getByText("Wed")).toBeInTheDocument();
    expect(screen.getByText("Fri")).toBeInTheDocument();
    const eventTime = formatTime(createEvent().start);
    expect(
      screen.getByRole("button", { name: new RegExp(`Planning sync ${eventTime}`) }),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: new RegExp(`Planning sync ${eventTime}`) }),
    );
    expect(onSelectEvent).toHaveBeenCalledWith(
      expect.objectContaining({ summary: "Planning sync" }),
    );
  });

  it("hides the current-time indicator on a non-today date and renders an empty week", () => {
    renderWithProviders(
      <WeekView
        currentDate={new Date("2026-04-01T12:00:00.000Z")}
        events={[]}
        onSelectEvent={vi.fn()}
      />,
    );

    expect(screen.getByText("Wed")).toBeInTheDocument();
    expect(screen.getByText("Sat")).toBeInTheDocument();
    expect(screen.queryByText("Planning sync")).not.toBeInTheDocument();
  });

  it("omits the current-time marker when the current time is outside the visible window", async () => {
    const user = userEvent.setup();
    const onSelectEvent = vi.fn();

    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-04-08T23:30:00.000Z"));

    renderWithProviders(
      <WeekView
        currentDate={new Date("2026-04-08T12:00:00.000Z")}
        events={[createEvent({ id: "event-3", summary: "Late sync" })]}
        onSelectEvent={onSelectEvent}
      />,
    );

    expect(screen.getByText("Wed")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Late sync/ }).length).toBe(1);

    await user.click(screen.getByRole("button", { name: /Late sync/ }));
    expect(onSelectEvent).toHaveBeenCalledWith(expect.objectContaining({ summary: "Late sync" }));

    vi.useRealTimers();
  });
});
