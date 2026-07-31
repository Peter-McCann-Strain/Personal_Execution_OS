import {
  Activity,
  Bell,
  BookOpen,
  Brain,
  Calendar,
  Flame,
  FolderKanban,
  Gauge,
  GraduationCap,
  LayoutDashboard,
  ListChecks,
  Mail,
  MessageSquare,
  PanelTop,
  Scale,
  Settings,
  Share2,
  StickyNote,
  Target,
  Users,
  Waves,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { AgentName } from "@/types";

interface NavItem {
  label: string;
  icon: LucideIcon;
  path: string;
  badgeKey?: string;
  agentColor?: AgentName;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

const navSections: NavSection[] = [
  {
    title: "Primary",
    items: [
      { label: "Dashboard", icon: LayoutDashboard, path: "/dashboard" },
      { label: "Chat", icon: MessageSquare, path: "/chat", agentColor: "communications" },
      { label: "Capture", icon: BookOpen, path: "/diary", agentColor: "diary" },
      { label: "Workbench", icon: PanelTop, path: "/workbench", agentColor: "project" },
      { label: "Memory", icon: Brain, path: "/memory", agentColor: "memory" },
    ],
  },
  {
    title: "Workspace",
    items: [
      { label: "Projects", icon: FolderKanban, path: "/projects", agentColor: "project" },
      { label: "Goals", icon: Target, path: "/goals" },
      { label: "Notes", icon: StickyNote, path: "/notes", agentColor: "memory" },
      { label: "Knowledge Graph", icon: Share2, path: "/knowledge-graph", agentColor: "memory" },
      { label: "Contacts", icon: Users, path: "/contacts" },
      { label: "Calendar", icon: Calendar, path: "/calendar", agentColor: "tools" },
      { label: "Email", icon: Mail, path: "/email", agentColor: "communications" },
      { label: "Reviews", icon: Activity, path: "/reviews", agentColor: "review" },
      { label: "Habits", icon: Flame, path: "/habits" },
      { label: "Commitments", icon: ListChecks, path: "/commitments", agentColor: "notification" },
      { label: "Decisions", icon: Scale, path: "/decisions" },
      { label: "Tutorials", icon: GraduationCap, path: "/tutorials" },
    ],
  },
  {
    title: "Operations",
    items: [
      { label: "Pulse", icon: Waves, path: "/pulse", agentColor: "notification" },
      { label: "Notifications", icon: Bell, path: "/notifications", agentColor: "notification" },
      { label: "Monitoring", icon: Gauge, path: "/monitoring" },
      { label: "Settings", icon: Settings, path: "/settings" },
    ],
  },
];

export { navSections };
export type { NavItem, NavSection };
