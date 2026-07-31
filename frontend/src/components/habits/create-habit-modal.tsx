import { useState, useCallback } from "react";
import { X, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { CreateHabitData, HabitFrequency } from "@/api/habits";

// ─── Frequency Options ─────────────────────────────────────

const FREQUENCY_OPTIONS: { value: HabitFrequency; label: string }[] = [
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
  { value: "custom", label: "Custom" },
];

// ─── Create Habit Modal ────────────────────────────────────

interface CreateHabitModalProps {
  open: boolean;
  onClose: () => void;
  onCreate: (data: CreateHabitData) => void;
  isCreating?: boolean;
}

function CreateHabitModal({ open, onClose, onCreate, isCreating }: CreateHabitModalProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [frequency, setFrequency] = useState<HabitFrequency>("daily");
  const [frequencyDays, setFrequencyDays] = useState<string>("");
  const [tagInput, setTagInput] = useState("");
  const [tags, setTags] = useState<string[]>([]);

  const reset = useCallback(() => {
    setName("");
    setDescription("");
    setFrequency("daily");
    setFrequencyDays("");
    setTagInput("");
    setTags([]);
  }, []);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [onClose, reset]);

  const addTag = useCallback(() => {
    const tag = tagInput.trim().toLowerCase();
    if (tag && !tags.includes(tag)) {
      setTags((prev) => [...prev, tag]);
    }
    setTagInput("");
  }, [tagInput, tags]);

  const removeTag = useCallback((tag: string) => {
    setTags((prev) => prev.filter((t) => t !== tag));
  }, []);

  const handleTagKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addTag();
      }
      if (e.key === "Backspace" && tagInput === "" && tags.length > 0) {
        setTags((prev) => prev.slice(0, -1));
      }
    },
    [addTag, tagInput, tags],
  );

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!name.trim()) return;

      const data: CreateHabitData = {
        name: name.trim(),
      };
      if (description.trim()) data.description = description.trim();
      if (frequency !== "daily") data.frequency = frequency;
      if (frequency === "custom" && frequencyDays) {
        data.frequency = "custom";
        data.frequency_days = Number(frequencyDays);
      } else if (frequency !== "daily") {
        data.frequency = frequency;
      }
      if (tags.length > 0) data.tags = tags;

      onCreate(data);
    },
    [name, description, frequency, frequencyDays, tags, onCreate],
  );

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={handleClose} />

      {/* Modal */}
      <div className="relative z-10 mx-4 w-full max-w-md rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-5 py-4">
          <h2 className="text-base font-semibold text-[var(--color-fg-primary)]">New Habit</h2>
          <button
            type="button"
            onClick={handleClose}
            className="rounded-[var(--radius-md)] p-1.5 text-[var(--color-fg-tertiary)] transition-colors hover:bg-[var(--color-bg-overlay)] hover:text-[var(--color-fg-primary)]"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4 px-5 py-4">
          {/* Name */}
          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
              Name <span className="text-[var(--color-error-500)]">*</span>
            </label>
            <Input
              placeholder="e.g. Morning meditation"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              required
            />
          </div>

          {/* Description */}
          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
              Description
            </label>
            <textarea
              placeholder="Optional description..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              className={cn(
                "flex w-full rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 py-2 text-sm text-[var(--color-fg-primary)] shadow-sm transition-colors",
                "placeholder:text-[var(--color-fg-tertiary)]",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-border-focus)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-bg-base)]",
                "resize-none",
              )}
            />
          </div>

          {/* Frequency */}
          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
              Frequency
            </label>
            <div className="flex items-center gap-1.5">
              {FREQUENCY_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setFrequency(opt.value)}
                  className={cn(
                    "rounded-[var(--radius-full)] px-3 py-1.5 text-xs font-medium transition-colors",
                    frequency === opt.value
                      ? "bg-[var(--color-info-500)] text-[var(--color-fg-on-accent)]"
                      : "bg-[var(--color-bg-overlay)] text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)]",
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            {/* Custom frequency days */}
            {frequency === "custom" && (
              <div className="mt-2 flex items-center gap-2">
                <span className="text-xs text-[var(--color-fg-tertiary)]">Every</span>
                <Input
                  type="number"
                  min={1}
                  max={365}
                  placeholder="N"
                  value={frequencyDays}
                  onChange={(e) => setFrequencyDays(e.target.value)}
                  className="w-20"
                />
                <span className="text-xs text-[var(--color-fg-tertiary)]">days</span>
              </div>
            )}
          </div>

          {/* Tags */}
          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
              Tags
            </label>
            <div className="flex flex-wrap items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-2 py-1.5">
              {tags.map((tag) => (
                <span
                  key={tag}
                  className="inline-flex items-center gap-1 rounded-[var(--radius-full)] bg-[var(--color-bg-overlay)] px-2 py-0.5 text-xs font-medium text-[var(--color-fg-secondary)]"
                >
                  {tag}
                  <button
                    type="button"
                    onClick={() => removeTag(tag)}
                    className="ml-0.5 text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)]"
                    aria-label={`Remove tag ${tag}`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
              <input
                type="text"
                placeholder={tags.length === 0 ? "Add tags..." : ""}
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={handleTagKeyDown}
                onBlur={addTag}
                className="min-w-[60px] flex-1 bg-transparent py-0.5 text-xs text-[var(--color-fg-primary)] placeholder:text-[var(--color-fg-tertiary)] focus:outline-none"
              />
            </div>
            <p className="mt-1 text-[10px] text-[var(--color-fg-tertiary)]">
              Press Enter to add a tag
            </p>
          </div>
        </form>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-[var(--color-border-subtle)] px-5 py-3">
          <Button variant="ghost" size="sm" onClick={handleClose} disabled={isCreating}>
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={handleSubmit}
            disabled={!name.trim() || isCreating}
            loading={isCreating}
          >
            <Plus className="h-4 w-4" />
            Create Habit
          </Button>
        </div>
      </div>
    </div>
  );
}

export { CreateHabitModal };
export type { CreateHabitModalProps };
