import { motion } from "motion/react";
import { StickyNote } from "lucide-react";

import { Section } from "../primitives";

export function PersonalKnowledgeSection() {
  return (
    <Section>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16 items-center">
        <motion.div
          className="order-2 lg:order-1"
          initial={{ opacity: 0, x: -40 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.7, delay: 0.2 }}
        >
          {/* Notes/commitments/decisions visual */}
          <div className="space-y-3 max-w-md mx-auto">
            {[
              {
                type: "Note",
                title: "Atomic notes on distributed systems",
                icon: "N",
                color: "var(--color-agent-memory)",
              },
              {
                type: "Commitment",
                title: "Send proposal to Sarah by Friday",
                icon: "C",
                color: "var(--color-agent-notif)",
              },
              {
                type: "Decision",
                title: "Chose PostgreSQL over MongoDB -- query flexibility",
                icon: "D",
                color: "var(--color-agent-review)",
              },
              {
                type: "Note",
                title: "CAP theorem implies partition tolerance trade-offs",
                icon: "N",
                color: "var(--color-agent-memory)",
              },
              {
                type: "Commitment",
                title: "Review team OKRs before quarterly meeting",
                icon: "C",
                color: "var(--color-agent-notif)",
              },
            ].map((item, i) => (
              <motion.div
                key={i}
                className="flex items-center gap-3 rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] px-4 py-3"
                style={{ background: "var(--color-bg-elevated)" }}
                initial={{ opacity: 0, x: -20 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.4, delay: 0.2 + i * 0.1 }}
              >
                <div
                  className="w-7 h-7 rounded-[var(--radius-sm)] flex items-center justify-center flex-shrink-0 text-[10px] font-bold"
                  style={{
                    background: `color-mix(in oklch, ${item.color} 15%, transparent)`,
                    color: item.color,
                  }}
                >
                  {item.icon}
                </div>
                <div className="flex-1 min-w-0">
                  <div
                    className="text-[9px] font-semibold uppercase tracking-wider"
                    style={{ color: item.color }}
                  >
                    {item.type}
                  </div>
                  <div className="text-xs text-[var(--color-fg-primary)] truncate">
                    {item.title}
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        </motion.div>

        <motion.div
          className="order-1 lg:order-2"
          initial={{ opacity: 0, x: 40 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.7 }}
        >
          <span
            className="inline-flex items-center gap-2 mb-4 text-xs font-semibold uppercase tracking-[0.2em]"
            style={{ color: "var(--color-agent-memory)" }}
          >
            <StickyNote className="w-3.5 h-3.5" />
            Personal Knowledge
          </span>
          <h2 className="text-3xl md:text-4xl font-bold text-[var(--color-fg-primary)] mb-4 leading-tight">
            Notes. Commitments.{" "}
            <span style={{ color: "var(--color-agent-memory)" }}>Decisions.</span>
          </h2>
          <p className="text-sm md:text-base text-[var(--color-fg-secondary)] leading-relaxed mb-6">
            Zettelkasten atomic notes build compound knowledge over time. Commitments are stored
            explicitly and can also be suggested from conversations when a model is enabled.
            Decisions retain context for later outcome reviews, and spaced repetition can bring
            selected knowledge back into view.
          </p>
          <div className="space-y-3">
            {[
              "Zettelkasten atomic notes with semantic linking",
              "Optional commitment suggestions from conversations",
              "Decision journal with outcome tracking",
              "SM-2 spaced repetition for long-term retention",
            ].map((item, i) => (
              <motion.div
                key={i}
                className="flex items-start gap-3"
                initial={{ opacity: 0, x: 20 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.4, delay: 0.2 + i * 0.1 }}
              >
                <div
                  className="w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5"
                  style={{
                    background: "color-mix(in oklch, var(--color-agent-memory) 20%, transparent)",
                  }}
                >
                  <div
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ background: "var(--color-agent-memory)" }}
                  />
                </div>
                <span className="text-xs text-[var(--color-fg-secondary)]">{item}</span>
              </motion.div>
            ))}
          </div>
        </motion.div>
      </div>
    </Section>
  );
}
