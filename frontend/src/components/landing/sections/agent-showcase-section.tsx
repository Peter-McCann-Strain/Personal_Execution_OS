import { Link } from "react-router";
import { motion } from "motion/react";
import { ArrowRight } from "lucide-react";

import { agents } from "../content";
import { GlassCard, Section, SectionHeading } from "../primitives";

export function AgentShowcaseSection() {
  return (
    <Section id="agents" className="overflow-hidden">
      <SectionHeading
        label="Meet Your Agents"
        title="8 Focused Workflows, One Workspace"
        description="Each workflow owns a clear domain. Local records remain useful without a model; model-backed classification, synthesis, and alerts appear only after you configure and enable a provider."
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 md:gap-5">
        {agents.map((agent, i) => (
          <motion.div
            key={agent.name}
            initial={{ opacity: 0, y: 50 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.2 }}
            transition={{
              duration: 0.5,
              delay: i * 0.08,
              ease: [0.25, 0.46, 0.45, 0.94],
            }}
          >
            <Link to={agent.route} className="block h-full">
              <GlassCard className="h-full cursor-pointer" hoverGlow={agent.color}>
                {/* Icon + Name */}
                <div className="flex items-center gap-3 mb-3">
                  <div
                    className="w-10 h-10 rounded-[var(--radius-md)] flex items-center justify-center flex-shrink-0"
                    style={{
                      background: `color-mix(in oklch, ${agent.color} 15%, transparent)`,
                      border: `1px solid color-mix(in oklch, ${agent.color} 30%, transparent)`,
                    }}
                  >
                    <agent.icon className="w-5 h-5" style={{ color: agent.color }} />
                  </div>
                  <h3 className="text-base font-semibold" style={{ color: agent.color }}>
                    {agent.name}
                  </h3>
                </div>

                {/* Description */}
                <p className="text-xs text-[var(--color-fg-secondary)] leading-relaxed mb-4">
                  {agent.description}
                </p>

                {/* Capabilities */}
                <div className="space-y-1.5">
                  {agent.capabilities.map((cap, j) => (
                    <div key={j} className="flex items-center gap-2">
                      <div
                        className="w-1 h-1 rounded-full flex-shrink-0"
                        style={{ background: agent.color }}
                      />
                      <span className="text-[11px] text-[var(--color-fg-tertiary)]">{cap}</span>
                    </div>
                  ))}
                </div>

                {/* Hover arrow */}
                <div
                  className="mt-4 flex items-center gap-1 text-[11px] font-medium opacity-0 group-hover:opacity-100 transition-opacity duration-300"
                  style={{ color: agent.color }}
                >
                  Explore <ArrowRight className="w-3 h-3" />
                </div>
              </GlassCard>
            </Link>
          </motion.div>
        ))}
      </div>
    </Section>
  );
}
