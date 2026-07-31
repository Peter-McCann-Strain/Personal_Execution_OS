import { useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  CircleDashed,
  Clock,
  Columns3,
  FolderKanban,
  Flame,
  LayoutGrid,
  ListChecks,
  NotebookText,
  PanelTop,
  Search,
  Target,
} from "lucide-react";
import {
  addDays,
  differenceInCalendarDays,
  endOfDay,
  format,
  isAfter,
  isBefore,
  isToday,
  parseISO,
  startOfDay,
} from "date-fns";
import { getEvents } from "@/api/calendar";
import { getOpenCommitments, getOverdueCommitments } from "@/api/commitments";
import { getGoals } from "@/api/goals";
import { getHabits, type Habit } from "@/api/habits";
import { listNotes } from "@/api/notes";
import { getProjects } from "@/api/projects";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { PageTransition } from "@/components/ui/page-transition";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, normalizeProgressPercent, truncate } from "@/lib/utils";
import type { CalendarEvent, Commitment, Goal, Note, Project, Task } from "@/types";

type WorkbenchMode = "list" | "board" | "timeline";
type SavedViewId = "today" | "at-risk" | "projects" | "knowledge" | "all";
type WorkbenchType = "commitment" | "event" | "goal" | "habit" | "note" | "project" | "task";
type WorkbenchStatus = "active" | "blocked" | "done" | "due" | "overdue" | "scheduled" | "waiting";

interface WorkbenchItem {
  id: string;
  type: WorkbenchType;
  title: string;
  detail: string;
  status: WorkbenchStatus;
  dueAt: string | null;
  updatedAt: string | null;
  progress: number | null;
  route: string;
  searchText: string;
}

interface SavedView {
  id: SavedViewId;
  label: string;
  description: string;
  tone: "default" | "urgent" | "success" | "info";
  predicate: (item: WorkbenchItem) => boolean;
}

const MODE_OPTIONS: Array<{ value: WorkbenchMode; label: string }> = [
  { value: "list", label: "List" },
  { value: "board", label: "Board" },
  { value: "timeline", label: "Timeline" },
];

const BOARD_COLUMNS: Array<{ status: WorkbenchStatus; label: string }> = [
  { status: "overdue", label: "Overdue" },
  { status: "due", label: "Due Now" },
  { status: "active", label: "Active" },
  { status: "waiting", label: "Waiting" },
  { status: "scheduled", label: "Scheduled" },
  { status: "blocked", label: "Blocked" },
  { status: "done", label: "Done" },
];

function safeDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDate(value: string | null): string {
  const date = safeDate(value);
  if (!date) return "No date";
  if (isToday(date)) return format(date, "HH:mm");
  return format(date, "d MMM");
}

function isWithinDays(value: string | null, days: number): boolean {
  const date = safeDate(value);
  if (!date) return false;
  const now = new Date();
  return !isBefore(date, startOfDay(now)) && !isAfter(date, endOfDay(addDays(now, days)));
}

function isPastDue(value: string | null): boolean {
  const date = safeDate(value);
  return date != null && isBefore(date, startOfDay(new Date()));
}

function habitIntervalDays(habit: Habit): number {
  if (habit.frequency === "weekly") return 7;
  if (habit.frequency === "monthly") return 30;
  if (habit.frequency === "custom") return Math.max(1, habit.frequency_days ?? 1);
  return 1;
}

function isHabitDue(habit: Habit): boolean {
  if (!habit.active) return false;
  if (!habit.last_completed_at) return true;
  const completedAt = parseISO(habit.last_completed_at);
  if (Number.isNaN(completedAt.getTime())) return true;
  if (isToday(completedAt)) return false;
  return differenceInCalendarDays(new Date(), completedAt) >= habitIntervalDays(habit);
}

function projectTasks(project: Project): Task[] {
  return project.epics.flatMap((epic) => epic.milestones.flatMap((milestone) => milestone.tasks));
}

function projectProgress(project: Project): number {
  const tasks = projectTasks(project);
  if (tasks.length === 0) return 0;
  return Math.round((tasks.filter((task) => task.status === "done").length / tasks.length) * 100);
}

function projectStatus(project: Project): WorkbenchStatus {
  const tasks = projectTasks(project);
  if (project.status === "completed") return "done";
  if (tasks.some((task) => task.status === "blocked")) return "blocked";
  if (project.deadline && isPastDue(project.deadline)) return "overdue";
  return project.status === "planning" ? "waiting" : "active";
}

