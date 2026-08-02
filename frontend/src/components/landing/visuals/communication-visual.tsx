import { motion } from "motion/react";

export function CommunicationVisual() {
  const emails = [
    { from: "Sarah Chen", subject: "Project Alpha update", priority: "high", time: "2h ago" },
    { from: "Newsletter", subject: "Weekly digest: AI trends", priority: "low", time: "4h ago" },
    { from: "David Park", subject: "Meeting reschedule?", priority: "medium", time: "5h ago" },
  ];

  return (
    <div className="max-w-md mx-auto space-y-3">
      {/* Email triage */}
      {emails.map((email, i) => (
        <motion.div
          key={i}
          className="rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] px-4 py-3 flex items-center gap-3"
          style={{ background: "var(--color-bg-elevated)" }}
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.4, delay: i * 0.12 }}
        >
          <div
            className="w-2 h-2 rounded-full flex-shrink-0"
            style={{
              background:
                email.priority === "high"
                  ? "var(--color-error-500)"
                  : email.priority === "medium"
                    ? "var(--color-warning-500)"
                    : "var(--color-fg-tertiary)",
            }}
          />
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-[var(--color-fg-primary)] truncate">
                {email.from}
              </span>
              <span className="text-[10px] text-[var(--color-fg-tertiary)] flex-shrink-0 ml-2">
                {email.time}
              </span>
            </div>
            <div className="text-xs text-[var(--color-fg-secondary)] truncate">{email.subject}</div>
          </div>
          <div
            className="text-[9px] font-medium uppercase px-2 py-0.5 rounded-[var(--radius-full)]"
            style={{
              background:
                email.priority === "high"
                  ? "var(--color-error-50)"
                  : email.priority === "medium"
                    ? "var(--color-warning-50)"
                    : "var(--color-bg-overlay)",
              color:
                email.priority === "high"
                  ? "var(--color-error-500)"
                  : email.priority === "medium"
                    ? "var(--color-warning-500)"
                    : "var(--color-fg-tertiary)",
            }}
          >
            {email.priority}
          </div>
        </motion.div>
      ))}

      {/* Calendar strip */}
      <motion.div
        className="mt-4 rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] p-4"
        style={{ background: "var(--color-bg-elevated)" }}
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5, delay: 0.5 }}
      >
        <div className="text-xs font-semibold text-[var(--color-fg-secondary)] mb-3 uppercase tracking-wider">
          Today's Schedule
        </div>
        <div className="space-y-2">
          {[
            { time: "09:00", event: "Team standup", dur: "30m" },
            { time: "11:00", event: "Design review", dur: "1h" },
            { time: "14:30", event: "Focus time (blocked)", dur: "2h" },
          ].map((ev, i) => (
            <div key={i} className="flex items-center gap-3">
              <span className="text-[10px] font-mono text-[var(--color-fg-tertiary)] w-10 flex-shrink-0">
                {ev.time}
              </span>
              <div
                className="h-1 w-1 rounded-full flex-shrink-0"
                style={{ background: "var(--color-agent-tools)" }}
              />
              <span className="text-xs text-[var(--color-fg-primary)]">{ev.event}</span>
              <span className="text-[10px] text-[var(--color-fg-tertiary)] ml-auto">{ev.dur}</span>
            </div>
          ))}
        </div>
      </motion.div>
    </div>
  );
}
