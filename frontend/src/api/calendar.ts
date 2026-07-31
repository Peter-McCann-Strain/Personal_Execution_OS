import { api, apiPath, getWithQuery } from "./client";
import { API_PATHS } from "./generated/paths";
import type { CalendarEvent, FreeSlot } from "@/types";

export interface GetFreeSlotsParams {
  duration_minutes: number;
  start_hour?: number;
  end_hour?: number;
  days_ahead?: number;
}

export async function getEvents(start: string, end: string): Promise<CalendarEvent[]> {
  return api.get<CalendarEvent[]>(apiPath(API_PATHS.apiCalendarEvents), {
    start,
    end,
  });
}

export async function getFreeSlots(params: GetFreeSlotsParams): Promise<FreeSlot[]> {
  return getWithQuery<FreeSlot[], GetFreeSlotsParams>(
    apiPath(API_PATHS.apiCalendarFreeSlots),
    params,
  );
}
