import type { LucideIcon } from "lucide-react";
import { AlertTriangle, ServerCrash, WifiOff } from "lucide-react";

function classifyError(message?: string): {
  icon: LucideIcon;
  title: string;
  hint?: string;
} {
  const msg = (message ?? "").toLowerCase();

  if (
    msg.includes("fetch") ||
    msg.includes("network") ||
    msg.includes("failed to fetch") ||
    msg.includes("err_connection")
  ) {
    return {
      icon: WifiOff,
      title: "Connection failed",
      hint: "The backend server isn't reachable.",
    };
  }
  if (msg.includes("500") || msg.includes("internal server")) {
    return {
      icon: ServerCrash,
      title: "Server error",
      hint: "The request reached the server but failed there.",
    };
  }
  if (msg.includes("404") || msg.includes("not found")) {
    return {
      icon: AlertTriangle,
      title: "Not found",
      hint: "The requested resource could not be found.",
    };
  }
  if (msg.includes("401") || msg.includes("403") || msg.includes("unauthorized")) {
    return {
      icon: AlertTriangle,
      title: "Access denied",
      hint: "Check your sign-in state or access permissions.",
    };
  }
  return {
    icon: AlertTriangle,
    title: "Request failed",
  };
}

export { classifyError };
