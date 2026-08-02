import { Link } from "react-router";
import { motion } from "motion/react";
import { Brain, LayoutDashboard } from "lucide-react";

export function LandingNavigation() {
  return (
    <motion.nav
      className="fixed top-0 left-0 right-0 z-50 px-6 py-3"
      style={{
        background: "var(--nav-bg)",
        backdropFilter: "blur(16px)",
        WebkitBackdropFilter: "blur(16px)",
        borderBottom: "1px solid var(--color-border-subtle)",
      }}
      initial={{ y: -60, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.6, delay: 0.2 }}
    >
      <div className="max-w-6xl mx-auto flex items-center justify-between">
        <Link to="/welcome" className="flex items-center gap-2.5 group">
          <div
            className="w-8 h-8 rounded-[var(--radius-md)] flex items-center justify-center"
            style={{
              background: "linear-gradient(135deg, oklch(0.55 0.18 250), oklch(0.5 0.2 290))",
            }}
          >
            <Brain className="w-4.5 h-4.5 text-white" />
          </div>
          <span className="text-sm font-semibold text-[var(--color-fg-primary)] group-hover:text-[var(--color-fg-secondary)] transition-colors">
            Execution OS
          </span>
        </Link>

        <div className="flex items-center gap-4">
          <a
            href="#agents"
            className="text-xs text-[var(--color-fg-secondary)] hover:text-[var(--color-fg-primary)] transition-colors hidden sm:inline"
          >
            Agents
          </a>
          <a
            href="#features"
            className="text-xs text-[var(--color-fg-secondary)] hover:text-[var(--color-fg-primary)] transition-colors hidden sm:inline"
          >
            Features
          </a>
          <a
            href="#architecture"
            className="text-xs text-[var(--color-fg-secondary)] hover:text-[var(--color-fg-primary)] transition-colors hidden sm:inline"
          >
            Architecture
          </a>
          <Link
            to="/dashboard"
            className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium rounded-[var(--radius-full)] transition-all duration-300"
            style={{
              background: "linear-gradient(135deg, oklch(0.55 0.18 250), oklch(0.5 0.2 290))",
              color: "white",
            }}
          >
            <LayoutDashboard className="w-3.5 h-3.5" />
            Dashboard
          </Link>
        </div>
      </div>
    </motion.nav>
  );
}
