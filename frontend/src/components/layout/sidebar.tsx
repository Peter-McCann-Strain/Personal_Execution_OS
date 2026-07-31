import { Link, useLocation, useNavigate } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import * as Tooltip from "@radix-ui/react-tooltip";
import { Brain, ChevronsLeft, ChevronsRight, Plus, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatShortcut } from "@/lib/platform";
import { AGENT_COLORS } from "@/lib/agent-utils";
import { useAppStore } from "@/stores/app";
import { navSections } from "./sidebar.config";
import type { NavItem } from "./sidebar.config";

// ─── NavItem Component ───────────────────────────────────────

interface NavItemButtonProps {
  item: NavItem;
  isActive: boolean;
  collapsed: boolean;
  onNavigate?: () => void;
}

function NavItemButton({ item, isActive, collapsed, onNavigate }: NavItemButtonProps) {
  const navigate = useNavigate();
  const Icon = item.icon;
  const accentColor = item.agentColor ? AGENT_COLORS[item.agentColor] : undefined;

  const button = (
    <button
      onClick={() => {
        navigate(item.path);
        onNavigate?.();
      }}
      className={cn(
        "group flex w-full items-center gap-3 rounded-[var(--radius-md)] text-sm font-medium transition-all duration-150",
        collapsed ? "h-10 w-10 justify-center mx-auto" : "h-10 px-3",
        isActive
          ? "bg-[var(--color-bg-overlay)] text-[var(--color-fg-primary)]"
          : "text-[var(--color-fg-secondary)] hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-fg-primary)]",
      )}
      style={isActive && accentColor ? { borderLeft: `2px solid ${accentColor}` } : undefined}
    >
      <Icon
        className="h-[18px] w-[18px] shrink-0"
        style={isActive && accentColor ? { color: accentColor } : undefined}
      />
      <AnimatePresence mode="wait">
        {!collapsed && (
          <motion.span
            initial={{ opacity: 0, width: 0 }}
            animate={{ opacity: 1, width: "auto" }}
            exit={{ opacity: 0, width: 0 }}
            transition={{ duration: 0.15 }}
            className="truncate"
          >
            {item.label}
          </motion.span>
        )}
      </AnimatePresence>
    </button>
  );

  if (!collapsed) return button;

  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{button}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          side="right"
          sideOffset={12}
          className="z-50 rounded-[var(--radius-md)] bg-[var(--color-bg-elevated)] border border-[var(--color-border-default)] px-2.5 py-1.5 text-xs font-medium text-[var(--color-fg-primary)] shadow-lg"
        >
          {item.label}
          <Tooltip.Arrow className="fill-[var(--color-bg-elevated)]" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

// ─── Sidebar Component ───────────────────────────────────────

interface SidebarProps {
  className?: string;
  mobile?: boolean;
  onNavigate?: () => void;
}

function Sidebar({ className, mobile = false, onNavigate }: SidebarProps) {
  const storedCollapsed = useAppStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const location = useLocation();
  const navigate = useNavigate();
  const collapsed = mobile ? false : storedCollapsed;

  return (
    <motion.aside
      className={cn(
        "flex h-full flex-col overflow-hidden border-r border-[var(--color-border-default)] bg-[var(--color-bg-surface)]",
        className,
      )}
      initial={false}
      animate={{ width: mobile ? 300 : collapsed ? 56 : 240 }}
      transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
      style={mobile ? undefined : { gridArea: "sidebar" }}
    >
      <Tooltip.Provider delayDuration={400}>
        {/* Header: Logo + Collapse Toggle */}
        <div
          className={cn(
            "flex h-12 shrink-0 items-center border-b border-[var(--color-border-subtle)]",
            collapsed ? "justify-center px-2" : "justify-between px-3",
          )}
        >
          <Link
            to="/welcome"
            className="flex items-center gap-2 hover:opacity-80 transition-opacity"
            title="Home"
          >
            <Brain className="h-6 w-6 text-[var(--color-info-500)]" />
            <AnimatePresence mode="wait">
              {!collapsed && (
                <motion.span
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.15 }}
                  className="text-sm font-semibold text-[var(--color-fg-primary)]"
                >
                  Execution OS
                </motion.span>
              )}
            </AnimatePresence>
          </Link>
          {mobile ? (
            <button
              onClick={onNavigate}
              className="flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)] text-[var(--color-fg-tertiary)] hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-fg-primary)] transition-colors"
              aria-label="Close navigation menu"
            >
              <X className="h-4 w-4" />
            </button>
          ) : (
            <button
              onClick={toggleSidebar}
              className="flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)] text-[var(--color-fg-tertiary)] hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-fg-primary)] transition-colors"
              title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-label="Toggle sidebar"
            >
              {collapsed ? (
                <ChevronsRight className="h-4 w-4" />
              ) : (
                <ChevronsLeft className="h-4 w-4" />
              )}
            </button>
          )}
        </div>

        {/* Navigation Sections */}
        <nav className="flex-1 overflow-y-auto overflow-x-hidden py-2">
          {navSections.map((section, sectionIdx) => (
            <div key={section.title}>
              {/* Section header or divider */}
              {collapsed ? (
                sectionIdx > 0 && (
                  <div className="mx-3 my-2 border-t border-[var(--color-border-subtle)]" />
                )
              ) : (
                <div className="px-3 pt-5 pb-1.5">
                  <span className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
                    {section.title}
                  </span>
                </div>
              )}

              {/* Nav items */}
              <div
                className={cn("flex flex-col gap-0.5", collapsed ? "items-center px-1" : "px-2")}
              >
                {section.items.map((item) => {
                  const isActive = location.pathname === item.path;
                  return (
                    <NavItemButton
                      key={item.path}
                      item={item}
                      isActive={isActive}
                      collapsed={collapsed}
                      onNavigate={onNavigate}
                    />
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* Quick Capture FAB */}
        <div
          className={cn(
            "shrink-0 border-t border-[var(--color-border-subtle)]",
            collapsed ? "p-2" : "px-3 py-2",
          )}
        >
          <button
            onClick={() => {
              navigate("/diary?capture=1");
              onNavigate?.();
            }}
            className={cn(
              "flex items-center justify-center gap-2 rounded-[var(--radius-md)] bg-[var(--color-info-500)] text-[var(--color-fg-on-accent)] font-medium text-sm transition-transform active:scale-[0.97]",
              collapsed ? "h-10 w-10 mx-auto" : "h-10 w-full",
            )}
            title={collapsed ? `Quick Capture (${formatShortcut("Mod+N")})` : undefined}
          >
            <Plus className="h-4 w-4" />
            <AnimatePresence mode="wait">
              {!collapsed && (
                <motion.span
                  initial={{ opacity: 0, width: 0 }}
                  animate={{ opacity: 1, width: "auto" }}
                  exit={{ opacity: 0, width: 0 }}
                  transition={{ duration: 0.15 }}
                  className="whitespace-nowrap"
                >
                  Quick Capture
                </motion.span>
              )}
            </AnimatePresence>
          </button>
        </div>

        {/* Agent Activity Dots */}
        <Tooltip.Provider delayDuration={300}>
          <div
            className={cn(
              "flex shrink-0 items-center gap-1.5 border-t border-[var(--color-border-subtle)]",
              collapsed ? "justify-center px-2 py-2" : "px-3 py-2",
            )}
          >
            {(
              [
                "diary",
                "memory",
                "research",
                "review",
                "notification",
                "tools",
                "project",
                "communications",
              ] as const
            ).map((agent) => (
              <Tooltip.Root key={agent}>
                <Tooltip.Trigger asChild>
                  <span
                    className="inline-block h-2 w-2 rounded-full opacity-40 transition-all duration-300 hover:opacity-80 hover:scale-150 cursor-default"
                    style={{ backgroundColor: AGENT_COLORS[agent] }}
                  />
                </Tooltip.Trigger>
                <Tooltip.Portal>
                  <Tooltip.Content
                    side="top"
                    sideOffset={8}
                    className="z-50 rounded-[var(--radius-md)] bg-[var(--color-bg-elevated)] border border-[var(--color-border-default)] px-2.5 py-1.5 text-xs text-[var(--color-fg-primary)] shadow-lg"
                  >
                    <span className="capitalize font-medium">{agent}</span>
                    <span className="text-[var(--color-fg-tertiary)]"> — idle</span>
                    <Tooltip.Arrow className="fill-[var(--color-bg-elevated)]" />
                  </Tooltip.Content>
                </Tooltip.Portal>
              </Tooltip.Root>
            ))}
          </div>
        </Tooltip.Provider>
      </Tooltip.Provider>
    </motion.aside>
  );
}

export { Sidebar };
