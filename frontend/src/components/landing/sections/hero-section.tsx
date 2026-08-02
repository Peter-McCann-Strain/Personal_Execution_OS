import { useRef } from "react";
import { Link } from "react-router";
import { motion, useScroll, useTransform } from "motion/react";
import { ArrowRight, ChevronDown, Sparkles } from "lucide-react";

import { GradientMesh, ParticleField } from "../primitives";
import { useCountUp } from "../use-count-up";

export function HeroSection() {
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
            <span className="text-3xl sm:text-4xl font-bold text-[var(--color-fg-primary)]">1</span>
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
  );
}
