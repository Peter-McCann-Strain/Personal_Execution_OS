import {
  BarChart3,
  Bell,
  BookOpen,
  FlaskConical,
  FolderKanban,
  Mail,
  Network,
  Search,
  Send,
  Sparkles,
  Wrench,
} from "lucide-react";

export const agents = [
  {
    name: "Diary",
    icon: BookOpen,
    color: "var(--color-agent-diary)",
    description:
      "Your timestamped journal, mood tracker, and cognitive companion. Captures thoughts as they happen with interstitial journaling and progressive summarisation.",
    capabilities: [
      "Mood & energy tracking",
      "Interstitial journaling",
      "Progressive summarisation",
      "Plan my day (energy-aware)",
    ],
    route: "/diary",
  },
  {
    name: "Memory",
    icon: Search,
    color: "var(--color-agent-memory)",
    description:
      "Searches local records and linked knowledge. Optional embeddings and model-backed extraction add semantic retrieval and entity suggestions.",
    capabilities: [
      "Structured local search",
      "Optional vector retrieval",
      "Knowledge graph",
      "Spaced repetition (SM-2)",
    ],
    route: "/memory",
  },
  {
    name: "Research",
    icon: FlaskConical,
    color: "var(--color-agent-research)",
    description:
      "Source-attributed research and decision frameworks when a model and web-search provider are configured.",
    capabilities: [
      "Multi-source web synthesis",
      "Decision frameworks",
      "URL capture & extraction",
      "Deep analysis",
    ],
    route: "/chat",
  },
  {
    name: "Review",
    icon: BarChart3,
    color: "var(--color-agent-review)",
    description:
      "Weekly and quarterly review workflows for goals, decisions, trends, and follow-through.",
    capabilities: [
      "Weekly/quarterly reviews",
      "Pattern detection",
      "Decision journal",
      "Trend analysis",
    ],
    route: "/reviews",
  },
  {
    name: "Notification",
    icon: Bell,
    color: "var(--color-agent-notif)",
    description:
      "Optional briefings and alerts for commitments, deadlines, relationships, and notification load.",
    capabilities: [
      "Commitment extraction",
      "Content curation (RSS + AI)",
      "Fatigue management",
      "Morning briefings",
    ],
    route: "/notifications",
  },
  {
    name: "Tools",
    icon: Wrench,
    color: "var(--color-agent-tools)",
    description:
      "Read-only context from connected calendars, inboxes, and files through provider adapters. Source material stays attributable and external accounts are never modified.",
    capabilities: [
      "Read-only calendar context",
      "Read-only mail context",
      "Provider adapter boundary",
      "Free slot detection",
    ],
    route: "/calendar",
  },
  {
    name: "Project",
    icon: FolderKanban,
    color: "var(--color-agent-project)",
    description:
      "Work breakdown structures, WSJF prioritisation, and velocity tracking. Turns vague goals into structured, executable plans.",
    capabilities: [
      "Work breakdown (WBS)",
      "WSJF prioritisation",
      "Velocity tracking",
      "Habit & goal tracking",
    ],
    route: "/projects",
  },
  {
    name: "Communications",
    icon: Mail,
    color: "var(--color-agent-comms)",
    description:
      "Read-only email triage, editable local draft suggestions, and response prioritisation. It does not send or modify provider mail.",
    capabilities: [
      "Email triage & sorting",
      "Editable draft suggestions",
      "Response priority",
      "Contact CRM",
    ],
    route: "/email",
  },
];

export const steps = [
  {
    number: "01",
    title: "Capture",
    description:
      "Capture through the web dashboard, diary, notes, or a connected inbox. Keep thoughts, tasks, ideas, and observations together before they fade.",
    icon: Send,
    gradient: "from-blue-500/20 to-purple-500/20",
  },
  {
    number: "02",
    title: "Organise",
    description:
      "Organise records explicitly. When you enable a model, assistants can suggest classifications, entities, links, and PARA categories for you to review.",
    icon: Network,
    gradient: "from-purple-500/20 to-pink-500/20",
  },
  {
    number: "03",
    title: "Surface",
    description:
      "Use local search and reviews by default. Optional briefings, alerts, pattern analysis, and semantic retrieval appear only when configured.",
    icon: Sparkles,
    gradient: "from-pink-500/20 to-amber-500/20",
  },
];

export const techStack = [
  { name: "Python", label: "Backend" },
  { name: "FastAPI", label: "API Framework" },
  { name: "LangGraph", label: "Agent Orchestration" },
  { name: "Provider adapters", label: "Language Models" },
  { name: "PostgreSQL", label: "Database" },
  { name: "pgvector", label: "Vector Search" },
  { name: "React 19", label: "Frontend" },
  { name: "TypeScript", label: "Type Safety" },
  { name: "Ollama", label: "Local Embeddings" },
  { name: "Redis", label: "Job Queue" },
  { name: "OpenTelemetry", label: "Observability" },
  { name: "PWA", label: "Installable Web App" },
];
