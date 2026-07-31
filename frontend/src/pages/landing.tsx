import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { motion, useInView, useScroll, useTransform } from "motion/react";
import {
  Brain,
  BookOpen,
  Search,
  FlaskConical,
  BarChart3,
  Bell,
  Wrench,
  FolderKanban,
  Mail,
  ArrowRight,
  Sparkles,
  Network,
  Sun,
  Target,
  Shield,
  ChevronDown,
  Globe,
  Database,
  Zap,
  Send,
  GitBranch,
  LayoutDashboard,
  Settings,
  ExternalLink,
  Quote,
  GraduationCap,
  StickyNote,
} from "lucide-react";

/* ─────────────────────────── Helpers ─────────────────────────── */

function useCountUp(end: number, duration = 2000) {
  const [count, setCount] = useState(0);
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.5 });

  useEffect(() => {
    if (!inView) return;
    let start = 0;
    const startTime = performance.now();
    function tick(now: number) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      start = Math.round(eased * end);
      setCount(start);
      if (progress < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }, [inView, end, duration]);

  return [count, ref] as const;
}

function seededRandom(seed: number): number {
  const x = Math.sin(seed * 12.9898) * 43758.5453;
  return x - Math.floor(x);
}

function getSourceRepositoryUrl(): string | null {
  const configured = (import.meta.env.VITE_SOURCE_REPOSITORY_URL as string | undefined)?.trim();
  if (!configured) return null;
  try {
    const url = new URL(configured);
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

const sourceRepositoryUrl = getSourceRepositoryUrl();

/* Floating particle background */
function ParticleField() {
  const [particles] = useState(() =>
    Array.from({ length: 50 }, (_, i) => ({
      id: i,
      x: seededRandom(i + 1) * 100,
      y: seededRandom(i + 101) * 100,
      size: seededRandom(i + 201) * 3 + 1,
      duration: seededRandom(i + 301) * 20 + 15,
      delay: seededRandom(i + 401) * 10,
      opacity: seededRandom(i + 501) * 0.3 + 0.1,
    })),
  );

  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none">
      {particles.map((p) => (
        <motion.div
          key={p.id}
          className="absolute rounded-full"
          style={{
            width: p.size,
            height: p.size,
            left: `${p.x}%`,
            top: `${p.y}%`,
            background: `oklch(0.62 0.15 250 / ${p.opacity})`,
          }}
          animate={{
            y: [0, -30, 10, -20, 0],
            x: [0, 15, -10, 20, 0],
            opacity: [p.opacity, p.opacity * 1.5, p.opacity * 0.5, p.opacity * 1.2, p.opacity],
          }}
          transition={{
            duration: p.duration,
            repeat: Infinity,
            delay: p.delay,
            ease: "easeInOut",
          }}
        />
      ))}
    </div>
  );
}

/* Animated gradient mesh background */
function GradientMesh() {
  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none">
      <motion.div
        className="absolute -top-1/2 -left-1/2 w-[200%] h-[200%]"
        style={{
          background:
            "radial-gradient(ellipse at 30% 20%, var(--mesh-color-1) 0%, transparent 50%), " +
            "radial-gradient(ellipse at 70% 80%, var(--mesh-color-2) 0%, transparent 50%), " +
            "radial-gradient(ellipse at 50% 50%, var(--mesh-color-3) 0%, transparent 60%)",
        }}
        animate={{ rotate: [0, 360] }}
        transition={{ duration: 120, repeat: Infinity, ease: "linear" }}
      />
    </div>
  );
}

/* Section wrapper with scroll animation */
function Section({
  children,
  className = "",
  id,
}: {
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <motion.section
      id={id}
      className={`relative py-24 md:py-32 px-6 ${className}`}
      initial={{ opacity: 0 }}
      whileInView={{ opacity: 1 }}
      viewport={{ once: true, amount: 0.1 }}
      transition={{ duration: 0.8 }}
    >
      <div className="max-w-6xl mx-auto">{children}</div>
    </motion.section>
  );
}

/* Section heading */
function SectionHeading({
  label,
  title,
  description,
}: {
  label?: string;
  title: string;
  description?: string;
}) {
  return (
    <motion.div
      className="text-center mb-16 md:mb-20"
      initial={{ opacity: 0, y: 30 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.3 }}
      transition={{ duration: 0.6 }}
    >
      {label && (
        <span className="inline-block mb-4 text-xs font-semibold uppercase tracking-[0.2em] text-[var(--color-fg-tertiary)]">
          {label}
        </span>
      )}
      <h2
        className="text-3xl md:text-4xl lg:text-5xl font-bold leading-tight"
        style={{
          background:
            "linear-gradient(135deg, var(--color-fg-primary) 0%, var(--color-fg-secondary) 100%)",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          backgroundClip: "text",
        }}
      >
        {title}
      </h2>
      {description && (
        <p className="mt-4 text-base md:text-lg text-[var(--color-fg-secondary)] max-w-2xl mx-auto leading-relaxed">
          {description}
        </p>
      )}
    </motion.div>
  );
}

