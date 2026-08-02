import { motion } from "motion/react";

export function KnowledgeGraphVisual() {
  const nodes = [
    { id: 0, cx: 50, cy: 30, label: "Meeting Notes", color: "var(--color-agent-diary)" },
    { id: 1, cx: 20, cy: 50, label: "Project Alpha", color: "var(--color-agent-project)" },
    { id: 2, cx: 80, cy: 45, label: "Research Paper", color: "var(--color-agent-research)" },
    { id: 3, cx: 35, cy: 75, label: "Contact: Sarah", color: "var(--color-agent-comms)" },
    { id: 4, cx: 65, cy: 70, label: "Decision Log", color: "var(--color-agent-review)" },
    { id: 5, cx: 50, cy: 55, label: "Key Insight", color: "var(--color-agent-memory)" },
    { id: 6, cx: 15, cy: 25, label: "Diary Entry", color: "var(--color-agent-diary)" },
    { id: 7, cx: 85, cy: 20, label: "Email Thread", color: "var(--color-agent-comms)" },
  ];

  const edges = [
    [0, 5],
    [1, 5],
    [2, 5],
    [3, 1],
    [4, 5],
    [0, 1],
    [2, 4],
    [6, 0],
    [7, 2],
    [3, 4],
  ];

  return (
    <div className="relative w-full aspect-[4/3] max-w-lg mx-auto">
      <svg viewBox="0 0 100 100" className="w-full h-full">
        {/* Edges */}
        {edges.map(([from, to], i) => (
          <motion.line
            key={`edge-${i}`}
            x1={nodes[from].cx}
            y1={nodes[from].cy}
            x2={nodes[to].cx}
            y2={nodes[to].cy}
            stroke="var(--color-border-default)"
            strokeWidth="0.3"
            strokeOpacity="0.6"
            initial={{ pathLength: 0, opacity: 0 }}
            whileInView={{ pathLength: 1, opacity: 1 }}
            viewport={{ once: true }}
            transition={{ duration: 1, delay: 0.3 + i * 0.08 }}
          />
        ))}

        {/* Animated pulses along edges */}
        {edges.slice(0, 5).map(([from, to], i) => (
          <motion.circle
            key={`pulse-${i}`}
            r="0.6"
            fill="var(--color-info-500)"
            initial={{ opacity: 0 }}
            whileInView={{ opacity: [0, 0.8, 0] }}
            viewport={{ once: true }}
            transition={{
              duration: 2.5,
              delay: 1.5 + i * 0.4,
              repeat: Infinity,
              repeatDelay: 3,
            }}
          >
            <animateMotion
              dur={`${2.5 + i * 0.3}s`}
              repeatCount="indefinite"
              begin={`${1.5 + i * 0.4}s`}
              path={`M${nodes[from].cx},${nodes[from].cy} L${nodes[to].cx},${nodes[to].cy}`}
            />
          </motion.circle>
        ))}

        {/* Nodes */}
        {nodes.map((node, i) => (
          <motion.g
            key={node.id}
            initial={{ scale: 0, opacity: 0 }}
            whileInView={{ scale: 1, opacity: 1 }}
            viewport={{ once: true }}
            transition={{ duration: 0.5, delay: 0.1 + i * 0.1, type: "spring", stiffness: 200 }}
          >
            {/* Glow */}
            <circle cx={node.cx} cy={node.cy} r="4" fill={node.color} opacity="0.15" />
            {/* Node circle */}
            <circle
              cx={node.cx}
              cy={node.cy}
              r="2.2"
              fill="var(--color-bg-elevated)"
              stroke={node.color}
              strokeWidth="0.4"
            />
            {/* Label */}
            <text
              x={node.cx}
              y={node.cy + 5}
              textAnchor="middle"
              fill="var(--color-fg-secondary)"
              fontSize="2.2"
              fontFamily="Inter, sans-serif"
            >
              {node.label}
            </text>
          </motion.g>
        ))}
      </svg>
    </div>
  );
}