function commitmentStatus(commitment: Commitment): WorkbenchStatus {
  if (commitment.status === "completed") return "done";
  if (commitment.status === "cancelled") return "done";
  if (isPastDue(commitment.temporal_normalized)) return "overdue";
  if (commitment.temporal_normalized && isWithinDays(commitment.temporal_normalized, 1)) {
    return "due";
  }
  return commitment.status === "detected" ? "waiting" : "active";
}

function taskStatus(task: Task, project: Project): WorkbenchStatus {
  if (task.status === "done") return "done";
  if (task.status === "blocked") return "blocked";
  if (project.deadline && isPastDue(project.deadline)) return "overdue";
  if (task.status === "backlog") return "waiting";
  return "active";
}

function eventStatus(event: CalendarEvent): WorkbenchStatus {
  const start = safeDate(event.start);
  const end = safeDate(event.end);
  const now = new Date();
  if (end && isBefore(end, now)) return "done";
  if (start && end && !isBefore(now, start) && !isAfter(now, end)) return "due";
  return "scheduled";
}

function WorkbenchTypeIcon({ type, className }: { type: WorkbenchType; className?: string }) {
  switch (type) {
    case "commitment":
      return <ListChecks className={className} />;
    case "event":
      return <CalendarClock className={className} />;
    case "goal":
      return <Target className={className} />;
    case "habit":
      return <Flame className={className} />;
    case "note":
      return <NotebookText className={className} />;
    case "project":
      return <FolderKanban className={className} />;
    case "task":
      return <CheckCircle2 className={className} />;
  }
}

function statusVariant(
  status: WorkbenchStatus,
): "default" | "error" | "info" | "success" | "warning" {
  if (status === "overdue" || status === "blocked") return "error";
  if (status === "due") return "warning";
  if (status === "scheduled") return "info";
  if (status === "done") return "success";
  return "default";
}

function buildItems({
  commitments,
  events,
  goals,
  habits,
  notes,
  projects,
}: {
  commitments: Commitment[];
  events: CalendarEvent[];
  goals: Goal[];
  habits: Habit[];
  notes: Note[];
  projects: Project[];
}): WorkbenchItem[] {
  const projectItems = projects.map((project): WorkbenchItem => {
    const tasks = projectTasks(project);
    return {
      id: `project:${project.id}`,
      type: "project",
      title: project.title,
      detail: `${tasks.length} tasks • ${project.appetite ?? "no appetite"}`,
      status: projectStatus(project),
      dueAt: project.deadline,
      updatedAt: project.updated_at,
      progress: projectProgress(project),
      route: "/projects",
      searchText: `${project.title} ${project.description ?? ""}`,
    };
  });

  const taskItems = projects.flatMap((project) =>
    projectTasks(project)
      .filter((task) => task.status !== "done")
      .slice(0, 6)
      .map((task): WorkbenchItem => ({
        id: `task:${task.id}`,
        type: "task",
        title: task.title,
        detail: `${project.title} • ${task.status.replaceAll("_", " ")}`,
        status: taskStatus(task, project),
        dueAt: project.deadline,
        updatedAt: task.created_at,
        progress: null,
        route: "/projects",
        searchText: `${task.title} ${task.description ?? ""} ${project.title}`,
      })),
  );

  const commitmentItems = commitments.map((commitment): WorkbenchItem => ({
    id: `commitment:${commitment.id}`,
    type: "commitment",
    title: commitment.normalized_action || commitment.verbatim_text,
    detail: commitment.temporal_expression_raw ?? commitment.commitment_type,
    status: commitmentStatus(commitment),
    dueAt: commitment.temporal_normalized,
    updatedAt: commitment.updated_at,
    progress: null,
    route: "/commitments",
    searchText: `${commitment.normalized_action} ${commitment.verbatim_text} ${commitment.who_to ?? ""}`,
  }));

  const goalItems = goals.map((goal): WorkbenchItem => ({
    id: `goal:${goal.id}`,
    type: "goal",
    title: goal.title,
    detail: goal.goal_type ?? "goal",
    status:
      goal.status === "completed"
        ? "done"
        : goal.deadline && isPastDue(goal.deadline)
          ? "overdue"
          : normalizeProgressPercent(goal.progress) < 35
            ? "waiting"
            : "active",
    dueAt: goal.deadline,
    updatedAt: goal.updated_at,
    progress: normalizeProgressPercent(goal.progress),
    route: "/goals",
    searchText: `${goal.title} ${goal.goal_type ?? ""}`,
  }));

  const habitItems = habits.map((habit): WorkbenchItem => ({
    id: `habit:${habit.id}`,
    type: "habit",
    title: habit.name,
    detail: `${habit.current_streak} day streak`,
    status: isHabitDue(habit) ? "due" : "active",
    dueAt: isHabitDue(habit) ? new Date().toISOString() : habit.last_completed_at,
    updatedAt: habit.last_completed_at ?? habit.created_at,
    progress: null,
    route: "/habits",
    searchText: `${habit.name} ${habit.description ?? ""} ${habit.tags.join(" ")}`,
  }));

  const eventItems = events.map((event): WorkbenchItem => ({
    id: `event:${event.id}`,
    type: "event",
    title: event.summary,
    detail: `${formatDate(event.start)}-${formatDate(event.end)}`,
    status: eventStatus(event),
    dueAt: event.start,
    updatedAt: event.start,
    progress: null,
    route: "/calendar",
    searchText: `${event.summary} ${event.location ?? ""} ${event.description ?? ""}`,
  }));

  const noteItems = notes.slice(0, 30).map((note): WorkbenchItem => ({
    id: `note:${note.id}`,
    type: "note",
    title: note.title,
    detail: note.para_category ?? note.note_type ?? note.kind ?? "note",
    status: "active",
    dueAt: null,
    updatedAt: note.updated_at,
    progress: null,
    route: "/notes",
    searchText: `${note.title} ${note.executive_summary ?? ""} ${note.tags.join(" ")}`,
  }));

  return [
    ...commitmentItems,
    ...eventItems,
    ...goalItems,
    ...habitItems,
    ...projectItems,
    ...taskItems,
    ...noteItems,
  ].sort((a, b) => {
    const aTime = safeDate(a.dueAt)?.getTime() ?? safeDate(a.updatedAt)?.getTime() ?? 0;
    const bTime = safeDate(b.dueAt)?.getTime() ?? safeDate(b.updatedAt)?.getTime() ?? 0;
    return aTime - bTime;
  });
}

