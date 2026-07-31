import { useEffect, useState } from "react";
import { ArrowUpDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

interface SortMenuOption<T extends string> {
  value: T;
  label: string;
}

interface SortMenuProps<T extends string> {
  value: T;
  options: SortMenuOption<T>[];
  onChange: (value: T) => void;
  buttonLabel: string;
  buttonAriaLabel: string;
  menuLabel?: string;
  widthClassName?: string;
}

function SortMenu<T extends string>({
  value,
  options,
  onChange,
  buttonLabel,
  buttonAriaLabel,
  menuLabel = "Sort options",
  widthClassName = "w-44",
}: SortMenuProps<T>) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  return (
    <div className="relative">
      <Button
        variant="outline"
        size="sm"
        className="gap-1.5"
        onClick={() => setOpen((prev) => !prev)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={buttonAriaLabel}
      >
        <ArrowUpDown className="h-3.5 w-3.5" />
        {buttonLabel}
      </Button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div
            className={cn(
              "absolute right-0 top-full z-50 mt-1 rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-1 shadow-lg",
              widthClassName,
            )}
            role="listbox"
            aria-label={menuLabel}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setOpen(false);
              }
            }}
          >
            {options.map((opt) => (
              <button
                key={opt.value}
                role="option"
                aria-selected={value === opt.value}
                className={cn(
                  "w-full rounded-[var(--radius-sm)] px-3 py-1.5 text-left text-sm transition-colors",
                  value === opt.value
                    ? "bg-[var(--color-bg-overlay)] text-[var(--color-fg-primary)]"
                    : "text-[var(--color-fg-secondary)] hover:bg-[var(--color-bg-elevated)]",
                )}
                onClick={() => {
                  onChange(opt.value);
                  setOpen(false);
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export { SortMenu };
export type { SortMenuOption, SortMenuProps };
