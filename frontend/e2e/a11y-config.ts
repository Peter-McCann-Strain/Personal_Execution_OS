/**
 * Curated list of Axe rule exemptions for the Brain UI.
 *
 * Only add a rule here with a clear rationale. Each exemption should be
 * re-reviewed when the design system changes. Prefer fixing the underlying
 * issue over adding an exemption.
 *
 * NOTE: `selectors` is applied via `.exclude(selector)` on AxeBuilder so the
 * exemption only affects the specific offending region, not the whole page.
 */
export interface AxeExemption {
  /** Axe rule id (e.g. "color-contrast"). */
  rule: string;
  /** CSS selectors for the regions to exclude from this rule. Empty = disable globally. */
  selectors: string[];
  /** Why we are accepting this violation. */
  rationale: string;
}

export const AXE_EXEMPTIONS: AxeExemption[] = [
  {
    rule: "color-contrast",
    selectors: ["[data-brain-logo]", ".brain-logo-gradient"],
    rationale:
      "Branded Brain logo uses a gradient that falls just below AA on the deepest background. Decorative / marketing element — text equivalent is present in the header title.",
  },
  {
    rule: "color-contrast",
    selectors: ["[data-sparkline] *", ".recharts-cartesian-axis-tick-value"],
    rationale:
      "Sparklines and chart axis ticks use intentionally muted tones; data is surfaced via tooltips and aria-label summaries on the parent chart.",
  },
  {
    rule: "landmark-unique",
    selectors: [".sonner-toast-container"],
    rationale:
      "Sonner toast library injects an additional `status` landmark at the root. We keep the default so screen readers announce toasts; the duplicate is an upstream quirk.",
  },
  {
    rule: "region",
    selectors: [],
    rationale:
      "Globally disabled: the AppLayout deliberately renders floating status overlays (stream bridge, notification bridge) outside traditional landmarks. Their content is announced via aria-live regions.",
  },
];

/** Rule ids that are fully disabled (no selector-based exclusion). */
export const GLOBAL_DISABLED_RULES: string[] = AXE_EXEMPTIONS.filter(
  (e) => e.selectors.length === 0,
).map((e) => e.rule);

/** Selectors to pass to AxeBuilder.exclude() before analyse. */
export const EXCLUDE_SELECTORS: string[] = AXE_EXEMPTIONS.filter(
  (e) => e.selectors.length > 0,
).flatMap((e) => e.selectors);
