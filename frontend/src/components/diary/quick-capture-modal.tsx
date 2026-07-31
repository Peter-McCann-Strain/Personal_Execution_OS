import { useState, useEffect, useRef, useCallback } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X, Loader2 } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { sendChatMessage } from "@/api/chat";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatShortcut, MOD_KEY } from "@/lib/platform";

interface QuickCaptureModalProps {
  externalOpen?: boolean;
  onExternalOpenChange?: (open: boolean) => void;
}

export function QuickCaptureModal({
  externalOpen,
  onExternalOpenChange,
}: QuickCaptureModalProps = {}) {
  const [internalOpen, setInternalOpen] = useState(false);
  const open = externalOpen ?? internalOpen;
  const setOpen = onExternalOpenChange ?? setInternalOpen;
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (content: string) => sendChatMessage(content, "api"),
    onSuccess: (response) => {
      setText("");
      setOpen(false);
      queryClient.invalidateQueries({ queryKey: ["recentDiary"] });
      queryClient.invalidateQueries({ queryKey: ["episodes"] });

      const meta = response.metadata ?? {};
      const mood = meta.mood_score as number | undefined;
      const energy = meta.energy_rating as number | undefined;
      const para = meta.para_category as string | undefined;
      const tags = (meta.tags as string[] | undefined) ?? [];

      toast.success("Entry captured!", {
        description:
          [
            mood != null ? `Mood: ${Number(mood).toFixed(1)}` : null,
            energy != null ? `Energy: ${Number(energy).toFixed(1)}` : null,
            para ? `PARA: ${para}` : null,
            tags.length > 0 ? `Tags: ${tags.join(", ")}` : null,
          ]
            .filter(Boolean)
            .join("  |  ") || "Processing complete.",
        duration: 5000,
      });
    },
    onError: (error) => {
      const message =
        error instanceof Error ? error.message : "Diary capture failed with an unknown error.";
      toast.error(message);
    },
  });

  // Cmd+N global shortcut
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "n") {
        e.preventDefault();
        setOpen(true);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [setOpen]);

  // Focus textarea on open
  useEffect(() => {
    if (open && textareaRef.current) {
      setTimeout(() => textareaRef.current?.focus(), 50);
    }
  }, [open]);

  // Auto-resize textarea
  const handleTextChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 288)}px`; // max ~12 rows
  }, []);

  // Cmd+Enter to submit
  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handleSubmit();
    }
  }

  function handleSubmit() {
    const trimmed = text.trim();
    if (!trimmed || mutation.isPending) return;
    mutation.mutate(trimmed);
  }

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      {/* FAB trigger */}
      <Dialog.Trigger asChild>
        <button
          className={cn(
            "fixed bottom-6 right-6 z-50 flex h-14 w-14 items-center justify-center",
            "rounded-full bg-[var(--color-info-500)] text-[var(--color-fg-on-accent)]",
            "shadow-lg transition-transform duration-150",
            "hover:scale-105 hover:shadow-xl active:scale-95",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-border-focus)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--color-bg-base)]",
            "cursor-pointer",
          )}
          aria-label={`Quick capture (${formatShortcut("Mod+N")})`}
        >
          <svg
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>
      </Dialog.Trigger>

      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50 data-[state=open]:animate-in data-[state=open]:fade-in data-[state=closed]:animate-out data-[state=closed]:fade-out" />
        <Dialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-50 w-full max-w-[560px] -translate-x-1/2 -translate-y-1/2",
            "rounded-[var(--radius-xl)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] shadow-xl",
            "data-[state=open]:animate-in data-[state=open]:fade-in data-[state=open]:zoom-in-95",
            "data-[state=closed]:animate-out data-[state=closed]:fade-out data-[state=closed]:zoom-out-95",
          )}
        >
          {/* Header */}
          <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-6 py-4">
            <Dialog.Title className="text-base font-semibold text-[var(--color-fg-primary)]">
              What&apos;s on your mind?
            </Dialog.Title>
            <Dialog.Close asChild>
              <button
                className="text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)] transition-colors cursor-pointer"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">
            Capture a quick diary entry to send through the assistant pipeline.
          </Dialog.Description>

          {/* Body */}
          <div className="px-6 py-4">
            <textarea
              ref={textareaRef}
              value={text}
              onChange={handleTextChange}
              onKeyDown={handleKeyDown}
              placeholder="Type anything..."
              rows={3}
              disabled={mutation.isPending}
              className={cn(
                "w-full resize-none rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)]",
                "px-3 py-2 text-sm text-[var(--color-fg-primary)]",
                "placeholder:text-[var(--color-fg-tertiary)]",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-border-focus)]",
                "disabled:opacity-50",
              )}
            />
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between border-t border-[var(--color-border-subtle)] px-6 py-3">
            <Button
              onClick={handleSubmit}
              disabled={!text.trim() || mutation.isPending}
              loading={mutation.isPending}
            >
              {mutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Processing...
                </>
              ) : (
                "Capture"
              )}
            </Button>
            <kbd className="text-[10px] font-mono text-[var(--color-fg-tertiary)] rounded border border-[var(--color-border-subtle)] bg-[var(--color-bg-overlay)] px-1.5 py-0.5">
              {MOD_KEY}+Enter to submit
            </kbd>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
