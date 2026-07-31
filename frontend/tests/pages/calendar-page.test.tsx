import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  addMonths,
  endOfMonth,
  endOfWeek,
  startOfDay,
  startOfMonth,
  startOfWeek,
  subDays,
  subMonths,
} from "date-fns";
import { fireEvent } from "@testing-library/react";
import { renderWithProviders, screen, waitFor, within } from "../test-utils";
import { CalendarPage } from "@/pages/calendar";
import type { CalendarEvent } from "@/types";

const mocks = vi.hoisted(() => ({
  getEvents: vi.fn(),
}));

const selectedDate = new Date(2099, 3, 9, 12, 0, 0);
const fixedNow = new Date("2099-04-08T12:00:00.000Z");

function createEvent(overrides: Partial<CalendarEvent> = {}): CalendarEvent {
  return {
    id: "event-1",
    summary: "Planning sync",
    start: "2099-04-08T09:00:00.000Z",
    end: "2099-04-08T10:00:00.000Z",
    location: "Room 1",
    description: "Discuss the next milestone",
    attendees: ["a@example.com", "b@example.com"],
    ...overrides,
  };
}

vi.mock("@/api/calendar", () => ({
  getEvents: mocks.getEvents,
}));

vi.mock("@/components/ui/page-transition", () => ({
  PageTransition: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("@/components/ui/page-error", () => ({
  PageError: ({ message, onRetry }: { message: string; onRetry: () => void }) => (
    <div>
      <div>Page Error: {message}</div>
      <button type="button" onClick={onRetry}>
        Retry calendar
      </button>
    </div>
  ),
}));

vi.mock("@/components/calendar/month-view", () => ({
  MonthView: ({
    currentDate,
    onSelectDay,
    onSelectEvent,
  }: {
    currentDate: Date;
    onSelectDay: (date: Date) => void;
    onSelectEvent: (event: CalendarEvent) => void;
  }) => (
    <div>
      <div>Month view {currentDate.toDateString()}</div>
      <button type="button" onClick={() => onSelectDay(selectedDate)}>
        Select day
      </button>
      <button type="button" onClick={() => onSelectEvent(createEvent())}>
        Open month event
      </button>
    </div>
  ),
}));

vi.mock("@/components/calendar/week-view", () => ({
  WeekView: ({
    currentDate,
    onSelectEvent,
  }: {
    currentDate: Date;
    onSelectEvent: (event: CalendarEvent) => void;
  }) => (
    <div>
      <div>Week view {currentDate.toDateString()}</div>
      <button type="button" onClick={() => onSelectEvent(createEvent())}>
        Open week event
      </button>
      <button
        type="button"
        onClick={() =>
          onSelectEvent(
            createEvent({
              id: "event-sparse",
              summary: "Sparse event",
              location: null,
              description: null,
              attendees: [],
            }),
          )
        }
      >
        Open sparse week event
      </button>
    </div>
  ),
}));

vi.mock("@/components/calendar/day-view", () => ({
  DayView: ({
    currentDate,
    onSelectEvent,
  }: {
    currentDate: Date;
    onSelectEvent: (event: CalendarEvent) => void;
  }) => (
    <div>
      <div>Day view {currentDate.toDateString()}</div>
      <button type="button" onClick={() => onSelectEvent(createEvent())}>
        Open day event
      </button>
    </div>
  ),
}));

vi.mock("@/components/calendar/event-card", () => ({
  EventCard: ({
    event,
    compact,
    onClick,
  }: {
    event: CalendarEvent;
    compact?: boolean;
    onClick?: (event: CalendarEvent) => void;
  }) => (
    <button type="button" onClick={() => onClick?.(event)}>
      {compact ? `Open ${event.summary}` : event.summary}
    </button>
  ),
}));

describe("CalendarPage", () => {
  beforeEach(() => {
    mocks.getEvents.mockReset();
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(fixedNow);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders read-only views and event details without calendar mutation controls", async () => {
    const event = createEvent();
    const laterEvent = createEvent({
      id: "event-2",
      summary: "Quarterly review",
      start: "2099-04-09T14:00:00.000Z",
      end: "2099-04-09T15:00:00.000Z",
    });

    mocks.getEvents.mockResolvedValue([event, laterEvent]);

    const expectedWeekStart = startOfWeek(fixedNow, { weekStartsOn: 1 }).toISOString();
    const expectedWeekEnd = endOfWeek(fixedNow, { weekStartsOn: 1 }).toISOString();

    renderWithProviders(<CalendarPage />);

    expect(await screen.findByText(/Week view/)).toBeInTheDocument();
    expect(screen.getByText("Read-only calendar")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Event" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /create/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /edit/i })).not.toBeInTheDocument();
    await waitFor(() => {
      expect(mocks.getEvents).toHaveBeenCalledWith(expectedWeekStart, expectedWeekEnd);
    });

    fireEvent.click(screen.getByRole("button", { name: "Open week event" }));
    const dialog = await screen.findByRole("dialog", { name: "Event details" });
    expect(dialog).toHaveTextContent("Planning sync");
    expect(dialog).toHaveTextContent("Room 1");

    fireEvent.click(screen.getByRole("button", { name: "Close event details" }));
    expect(screen.queryByRole("dialog", { name: "Event details" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "month" }));
    expect(await screen.findByText(/Month view/)).toBeInTheDocument();

    const expectedMonthStart = startOfMonth(subMonths(fixedNow, 1)).toISOString();
    const expectedMonthEnd = endOfMonth(addMonths(fixedNow, 1)).toISOString();
    await waitFor(() => {
      expect(mocks.getEvents).toHaveBeenLastCalledWith(expectedMonthStart, expectedMonthEnd);
    });

    fireEvent.click(screen.getByRole("button", { name: "Select day" }));
    expect(await screen.findByText(/Day view/)).toBeInTheDocument();
    await waitFor(() => {
      expect(mocks.getEvents).toHaveBeenLastCalledWith(
        startOfDay(selectedDate).toISOString(),
        new Date(startOfDay(selectedDate).setHours(23, 59, 59, 999)).toISOString(),
      );
    });
  });

  it("renders a page error when calendar loading fails", async () => {
    mocks.getEvents.mockRejectedValue(new Error("calendar failed"));

    renderWithProviders(<CalendarPage />);

    expect(await screen.findByText("Page Error: calendar failed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry calendar" }));
    await waitFor(() => {
      expect(mocks.getEvents).toHaveBeenCalledTimes(2);
    });
  });

  it("falls back to the default page error message when the rejection has no message", async () => {
    mocks.getEvents.mockRejectedValue({});

    renderWithProviders(<CalendarPage />);

    expect(
      await screen.findByText("Page Error: Failed to load calendar events"),
    ).toBeInTheDocument();
  });

  it("renders the loading and empty upcoming states and supports calendar navigation controls", async () => {
    mocks.getEvents.mockImplementation(() => new Promise<CalendarEvent[]>(() => {}));

    const { container, unmount } = renderWithProviders(<CalendarPage />);
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);

    unmount();
    mocks.getEvents.mockResolvedValue([]);

    renderWithProviders(<CalendarPage />);

    expect(await screen.findByText(/Week view/)).toBeInTheDocument();
    expect(screen.getByText("No upcoming events")).toBeInTheDocument();
    expect(screen.getByText("April 2099")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Previous month" }));
    expect(screen.getByText("March 2099")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next month" }));
    expect(screen.getByText("April 2099")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Navigate back" }));
    await waitFor(() => {
      expect(mocks.getEvents).toHaveBeenLastCalledWith(
        startOfWeek(subDays(fixedNow, 7), { weekStartsOn: 1 }).toISOString(),
        endOfWeek(subDays(fixedNow, 7), { weekStartsOn: 1 }).toISOString(),
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Navigate forward" }));
    await waitFor(() => {
      expect(mocks.getEvents).toHaveBeenLastCalledWith(
        startOfWeek(fixedNow, { weekStartsOn: 1 }).toISOString(),
        endOfWeek(fixedNow, { weekStartsOn: 1 }).toISOString(),
      );
    });

    fireEvent.click(screen.getByRole("tab", { name: "month" }));
    fireEvent.click(screen.getByRole("button", { name: "Navigate back" }));
    await waitFor(() => {
      expect(mocks.getEvents).toHaveBeenLastCalledWith(
        startOfMonth(subMonths(subMonths(fixedNow, 1), 1)).toISOString(),
        endOfMonth(addMonths(subMonths(fixedNow, 1), 1)).toISOString(),
      );
    });

    const todayButtons = screen.getAllByRole("button", { name: "Today" });
    fireEvent.click(todayButtons[0]);
    expect(screen.getAllByText("April 2099").length).toBeGreaterThanOrEqual(2);
  });

  it("shows upcoming events in chronological order and limits the sidebar to five entries", async () => {
    const events = [
      createEvent({
        id: "event-6",
        summary: "Sixth future",
        start: "2099-04-14T09:00:00.000Z",
        end: "2099-04-14T10:00:00.000Z",
      }),
      createEvent({
        id: "event-2",
        summary: "Second future",
        start: "2099-04-10T09:00:00.000Z",
        end: "2099-04-10T10:00:00.000Z",
      }),
      createEvent({
        id: "event-5",
        summary: "Fifth future",
        start: "2099-04-13T09:00:00.000Z",
        end: "2099-04-13T10:00:00.000Z",
      }),
      createEvent({
        id: "event-1",
        summary: "First future",
        start: "2099-04-09T09:00:00.000Z",
        end: "2099-04-09T10:00:00.000Z",
      }),
      createEvent({
        id: "event-4",
        summary: "Fourth future",
        start: "2099-04-12T09:00:00.000Z",
        end: "2099-04-12T10:00:00.000Z",
      }),
      createEvent({
        id: "event-3",
        summary: "Third future",
        start: "2099-04-11T09:00:00.000Z",
        end: "2099-04-11T10:00:00.000Z",
      }),
    ];

    mocks.getEvents.mockResolvedValue(events);

    renderWithProviders(<CalendarPage />);

    expect(await screen.findByText(/Week view/)).toBeInTheDocument();

    const upcomingHeading = screen.getByRole("heading", { name: "Upcoming" });
    const upcomingSection = upcomingHeading.parentElement as HTMLElement;
    const upcomingButtons = within(upcomingSection).getAllByRole("button");

    expect(upcomingButtons).toHaveLength(5);
    expect(upcomingButtons.map((button) => button.textContent)).toEqual([
      "Open First future",
      "Open Second future",
      "Open Third future",
      "Open Fourth future",
      "Open Fifth future",
    ]);
  });

  it("keeps week mode when the mini calendar is used outside month view", async () => {
    mocks.getEvents.mockResolvedValue([createEvent()]);

    renderWithProviders(<CalendarPage />);

    expect(await screen.findByText(/Week view/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "15" }));

    expect(await screen.findByText(/Week view/)).toBeInTheDocument();
    const selectedDay = new Date(2099, 3, 15);
    await waitFor(() => {
      expect(mocks.getEvents).toHaveBeenLastCalledWith(
        startOfWeek(selectedDay, { weekStartsOn: 1 }).toISOString(),
        endOfWeek(selectedDay, { weekStartsOn: 1 }).toISOString(),
      );
    });
  });

  it("closes sparse event details with escape and omits optional sections when data is absent", async () => {
    mocks.getEvents.mockResolvedValue([createEvent()]);

    renderWithProviders(<CalendarPage />);

    expect(await screen.findByText(/Week view/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open sparse week event" }));
    const dialog = await screen.findByRole("dialog", { name: "Event details" });
    expect(within(dialog).getByText("Sparse event")).toBeInTheDocument();
    expect(within(dialog).queryByText("Location")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("Description")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("Attendees")).not.toBeInTheDocument();

    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Event details" })).not.toBeInTheDocument();
    });
  });

  it("closes event details from the backdrop click path", async () => {
    mocks.getEvents.mockResolvedValue([createEvent()]);

    renderWithProviders(<CalendarPage />);

    expect(await screen.findByText(/Week view/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open sparse week event" }));
    const firstBackdrop = screen.getByRole("presentation");
    fireEvent.click(firstBackdrop);
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Event details" })).not.toBeInTheDocument();
    });
  });

  it("uses the mini calendar to switch from month view into the selected day", async () => {
    mocks.getEvents.mockResolvedValue([createEvent()]);

    renderWithProviders(<CalendarPage />);

    expect(await screen.findByText(/Week view/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "month" }));
    expect(await screen.findByText(/Month view/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "15" }));

    const selectedDay = new Date(2099, 3, 15);
    expect(await screen.findByText(/Day view/)).toBeInTheDocument();
    await waitFor(() => {
      expect(mocks.getEvents).toHaveBeenLastCalledWith(
        startOfDay(selectedDay).toISOString(),
        new Date(startOfDay(selectedDay).setHours(23, 59, 59, 999)).toISOString(),
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Navigate back" }));
    await waitFor(() => {
      expect(mocks.getEvents).toHaveBeenLastCalledWith(
        startOfDay(subDays(selectedDay, 1)).toISOString(),
        new Date(startOfDay(subDays(selectedDay, 1)).setHours(23, 59, 59, 999)).toISOString(),
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Navigate forward" }));
    await waitFor(() => {
      expect(mocks.getEvents).toHaveBeenLastCalledWith(
        startOfDay(selectedDay).toISOString(),
        new Date(startOfDay(selectedDay).setHours(23, 59, 59, 999)).toISOString(),
      );
    });
  });
});
