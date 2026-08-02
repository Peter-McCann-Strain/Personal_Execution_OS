import { motion } from "motion/react";
import { Target } from "lucide-react";

import { Section } from "../primitives";
import { ProjectVisual } from "../visuals/project-visual";

export function ProjectsGoalsSection() {
  return (
    <Section>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16 items-center">
        <motion.div
          initial={{ opacity: 0, x: -40 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.7 }}
        >
          <span
            className="inline-flex items-center gap-2 mb-4 text-xs font-semibold uppercase tracking-[0.2em]"
            style={{ color: "var(--color-agent-project)" }}
          >
            <Target className="w-3.5 h-3.5" />
            Projects & Goals
          </span>
          <h2 className="text-3xl md:text-4xl font-bold text-[var(--color-fg-primary)] mb-4 leading-tight">
            From Vision to <span style={{ color: "var(--color-agent-project)" }}>Execution.</span>
          </h2>
          <p className="text-sm md:text-base text-[var(--color-fg-secondary)] leading-relaxed mb-6">
            Turn vague ambitions into structured, executable plans. Work breakdown structures
            decompose projects into actionable tasks. WSJF offers an explicit way to compare
            competing work. Habit tracking makes consistency visible over time.
          </p>
          <div className="space-y-3">
            {[
              "Work breakdown structures for complex projects",
              "WSJF (Weighted Shortest Job First) prioritisation",
              "Velocity tracking to understand your real capacity",
              "Habit streaks and goal progress visualisation",
            ].map((item, i) => (
              <motion.div
                key={i}
                className="flex items-start gap-3"
                initial={{ opacity: 0, x: -20 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.4, delay: 0.2 + i * 0.1 }}
              >
                <div
                  className="w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5"
                  style={{
                    background: "color-mix(in oklch, var(--color-agent-project) 20%, transparent)",
                  }}
                >
                  <div
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ background: "var(--color-agent-project)" }}
                  />
                </div>
                <span className="text-xs text-[var(--color-fg-secondary)]">{item}</span>
              </motion.div>
            ))}
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, x: 40 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.7, delay: 0.2 }}
        >
          <ProjectVisual />
        </motion.div>
      </div>
    </Section>
  );
}