/* Glassmorphism card */
function GlassCard({
  children,
  className = "",
  hoverGlow,
}: {
  children: ReactNode;
  className?: string;
  hoverGlow?: string;
}) {
  return (
    <motion.div
      className={`relative rounded-[var(--radius-xl)] border border-[var(--color-border-default)] p-6 overflow-hidden group ${className}`}
      style={{
        background: "var(--glass-bg)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        boxShadow: "var(--glass-shadow)",
      }}
      whileHover={{
        y: -4,
        borderColor: hoverGlow || "var(--color-border-strong)",
        transition: { duration: 0.3 },
      }}
    >
      {hoverGlow && (
        <div
          className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"
          style={{
            background: `radial-gradient(600px circle at var(--mouse-x, 50%) var(--mouse-y, 50%), ${hoverGlow}15, transparent 40%)`,
          }}
        />
      )}
      {children}
    </motion.div>
  );
}

/* ──────────────────────── Agent Data ──────────────────────── */

const agents = [
  {
    name: "Diary",
    icon: BookOpen,
    color: "var(--color-agent-diary)",
    description:
      "Your timestamped journal, mood tracker, and cognitive companion. Captures thoughts as they happen with interstitial journaling and progressive summarisation.",
    capabilities: [
      "Mood & energy tracking",
      "Interstitial journaling",
      "Progressive summarisation",
      "Plan my day (energy-aware)",
    ],
    route: "/diary",
  },
  {
    name: "Memory",
    icon: Search,
    color: "var(--color-agent-memory)",
    description:
      "Searches local records and linked knowledge. Optional embeddings and model-backed extraction add semantic retrieval and entity suggestions.",
    capabilities: [
      "Structured local search",
      "Optional vector retrieval",
      "Knowledge graph",
      "Spaced repetition (SM-2)",
    ],
    route: "/memory",
  },
  {
    name: "Research",
    icon: FlaskConical,
    color: "var(--color-agent-research)",
    description:
      "Source-attributed research and decision frameworks when a model and web-search provider are configured.",
    capabilities: [
      "Multi-source web synthesis",
      "Decision frameworks",
      "URL capture & extraction",
      "Deep analysis",
    ],
    route: "/chat",
  },
  {
    name: "Review",
    icon: BarChart3,
    color: "var(--color-agent-review)",
    description:
      "Weekly and quarterly review workflows for goals, decisions, trends, and follow-through.",
    capabilities: [
      "Weekly/quarterly reviews",
      "Pattern detection",
      "Decision journal",
      "Trend analysis",
    ],
    route: "/reviews",
  },
  {
    name: "Notification",
    icon: Bell,
    color: "var(--color-agent-notif)",
    description:
      "Optional briefings and alerts for commitments, deadlines, relationships, and notification load.",
    capabilities: [
      "Commitment extraction",
      "Content curation (RSS + AI)",
      "Fatigue management",
      "Morning briefings",
    ],
    route: "/notifications",
  },
  {
    name: "Tools",
    icon: Wrench,
    color: "var(--color-agent-tools)",
    description:
      "Read-only context from connected calendars, inboxes, and files through provider adapters. Source material stays attributable and external accounts are never modified.",
    capabilities: [
      "Read-only calendar context",
      "Read-only mail context",
      "Provider adapter boundary",
      "Free slot detection",
    ],
    route: "/calendar",
  },
  {
    name: "Project",
    icon: FolderKanban,
    color: "var(--color-agent-project)",
    description:
      "Work breakdown structures, WSJF prioritisation, and velocity tracking. Turns vague goals into structured, executable plans.",
    capabilities: [
      "Work breakdown (WBS)",
      "WSJF prioritisation",
      "Velocity tracking",
      "Habit & goal tracking",
    ],
    route: "/projects",
  },
  {
    name: "Communications",
    icon: Mail,
    color: "var(--color-agent-comms)",
    description:
      "Read-only email triage, editable local draft suggestions, and response prioritisation. It does not send or modify provider mail.",
    capabilities: [
      "Email triage & sorting",
      "Editable draft suggestions",
      "Response priority",
      "Contact CRM",
    ],
    route: "/email",
  },
];

/* ──────────────────────── How It Works Steps ──────────────────────── */

const steps = [
  {
    number: "01",
    title: "Capture",
    description:
      "Capture through the web dashboard, diary, notes, or a connected inbox. Keep thoughts, tasks, ideas, and observations together before they fade.",
    icon: Send,
    gradient: "from-blue-500/20 to-purple-500/20",
  },
  {
    number: "02",
    title: "Organise",
    description:
      "Organise records explicitly. When you enable a model, assistants can suggest classifications, entities, links, and PARA categories for you to review.",
    icon: Network,
    gradient: "from-purple-500/20 to-pink-500/20",
  },
  {
    number: "03",
    title: "Surface",
    description:
      "Use local search and reviews by default. Optional briefings, alerts, pattern analysis, and semantic retrieval appear only when configured.",
    icon: Sparkles,
    gradient: "from-pink-500/20 to-amber-500/20",
  },
];

