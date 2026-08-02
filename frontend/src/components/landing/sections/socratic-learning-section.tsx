import { motion } from "motion/react";
import { GraduationCap } from "lucide-react";

import { Section } from "../primitives";

export function SocraticLearningSection() {
  return (
    <Section>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16 items-center">
        <motion.div
          initial={{ opacity: 0, x: -40 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.7 }}
        >
          <span className="inline-flex items-center gap-2 mb-4 text-xs font-semibold uppercase tracking-[0.2em] text-[var(--color-info-500)]">
            <GraduationCap className="w-3.5 h-3.5" />
            Socratic Learning
          </span>
          <h2 className="text-3xl md:text-4xl font-bold text-[var(--color-fg-primary)] mb-4 leading-tight">
            Learn by <span className="text-[var(--color-info-500)]">Thinking, Not Reading.</span>
          </h2>
          <p className="text-sm md:text-base text-[var(--color-fg-secondary)] leading-relaxed mb-6">
            With a model provider enabled, the Socratic workflow guides your reasoning with probing
            questions instead of simply handing you answers. Tutor, clarifier, devil's advocate,
            connector, and assessor roles structure the conversation.
          </p>
          <div className="space-y-3">
            {[
              "Oxford-style Socratic dialogue that builds real understanding",
              "Bloom's taxonomy assessment from recall to synthesis",
              "Devil's advocate challenges your assumptions",
              "Connector links new ideas to your existing knowledge graph",
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
                    background: "color-mix(in oklch, var(--color-info-500) 20%, transparent)",
                  }}
                >
                  <div className="w-1.5 h-1.5 rounded-full bg-[var(--color-info-500)]" />
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
          {/* Socratic dialogue visual */}
          <div className="space-y-3 max-w-md mx-auto">
            {[
              {
                role: "tutor",
                text: "What do you think happens when a neural network overfits?",
              },
              {
                role: "user",
                text: "It memorises the training data instead of learning patterns?",
              },
              {
                role: "clarifier",
                text: "Good intuition. Can you explain why memorisation is different from generalisation?",
              },
              { role: "user", text: "Because it won't work on new data it hasn't seen..." },
              {
                role: "devil",
                text: "But isn't all learning a form of memorisation? What makes pattern recognition different?",
              },
            ].map((msg, i) => (
              <motion.div
                key={i}
                className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                initial={{ opacity: 0, y: 15 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.4, delay: 0.3 + i * 0.15 }}
              >
                <div
                  className={`rounded-[var(--radius-lg)] px-4 py-2.5 max-w-[85%] ${
                    msg.role === "user"
                      ? "rounded-br-[var(--radius-sm)]"
                      : "rounded-bl-[var(--radius-sm)]"
                  }`}
                  style={{
                    background:
                      msg.role === "user" ? "var(--color-info-500)" : "var(--color-bg-elevated)",
                    color: msg.role === "user" ? "white" : "var(--color-fg-primary)",
                    border:
                      msg.role !== "user" ? "1px solid var(--color-border-subtle)" : undefined,
                  }}
                >
                  {msg.role !== "user" && (
                    <div
                      className="text-[9px] font-semibold uppercase tracking-wider mb-1"
                      style={{
                        color:
                          msg.role === "devil" ? "var(--color-error-500)" : "var(--color-info-500)",
                      }}
                    >
                      {msg.role === "devil"
                        ? "Devil's Advocate"
                        : msg.role === "clarifier"
                          ? "Clarifier"
                          : "Tutor"}
                    </div>
                  )}
                  <div className="text-xs leading-relaxed">{msg.text}</div>
                </div>
              </motion.div>
            ))}
          </div>
        </motion.div>
      </div>
    </Section>
  );
}
