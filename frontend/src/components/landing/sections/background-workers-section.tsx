import { motion } from "motion/react";
import { Bell, Globe, Network, Shield, Sparkles, Zap } from "lucide-react";

import { GlassCard, Section, SectionHeading } from "../primitives";

export function BackgroundWorkersSection() {
  return (
    <Section>
      <SectionHeading
        label="Optional Automation"
        title="Background Work You Explicitly Enable"
        description="The worker runs local scheduling and maintenance. Model-backed evaluation, curation, alerts, and provider integrations stay off until you configure them."
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 md:gap-5">
        {[
          {
            icon: Sparkles,
            title: "Pattern Detection",
            desc: "Review workflows can analyse diary entries for mood, energy, stress, and productivity patterns when model processing is enabled.",
            color: "var(--color-agent-review)",
          },
          {
            icon: Globe,
            title: "Content Curation",
            desc: "An opt-in worker can read configured RSS sources, score relevance with a model, and add selected material to a briefing.",
            color: "var(--color-agent-research)",
          },
          {
            icon: Bell,
            title: "Heartbeat Monitor",
            desc: "The scheduled worker can check stale goals, deadlines, commitments, and relationship follow-ups after proactive automation is enabled.",
            color: "var(--color-agent-notif)",
          },
          {
            icon: Shield,
            title: "Optional Quality Evaluation",
            desc: "An opt-in evaluator can score model interactions for relevance, actionability, tone, and conciseness in the monitoring workspace.",
            color: "var(--color-success-500)",
          },
          {
            icon: Network,
            title: "Memory Consolidation",
            desc: "Optional model-backed jobs can propose episode clusters, summary notes, and entity links for the local knowledge workspace.",
            color: "var(--color-agent-memory)",
          },
          {
            icon: Zap,
            title: "Evaluation Tooling",
            desc: "Prompt versions, comparison experiments, and failure analysis are available to operators; they do not run on every response by default.",
            color: "var(--color-info-500)",
          },
        ].map((worker, i) => (
          <motion.div
            key={worker.title}
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.2 }}
            transition={{ duration: 0.5, delay: i * 0.08 }}
          >
            <GlassCard className="h-full">
              <div className="flex items-center gap-3 mb-3">
                <div
                  className="w-9 h-9 rounded-[var(--radius-md)] flex items-center justify-center flex-shrink-0"
                  style={{
                    background: `color-mix(in oklch, ${worker.color} 15%, transparent)`,
                    border: `1px solid color-mix(in oklch, ${worker.color} 25%, transparent)`,
                  }}
                >
                  <worker.icon className="w-4 h-4" style={{ color: worker.color }} />
                </div>
                <h3 className="text-sm font-semibold text-[var(--color-fg-primary)]">
                  {worker.title}
                </h3>
              </div>
              <p className="text-xs text-[var(--color-fg-secondary)] leading-relaxed">
                {worker.desc}
              </p>
            </GlassCard>
          </motion.div>
        ))}
      </div>
    </Section>
  );
}
