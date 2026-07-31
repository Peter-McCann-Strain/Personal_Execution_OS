import { useNavigate } from "react-router";
import { PenLine, Search, Mail, Calendar, BarChart3, Brain } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatShortcut } from "@/lib/platform";

interface QuickAction {
  label: string;
  icon: React.ReactNode;
  shortcut?: string;
  target: string;
}

const actions: QuickAction[] = [
  {
    label: "New Diary Entry",
    icon: <PenLine className="h-5 w-5" />,
    shortcut: formatShortcut("Mod+N"),
    target: "/diary?capture=1",
  },
  {
    label: "Search Memory",
    icon: <Brain className="h-5 w-5" />,
    shortcut: formatShortcut("Mod+4"),
    target: "/memory",
  },
  {
    label: "Research",
    icon: <Search className="h-5 w-5" />,
    shortcut: formatShortcut("Mod+2"),
    target: "/chat",
  },
  {
    label: "Check Calendar",
    icon: <Calendar className="h-5 w-5" />,
    shortcut: formatShortcut("Mod+6"),
    target: "/calendar",
  },
  {
    label: "Check Email",
    icon: <Mail className="h-5 w-5" />,
    shortcut: formatShortcut("Mod+7"),
    target: "/email",
  },
  {
    label: "Weekly Review",
    icon: <BarChart3 className="h-5 w-5" />,
    target: "/reviews",
  },
];

function QuickActionButton({ action }: { action: QuickAction }) {
  const navigate = useNavigate();

  function handleClick() {
    navigate(action.target);
  }

  return (
    <button
      onClick={handleClick}
      className={cn(
        "group flex flex-col items-center gap-2 rounded-[var(--radius-lg)] border border-[var(--color-border-default)]",
        "bg-[var(--color-bg-surface)] p-4 transition-all duration-150",
        "hover:border-[var(--color-border-strong)] hover:bg-[var(--color-bg-elevated)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-border-focus)]",
        "active:scale-[0.97] cursor-pointer",
      )}
    >
      <span className="text-[var(--color-fg-secondary)] group-hover:text-[var(--color-info-500)] transition-colors">
        {action.icon}
      </span>
      <span className="text-xs font-medium text-[var(--color-fg-primary)]">{action.label}</span>
      {action.shortcut ? (
        <kbd className="text-[10px] font-mono text-[var(--color-fg-tertiary)] rounded border border-[var(--color-border-subtle)] bg-[var(--color-bg-overlay)] px-1 py-0.5">
          {action.shortcut}
        </kbd>
      ) : (
        <span className="h-[19px]" aria-hidden="true" />
      )}
    </button>
  );
}

export function QuickActions() {
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)]">
      <div className="border-b border-[var(--color-border-subtle)] px-4 py-3">
        <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">Quick Actions</h3>
      </div>
      <div className="grid grid-cols-3 gap-3 p-4 sm:grid-cols-6">
        {actions.map((action) => (
          <QuickActionButton key={action.label} action={action} />
        ))}
      </div>
    </div>
  );
}
