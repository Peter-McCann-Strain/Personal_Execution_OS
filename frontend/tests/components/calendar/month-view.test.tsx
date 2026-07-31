import { describe, expect, it, vi } from "vitest";
import { format } from "date-fns";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { MonthView } from "@/components/calendar/month-view";
import type { CalendarEvent } from "@/types";

function createEvent(overrides: Partial<CalendarEvent> = {}): CalendarEvent {
  return {
    id: "event-1",
    summary: "Planning sync",
    start: new Date(2026, 3, 8, 9, 0, 0).toISOString(),
    end: new Date(2026, 3, 8, 10, 0, 0).toISOString(),
    location: null,
    description: null,
    attendees: [],
    ...overrides,
  };
}

describe("MonthView", () => {
  it("renders the month grid, forwards day selection, and shows overflow", async () => {
    const user = userEvent.setup();
    const onSelectDay = vi.fn();
    const onSelectEvent = vi.fn();
    const currentDate = new Date("2026-04-08T12:00:00.000Z");
    const events = [
      createEvent(),
      createEvent({
        id: "event-2",
        summary: "Design review",
        start: "2026-04-08T11:00:00.000Z",
        end: "2026-04-08T12:00:00.000Z",
      }),
      createEvent({
        id: "event-3",
        summary: "Stakeholder sync",
        start: "2026-04-08T13:00:00.000Z",
        end: "2026-04-08T14:00:00.000Z",
      }),
      createEvent({
        id: "event-4",
        summary: "Follow-up",
        start: "2026-04-08T15:00:00.000Z",
        end: "2026-04-08T16:00:00.000Z",
      }),
      createEvent({
        id: "event-5",
        summary: "Next day",
        start: "2026-04-09T09:00:00.000Z",
        end: "2026-04-09T10:00:00.000Z",
      }),
    ];

    renderWithProviders(
      <MonthView
        currentDate={currentDate}
        events={events}
        onSelectDay={onSelectDay}
        onSelectEvent={onSelectEvent}
      />,
    );

    expect(screen.getByText("Mon")).toBeInTheDocument();
    expect(screen.getByText("Sun")).toBeInTheDocument();
    expect(screen.getByText("+1 more")).toBeInTheDocument();

    const dayCell = screen.getByText("8").closest('[role="button"]') as HTMLElement;
    await user.click(dayCell);
    expect(onSelectDay).toHaveBeenCalled();
    expect(format(onSelectDay.mock.calls[0][0], "yyyy-MM-dd")).toBe("2026-04-08");
    fireEvent.keyDown(dayCell, { key: "Enter" });
    fireEvent.keyDown(dayCell, { key: " " });
    expect(onSelectDay).toHaveBeenCalledTimes(3);

    await user.click(screen.getByRole("button", { name: "Planning sync" }));
    expect(onSelectEvent).toHaveBeenCalledWith(
      expect.objectContaining({ summary: "Planning sync" }),
    );
  });

  it("includes overlapping overnight events on the target day and handles keyboard selection", async () => {
    const onSelectDay = vi.fn();
    const onSelectEvent = vi.fn();
    const currentDate = new Date("2026-04-08T12:00:00.000Z");
    const events = [
      createEvent({
        id: "overnight",
        summary: "Overnight handoff",
        start: new Date(2026, 3, 8, 0, 30, 0).toISOString(),
        end: new Date(2026, 3, 8, 1, 30, 0).toISOString(),
      }),
    ];

    renderWithProviders(
      <MonthView
        currentDate={currentDate}
        events={events}
        onSelectDay={onSelectDay}
        onSelectEvent={onSelectEvent}
      />,
    );

    const dayCell = screen.getByText("8").closest('[role="button"]') as HTMLElement;
    fireEvent.keyDown(dayCell, { key: " " });
    expect(onSelectDay).toHaveBeenCalled();

    expect(await screen.findByRole("button", { name: "Overnight handoff" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Overnight handoff" }));
    expect(onSelectEvent).toHaveBeenCalledWith(
      expect.objectContaining({ summary: "Overnight handoff" }),
    );
  });
});
