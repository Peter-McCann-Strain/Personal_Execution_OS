import { pickColor } from "@/lib/colors";

function getEventColor(summary: string): string {
  return pickColor(summary);
}

export { getEventColor };
