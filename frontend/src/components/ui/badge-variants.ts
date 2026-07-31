import { cva } from "class-variance-authority";

const badgeVariants = cva(
  "inline-flex items-center font-medium whitespace-nowrap rounded-[var(--radius-full)] border transition-colors",
  {
    variants: {
      variant: {
        default:
          "border-[var(--color-border-default)] bg-[var(--color-bg-overlay)] text-[var(--color-fg-secondary)]",
        success:
          "border-[var(--color-success-500)]/30 bg-[var(--color-success-50)] text-[var(--color-success-900)]",
        warning:
          "border-[var(--color-warning-500)]/30 bg-[var(--color-warning-50)] text-[var(--color-warning-900)]",
        error:
          "border-[var(--color-error-500)]/30 bg-[var(--color-error-50)] text-[var(--color-error-900)]",
        info: "border-[var(--color-info-500)]/30 bg-[var(--color-info-50)] text-[var(--color-info-900)]",
      },
      size: {
        sm: "px-1.5 py-0.5 text-[10px] leading-tight",
        md: "px-2 py-0.5 text-xs",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "md",
    },
  },
);

export { badgeVariants };
