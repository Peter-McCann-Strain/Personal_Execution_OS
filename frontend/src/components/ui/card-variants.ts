import { cva } from "class-variance-authority";

const cardVariants = cva(
  "rounded-[var(--radius-lg)] border border-[var(--color-border-default)] transition-colors",
  {
    variants: {
      variant: {
        default: "bg-[var(--color-bg-surface)]",
        elevated: "bg-[var(--color-bg-elevated)]",
      },
      padding: {
        none: "",
        sm: "p-3",
        md: "p-4",
        lg: "p-6",
      },
      hoverable: {
        true: "hover:border-[var(--color-border-strong)] hover:bg-[var(--color-bg-elevated)] cursor-pointer",
        false: "",
      },
    },
    defaultVariants: {
      variant: "default",
      padding: "md",
      hoverable: false,
    },
  },
);

export { cardVariants };
