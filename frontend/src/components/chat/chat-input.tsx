import { useRef, useCallback, type KeyboardEvent, type ChangeEvent, type FormEvent } from "react";
import { Send, Square } from "lucide-react";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSend: (content: string) => void;
  onStop?: () => void;
  isStreaming: boolean;
  value: string;
  onChange: (value: string) => void;
}

const MAX_HEIGHT = 200;

export function ChatInput({ onSend, onStop, isStreaming, value, onChange }: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const resizeTextarea = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
  }, []);

  const handleChange = useCallback(
    (e: ChangeEvent<HTMLTextAreaElement>) => {
      onChange(e.target.value);
      resizeTextarea();
    },
    [onChange, resizeTextarea],
  );

  const handleSubmit = useCallback(
    (e?: FormEvent) => {
      e?.preventDefault();
      const trimmed = value.trim();
      if (!trimmed || isStreaming) return;
      onSend(trimmed);
      onChange("");
      // Reset textarea height after send
      requestAnimationFrame(() => {
        const el = textareaRef.current;
        if (el) {
          el.style.height = "auto";
        }
      });
    },
    [value, isStreaming, onSend, onChange],
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit],
  );

  const handleStopClick = useCallback(() => {
    onStop?.();
  }, [onStop]);

  const canSend = value.trim().length > 0 && !isStreaming;

  return (
    <div className="border-t border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] px-4 py-3">
      <form onSubmit={handleSubmit} className="mx-auto flex max-w-[720px] items-end gap-3">
        <div className="relative flex-1">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            placeholder="Ask anything..."
            disabled={isStreaming}
            rows={1}
            className={cn(
              "w-full resize-none rounded-xl border border-[var(--color-border-default)] bg-[var(--color-bg-base)] px-4 py-3 text-sm text-[var(--color-fg-primary)] outline-none",
              "placeholder:text-[var(--color-fg-tertiary)]",
              "focus:border-[var(--color-border-focus)] focus:ring-2 focus:ring-[var(--color-border-focus)]/30",
              "disabled:cursor-not-allowed disabled:opacity-60",
            )}
            style={{
              maxHeight: `${MAX_HEIGHT}px`,
              minHeight: "44px",
              transition: "height 100ms ease-out, border-color 150ms ease, box-shadow 150ms ease",
            }}
          />
        </div>

        {isStreaming ? (
          <button
            type="button"
            onClick={handleStopClick}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[var(--color-error-500)] text-[var(--color-fg-on-accent)] transition-all hover:opacity-90"
            aria-label="Stop generation"
          >
            <Square className="h-4 w-4" />
          </button>
        ) : (
          <button
            type="submit"
            disabled={!canSend}
            className={cn(
              "flex h-11 w-11 shrink-0 items-center justify-center rounded-xl transition-all",
              "disabled:cursor-not-allowed",
              canSend
                ? "bg-[var(--color-info-500)] text-[var(--color-fg-on-accent)]"
                : "bg-[var(--color-bg-elevated)] text-[var(--color-fg-disabled)]",
            )}
            aria-label="Send message"
          >
            <Send className="h-4 w-4" />
          </button>
        )}
      </form>
    </div>
  );
}
