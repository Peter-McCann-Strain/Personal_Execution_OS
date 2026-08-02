import { Link } from "react-router";
import { motion } from "motion/react";
import { LayoutDashboard, Settings } from "lucide-react";

import { Section } from "../primitives";

export function CallToActionSection() {
  return (
    <Section className="pb-12 md:pb-16">
      <motion.div
        className="relative text-center rounded-[var(--radius-xl)] border border-[var(--color-border-default)] py-16 md:py-20 px-8 overflow-hidden"
        style={{
          background: "var(--cta-bg)",
        }}
        initial={{ opacity: 0, y: 40 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.3 }}
        transition={{ duration: 0.8 }}
      >
        {/* Background glow */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background: `radial-gradient(ellipse at 50% 0%, var(--cta-glow) 0%, transparent 60%)`,
          }}
        />

        <div className="relative z-10">
          <h2 className="text-3xl md:text-4xl lg:text-5xl font-bold mb-4">
            <span
              style={{
                background:
                  "linear-gradient(135deg, var(--color-fg-primary) 0%, var(--color-info-500) 100%)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
              }}
            >
              Ready to extend your mind?
            </span>
          </h2>
          <p className="text-sm md:text-base text-[var(--color-fg-secondary)] mb-8 max-w-lg mx-auto">
            Your workspace is ready. Start capturing, organising, and surfacing the knowledge that
            matters.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              to="/dashboard"
              className="inline-flex items-center gap-2 px-8 py-3.5 text-sm font-semibold rounded-[var(--radius-full)] transition-all duration-300 hover:scale-105 hover:shadow-[0_0_30px_oklch(0.55_0.18_250_/_0.3)]"
              style={{
                background: "linear-gradient(135deg, oklch(0.55 0.18 250), oklch(0.5 0.2 290))",
                color: "white",
              }}
            >
              <LayoutDashboard className="w-4 h-4" />
              Go to Dashboard
            </Link>
            <Link
              to="/settings"
              className="inline-flex items-center gap-2 px-6 py-3.5 text-sm font-medium rounded-[var(--radius-full)] border border-[var(--color-border-default)] text-[var(--color-fg-secondary)] hover:text-[var(--color-fg-primary)] hover:border-[var(--color-border-strong)] transition-all duration-300"
            >
              <Settings className="w-4 h-4" />
              Settings
            </Link>
          </div>
        </div>
      </motion.div>
    </Section>
  );
}