const SAVED_VIEWS: SavedView[] = [
  {
    id: "today",
    label: "Today",
    description: "Due now, scheduled today, and active routines.",
    tone: "info",
    predicate: (item) =>
      item.status === "due" ||
      item.status === "overdue" ||
      (item.dueAt != null && isWithinDays(item.dueAt, 0)),
  },
  {
    id: "at-risk",
    label: "At Risk",
    description: "Overdue, blocked, and low-progress items.",
    tone: "urgent",
    predicate: (item) =>
      item.status === "overdue" ||
      item.status === "blocked" ||
      (item.progress != null && item.progress < 35 && item.status !== "done"),
  },
  {
    id: "projects",
    label: "Projects",
    description: "Projects and next actions from nested tasks.",
    tone: "default",
    predicate: (item) => item.type === "project" || item.type === "task" || item.type === "goal",
  },
  {
    id: "knowledge",
    label: "Knowledge",
    description: "Recent notes and knowledge artifacts.",
    tone: "success",
    predicate: (item) => item.type === "note",
  },
  {
    id: "all",
    label: "All",
    description: "Everything the workbench can currently see.",
    tone: "default",
    predicate: () => true,
  },
];

function WorkbenchItemRow({ item }: { item: WorkbenchItem }) {
  const navigate = useNavigate();

  return (
    <div className="grid gap-3 border-b border-[var(--color-border-subtle)] px-4 py-3 last:border-b-0 md:grid-cols-[minmax(0,1.5fr)_120px_120px_160px] md:items-center">
      <div className="flex min-w-0 items-start gap-3">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--color-bg-elevated)]">
          <WorkbenchTypeIcon
            type={item.type}
            className="h-4 w-4 text-[var(--color-fg-secondary)]"
          />
        </div>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="line-clamp-1 text-sm font-medium text-[var(--color-fg-primary)]">
              {item.title}
            </h3>
            <Badge size="sm" variant={statusVariant(item.status)}>
              {item.status}
            </Badge>
          </div>
          <p className="mt-1 line-clamp-1 text-xs text-[var(--color-fg-tertiary)]">{item.detail}</p>
        </div>
      </div>
      <div className="text-xs capitalize text-[var(--color-fg-secondary)]">{item.type}</div>
      <div className="text-xs text-[var(--color-fg-secondary)]">{formatDate(item.dueAt)}</div>
      <div className="flex items-center justify-between gap-2 md:justify-end">
        {item.progress != null ? (
          <span className="text-xs tabular-nums text-[var(--color-fg-tertiary)]">
            {Math.round(item.progress)}%
          </span>
        ) : null}
        <Button size="sm" variant="ghost" onClick={() => navigate(item.route)}>
          Open
        </Button>
      </div>
    </div>
  );
}

