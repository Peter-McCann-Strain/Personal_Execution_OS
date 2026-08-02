import { motion } from "motion/react";
import { ArrowRight } from "lucide-react";

import { steps } from "../content";
import { GlassCard, Section, SectionHeading } from "../primitives";

export function HowItWorksSection() {
  return (
    <Section id="how-it-works">
      <SectionHeading
        label="How It Works"
        title="Three Steps to a Calmer Mind"
        description="Stop trying to remember everything. Let your knowledge system handle the cognitive load while you focus on what matters most."
      />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 md:gap-8">
        {steps.map((step, i) => (
          <motion.div
            key={step.number}
            className="relative"
            initial={{ opacity: 0, y: 40 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.3 }}
            transition={{ duration: 0.6, delay: i * 0.2 }}
          >
            <GlassCard className="h-full text-center">
              {/* Step number */}
              <div className="text-5xl font-bold text-[var(--color-fg-disabled)] mb-4 select-none">
                {step.number}
              </div>

              {/* Icon */}
              <motion.div
                className="w-14 h-14 rounded-[var(--radius-lg)] mx-auto mb-5 flex items-center justify-center"
                style={{
                  background: `linear-gradient(135deg, color-mix(in oklch, var(--color-info-500) 15%, var(--color-bg-elevated)), color-mix(in oklch, var(--color-info-500) 10%, var(--color-bg-elevated)))`,
                  border: "1px solid var(--color-border-subtle)",
                }}
                whileInView={{
                  scale: [0.8, 1.1, 1],
                }}
                viewport={{ once: true }}
                transition={{ duration: 0.8, delay: 0.3 + i * 0.2 }}
              >
                <step.icon className="w-6 h-6 text-[var(--color-info-500)]" />
              </motion.div>

              <h3 className="text-xl font-semibold text-[var(--color-fg-primary)] mb-3">
                {step.title}
              </h3>
              <p className="text-sm text-[var(--color-fg-secondary)] leading-relaxed">
                {step.description}
              </p>
            </GlassCard>

            {/* Connector arrow (desktop only) */}
            {i < steps.length - 1 && (
              <div className="hidden md:block absolute top-1/2 -right-4 md:-right-5 -translate-y-1/2 z-10">
                <ArrowRight className="w-4 h-4 text-[var(--color-fg-disabled)]" />
              </div>
            )}
          </motion.div>
        ))}
      </div>
    </Section>
  );
}
