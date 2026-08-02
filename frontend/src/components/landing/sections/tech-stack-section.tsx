import { motion } from "motion/react";
import { Database, GitBranch, Shield, Zap } from "lucide-react";

import { techStack } from "../content";
import { Section, SectionHeading } from "../primitives";

export function TechStackSection() {
  return (
    <Section>
      <SectionHeading
        label="Built With"
        title="A Modern, Inspectable Stack"
        description="Pinned containers, typed application boundaries, automated tests, and documented trust boundaries support a cautious self-hosted preview."
      />

      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3 md:gap-4">
        {techStack.map((tech, i) => (
          <motion.div
            key={tech.name}
            className="rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] p-4 text-center"
            style={{ background: "var(--color-bg-surface)" }}
            initial={{ opacity: 0, scale: 0.9 }}
            whileInView={{ opacity: 1, scale: 1 }}
            viewport={{ once: true, amount: 0.2 }}
            transition={{ duration: 0.4, delay: i * 0.05 }}
            whileHover={{
              y: -2,
              borderColor: "var(--color-border-strong)",
              transition: { duration: 0.2 },
            }}
          >
            <div className="text-sm font-semibold text-[var(--color-fg-primary)] mb-0.5">
              {tech.name}
            </div>
            <div className="text-[10px] text-[var(--color-fg-tertiary)]">{tech.label}</div>
          </motion.div>
        ))}
      </div>

      {/* Key principles */}
      <motion.div
        className="mt-12 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.2 }}
        transition={{ duration: 0.6, delay: 0.3 }}
      >
        {[
          {
            icon: Shield,
            label: "Local by Default",
            desc: "Enabled providers receive only feature-specific data",
          },
          { icon: Zap, label: "Fail Fast", desc: "No silent degradation, clear errors" },
          { icon: GitBranch, label: "Checked Changes", desc: "Lint, tests, audits, and CI" },
          { icon: Database, label: "Observable", desc: "Opt-in evaluation and monitoring" },
        ].map((principle) => (
          <div
            key={principle.label}
            className="flex items-start gap-3 rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] p-4"
            style={{ background: "var(--color-bg-elevated)" }}
          >
            <principle.icon className="w-4 h-4 text-[var(--color-fg-tertiary)] flex-shrink-0 mt-0.5" />
            <div>
              <div className="text-xs font-semibold text-[var(--color-fg-primary)]">
                {principle.label}
              </div>
              <div className="text-[11px] text-[var(--color-fg-tertiary)]">{principle.desc}</div>
            </div>
          </div>
        ))}
      </motion.div>
    </Section>
  );
}
