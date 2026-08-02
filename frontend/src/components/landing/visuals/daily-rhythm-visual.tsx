import { motion } from "motion/react";

export function DailyRhythmVisual() {
  const entries = [
    {
      time: "07:00",
      label: "Morning Briefing",
      desc: "Calendar, priorities, curated content",
      color: "var(--color-agent-notif)",
    },
    {
      time: "09:15",
      label: "Diary Capture",
      desc: '"Feeling focused. Starting the refactor."',
      color: "var(--color-agent-diary)",
    },
    {
      time: "11:30",
      label: "Memory Link",
      desc: "Connected meeting notes to Project Alpha",
      color: "var(--color-agent-memory)",
    },
    {
      time: "14:00",
      label: "Smart Alert",
      desc: '"Follow up with Sarah -- 5 days overdue"',
      color: "var(--color-agent-notif)",
    },
    {
      time: "17:00",
      label: "Review Nudge",
      desc: "Weekly review ready. 3 patterns detected.",
      color: "var(--color-agent-review)",
    },
  ];

  return (
    <div className="space-y-4 max-w-md mx-auto">
      {entries.map((entry, i) => (
        <motion.div
          key={i}
          className="flex items-start gap-4"
          initial={{ opacity: 0, x: -30 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.5, delay: i * 0.15 }}
        >
          {/* Timeline dot */}
          <div className="flex flex-col items-center flex-shrink-0">
            <span className="text-[10px] font-mono text-[var(--color-fg-tertiary)] mb-1">
              {entry.time}
            </span>
            <div
              className="w-3 h-3 rounded-full border-2"
              style={{
                borderColor: entry.color,
                background: `color-mix(in oklch, ${entry.color} 20%, transparent)`,
              }}
            />
            {i < entries.length - 1 && <div className="w-px h-8 bg-[var(--color-border-subtle)]" />}
          </div>

          {/* Card */}
          <div
            className="rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] px-3 py-2 flex-1"
            style={{ background: "var(--color-bg-elevated)" }}
          >
            <div className="text-sm font-medium text-[var(--color-fg-primary)]">{entry.label}</div>
            <div className="text-xs text-[var(--color-fg-secondary)] mt-0.5">{entry.desc}</div>
          </div>
        </motion.div>
      ))}
    </div>
  );
}