/* ──────────────────────── Tech Stack ──────────────────────── */

const techStack = [
  { name: "Python", label: "Backend" },
  { name: "FastAPI", label: "API Framework" },
  { name: "LangGraph", label: "Agent Orchestration" },
  { name: "Provider adapters", label: "Language Models" },
  { name: "PostgreSQL", label: "Database" },
  { name: "pgvector", label: "Vector Search" },
  { name: "React 19", label: "Frontend" },
  { name: "TypeScript", label: "Type Safety" },
  { name: "Ollama", label: "Local Embeddings" },
  { name: "Redis", label: "Job Queue" },
  { name: "OpenTelemetry", label: "Observability" },
  { name: "PWA", label: "Installable Web App" },
];

/* ─────────────────── Knowledge Graph Visualisation ─────────────────── */

function KnowledgeGraphVisual() {
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

/* ────────────────── Architecture Diagram ────────────────── */

function ArchitectureDiagram() {
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

/* ────────────────── Daily Rhythm Visual ────────────────── */

function DailyRhythmVisual() {
  const entries = [
    {
      time: "07:00",
      label: "Morning Briefing",
      desc: "Calendar, priorities, curated content",
      color: "var(--color-agent-notif)",
    },
    {
      time: "09:15",
      label: "Diary Capture",
      desc: '"Feeling focused. Starting the refactor."',
      color: "var(--color-agent-diary)",
    },
    {
      time: "11:30",
      label: "Memory Link",
      desc: "Connected meeting notes to Project Alpha",
      color: "var(--color-agent-memory)",
    },
    {
      time: "14:00",
      label: "Smart Alert",
      desc: '"Follow up with Sarah -- 5 days overdue"',
      color: "var(--color-agent-notif)",
    },
    {
      time: "17:00",
      label: "Review Nudge",
      desc: "Weekly review ready. 3 patterns detected.",
      color: "var(--color-agent-review)",
    },
  ];

  return (
    <div className="space-y-4 max-w-md mx-auto">
      {entries.map((entry, i) => (
        <motion.div
          key={i}
          className="flex items-start gap-4"
          initial={{ opacity: 0, x: -30 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.5, delay: i * 0.15 }}
        >
          {/* Timeline dot */}
          <div className="flex flex-col items-center flex-shrink-0">
            <span className="text-[10px] font-mono text-[var(--color-fg-tertiary)] mb-1">
              {entry.time}
            </span>
            <div
              className="w-3 h-3 rounded-full border-2"
              style={{
                borderColor: entry.color,
                background: `color-mix(in oklch, ${entry.color} 20%, transparent)`,
              }}
            />
            {i < entries.length - 1 && <div className="w-px h-8 bg-[var(--color-border-subtle)]" />}
          </div>

          {/* Card */}
          <div
            className="rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] px-3 py-2 flex-1"
            style={{ background: "var(--color-bg-elevated)" }}
          >
            <div className="text-sm font-medium text-[var(--color-fg-primary)]">{entry.label}</div>
            <div className="text-xs text-[var(--color-fg-secondary)] mt-0.5">{entry.desc}</div>
          </div>
        </motion.div>
      ))}
    </div>
  );
}

/* ────────────────── Project Visual ────────────────── */

function ProjectVisual() {
  const goals = [
    { name: "Launch MVP", progress: 78, color: "var(--color-agent-project)" },
    { name: "Read 24 books", progress: 54, color: "var(--color-agent-research)" },
    { name: "Exercise 4x/week", progress: 85, color: "var(--color-success-500)" },
    { name: "Clear inbox daily", progress: 62, color: "var(--color-agent-comms)" },
  ];

  return (
    <div className="space-y-5 max-w-md mx-auto">
      {goals.map((goal, i) => (
        <motion.div
          key={i}
          initial={{ opacity: 0, x: 30 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.5, delay: i * 0.12 }}
        >
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-sm font-medium text-[var(--color-fg-primary)]">{goal.name}</span>
            <span className="text-xs font-mono text-[var(--color-fg-secondary)]">
              {goal.progress}%
            </span>
          </div>
          <div
            className="h-2 rounded-full overflow-hidden"
            style={{ background: "var(--color-bg-overlay)" }}
          >
            <motion.div
              className="h-full rounded-full"
              style={{ background: goal.color }}
              initial={{ width: 0 }}
              whileInView={{ width: `${goal.progress}%` }}
              viewport={{ once: true }}
              transition={{ duration: 1, delay: 0.3 + i * 0.1, ease: "easeOut" }}
            />
          </div>
        </motion.div>
      ))}

      {/* Habit streak */}
      <motion.div
        className="mt-6 rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] p-4"
        style={{ background: "var(--color-bg-elevated)" }}
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5, delay: 0.6 }}
      >
        <div className="text-xs font-semibold text-[var(--color-fg-secondary)] mb-2 uppercase tracking-wider">
          This Week
        </div>
        <div className="flex gap-1.5">
          {["M", "T", "W", "T", "F", "S", "S"].map((day, i) => (
            <div key={i} className="flex flex-col items-center gap-1">
              <div
                className="w-7 h-7 rounded-[var(--radius-sm)] flex items-center justify-center text-[10px] font-medium"
                style={{
                  background:
                    i < 5
                      ? "var(--color-success-500)"
                      : i === 5
                        ? "var(--color-warning-500)"
                        : "var(--color-bg-overlay)",
                  color: i < 6 ? "var(--color-fg-on-accent)" : "var(--color-fg-tertiary)",
                  opacity: i === 6 ? 0.4 : 1,
                }}
              >
                {i < 5 ? "\u2713" : i === 5 ? "\u00BD" : "\u00B7"}
              </div>
              <span className="text-[9px] text-[var(--color-fg-tertiary)]">{day}</span>
            </div>
          ))}
        </div>
      </motion.div>
    </div>
  );
}

