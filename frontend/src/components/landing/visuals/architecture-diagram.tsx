import { motion } from "motion/react";
import { Bell, BookOpen, Globe, Mail, Sparkles, StickyNote, Sun, Zap } from "lucide-react";

export function ArchitectureDiagram() {
  const inputs = [
    { label: "Diary", icon: BookOpen, y: 15 },
    { label: "Web", icon: Globe, y: 35 },
    { label: "Notes", icon: StickyNote, y: 55 },
    { label: "Email", icon: Mail, y: 75 },
  ];

  const agentItems = [
    { label: "Diary", color: "var(--color-agent-diary)", y: 10 },
    { label: "Memory", color: "var(--color-agent-memory)", y: 22 },
    { label: "Research", color: "var(--color-agent-research)", y: 34 },
    { label: "Review", color: "var(--color-agent-review)", y: 46 },
    { label: "Notification", color: "var(--color-agent-notif)", y: 58 },
    { label: "Tools", color: "var(--color-agent-tools)", y: 70 },
    { label: "Project", color: "var(--color-agent-project)", y: 82 },
    { label: "Comms", color: "var(--color-agent-comms)", y: 94 },
  ];

  const outputs = [
    { label: "Briefings", icon: Sun, y: 20 },
    { label: "Alerts", icon: Bell, y: 40 },
    { label: "Insights", icon: Sparkles, y: 60 },
    { label: "Actions", icon: Zap, y: 80 },
  ];

  return (
    <div
      aria-label="Execution OS architecture diagram"
      className="relative w-full overflow-x-auto"
      role="region"
      tabIndex={0}
    >
      <div className="min-w-[700px] max-w-4xl mx-auto">
        <svg viewBox="0 0 700 300" className="w-full h-auto" style={{ minHeight: 260 }}>
          {/* Connection lines: Inputs -> Router */}
          {inputs.map((inp, i) => (
            <motion.path
              key={`in-${i}`}
              d={`M 110 ${inp.y * 2.6 + 20} Q 170 ${inp.y * 2.6 + 20} 210 150`}
              fill="none"
              stroke="var(--color-border-default)"
              strokeWidth="1"
              strokeDasharray="4 4"
              initial={{ pathLength: 0, opacity: 0 }}
              whileInView={{ pathLength: 1, opacity: 0.5 }}
              viewport={{ once: true }}
              transition={{ duration: 1, delay: i * 0.15 }}
            />
          ))}

          {/* Connection lines: Router -> Agents */}
          {agentItems.map((ag, i) => (
            <motion.line
              key={`ra-${i}`}
              x1="260"
              y1="150"
              x2="370"
              y2={ag.y * 2.6 + 12}
              stroke={ag.color}
              strokeWidth="1"
              strokeOpacity="0.4"
              initial={{ pathLength: 0, opacity: 0 }}
              whileInView={{ pathLength: 1, opacity: 1 }}
              viewport={{ once: true }}
              transition={{ duration: 0.6, delay: 0.5 + i * 0.08 }}
            />
          ))}

          {/* Connection lines: Agents -> Database */}
          {agentItems.map((ag, i) => (
            <motion.line
              key={`ad-${i}`}
              x1="440"
              y1={ag.y * 2.6 + 12}
              x2="490"
              y2="150"
              stroke={ag.color}
              strokeWidth="1"
              strokeOpacity="0.3"
              initial={{ pathLength: 0, opacity: 0 }}
              whileInView={{ pathLength: 1, opacity: 1 }}
              viewport={{ once: true }}
              transition={{ duration: 0.6, delay: 0.8 + i * 0.08 }}
            />
          ))}

          {/* Connection lines: Database -> Outputs */}
          {outputs.map((out, i) => (
            <motion.path
              key={`out-${i}`}
              d={`M 540 150 Q 580 ${out.y * 2.6 + 20} 620 ${out.y * 2.6 + 20}`}
              fill="none"
              stroke="var(--color-border-default)"
              strokeWidth="1"
              strokeDasharray="4 4"
              initial={{ pathLength: 0, opacity: 0 }}
              whileInView={{ pathLength: 1, opacity: 0.5 }}
              viewport={{ once: true }}
              transition={{ duration: 1, delay: 1 + i * 0.15 }}
            />
          ))}

          {/* Input labels */}
          {inputs.map((inp, i) => (
            <motion.g
              key={`inlabel-${i}`}
              initial={{ opacity: 0, x: -20 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: i * 0.1 }}
            >
              <rect
                x="15"
                y={inp.y * 2.6 + 6}
                width="90"
                height="28"
                rx="6"
                fill="var(--color-bg-elevated)"
                stroke="var(--color-border-default)"
                strokeWidth="1"
              />
              <text
                x="60"
                y={inp.y * 2.6 + 24}
                textAnchor="middle"
                fill="var(--color-fg-secondary)"
                fontSize="11"
                fontFamily="Inter, sans-serif"
              >
                {inp.label}
              </text>
            </motion.g>
          ))}

          {/* Router box */}
          <motion.g
            initial={{ scale: 0.8, opacity: 0 }}
            whileInView={{ scale: 1, opacity: 1 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6, delay: 0.3 }}
          >
            <rect
              x="210"
              y="125"
              width="50"
              height="50"
              rx="10"
              fill="var(--color-bg-elevated)"
              stroke="var(--color-info-500)"
              strokeWidth="1.5"
            />
            <text
              x="235"
              y="147"
              textAnchor="middle"
              fill="var(--color-info-500)"
              fontSize="9"
              fontFamily="Inter, sans-serif"
              fontWeight="600"
            >
              AI
            </text>
            <text
              x="235"
              y="160"
              textAnchor="middle"
              fill="var(--color-info-500)"
              fontSize="9"
              fontFamily="Inter, sans-serif"
              fontWeight="600"
            >
              Router
            </text>
          </motion.g>

          {/* Agent boxes */}
          {agentItems.map((ag, i) => (
            <motion.g
              key={`agbox-${i}`}
              initial={{ scale: 0, opacity: 0 }}
              whileInView={{ scale: 1, opacity: 1 }}
              viewport={{ once: true }}
              transition={{
                duration: 0.4,
                delay: 0.5 + i * 0.07,
                type: "spring",
                stiffness: 300,
              }}
            >
              <rect
                x="370"
                y={ag.y * 2.6}
                width="70"
                height="22"
                rx="4"
                fill="var(--color-bg-elevated)"
                stroke={ag.color}
                strokeWidth="1"
              />
              <text
                x="405"
                y={ag.y * 2.6 + 15}
                textAnchor="middle"
                fill={ag.color}
                fontSize="9"
                fontFamily="Inter, sans-serif"
                fontWeight="500"
              >
                {ag.label}
              </text>
            </motion.g>
          ))}

          {/* Database */}
          <motion.g
            initial={{ scale: 0.8, opacity: 0 }}
            whileInView={{ scale: 1, opacity: 1 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6, delay: 0.8 }}
          >
            <ellipse
              cx="515"
              cy="138"
              rx="25"
              ry="8"
              fill="var(--color-bg-overlay)"
              stroke="var(--color-success-500)"
              strokeWidth="1"
            />
            <rect
              x="490"
              y="138"
              width="50"
              height="30"
              fill="var(--color-bg-overlay)"
              stroke="var(--color-success-500)"
              strokeWidth="1"
            />
            <line
              x1="490"
              y1="138"
              x2="490"
              y2="168"
              stroke="var(--color-success-500)"
              strokeWidth="1"
            />
            <line
              x1="540"
              y1="138"
              x2="540"
              y2="168"
              stroke="var(--color-success-500)"
              strokeWidth="1"
            />
            <ellipse
              cx="515"
              cy="168"
              rx="25"
              ry="8"
              fill="var(--color-bg-overlay)"
              stroke="var(--color-success-500)"
              strokeWidth="1"
            />
            <text
              x="515"
              y="157"
              textAnchor="middle"
              fill="var(--color-success-500)"
              fontSize="9"
              fontFamily="Inter, sans-serif"
              fontWeight="600"
            >
              DB
            </text>
          </motion.g>

          {/* Output labels */}
          {outputs.map((out, i) => (
            <motion.g
              key={`outlabel-${i}`}
              initial={{ opacity: 0, x: 20 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: 1.2 + i * 0.1 }}
            >
              <rect
                x="620"
                y={out.y * 2.6 + 6}
                width="70"
                height="28"
                rx="6"
                fill="var(--color-bg-elevated)"
                stroke="var(--color-border-default)"
                strokeWidth="1"
              />
              <text
                x="655"
                y={out.y * 2.6 + 24}
                textAnchor="middle"
                fill="var(--color-fg-secondary)"
                fontSize="10"
                fontFamily="Inter, sans-serif"
              >
                {out.label}
              </text>
            </motion.g>
          ))}
        </svg>
      </div>
    </div>
  );
}