function WorkbenchBoardCard({ item }: { item: WorkbenchItem }) {
  const navigate = useNavigate();

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3 transition-colors hover:border-[var(--color-border-strong)] hover:bg-[var(--color-bg-elevated)]">
      <button type="button" onClick={() => navigate(item.route)} className="w-full text-left">
        <div className="flex items-start gap-2">
          <WorkbenchTypeIcon
            type={item.type}
            className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-fg-tertiary)]"
          />
          <div className="min-w-0">
            <p className="line-clamp-2 text-sm font-medium text-[var(--color-fg-primary)]">
              {item.title}
            </p>
            <p className="mt-1 line-clamp-1 text-xs text-[var(--color-fg-tertiary)]">
              {item.type} • {formatDate(item.dueAt)}
            </p>
          </div>
        </div>
      </button>
      <div className="mt-3 flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={() => navigate(item.route)}>
          Open
        </Button>
      </div>
    </div>
  );
}

function WorkbenchStats({ items }: { items: WorkbenchItem[] }) {
  const overdue = items.filter((item) => item.status === "overdue").length;
  const due = items.filter((item) => item.status === "due").length;
  const blocked = items.filter((item) => item.status === "blocked").length;
  const scheduled = items.filter((item) => item.status === "scheduled").length;

  return (
    <div className="grid gap-3 sm:grid-cols-4">
      {[
        { label: "Due", value: due, icon: Clock },
        { label: "Overdue", value: overdue, icon: AlertTriangle },
        { label: "Blocked", value: blocked, icon: CircleDashed },
        { label: "Scheduled", value: scheduled, icon: CalendarClock },
      ].map((stat) => {
        const Icon = stat.icon;
        return (
          <Card key={stat.label} padding="md">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-2xl font-semibold tabular-nums text-[var(--color-fg-primary)]">
                  {stat.value}
                </p>
                <p className="text-xs text-[var(--color-fg-tertiary)]">{stat.label}</p>
              </div>
              <Icon className="h-4 w-4 text-[var(--color-fg-tertiary)]" />
            </div>
          </Card>
        );
      })}
    </div>
  );
}

