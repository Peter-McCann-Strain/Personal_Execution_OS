export interface RouteMeta {
  label: string;
  description: string;
}

export const ROUTE_META: Record<string, RouteMeta> = {
  "/dashboard": {
    label: "Dashboard",
    description: "Daily pulse, morning briefing, and a compact view of your active priorities.",
  },
  "/pulse": {
    label: "Pulse",
    description:
      "Scheduled actions, approvals, proactive inbox items, and the runtime surface for background work.",
  },
  "/chat": {
    label: "Chat",
    description:
      "Direct conversation with the assistant across planning, research, writing, and operations.",
  },
  "/diary": {
    label: "Diary",
    description: "Timestamped journaling, mood capture, and reflective memory building.",
  },
  "/memory": {
    label: "Memory",
    description: "Search and synthesize notes, diary entries, and past interactions.",
  },
  "/knowledge-graph": {
    label: "Knowledge Graph",
    description:
      "Explore extracted entities and the relationships forming across your captured context.",
  },
  "/notes": {
    label: "Notes",
    description: "Longer-lived notes, permanent references, and curated knowledge artifacts.",
  },
  "/workbench": {
    label: "Workbench",
    description:
      "Saved views across projects, goals, commitments, routines, notes, and calendar time.",
  },
  "/projects": {
    label: "Projects",
    description: "Track active work, milestones, tasks, and execution progress.",
  },
  "/goals": {
    label: "Goals",
    description: "Manage higher-level goals, progress signals, and deadlines.",
  },
  "/reviews": {
    label: "Reviews",
    description:
      "Weekly and periodic review outputs with patterns, recommendations, and follow-through.",
  },
  "/habits": {
    label: "Habits",
    description: "Daily and recurring routines with streaks, completion history, and notes.",
  },
  "/commitments": {
    label: "Commitments",
    description: "Promises, follow-ups, and time-bound obligations extracted from conversations.",
  },
  "/decisions": {
    label: "Decisions",
    description: "Capture choices, context, rationale, and later outcomes for major decisions.",
  },
  "/tutorials": {
    label: "Tutorials",
    description: "Run Socratic tutorial sessions and review prior learning conversations.",
  },
  "/contacts": {
    label: "Contacts",
    description: "Relationship tracking, interaction history, and lightweight personal CRM.",
  },
  "/calendar": {
    label: "Calendar",
    description: "View upcoming events and inspect available time windows without changing them.",
  },
  "/email": {
    label: "Email",
    description: "Read-only Gmail inbox triage and message detail.",
  },
  "/notifications": {
    label: "Notifications",
    description: "Operational alerts, unread items, and priority-driven system nudges.",
  },
  "/monitoring": {
    label: "Monitoring",
    description: "Health, traces, quality metrics, readiness checks, and runtime observability.",
  },
  "/settings": {
    label: "Settings",
    description: "Profile, integrations, data controls, and account configuration.",
  },
};

export function getRouteMeta(pathname: string): RouteMeta {
  return ROUTE_META[pathname] ?? ROUTE_META["/dashboard"];
}
