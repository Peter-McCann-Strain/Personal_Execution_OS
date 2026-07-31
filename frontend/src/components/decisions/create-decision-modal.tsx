import { useState, useCallback } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import { Plus, X, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createDecision } from "@/api/decisions";
import type { CreateDecisionData } from "@/api/decisions";

// ─── Chip Input (tags) ─────────────────────────────────────

function ChipInput({
  items,
  onAdd,
  onRemove,
  placeholder,
  label,
}: {
  items: string[];
  onAdd: (item: string) => void;
  onRemove: (item: string) => void;
  placeholder?: string;
  label: string;
}) {
  function handleAdd(input: string) {
    const value = input.trim();
    if (value && !items.includes(value)) {
      onAdd(value);
    }
  }

  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
        {label}
      </label>
      <div className="flex gap-2">
        <Input
          placeholder={placeholder}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleAdd(e.currentTarget.value);
              e.currentTarget.value = "";
            }
          }}
        />
        <Button
          variant="outline"
          size="sm"
          type="button"
          onClick={(e) => {
            const input = e.currentTarget.previousElementSibling as HTMLInputElement;
            handleAdd(input.value);
            input.value = "";
          }}
        >
          Add
        </Button>
      </div>
      {items.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {items.map((item) => (
            <span
              key={item}
              className="inline-flex items-center gap-1 rounded-[var(--radius-full)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-2 py-0.5 text-xs text-[var(--color-fg-secondary)]"
            >
              {item}
              <button
                type="button"
                onClick={() => onRemove(item)}
                className="text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)]"
                aria-label={`Remove ${item}`}
              >
                &times;
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Dynamic List Input (options considered) ───────────────

function DynamicListInput({
  items,
  onChange,
  label,
  placeholder,
}: {
  items: string[];
  onChange: (items: string[]) => void;
  label: string;
  placeholder?: string;
}) {
  const handleAdd = useCallback(() => {
    onChange([...items, ""]);
  }, [items, onChange]);

  const handleUpdate = useCallback(
    (index: number, value: string) => {
      const updated = [...items];
      updated[index] = value;
      onChange(updated);
    },
    [items, onChange],
  );

  const handleRemove = useCallback(
    (index: number) => {
      onChange(items.filter((_, i) => i !== index));
    },
    [items, onChange],
  );

  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
        {label}
      </label>
      <div className="space-y-2">
        {items.map((item, index) => (
          <div key={index} className="flex items-center gap-2">
            <Input
              value={item}
              onChange={(e) => handleUpdate(index, e.target.value)}
              placeholder={placeholder ?? `Option ${index + 1}`}
            />
            <button
              type="button"
              onClick={() => handleRemove(index)}
              className="shrink-0 rounded-[var(--radius-sm)] p-1.5 text-[var(--color-fg-tertiary)] hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-error-500)] transition-colors"
              aria-label={`Remove option ${index + 1}`}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={handleAdd}
          className="flex items-center gap-1.5 text-xs font-medium text-[var(--color-info-500)] hover:underline"
        >
          <Plus className="h-3.5 w-3.5" />
          Add option
        </button>
      </div>
    </div>
  );
}

// ─── Create Decision Modal ─────────────────────────────────

interface CreateDecisionModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function CreateDecisionModal({ open, onOpenChange }: CreateDecisionModalProps) {
  const queryClient = useQueryClient();

  const [title, setTitle] = useState("");
  const [decisionMade, setDecisionMade] = useState("");
  const [context, setContext] = useState("");
  const [optionsConsidered, setOptionsConsidered] = useState<string[]>([]);
  const [reasoning, setReasoning] = useState("");
  const [expectedOutcome, setExpectedOutcome] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [reviewDate, setReviewDate] = useState("");

  function resetForm() {
    setTitle("");
    setDecisionMade("");
    setContext("");
    setOptionsConsidered([]);
    setReasoning("");
    setExpectedOutcome("");
    setTags([]);
    setReviewDate("");
  }

  const mutation = useMutation({
    mutationFn: (data: CreateDecisionData) => createDecision(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["decisions"] });
      queryClient.invalidateQueries({ queryKey: ["decisions-due-review"] });
      toast.success("Decision recorded");
      resetForm();
      onOpenChange(false);
    },
    onError: () => {
      toast.error("Failed to create decision");
    },
  });

  function handleSubmit() {
    const data: CreateDecisionData = {
      title: title.trim(),
      decision_made: decisionMade.trim(),
    };

    if (context.trim()) data.context = context.trim();
    const filteredOptions = optionsConsidered.filter((o) => o.trim());
    if (filteredOptions.length > 0) data.options_considered = filteredOptions;
    if (reasoning.trim()) data.reasoning = reasoning.trim();
    if (expectedOutcome.trim()) data.expected_outcome = expectedOutcome.trim();
    if (tags.length > 0) data.tags = tags;
    if (reviewDate) data.review_date = reviewDate;

    mutation.mutate(data);
  }

  const isValid = title.trim().length > 0 && decisionMade.trim().length > 0;

  const textareaClasses = cn(
    "w-full resize-none rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)]",
    "px-3 py-2 text-sm text-[var(--color-fg-primary)]",
    "placeholder:text-[var(--color-fg-tertiary)]",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-border-focus)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-bg-base)]",
  );

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-full max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-[var(--radius-xl)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] shadow-2xl focus:outline-none">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-6 py-4">
            <Dialog.Title className="text-base font-semibold text-[var(--color-fg-primary)]">
              New Decision
            </Dialog.Title>
            <Dialog.Close asChild>
              <button
                className="rounded-[var(--radius-sm)] p-1.5 text-[var(--color-fg-tertiary)] hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-fg-primary)] transition-colors"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">
            Record a decision, why it was made, and the outcomes you want to review later.
          </Dialog.Description>

          {/* Body */}
          <div className="flex max-h-[70vh] flex-col gap-4 overflow-y-auto px-6 py-4">
            {/* Title */}
            <div>
              <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                Title <span className="text-[var(--color-error-500)]">*</span>
              </label>
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="What decision are you making?"
              />
            </div>

            {/* Decision Made */}
            <div>
              <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                Decision Made <span className="text-[var(--color-error-500)]">*</span>
              </label>
              <textarea
                value={decisionMade}
                onChange={(e) => setDecisionMade(e.target.value)}
                placeholder="What did you decide?"
                rows={3}
                className={textareaClasses}
              />
            </div>

            {/* Context */}
            <div>
              <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                Context
              </label>
              <textarea
                value={context}
                onChange={(e) => setContext(e.target.value)}
                placeholder="What circumstances led to this decision?"
                rows={2}
                className={textareaClasses}
              />
            </div>

            {/* Options Considered */}
            <DynamicListInput
              items={optionsConsidered}
              onChange={setOptionsConsidered}
              label="Options Considered"
              placeholder="Describe an option..."
            />

            {/* Reasoning */}
            <div>
              <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                Reasoning
              </label>
              <textarea
                value={reasoning}
                onChange={(e) => setReasoning(e.target.value)}
                placeholder="Why did you make this choice?"
                rows={3}
                className={textareaClasses}
              />
            </div>

            {/* Expected Outcome */}
            <div>
              <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                Expected Outcome
              </label>
              <textarea
                value={expectedOutcome}
                onChange={(e) => setExpectedOutcome(e.target.value)}
                placeholder="What do you expect will happen?"
                rows={2}
                className={textareaClasses}
              />
            </div>

            {/* Tags */}
            <ChipInput
              items={tags}
              onAdd={(tag) => setTags([...tags, tag])}
              onRemove={(tag) => setTags(tags.filter((t) => t !== tag))}
              label="Tags"
              placeholder="Add a tag..."
            />

            {/* Review Date */}
            <div>
              <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                Review Date
              </label>
              <Input
                type="date"
                value={reviewDate}
                onChange={(e) => setReviewDate(e.target.value)}
              />
              <p className="mt-1 text-[10px] text-[var(--color-fg-tertiary)]">
                When should you revisit this decision to evaluate the outcome?
              </p>
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 border-t border-[var(--color-border-subtle)] px-6 py-4">
            <Dialog.Close asChild>
              <Button variant="ghost">Cancel</Button>
            </Dialog.Close>
            <Button disabled={!isValid} loading={mutation.isPending} onClick={handleSubmit}>
              Create Decision
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export { CreateDecisionModal };
export type { CreateDecisionModalProps };
