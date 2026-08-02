import { motion } from "motion/react";

export function ProjectVisual() {
  const goals = [
    { name: "Launch MVP", progress: 78, color: "var(--color-agent-project)" },
    { name: "Read 24 books", progress: 54, color: "var(--color-agent-research)" },
    { name: "Exercise 4x/week", progress: 85, color: "var(--color-success-500)" },
    { name: "Clear inbox daily", progress: 62, color: "var(--color-agent-comms)" },
  ];

  return (
    <div className="space-y-5 max-w-md mx-auto">
      {goals.map((goal, i) => (
        <motion.div
          key={i}
          initial={{ opacity: 0, x: 30 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.5, delay: i * 0.12 }}
        >
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-sm font-medium text-[var(--color-fg-primary)]">{goal.name}</span>
            <span className="text-xs font-mono text-[var(--color-fg-secondary)]">
              {goal.progress}%
            </span>
          </div>
          <div
            className="h-2 rounded-full overflow-hidden"
            style={{ background: "var(--color-bg-overlay)" }}
          >
            <motion.div
              className="h-full rounded-full"
              style={{ background: goal.color }}
              initial={{ width: 0 }}
              whileInView={{ width: `${goal.progress}%` }}
              viewport={{ once: true }}
              transition={{ duration: 1, delay: 0.3 + i * 0.1, ease: "easeOut" }}
            />
          </div>
        </motion.div>
      ))}

      {/* Habit streak */}
      <motion.div
        className="mt-6 rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] p-4"
        style={{ background: "var(--color-bg-elevated)" }}
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5, delay: 0.6 }}
      >
        <div className="text-xs font-semibold text-[var(--color-fg-secondary)] mb-2 uppercase tracking-wider">
          This Week
        </div>
        <div className="flex gap-1.5">
          {["M", "T", "W", "T", "F", "S", "S"].map((day, i) => (
            <div key={i} className="flex flex-col items-center gap-1">
              <div
                className="w-7 h-7 rounded-[var(--radius-sm)] flex items-center justify-center text-[10px] font-medium"
                style={{
                  background:
                    i < 5
                      ? "var(--color-success-500)"
                      : i === 5
                        ? "var(--color-warning-500)"
                        : "var(--color-bg-overlay)",
                  color: i < 6 ? "var(--color-fg-on-accent)" : "var(--color-fg-tertiary)",
                  opacity: i === 6 ? 0.4 : 1,
                }}
              >
                {i < 5 ? "\u2713" : i === 5 ? "\u00BD" : "\u00B7"}
              </div>
              <span className="text-[9px] text-[var(--color-fg-tertiary)]">{day}</span>
            </div>
          ))}
        </div>
      </motion.div>
    </div>
  );
}
