import { useState, type ReactNode } from "react";
import { motion } from "motion/react";

function seededRandom(seed: number): number {
  const x = Math.sin(seed * 12.9898) * 43758.5453;
  return x - Math.floor(x);
}

/* Floating particle background */
export function ParticleField() {
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
export function GradientMesh() {
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
export function Section({
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
export function SectionHeading({
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
export function GlassCard({
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
