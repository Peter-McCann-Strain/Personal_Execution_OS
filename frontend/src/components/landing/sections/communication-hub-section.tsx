import { motion } from "motion/react";
import { Mail } from "lucide-react";

import { Section } from "../primitives";
import { CommunicationVisual } from "../visuals/communication-visual";

export function CommunicationHubSection() {
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
          <CommunicationVisual />
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
            style={{ color: "var(--color-agent-comms)" }}
          >
            <Mail className="w-3.5 h-3.5" />
            Communication Hub
          </span>
          <h2 className="text-3xl md:text-4xl font-bold text-[var(--color-fg-primary)] mb-4 leading-tight">
            Tame the <span style={{ color: "var(--color-agent-comms)" }}>Communication Flood.</span>
          </h2>
          <p className="text-sm md:text-base text-[var(--color-fg-secondary)] leading-relaxed mb-6">
            AI reads synced email context to suggest priorities and editable local response drafts;
            it does not send or change provider mail. Read-only calendar context can reveal free
            slots when a supported account is connected. Your contact workspace keeps follow-ups
            visible.
          </p>
          <div className="space-y-3">
            {[
              "Email triage with priority scoring and smart categorisation",
              "Editable draft suggestions with human approval",
              "Read-only calendar context with free slot detection",
              "Contact CRM with relationship decay warnings",
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
                    background: "color-mix(in oklch, var(--color-agent-comms) 20%, transparent)",
                  }}
                >
                  <div
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ background: "var(--color-agent-comms)" }}
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
