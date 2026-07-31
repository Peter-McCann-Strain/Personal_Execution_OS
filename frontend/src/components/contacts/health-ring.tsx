import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { getHealthColor } from "./health-ring.utils";

interface HealthRingProps {
  score: number;
  size?: number;
  strokeWidth?: number;
  className?: string;
  showLabel?: boolean;
}

function HealthRing({
  score,
  size = 48,
  strokeWidth = 4,
  className,
  showLabel = true,
}: HealthRingProps) {
  const [animatedScore, setAnimatedScore] = useState(0);
  const rafRef = useRef<number>(0);
  const startRef = useRef<number | null>(null);

  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const clampedScore = Math.max(0, Math.min(100, score ?? 0));

  useEffect(() => {
    startRef.current = null;
    const duration = 600;

    function animate(timestamp: number) {
      if (startRef.current === null) startRef.current = timestamp;
      const elapsed = timestamp - startRef.current;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setAnimatedScore(eased * clampedScore);
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(animate);
      }
    }

    rafRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafRef.current);
  }, [clampedScore]);

  const offset = circumference * (1 - animatedScore / 100);
  const color = getHealthColor(clampedScore);
  const fontSize = size < 40 ? 10 : size < 64 ? 12 : 16;

  return (
    <div className={cn("relative inline-flex items-center justify-center", className)}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--color-border-subtle)"
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: "stroke 0.3s ease" }}
        />
      </svg>
      {showLabel && (
        <span
          className="absolute font-semibold text-[var(--color-fg-primary)]"
          style={{ fontSize }}
        >
          {Math.round(clampedScore)}
        </span>
      )}
    </div>
  );
}

export { HealthRing };
export type { HealthRingProps };