function WorkbenchPage() {
  const navigate = useNavigate();
  const [savedViewId, setSavedViewId] = useState<SavedViewId>("today");
  const [mode, setMode] = useState<WorkbenchMode>("list");
  const [query, setQuery] = useState("");

  const range = useMemo(() => {
    const start = startOfDay(new Date());
    const end = endOfDay(addDays(start, 14));
    return {
      start: start.toISOString(),
      end: end.toISOString(),
    };
  }, []);

  const goalsQuery = useQuery({
    queryKey: ["goals", { limit: 100, status: "active", sort: "priority" }],
    queryFn: () => getGoals({ limit: 100, status: "active", sort: "priority" }),
    staleTime: 30_000,
  });
  const projectsQuery = useQuery({
    queryKey: ["projects", { limit: 50, sort: "deadline", order: "asc" }],
    queryFn: () => getProjects({ limit: 50, sort: "deadline", order: "asc" }),
    staleTime: 30_000,
  });
  const openCommitmentsQuery = useQuery({
    queryKey: ["commitments", "open"],
    queryFn: () => getOpenCommitments(50),
    staleTime: 30_000,
  });
  const overdueCommitmentsQuery = useQuery({
    queryKey: ["commitments", "overdue"],
    queryFn: getOverdueCommitments,
    staleTime: 30_000,
  });
  const habitsQuery = useQuery({
    queryKey: ["habits"],
    queryFn: getHabits,
    staleTime: 30_000,
  });
  const eventsQuery = useQuery({
    queryKey: ["calendar-events", range.start, range.end],
    queryFn: () => getEvents(range.start, range.end),
    staleTime: 30_000,
  });
  const notesQuery = useQuery({
    queryKey: ["notes", "", undefined, undefined],
    queryFn: () => listNotes({ limit: 60 }),
    staleTime: 30_000,
  });

  const commitments = useMemo(() => {
    const seen = new Set<string>();
    const result: Commitment[] = [];
    for (const commitment of [
      ...(overdueCommitmentsQuery.data ?? []),
      ...(openCommitmentsQuery.data ?? []),
    ]) {
      if (seen.has(commitment.id)) continue;
      seen.add(commitment.id);
      result.push(commitment);
    }
    return result;
  }, [openCommitmentsQuery.data, overdueCommitmentsQuery.data]);

  const items = useMemo(
    () =>
      buildItems({
        commitments,
        events: eventsQuery.data ?? [],
        goals: goalsQuery.data?.items ?? [],
        habits: habitsQuery.data ?? [],
        notes: notesQuery.data?.items ?? [],
        projects: projectsQuery.data?.items ?? [],
      }),
    [
      commitments,
      eventsQuery.data,
      goalsQuery.data?.items,
      habitsQuery.data,
      notesQuery.data?.items,
      projectsQuery.data?.items,
    ],
  );

  const savedView = SAVED_VIEWS.find((view) => view.id === savedViewId) ?? SAVED_VIEWS[0];
  const filteredItems = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return items.filter((item) => {
      if (!savedView.predicate(item)) return false;
      if (!normalizedQuery) return true;
      return item.searchText.toLowerCase().includes(normalizedQuery);
    });
  }, [items, query, savedView]);

  const loading =
    goalsQuery.isLoading ||
    projectsQuery.isLoading ||
    openCommitmentsQuery.isLoading ||
    overdueCommitmentsQuery.isLoading ||
    habitsQuery.isLoading ||
    eventsQuery.isLoading ||
    notesQuery.isLoading;

  const unavailableCount = [
    goalsQuery,
    projectsQuery,
    openCommitmentsQuery,
    overdueCommitmentsQuery,
    habitsQuery,
    eventsQuery,
    notesQuery,
  ].filter((result) => result.isError).length;

  return (
    <PageTransition>
      <div className="mx-auto flex max-w-[1500px] flex-col gap-6 p-6">
        <PageHeader
          title="Workbench"
          subtitle="Saved views over projects, goals, promises, routines, notes, and calendar time."
          icon={PanelTop}
          agentColor="project"
        >
          <Button
            variant="outline"
            onClick={() =>
              navigate(
                `/chat?prompt=${encodeURIComponent(
                  "Review my workbench and suggest the best next actions for today.",
                )}`,
              )
            }
          >
            Ask Assistant
            <ArrowRight className="h-4 w-4" />
          </Button>
        </PageHeader>

        {unavailableCount > 0 ? (
          <div className="rounded-[var(--radius-lg)] border border-[var(--color-warning-500)]/30 bg-[var(--color-warning-500)]/10 px-4 py-3 text-sm text-[var(--color-fg-secondary)]">
            {unavailableCount} source{unavailableCount === 1 ? "" : "s"} unavailable. The workbench
            is showing the data it could load.
          </div>
        ) : null}

        <WorkbenchStats items={items} />

        <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
          <aside className="space-y-3">
            <Card padding="none">
              <CardHeader>
                <CardTitle>Saved Views</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {SAVED_VIEWS.map((view) => {
                  const count = items.filter(view.predicate).length;
                  const selected = savedViewId === view.id;
                  return (
                    <button
                      key={view.id}
                      type="button"
                      onClick={() => setSavedViewId(view.id)}
                      className={cn(
                        "w-full rounded-[var(--radius-md)] border px-3 py-2 text-left transition-colors",
                        selected
                          ? "border-[var(--color-info-500)]/50 bg-[var(--color-info-500)]/10"
                          : "border-transparent hover:bg-[var(--color-bg-elevated)]",
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium text-[var(--color-fg-primary)]">
                          {view.label}
                        </span>
                        <span className="text-xs tabular-nums text-[var(--color-fg-tertiary)]">
                          {count}
                        </span>
                      </div>
                      <p className="mt-1 line-clamp-2 text-xs text-[var(--color-fg-tertiary)]">
                        {view.description}
                      </p>
                    </button>
                  );
                })}
              </CardContent>
            </Card>

            <Card padding="md">
              <div className="flex items-start gap-3">
                <LayoutGrid className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-info-500)]" />
                <p className="text-xs leading-5 text-[var(--color-fg-tertiary)]">
                  This is a frontend-composed workbench. Saved views reuse the same backend records
                  already shown across the app.
                </p>
              </div>
            </Card>
          </aside>

          <section className="min-w-0 space-y-4">
            <div className="flex flex-col gap-3 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="relative min-w-0 flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-fg-tertiary)]" />
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Filter this view..."
                  className="pl-9"
                />
              </div>
              <SegmentedControl
                label="Workbench view mode"
                value={mode}
                onChange={setMode}
                options={MODE_OPTIONS}
                size="md"
              />
            </div>

            <Card padding="none">
              <CardHeader className="flex-col items-start gap-1 sm:flex-row sm:items-center">
                <div>
                  <CardTitle>{savedView.label}</CardTitle>
                  <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">
                    {filteredItems.length} visible of {items.length} loaded records
                  </p>
                </div>
                <Badge size="sm" variant={unavailableCount > 0 ? "warning" : "success"}>
                  {unavailableCount > 0 ? "Partial" : "Live"}
                </Badge>
              </CardHeader>

              {loading ? (
                <CardContent className="space-y-3">
                  {Array.from({ length: 6 }).map((_, index) => (
                    <Skeleton key={index} className="h-14 w-full" />
                  ))}
                </CardContent>
              ) : filteredItems.length === 0 ? (
                <CardContent>
                  <div className="flex flex-col items-center justify-center rounded-[var(--radius-md)] border border-dashed border-[var(--color-border-default)] py-12 text-center">
                    <Columns3 className="h-8 w-8 text-[var(--color-fg-tertiary)]" />
                    <p className="mt-3 text-sm font-medium text-[var(--color-fg-primary)]">
                      No records in this view
                    </p>
                    <p className="mt-1 text-xs text-[var(--color-fg-tertiary)]">
                      Change saved view or clear the filter.
                    </p>
                  </div>
                </CardContent>
              ) : mode === "list" ? (
                <div>
                  {filteredItems.slice(0, 80).map((item) => (
                    <WorkbenchItemRow key={item.id} item={item} />
                  ))}
                </div>
              ) : mode === "board" ? (
                <CardContent>
                  <div className="grid gap-3 xl:grid-cols-3 2xl:grid-cols-4">
                    {BOARD_COLUMNS.map((column) => {
                      const columnItems = filteredItems.filter(
                        (item) => item.status === column.status,
                      );
                      return (
                        <div
                          key={column.status}
                          className="min-h-40 rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-elevated)] p-3"
                        >
                          <div className="mb-3 flex items-center justify-between gap-2">
                            <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--color-fg-tertiary)]">
                              {column.label}
                            </h3>
                            <span className="text-xs tabular-nums text-[var(--color-fg-tertiary)]">
                              {columnItems.length}
                            </span>
                          </div>
                          <div className="space-y-2">
                            {columnItems.slice(0, 8).map((item) => (
                              <WorkbenchBoardCard key={item.id} item={item} />
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </CardContent>
              ) : (
                <CardContent>
                  <div className="space-y-1">
                    {filteredItems
                      .filter((item) => item.dueAt || item.updatedAt)
                      .slice(0, 80)
                      .map((item) => (
                        <button
                          type="button"
                          key={item.id}
                          onClick={() => navigate(item.route)}
                          className="grid w-full grid-cols-[84px_20px_minmax(0,1fr)] items-start gap-3 rounded-[var(--radius-md)] px-2 py-2 text-left hover:bg-[var(--color-bg-elevated)]"
                        >
                          <span className="font-mono text-xs tabular-nums text-[var(--color-fg-tertiary)]">
                            {formatDate(item.dueAt ?? item.updatedAt)}
                          </span>
                          <span className="mt-1 h-2 w-2 rounded-full bg-[var(--color-info-500)]" />
                          <span className="min-w-0">
                            <span className="flex items-center gap-2">
                              <WorkbenchTypeIcon
                                type={item.type}
                                className="h-4 w-4 shrink-0 text-[var(--color-fg-tertiary)]"
                              />
                              <span className="truncate text-sm font-medium text-[var(--color-fg-primary)]">
                                {truncate(item.title, 90)}
                              </span>
                            </span>
                            <span className="mt-1 block text-xs capitalize text-[var(--color-fg-tertiary)]">
                              {item.type} • {item.status}
                            </span>
                          </span>
                        </button>
                      ))}
                  </div>
                </CardContent>
              )}
            </Card>
          </section>
        </div>
      </div>
    </PageTransition>
  );
}

export { WorkbenchPage };
