function getHealthColor(score: number): string {
  if (score >= 80) return "var(--color-success-500)";
  if (score >= 50) return "var(--color-warning-500)";
  if (score >= 20) return "oklch(0.65 0.18 55)";
  return "var(--color-error-500)";
}

export { getHealthColor };