/* ────────────────── Communication Hub Visual ────────────────── */

function CommunicationVisual() {
  const emails = [
    { from: "Sarah Chen", subject: "Project Alpha update", priority: "high", time: "2h ago" },
    { from: "Newsletter", subject: "Weekly digest: AI trends", priority: "low", time: "4h ago" },
    { from: "David Park", subject: "Meeting reschedule?", priority: "medium", time: "5h ago" },
  ];

  return (
    <div className="max-w-md mx-auto space-y-3">
      {/* Email triage */}
      {emails.map((email, i) => (
        <motion.div
          key={i}
          className="rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] px-4 py-3 flex items-center gap-3"
          style={{ background: "var(--color-bg-elevated)" }}
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.4, delay: i * 0.12 }}
        >
          <div
            className="w-2 h-2 rounded-full flex-shrink-0"
            style={{
              background:
                email.priority === "high"
                  ? "var(--color-error-500)"
                  : email.priority === "medium"
                    ? "var(--color-warning-500)"
                    : "var(--color-fg-tertiary)",
            }}
          />
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-[var(--color-fg-primary)] truncate">
                {email.from}
              </span>
              <span className="text-[10px] text-[var(--color-fg-tertiary)] flex-shrink-0 ml-2">
                {email.time}
              </span>
            </div>
            <div className="text-xs text-[var(--color-fg-secondary)] truncate">{email.subject}</div>
          </div>
          <div
            className="text-[9px] font-medium uppercase px-2 py-0.5 rounded-[var(--radius-full)]"
            style={{
              background:
                email.priority === "high"
                  ? "var(--color-error-50)"
                  : email.priority === "medium"
                    ? "var(--color-warning-50)"
                    : "var(--color-bg-overlay)",
              color:
                email.priority === "high"
                  ? "var(--color-error-500)"
                  : email.priority === "medium"
                    ? "var(--color-warning-500)"
                    : "var(--color-fg-tertiary)",
            }}
          >
            {email.priority}
          </div>
        </motion.div>
      ))}

      {/* Calendar strip */}
      <motion.div
        className="mt-4 rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] p-4"
        style={{ background: "var(--color-bg-elevated)" }}
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5, delay: 0.5 }}
      >
        <div className="text-xs font-semibold text-[var(--color-fg-secondary)] mb-3 uppercase tracking-wider">
          Today's Schedule
        </div>
        <div className="space-y-2">
          {[
            { time: "09:00", event: "Team standup", dur: "30m" },
            { time: "11:00", event: "Design review", dur: "1h" },
            { time: "14:30", event: "Focus time (blocked)", dur: "2h" },
          ].map((ev, i) => (
            <div key={i} className="flex items-center gap-3">
              <span className="text-[10px] font-mono text-[var(--color-fg-tertiary)] w-10 flex-shrink-0">
                {ev.time}
              </span>
              <div
                className="h-1 w-1 rounded-full flex-shrink-0"
                style={{ background: "var(--color-agent-tools)" }}
              />
              <span className="text-xs text-[var(--color-fg-primary)]">{ev.event}</span>
              <span className="text-[10px] text-[var(--color-fg-tertiary)] ml-auto">{ev.dur}</span>
            </div>
          ))}
        </div>
      </motion.div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   LANDING PAGE
   ═══════════════════════════════════════════════════════════════ */

