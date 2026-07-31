import type {
  Contact,
  Episode,
  EpisodeStats,
  MoodTrendPoint,
  Goal,
  Habit,
  HabitLog,
  Interaction,
  Note,
  PaginatedResponse,
  Project,
  Epic,
  Milestone,
  Task,
} from "@/types";

function createPaginatedResponse<T>(
  items: T[],
  overrides: Partial<PaginatedResponse<T>> = {},
): PaginatedResponse<T> {
  return {
    items,
    total: items.length,
    page: 1,
    page_size: items.length || 10,
    has_more: false,
    ...overrides,
  };
}

function createTask(overrides: Partial<Task> = {}): Task {
  const normalizedStatus =
    overrides.status === "in-progress"
      ? "in_progress"
      : overrides.status === "completed"
        ? "done"
        : overrides.status;
  return {
    id: "task-1",
    milestone_id: "milestone-1",
    title: "Ship onboarding flow",
    description: null,
    status: normalizedStatus ?? "backlog",
    estimate_hours: null,
    actual_hours: null,
    wsjf_score: null,
    complexity: null,
    context_tags: [],
    blocked_reason: null,
    dependency_task_ids: [],
    sort_order: 0,
    started_at: null,
    completed_at: null,
    created_at: "2026-04-01T09:00:00Z",
    ...overrides,
  };
}

function createMilestone(overrides: Partial<Milestone> = {}): Milestone {
  return {
    id: "milestone-1",
    epic_id: "epic-1",
    title: "Milestone 1",
    success_criteria: null,
    sort_order: 0,
    tasks: [],
    created_at: "2026-04-01T09:00:00Z",
    ...overrides,
  };
}

function createEpic(overrides: Partial<Epic> = {}): Epic {
  return {
    id: "epic-1",
    project_id: "project-1",
    title: "Epic 1",
    description: null,
    sort_order: 0,
    milestones: [],
    created_at: "2026-04-01T09:00:00Z",
    ...overrides,
  };
}

function createProject(overrides: Partial<Project> = {}): Project {
  return {
    id: "project-1",
    title: "Project Alpha",
    description: "A shape-up style project",
    status: "planning",
    appetite: "small",
    deadline: "2026-04-10T12:00:00Z",
    epics: [],
    created_at: "2026-04-01T09:00:00Z",
    updated_at: "2026-04-01T09:00:00Z",
    ...overrides,
  };
}

function createContact(overrides: Partial<Contact> = {}): Contact {
  return {
    id: "contact-1",
    first_name: "Alex",
    last_name: "Morgan",
    email: "alex@example.com",
    tags: ["friend"],
    how_we_met: "Met through work",
    interaction_frequency_days: 14,
    relationship_score: 82,
    relationship_health: 78,
    last_interaction_at: "2026-04-01T12:00:00Z",
    created_at: "2026-01-01T09:00:00Z",
    updated_at: "2026-04-01T09:00:00Z",
    ...overrides,
  };
}

function createInteraction(overrides: Partial<Interaction> = {}): Interaction {
  return {
    id: "interaction-1",
    contact_id: "contact-1",
    interaction_type: "call",
    direction: "outgoing",
    channel: "manual",
    summary: "Discussed next steps",
    topics: ["planning"],
    interaction_at: "2026-04-02T10:00:00Z",
    created_at: "2026-04-02T10:00:00Z",
    ...overrides,
  };
}

function createNote(overrides: Partial<Note> = {}): Note {
  return {
    id: "note-1",
    title: "Zettelkasten note",
    slug: null,
    aliases: [],
    kind: "note",
    daily_date: null,
    frontmatter: {},
    content: "Atomic note content",
    note_type: "permanent",
    para_category: "resource",
    progressive_summary_level: 1,
    executive_summary: "Short summary",
    source_url: null,
    tags: ["pkm"],
    created_at: "2026-04-01T09:00:00Z",
    updated_at: "2026-04-01T09:00:00Z",
    ...overrides,
  };
}

function createEpisode(overrides: Partial<Episode> = {}): Episode {
  return {
    id: "episode-1",
    content: "Diary content",
    summary: "Diary summary",
    episode_type: "diary",
    para_category: "resource",
    mood_score: 7.5,
    energy_rating: 6.5,
    tags: ["focus", "work"],
    people_mentioned: ["Ada"],
    source: "api",
    created_at: "2026-04-08T12:00:00Z",
    ...overrides,
  };
}

function createGoal(overrides: Partial<Goal> = {}): Goal {
  return {
    id: "goal-1",
    title: "Ship world-class runtime",
    goal_type: "quarterly",
    parent_id: null,
    priority: 3,
    status: "active",
    progress: 45,
    deadline: "2026-04-20T09:00:00Z",
    evidence: [],
    created_at: "2026-04-01T09:00:00Z",
    updated_at: "2026-04-01T09:00:00Z",
    ...overrides,
  };
}

function createHabit(overrides: Partial<Habit> = {}): Habit {
  return {
    id: "habit-1",
    name: "Morning meditation",
    description: "Start the day calmly",
    frequency: "daily",
    frequency_days: 1,
    current_streak: 4,
    longest_streak: 8,
    total_completions: 12,
    last_completed_at: "2026-04-08T08:00:00Z",
    active: true,
    tags: ["wellbeing"],
    created_at: "2026-04-01T09:00:00Z",
    ...overrides,
  };
}

function createHabitLog(overrides: Partial<HabitLog> = {}): HabitLog {
  return {
    id: "habit-log-1",
    habit_id: "habit-1",
    completed_at: "2026-04-08T08:00:00Z",
    note: null,
    source: "manual",
    ...overrides,
  };
}

function createMoodTrendPoint(overrides: Partial<MoodTrendPoint> = {}): MoodTrendPoint {
  return {
    date: "2026-04-08T12:00:00Z",
    mood: 7.5,
    energy: 6.5,
    count: 1,
    ...overrides,
  };
}

function createEpisodeStats(overrides: Partial<EpisodeStats> = {}): EpisodeStats {
  return {
    totalEntries: 3,
    averageMood: 6.7,
    averageEnergy: 5.9,
    moodTrend: [createMoodTrendPoint()],
    tagFrequency: [
      { tag: "focus", count: 5 },
      { tag: "work", count: 3 },
    ],
    paraDistribution: [
      { category: "project", count: 2 },
      { category: "resource", count: 1 },
    ],
    ...overrides,
  };
}

export {
  createEpisode,
  createEpisodeStats,
  createContact,
  createEpic,
  createGoal,
  createHabit,
  createHabitLog,
  createInteraction,
  createMilestone,
  createNote,
  createPaginatedResponse,
  createProject,
  createTask,
};
