import { useEffect, useCallback } from "react";
import { useNavigate } from "react-router";
import { Command } from "cmdk";
import {
  LayoutDashboard,
  Waves,
  MessageSquare,
  BookOpen,
  Brain,
  Share2,
  FolderKanban,
  Target,
  Activity,
  Users,
  Calendar,
  Mail,
  Bell,
  Settings,
  PenLine,
  Search,
  FlaskConical,
  Moon,
  Sun,
  StickyNote,
  PanelTop,
  Flame,
  ListChecks,
  Scale,
  GraduationCap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatShortcut } from "@/lib/platform";
import { useAppStore } from "@/stores/app";

// ─── Pages Data ──────────────────────────────────────────────

interface CommandItem {
  label: string;
  icon: LucideIcon;
  shortcut?: string;
  onSelect: () => void;
}

function useCommandPages(navigate: ReturnType<typeof useNavigate>): CommandItem[] {
  return [
    {
      label: "Dashboard",
      icon: LayoutDashboard,
      shortcut: formatShortcut("Mod+1"),
      onSelect: () => navigate("/dashboard"),
    },
    {
      label: "Pulse",
      icon: Waves,
      shortcut: formatShortcut("Mod+8"),
      onSelect: () => navigate("/pulse"),
    },
    {
      label: "Chat",
      icon: MessageSquare,
      shortcut: formatShortcut("Mod+2"),
      onSelect: () => navigate("/chat"),
    },
    {
      label: "Diary",
      icon: BookOpen,
      shortcut: formatShortcut("Mod+3"),
      onSelect: () => navigate("/diary"),
    },
    {
      label: "Memory",
      icon: Brain,
      shortcut: formatShortcut("Mod+4"),
      onSelect: () => navigate("/memory"),
    },
    { label: "Knowledge Graph", icon: Share2, onSelect: () => navigate("/knowledge-graph") },
    { label: "Notes", icon: StickyNote, onSelect: () => navigate("/notes") },
    { label: "Workbench", icon: PanelTop, onSelect: () => navigate("/workbench") },
    {
      label: "Projects",
      icon: FolderKanban,
      shortcut: formatShortcut("Mod+5"),
      onSelect: () => navigate("/projects"),
    },
    { label: "Goals", icon: Target, onSelect: () => navigate("/goals") },
    { label: "Reviews", icon: Activity, onSelect: () => navigate("/reviews") },
    { label: "Habits", icon: Flame, onSelect: () => navigate("/habits") },
    { label: "Commitments", icon: ListChecks, onSelect: () => navigate("/commitments") },
    { label: "Decisions", icon: Scale, onSelect: () => navigate("/decisions") },
    { label: "Tutorials", icon: GraduationCap, onSelect: () => navigate("/tutorials") },
    { label: "Contacts", icon: Users, onSelect: () => navigate("/contacts") },
    {
      label: "Calendar",
      icon: Calendar,
      shortcut: formatShortcut("Mod+6"),
      onSelect: () => navigate("/calendar"),
    },
    {
      label: "Email",
      icon: Mail,
      shortcut: formatShortcut("Mod+7"),
      onSelect: () => navigate("/email"),
    },
    { label: "Notifications", icon: Bell, onSelect: () => navigate("/notifications") },
    { label: "Monitoring", icon: Activity, onSelect: () => navigate("/monitoring") },
    {
      label: "Settings",
      icon: Settings,
      shortcut: formatShortcut("Mod+9"),
      onSelect: () => navigate("/settings"),
    },
  ];
}

function useCommandActions(navigate: ReturnType<typeof useNavigate>): CommandItem[] {
  const theme = useAppStore((s) => s.theme);
  const setTheme = useAppStore((s) => s.setTheme);

  return [
    {
      label: "New diary entry",
      icon: PenLine,
      shortcut: formatShortcut("Mod+N"),
      onSelect: () => navigate("/diary?capture=1"),
    },
    { label: "Search memory", icon: Search, onSelect: () => navigate("/memory") },
    { label: "Check calendar", icon: Calendar, onSelect: () => navigate("/calendar") },
    { label: "Review email", icon: Mail, onSelect: () => navigate("/email") },
    { label: "Start research", icon: FlaskConical, onSelect: () => navigate("/chat") },
    { label: "Break down project", icon: FolderKanban, onSelect: () => navigate("/projects") },
    {
      label: theme === "dark" ? "Switch to light mode" : "Switch to dark mode",
      icon: theme === "dark" ? Sun : Moon,
      onSelect: () => setTheme(theme === "dark" ? "light" : "dark"),
    },
  ];
}

// ─── Command Palette ─────────────────────────────────────────