export function LandingPage() {
  const heroRef = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({
    target: heroRef,
    offset: ["start start", "end start"],
  });
  const heroOpacity = useTransform(scrollYProgress, [0, 1], [1, 0]);
  const heroY = useTransform(scrollYProgress, [0, 1], [0, 100]);

  const [stat1Count, stat1Ref] = useCountUp(8, 1500);
  const [stat2Count, stat2Ref] = useCountUp(0, 900);

  return (
    <div className="min-h-screen bg-[var(--color-bg-base)] text-[var(--color-fg-primary)] overflow-x-hidden">
      {/* ───── Top Nav ───── */}
      <motion.nav
        className="fixed top-0 left-0 right-0 z-50 px-6 py-3"
        style={{
          background: "var(--nav-bg)",
          backdropFilter: "blur(16px)",
          WebkitBackdropFilter: "blur(16px)",
          borderBottom: "1px solid var(--color-border-subtle)",
        }}
        initial={{ y: -60, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.6, delay: 0.2 }}
      >
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <Link to="/welcome" className="flex items-center gap-2.5 group">
            <div
              className="w-8 h-8 rounded-[var(--radius-md)] flex items-center justify-center"
              style={{
                background: "linear-gradient(135deg, oklch(0.55 0.18 250), oklch(0.5 0.2 290))",
              }}
            >
              <Brain className="w-4.5 h-4.5 text-white" />
            </div>
            <span className="text-sm font-semibold text-[var(--color-fg-primary)] group-hover:text-[var(--color-fg-secondary)] transition-colors">
              Execution OS
            </span>
          </Link>

          <div className="flex items-center gap-4">
            <a
              href="#agents"
              className="text-xs text-[var(--color-fg-secondary)] hover:text-[var(--color-fg-primary)] transition-colors hidden sm:inline"
            >
              Agents
            </a>
            <a
              href="#features"
              className="text-xs text-[var(--color-fg-secondary)] hover:text-[var(--color-fg-primary)] transition-colors hidden sm:inline"
            >
              Features
            </a>
            <a
              href="#architecture"
              className="text-xs text-[var(--color-fg-secondary)] hover:text-[var(--color-fg-primary)] transition-colors hidden sm:inline"
            >
              Architecture
            </a>
            <Link
              to="/dashboard"
              className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium rounded-[var(--radius-full)] transition-all duration-300"
              style={{
                background: "linear-gradient(135deg, oklch(0.55 0.18 250), oklch(0.5 0.2 290))",
                color: "white",
              }}
            >
              <LayoutDashboard className="w-3.5 h-3.5" />
              Dashboard
            </Link>
          </div>
        </div>
      </motion.nav>

      {/* ═══════════════════ 1. HERO ═══════════════════ */}
      <div
        ref={heroRef}
        className="relative min-h-screen flex items-center justify-center overflow-hidden"
      >
        <GradientMesh />
        <ParticleField />

        <motion.div
          className="relative z-10 text-center px-6 max-w-4xl"
          style={{ opacity: heroOpacity, y: heroY }}
        >
          {/* Badge */}
          <motion.div
            className="inline-flex items-center gap-2 mb-8 px-4 py-1.5 rounded-[var(--radius-full)]"
            style={{
              background: "var(--glass-bg)",
              backdropFilter: "blur(12px)",
              border: "1px solid var(--glass-border)",
              boxShadow: "var(--glass-shadow)",
            }}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.3 }}
          >
            <Sparkles className="w-3.5 h-3.5 text-[var(--color-info-500)]" />
            <span className="text-xs text-[var(--color-fg-secondary)]">
              Self-hosted public preview
            </span>
          </motion.div>

          {/* Title */}
          <motion.h1
            aria-label="Personal Execution OS"
            className="text-5xl sm:text-6xl md:text-7xl lg:text-8xl font-bold leading-[1.05] tracking-tight mb-6"
            initial={{ opacity: 0, y: 40 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.4 }}
          >
            <span
              style={{
                background:
                  "linear-gradient(135deg, oklch(0.55 0.2 250), oklch(0.5 0.22 280), oklch(0.55 0.18 320))",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
              }}
            >
              Your Personal
            </span>
            <br />
            <span
              style={{
                background:
                  "linear-gradient(135deg, oklch(0.55 0.2 250), oklch(0.5 0.22 280), oklch(0.55 0.18 320))",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
              }}
            >
              Execution OS
            </span>
          </motion.h1>

          {/* Subtitle */}
          <motion.p
            className="text-base sm:text-lg md:text-xl text-[var(--color-fg-secondary)] max-w-2xl mx-auto leading-relaxed mb-10"
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.6 }}
          >
            One private workspace to capture what matters, decide what is next, and review what
            changed.
          </motion.p>
          <motion.p
            className="text-xs sm:text-sm text-[var(--color-fg-tertiary)] max-w-2xl mx-auto leading-relaxed -mt-6 mb-10"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.7 }}
          >
            Core records work without an API key. Models, web search, Google data, messaging,
            telemetry, and automated evaluation are optional, disabled by default, and can send
            feature-specific data to the provider you choose.
          </motion.p>

          {/* CTA */}
          <motion.div
            className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-16"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.8 }}
          >
            <Link
              to="/dashboard"
              className="inline-flex items-center gap-2 px-8 py-3.5 text-sm font-semibold rounded-[var(--radius-full)] transition-all duration-300 hover:scale-105 hover:shadow-[0_0_30px_oklch(0.55_0.18_250_/_0.3)]"
              style={{
                background: "linear-gradient(135deg, oklch(0.55 0.18 250), oklch(0.5 0.2 290))",
                color: "white",
              }}
            >
              Go to Dashboard
              <ArrowRight className="w-4 h-4" />
            </Link>
            <a
              href="#how-it-works"
              className="inline-flex items-center gap-2 px-6 py-3.5 text-sm font-medium rounded-[var(--radius-full)] border border-[var(--color-border-default)] text-[var(--color-fg-secondary)] hover:text-[var(--color-fg-primary)] hover:border-[var(--color-border-strong)] transition-all duration-300"
              style={{ background: "var(--glass-bg)" }}
            >
              See How It Works
              <ChevronDown className="w-4 h-4" />
            </a>
          </motion.div>

          {/* Stats */}
          <motion.div
            className="flex items-center justify-center gap-8 sm:gap-16"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.8, delay: 1 }}
          >
            <div className="text-center">
              <span
                ref={stat1Ref}
                className="text-3xl sm:text-4xl font-bold text-[var(--color-fg-primary)]"
              >
                {stat1Count}
              </span>
              <p className="text-xs text-[var(--color-fg-tertiary)] mt-1">Focused Workflows</p>
            </div>
            <div className="w-px h-8 bg-[var(--color-border-subtle)]" />
            <div className="text-center">
              <span
                ref={stat2Ref}
                className="text-3xl sm:text-4xl font-bold text-[var(--color-fg-primary)]"
              >
                {stat2Count}
              </span>
              <p className="text-xs text-[var(--color-fg-tertiary)] mt-1">Required API Keys</p>
            </div>
            <div className="w-px h-8 bg-[var(--color-border-subtle)]" />
            <div className="text-center">
              <span className="text-3xl sm:text-4xl font-bold text-[var(--color-fg-primary)]">
                1
              </span>
              <p className="text-xs text-[var(--color-fg-tertiary)] mt-1">Private Owner</p>
            </div>
          </motion.div>
        </motion.div>

        {/* Scroll indicator */}
        <motion.div
          className="absolute bottom-8 left-1/2 -translate-x-1/2"
          animate={{ y: [0, 8, 0] }}
          transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
        >
          <ChevronDown className="w-5 h-5 text-[var(--color-fg-tertiary)]" />
        </motion.div>
      </div>

      {/* ═══════════════════ 2. HOW IT WORKS ═══════════════════ */}
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

      {/* ═══════════════════ 3. AGENT SHOWCASE ═══════════════════ */}
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

      {/* ═══════════════════ 4. FEATURE DEEP-DIVES ═══════════════════ */}
      <div id="features">
        {/* 4a. Intelligent Memory */}
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
                Structured search works against local records. Optional vector embeddings add
                semantic retrieval, while model-backed entity and link suggestions can enrich the
                knowledge graph when you enable them.
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
                        background:
                          "color-mix(in oklch, var(--color-agent-memory) 20%, transparent)",
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

        {/* 4b. Daily Rhythm */}
        <Section>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16 items-center">
            <motion.div
              className="order-2 lg:order-1"
              initial={{ opacity: 0, x: -40 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true, amount: 0.3 }}
              transition={{ duration: 0.7, delay: 0.2 }}
            >
              <DailyRhythmVisual />
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
                style={{ color: "var(--color-agent-diary)" }}
              >
                <Sun className="w-3.5 h-3.5" />
                Daily Rhythm
              </span>
              <h2 className="text-3xl md:text-4xl font-bold text-[var(--color-fg-primary)] mb-4 leading-tight">
                Your Day,{" "}
                <span style={{ color: "var(--color-agent-diary)" }}>Structured & Aware.</span>
              </h2>
              <p className="text-sm md:text-base text-[var(--color-fg-secondary)] leading-relaxed mb-6">
                Interstitial journaling captures thoughts between tasks, while mood and energy
                tracking makes changes visible over time. Optional briefings can combine priorities,
                calendar context, and curated material after you enable the required providers.
              </p>
              <div className="space-y-3">
                {[
                  "Optional briefings with calendar, priorities, and curated content",
                  "Interstitial journaling: capture thoughts between tasks",
                  "Mood and energy tracking with trend analysis",
                  "Progressive summarisation for long-term retrieval",
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
                        background:
                          "color-mix(in oklch, var(--color-agent-diary) 20%, transparent)",
                      }}
                    >
                      <div
                        className="w-1.5 h-1.5 rounded-full"
                        style={{ background: "var(--color-agent-diary)" }}
                      />
                    </div>
                    <span className="text-xs text-[var(--color-fg-secondary)]">{item}</span>
                  </motion.div>
                ))}
              </div>
            </motion.div>
          </div>
        </Section>

        {/* 4c. Project & Goals */}
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
                style={{ color: "var(--color-agent-project)" }}
              >
                <Target className="w-3.5 h-3.5" />
                Projects & Goals
              </span>
              <h2 className="text-3xl md:text-4xl font-bold text-[var(--color-fg-primary)] mb-4 leading-tight">
                From Vision to{" "}
                <span style={{ color: "var(--color-agent-project)" }}>Execution.</span>
              </h2>
              <p className="text-sm md:text-base text-[var(--color-fg-secondary)] leading-relaxed mb-6">
                Turn vague ambitions into structured, executable plans. Work breakdown structures
                decompose projects into actionable tasks. WSJF offers an explicit way to compare
                competing work. Habit tracking makes consistency visible over time.
              </p>
              <div className="space-y-3">
                {[
                  "Work breakdown structures for complex projects",
                  "WSJF (Weighted Shortest Job First) prioritisation",
                  "Velocity tracking to understand your real capacity",
                  "Habit streaks and goal progress visualisation",
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
                        background:
                          "color-mix(in oklch, var(--color-agent-project) 20%, transparent)",
                      }}
                    >
                      <div
                        className="w-1.5 h-1.5 rounded-full"
                        style={{ background: "var(--color-agent-project)" }}
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
              <ProjectVisual />
            </motion.div>
          </div>
        </Section>

        {/* 4d. Communication Hub */}
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
                Tame the{" "}
                <span style={{ color: "var(--color-agent-comms)" }}>Communication Flood.</span>
              </h2>
              <p className="text-sm md:text-base text-[var(--color-fg-secondary)] leading-relaxed mb-6">
                AI reads synced email context to suggest priorities and editable local response
                drafts; it does not send or change provider mail. Read-only calendar context can
                reveal free slots when a supported account is connected. Your contact workspace
                keeps follow-ups visible.
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
                        background:
                          "color-mix(in oklch, var(--color-agent-comms) 20%, transparent)",
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

        {/* 4e. Socratic Learning */}
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
                Learn by{" "}
                <span className="text-[var(--color-info-500)]">Thinking, Not Reading.</span>
              </h2>
              <p className="text-sm md:text-base text-[var(--color-fg-secondary)] leading-relaxed mb-6">
                With a model provider enabled, the Socratic workflow guides your reasoning with
                probing questions instead of simply handing you answers. Tutor, clarifier, devil's
                advocate, connector, and assessor roles structure the conversation.
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
                          msg.role === "user"
                            ? "var(--color-info-500)"
                            : "var(--color-bg-elevated)",
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
                              msg.role === "devil"
                                ? "var(--color-error-500)"
                                : "var(--color-info-500)",
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

        {/* 4f. Optional background workflows */}
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

        {/* 4g. Personal Knowledge */}
        <Section>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16 items-center">
            <motion.div
              className="order-2 lg:order-1"
              initial={{ opacity: 0, x: -40 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true, amount: 0.3 }}
              transition={{ duration: 0.7, delay: 0.2 }}
            >
              {/* Notes/commitments/decisions visual */}
              <div className="space-y-3 max-w-md mx-auto">
                {[
                  {
                    type: "Note",
                    title: "Atomic notes on distributed systems",
                    icon: "N",
                    color: "var(--color-agent-memory)",
                  },
                  {
                    type: "Commitment",
                    title: "Send proposal to Sarah by Friday",
                    icon: "C",
                    color: "var(--color-agent-notif)",
                  },
                  {
                    type: "Decision",
                    title: "Chose PostgreSQL over MongoDB -- query flexibility",
                    icon: "D",
                    color: "var(--color-agent-review)",
                  },
                  {
                    type: "Note",
                    title: "CAP theorem implies partition tolerance trade-offs",
                    icon: "N",
                    color: "var(--color-agent-memory)",
                  },
                  {
                    type: "Commitment",
                    title: "Review team OKRs before quarterly meeting",
                    icon: "C",
                    color: "var(--color-agent-notif)",
                  },
                ].map((item, i) => (
                  <motion.div
                    key={i}
                    className="flex items-center gap-3 rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] px-4 py-3"
                    style={{ background: "var(--color-bg-elevated)" }}
                    initial={{ opacity: 0, x: -20 }}
                    whileInView={{ opacity: 1, x: 0 }}
                    viewport={{ once: true }}
                    transition={{ duration: 0.4, delay: 0.2 + i * 0.1 }}
                  >
                    <div
                      className="w-7 h-7 rounded-[var(--radius-sm)] flex items-center justify-center flex-shrink-0 text-[10px] font-bold"
                      style={{
                        background: `color-mix(in oklch, ${item.color} 15%, transparent)`,
                        color: item.color,
                      }}
                    >
                      {item.icon}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div
                        className="text-[9px] font-semibold uppercase tracking-wider"
                        style={{ color: item.color }}
                      >
                        {item.type}
                      </div>
                      <div className="text-xs text-[var(--color-fg-primary)] truncate">
                        {item.title}
                      </div>
                    </div>
                  </motion.div>
                ))}
              </div>
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
                style={{ color: "var(--color-agent-memory)" }}
              >
                <StickyNote className="w-3.5 h-3.5" />
                Personal Knowledge
              </span>
              <h2 className="text-3xl md:text-4xl font-bold text-[var(--color-fg-primary)] mb-4 leading-tight">
                Notes. Commitments.{" "}
                <span style={{ color: "var(--color-agent-memory)" }}>Decisions.</span>
              </h2>
              <p className="text-sm md:text-base text-[var(--color-fg-secondary)] leading-relaxed mb-6">
                Zettelkasten atomic notes build compound knowledge over time. Commitments are stored
                explicitly and can also be suggested from conversations when a model is enabled.
                Decisions retain context for later outcome reviews, and spaced repetition can bring
                selected knowledge back into view.
              </p>
              <div className="space-y-3">
                {[
                  "Zettelkasten atomic notes with semantic linking",
                  "Optional commitment suggestions from conversations",
                  "Decision journal with outcome tracking",
                  "SM-2 spaced repetition for long-term retention",
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
                        background:
                          "color-mix(in oklch, var(--color-agent-memory) 20%, transparent)",
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
          </div>
        </Section>
      </div>

      {/* ═══════════════════ 5. ARCHITECTURE ═══════════════════ */}
      <Section id="architecture">
        <SectionHeading
          label="Under the Hood"
          title="An Inspectable Local Data Flow"
          description="Inputs move through explicit routes and focused workflows into PostgreSQL. Vector search and external providers remain optional."
        />
        <ArchitectureDiagram />
      </Section>

      {/* ═══════════════════ 6. PHILOSOPHY ═══════════════════ */}
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
                  <div className="text-xs text-[var(--color-fg-tertiary)] mb-3">
                    {phil.subtitle}
                  </div>
                  <p className="text-xs text-[var(--color-fg-secondary)] leading-relaxed">
                    {phil.description}
                  </p>
                </GlassCard>
              </motion.div>
            ))}
          </div>
        </div>
      </Section>

      {/* ═══════════════════ 7. TECH STACK ═══════════════════ */}
      <Section>
        <SectionHeading
          label="Built With"
          title="A Modern, Inspectable Stack"
          description="Pinned containers, typed application boundaries, automated tests, and documented trust boundaries support a cautious self-hosted preview."
        />

        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3 md:gap-4">
          {techStack.map((tech, i) => (
            <motion.div
              key={tech.name}
              className="rounded-[var(--radius-lg)] border border-[var(--color-border-subtle)] p-4 text-center"
              style={{ background: "var(--color-bg-surface)" }}
              initial={{ opacity: 0, scale: 0.9 }}
              whileInView={{ opacity: 1, scale: 1 }}
              viewport={{ once: true, amount: 0.2 }}
              transition={{ duration: 0.4, delay: i * 0.05 }}
              whileHover={{
                y: -2,
                borderColor: "var(--color-border-strong)",
                transition: { duration: 0.2 },
              }}
            >
              <div className="text-sm font-semibold text-[var(--color-fg-primary)] mb-0.5">
                {tech.name}
              </div>
              <div className="text-[10px] text-[var(--color-fg-tertiary)]">{tech.label}</div>
            </motion.div>
          ))}
        </div>

        {/* Key principles */}
        <motion.div
          className="mt-12 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.2 }}
          transition={{ duration: 0.6, delay: 0.3 }}
        >
          {[
            {
              icon: Shield,
              label: "Local by Default",
              desc: "Enabled providers receive only feature-specific data",
            },
            { icon: Zap, label: "Fail Fast", desc: "No silent degradation, clear errors" },
            { icon: GitBranch, label: "Checked Changes", desc: "Lint, tests, audits, and CI" },
            { icon: Database, label: "Observable", desc: "Opt-in evaluation and monitoring" },
          ].map((principle) => (
            <div
              key={principle.label}
              className="flex items-start gap-3 rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] p-4"
              style={{ background: "var(--color-bg-elevated)" }}
            >
              <principle.icon className="w-4 h-4 text-[var(--color-fg-tertiary)] flex-shrink-0 mt-0.5" />
              <div>
                <div className="text-xs font-semibold text-[var(--color-fg-primary)]">
                  {principle.label}
                </div>
                <div className="text-[11px] text-[var(--color-fg-tertiary)]">{principle.desc}</div>
              </div>
            </div>
          ))}
        </motion.div>
      </Section>

      {/* ═══════════════════ 8. FOOTER CTA ═══════════════════ */}
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

      {/* ───── Footer ───── */}
      <footer className="border-t border-[var(--color-border-subtle)] py-8 px-6">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <div
              className="w-6 h-6 rounded-[var(--radius-sm)] flex items-center justify-center"
              style={{
                background: "linear-gradient(135deg, oklch(0.55 0.18 250), oklch(0.5 0.2 290))",
              }}
            >
              <Brain className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="text-xs text-[var(--color-fg-tertiary)]">
              Personal Execution OS -- self-hosted workspace
            </span>
          </div>

          <div className="flex items-center gap-6">
            <Link
              to="/dashboard"
              className="text-xs text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-secondary)] transition-colors"
            >
              Dashboard
            </Link>
            <Link
              to="/settings"
              className="text-xs text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-secondary)] transition-colors"
            >
              Settings
            </Link>
            {sourceRepositoryUrl && (
              <a
                href={sourceRepositoryUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-secondary)] transition-colors"
              >
                Source
                <ExternalLink className="w-3 h-3" />
              </a>
            )}
          </div>
        </div>
      </footer>
    </div>
  );
}
