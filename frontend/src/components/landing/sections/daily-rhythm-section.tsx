import { motion } from "motion/react";
import { Sun } from "lucide-react";

import { Section } from "../primitives";
import { DailyRhythmVisual } from "../visuals/daily-rhythm-visual";

export function DailyRhythmSection() {
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
          <DailyRhythmVisual />
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
            style={{ color: "var(--color-agent-diary)" }}
          >
            <Sun className="w-3.5 h-3.5" />
            Daily Rhythm
          </span>
          <h2 className="text-3xl md:text-4xl font-bold text-[var(--color-fg-primary)] mb-4 leading-tight">
            Your Day, <span style={{ color: "var(--color-agent-diary)" }}>Structured & Aware.</span>
          </h2>
          <p className="text-sm md:text-base text-[var(--color-fg-secondary)] leading-relaxed mb-6">
            Interstitial journaling captures thoughts between tasks, while mood and energy tracking
            makes changes visible over time. Optional briefings can combine priorities, calendar
            context, and curated material after you enable the required providers.
          </p>
          <div className="space-y-3">
            {[
              "Optional briefings with calendar, priorities, and curated content",
              "Interstitial journaling: capture thoughts between tasks",
              "Mood and energy tracking with trend analysis",
              "Progressive summarisation for long-term retrieval",
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
                    background: "color-mix(in oklch, var(--color-agent-diary) 20%, transparent)",
                  }}
                >
                  <div
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ background: "var(--color-agent-diary)" }}
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
