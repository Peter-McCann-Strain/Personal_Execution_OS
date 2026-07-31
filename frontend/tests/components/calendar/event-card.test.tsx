import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "../../test-utils";
import { EventCard } from "@/components/calendar/event-card";
import { getEventColor } from "@/components/calendar/event-card.utils";
import { formatTime } from "@/lib/date";
import type { CalendarEvent } from "@/types";

function createEvent(overrides: Partial<CalendarEvent> = {}): CalendarEvent {
  return {
    id: "event-1",
    summary: "Planning sync",
    start: new Date(2026, 3, 8, 9, 0, 0).toISOString(),
    end: new Date(2026, 3, 8, 10, 30, 0).toISOString(),
    location: "Room 1",
    description: null,
    attendees: ["a@example.com", "b@example.com"],
    ...overrides,
  };
}

describe("EventCard", () => {
  it("renders the full card with location and attendees", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const event = createEvent();

    renderWithProviders(<EventCard event={event} onClick={onClick} />);

    const button = screen.getByRole("button");
    expect(button).toHaveTextContent("Planning sync");
    expect(button).toHaveTextContent(formatTime(event.start));
    expect(button).toHaveTextContent(formatTime(event.end));
    expect(button).toHaveTextContent("Room 1");
    expect(button).toHaveTextContent("2 attendees");
    expect(getEventColor("Planning sync")).toBe(getEventColor("Planning sync"));

    await user.click(button);
    expect(onClick).toHaveBeenCalledWith(expect.objectContaining({ summary: "Planning sync" }));
  });

  it("renders the compact card and forwards clicks", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const event = createEvent({ summary: "Compact event" });

    renderWithProviders(<EventCard event={event} compact onClick={onClick} />);

    expect(screen.getByRole("button")).toHaveTextContent("Compact event");

    await user.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledWith(expect.objectContaining({ summary: "Compact event" }));
  });

  it("renders without optional metadata and keeps singular attendee text", () => {
    renderWithProviders(
      <EventCard
        event={createEvent({
          summary: "Solo event",
          location: null,
          attendees: ["solo@example.com"],
        })}
      />,
    );

    expect(screen.getByRole("button")).toHaveTextContent("Solo event");
    expect(screen.queryByText("Room 1")).not.toBeInTheDocument();
    expect(screen.getByText("1 attendee")).toBeInTheDocument();
  });
});
