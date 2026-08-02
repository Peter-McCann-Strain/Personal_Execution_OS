import { motion } from "motion/react";
import { Search } from "lucide-react";

import { Section } from "../primitives";
import { KnowledgeGraphVisual } from "../visuals/knowledge-graph-visual";

export function IntelligentMemorySection() {
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
            style={{ color: "var(--color-agent-memory)" }}
          >
            <Search className="w-3.5 h-3.5" />
            Intelligent Memory
          </span>
          <h2 className="text-3xl md:text-4xl font-bold text-[var(--color-fg-primary)] mb-4 leading-tight">
            Everything Connected.{" "}
            <span style={{ color: "var(--color-agent-memory)" }}>Nothing Lost.</span>
          </h2>
          <p className="text-sm md:text-base text-[var(--color-fg-secondary)] leading-relaxed mb-6">
            Structured search works against local records. Optional vector embeddings add semantic
            retrieval, while model-backed entity and link suggestions can enrich the knowledge graph
            when you enable them.
          </p>
          <div className="space-y-3">
            {[
              "Structured search across locally stored records",
              "Optional pgvector retrieval with reciprocal rank fusion",
              "Reviewed entity and link suggestions when a model is enabled",
              "Explicit PARA classification: Projects, Areas, Resources, Archive",
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
                    background: "color-mix(in oklch, var(--color-agent-memory) 20%, transparent)",
                  }}
                >
                  <div
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ background: "var(--color-agent-memory)" }}
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
          <KnowledgeGraphVisual />
        </motion.div>
      </div>
    </Section>
  );
}