function CommandPalette() {
  const open = useAppStore((s) => s.commandPaletteOpen);
  const setOpen = useAppStore((s) => s.setCommandPaletteOpen);
  const navigate = useNavigate();

  const pages = useCommandPages(navigate);
  const actions = useCommandActions(navigate);

  // Global Cmd+K listener
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen(!open);
      }
    },
    [open, setOpen],
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  const handleSelect = (callback: () => void) => {
    setOpen(false);
    callback();
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50"
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={() => setOpen(false)}
        aria-hidden="true"
      />

      {/* Palette */}
      <div className="absolute left-1/2 top-[20%] w-[min(640px,90vw)] -translate-x-1/2">
        <Command
          className={cn(
            "flex flex-col overflow-hidden rounded-[var(--radius-xl)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] shadow-lg",
            "max-h-[min(480px,70vh)]",
          )}
          onKeyDown={(e: React.KeyboardEvent) => {
            if (e.key === "Escape") {
              setOpen(false);
            }
          }}
        >
          {/* Search Input */}
          <div className="flex items-center gap-2 border-b border-[var(--color-border-subtle)] px-3">
            <Search className="h-[18px] w-[18px] shrink-0 text-[var(--color-fg-tertiary)]" />
            <Command.Input
              placeholder="Search or type a command..."
              className="h-[52px] flex-1 bg-transparent text-base text-[var(--color-fg-primary)] placeholder:text-[var(--color-fg-tertiary)] outline-none"
              autoFocus
            />
          </div>

          {/* Results */}
          <Command.List className="overflow-y-auto overscroll-contain p-2">
            <Command.Empty className="py-6 text-center text-sm text-[var(--color-fg-tertiary)]">
              No results found.
            </Command.Empty>

            {/* Pages */}
            <Command.Group
              heading="Pages"
              className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pb-1.5 [&_[cmdk-group-heading]]:pt-3 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-[var(--color-fg-tertiary)]"
            >
              {pages.map((item) => (
                <CommandItemRow
                  key={item.label}
                  item={item}
                  onSelect={() => handleSelect(item.onSelect)}
                />
              ))}
            </Command.Group>

            {/* Actions */}
            <Command.Group
              heading="Actions"
              className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pb-1.5 [&_[cmdk-group-heading]]:pt-3 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-[var(--color-fg-tertiary)]"
            >
              {actions.map((item) => (
                <CommandItemRow
                  key={item.label}
                  item={item}
                  onSelect={() => handleSelect(item.onSelect)}
                />
              ))}
            </Command.Group>
          </Command.List>

          {/* Footer */}
          <div className="flex items-center gap-4 border-t border-[var(--color-border-subtle)] px-3 py-2 text-[11px] text-[var(--color-fg-tertiary)]">
            <span className="flex items-center gap-1">
              <kbd className="rounded-[var(--radius-sm)] border border-[var(--color-border-default)] bg-[var(--color-bg-overlay)] px-1 py-0.5 font-mono text-[10px]">
                &uarr;&darr;
              </kbd>
              Navigate
            </span>
            <span className="flex items-center gap-1">
              <kbd className="rounded-[var(--radius-sm)] border border-[var(--color-border-default)] bg-[var(--color-bg-overlay)] px-1 py-0.5 font-mono text-[10px]">
                &crarr;
              </kbd>
              Select
            </span>
            <span className="flex items-center gap-1">
              <kbd className="rounded-[var(--radius-sm)] border border-[var(--color-border-default)] bg-[var(--color-bg-overlay)] px-1 py-0.5 font-mono text-[10px]">
                Esc
              </kbd>
              Close
            </span>
          </div>
        </Command>
      </div>
    </div>
  );
}

// ─── Individual Item Row ─────────────────────────────────────

interface CommandItemRowProps {
  item: CommandItem;
  onSelect: () => void;
}

function CommandItemRow({ item, onSelect }: CommandItemRowProps) {
  const Icon = item.icon;
  return (
    <Command.Item
      value={item.label}
      onSelect={onSelect}
      className={cn(
        "flex h-10 cursor-pointer items-center gap-3 rounded-[var(--radius-md)] px-2 text-sm text-[var(--color-fg-secondary)]",
        "data-[selected=true]:bg-[var(--color-bg-overlay)] data-[selected=true]:text-[var(--color-fg-primary)]",
        "hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-fg-primary)]",
        "transition-colors",
      )}
    >
      <Icon className="h-[18px] w-[18px] shrink-0" />
      <span className="flex-1 truncate">{item.label}</span>
      {item.shortcut && (
        <kbd className="ml-auto shrink-0 rounded-[var(--radius-sm)] border border-[var(--color-border-default)] bg-[var(--color-bg-overlay)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-fg-tertiary)]">
          {item.shortcut}
        </kbd>
      )}
    </Command.Item>
  );
}

export { CommandPalette };
