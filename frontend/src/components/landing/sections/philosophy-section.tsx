import { motion } from "motion/react";
import { Quote } from "lucide-react";

import { GlassCard, Section } from "../primitives";

export function PhilosophySection() {
  return (
    <Section>
      <div className="max-w-3xl mx-auto text-center">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          whileInView={{ opacity: 1, scale: 1 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.8 }}
        >
          <Quote className="w-10 h-10 mx-auto mb-6 text-[var(--color-fg-disabled)]" />

          <blockquote className="text-2xl md:text-3xl lg:text-4xl font-bold leading-tight mb-12">
            <span
              style={{
                background:
                  "linear-gradient(135deg, oklch(0.55 0.2 250) 0%, oklch(0.5 0.22 290) 100%)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
              }}
            >
              "Capture what matters. Decide what is next. Review what changed."
            </span>
          </blockquote>
        </motion.div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-left">
          {[
            {
              title: "BASB",
              subtitle: "Capture, Organise, Distil, Express",
              description:
                "Capture everything of value, organise for actionability, distil into key insights, and express through creative output. The CODE framework made digital.",
            },
            {
              title: "GTD",
              subtitle: "Getting Things Done",
              description:
                "Trusted capture, next-action thinking, context-based execution, and regular reviews. Your system handles the remembering so you handle the doing.",
            },
            {
              title: "Zettelkasten",
              subtitle: "Linked Knowledge",
              description:
                "Atomic notes connected by meaning, not hierarchy. Ideas compound over time through a growing web of connections that surface unexpected insights.",
            },
          ].map((phil, i) => (
            <motion.div
              key={phil.title}
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.3 }}
              transition={{ duration: 0.5, delay: i * 0.15 }}
            >
              <GlassCard className="h-full">
                <div className="text-lg font-bold text-[var(--color-fg-primary)] mb-0.5">
                  {phil.title}
                </div>
                <div className="text-xs text-[var(--color-fg-tertiary)] mb-3">{phil.subtitle}</div>
                <p className="text-xs text-[var(--color-fg-secondary)] leading-relaxed">
                  {phil.description}
                </p>
              </GlassCard>
            </motion.div>
          ))}
        </div>
      </div>
    </Section>
  );
}
