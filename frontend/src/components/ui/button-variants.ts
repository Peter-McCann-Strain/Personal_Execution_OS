import { cva } from "class-variance-authority";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-md)] text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-border-focus)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--color-bg-base)] disabled:pointer-events-none disabled:opacity-50 cursor-pointer",
  {
    variants: {
      variant: {
        default:
          "bg-[var(--color-info-500)] text-[var(--color-fg-on-accent)] hover:bg-[var(--color-info-600)]",
        ghost:
          "text-[var(--color-fg-secondary)] hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-fg-primary)]",
        outline:
          "border border-[var(--color-border-default)] text-[var(--color-fg-secondary)] hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-fg-primary)]",
        destructive:
          "bg-[var(--color-error-500)] text-[var(--color-fg-on-accent)] hover:bg-[var(--color-error-600)]",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-9 px-4 text-sm",
        lg: "h-10 px-6 text-sm",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "md",
    },
  },
);

export { buttonVariants };
