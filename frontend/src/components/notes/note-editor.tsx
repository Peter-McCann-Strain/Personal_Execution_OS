import { useCallback, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Save, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createNote, updateNote } from "@/api/notes";
import type { CreateNoteData, UpdateNoteData } from "@/api/notes";
import type { Note, NoteKind, NoteType, ParaCategory } from "@/types";

interface NoteEditorProps {
  note?: Note;
  onClose: () => void;
  onSaved: (note: Note) => void;
}

const NOTE_TYPES: { value: NoteType; label: string }[] = [
  { value: "fleeting", label: "Fleeting" },
  { value: "literature", label: "Literature" },
  { value: "permanent", label: "Permanent" },
  { value: "reference", label: "Reference" },
];

const PARA_CATEGORIES: { value: ParaCategory; label: string }[] = [
  { value: "project", label: "Project" },
  { value: "area", label: "Area" },
  { value: "resource", label: "Resource" },
  { value: "archive", label: "Archive" },
];

const NOTE_KINDS: { value: NoteKind | "note"; label: string }[] = [
  { value: "note", label: "Note" },
  { value: "daily", label: "Daily" },
  { value: "moc", label: "MOC" },
];

const NOTE_TEMPLATES = {
  blank: {
    label: "Blank note",
    title: "",
    content: "",
    note_type: "fleeting" as NoteType,
    para_category: "" as ParaCategory | "",
    kind: "note" as NoteKind | "note",
    aliases: [] as string[],
    frontmatter: {},
  },
  literature: {
    label: "Literature note",
    title: "Paper / Source Summary",
    content:
      "# Source\n\n- Author:\n- URL:\n- Why it matters:\n\n# Key ideas\n\n- \n\n# Quotes / evidence\n\n- \n\n# Links\n\n- [[Related note]]\n",
    note_type: "literature" as NoteType,
    para_category: "resource" as ParaCategory,
    kind: "note" as NoteKind | "note",
    aliases: [],
    frontmatter: { template: "literature" },
  },
  permanent: {
    label: "Permanent note",
    title: "Permanent Insight",
    content:
      "# Claim\n\nOne durable idea in one sentence.\n\n# Why it is true\n\n- \n\n# Implications\n\n- \n\n# Links\n\n- [[Related note]]\n",
    note_type: "permanent" as NoteType,
    para_category: "resource" as ParaCategory,
    kind: "note" as NoteKind | "note",
    aliases: [],
    frontmatter: { template: "permanent" },
  },
  moc: {
    label: "Map of content",
    title: "Map of Content",
    content:
      "# Overview\n\nWhat this cluster is about.\n\n# Key notes\n\n- [[Note one]]\n- [[Note two]]\n\n# Open questions\n\n- \n",
    note_type: "reference" as NoteType,
    para_category: "resource" as ParaCategory,
    kind: "moc" as NoteKind | "note",
    aliases: [],
    frontmatter: { template: "moc", view: "index" },
  },
  project: {
    label: "Project brief",
    title: "Project Brief",
    content:
      "# Outcome\n\nWhat good looks like.\n\n# Constraints\n\n- \n\n# Critical path\n\n1. \n2. \n\n# Risks\n\n- \n\n# Links\n\n- [[Project draft]]\n",
    note_type: "reference" as NoteType,
    para_category: "project" as ParaCategory,
    kind: "note" as NoteKind | "note",
    aliases: [],
    frontmatter: { template: "project_brief", owner: "self" },
  },
} as const;

const selectClass =
  "h-9 w-full rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 text-sm text-[var(--color-fg-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-border-focus)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-bg-base)]";

function NoteEditor({ note, onClose, onSaved }: NoteEditorProps) {
  const isEditing = !!note;
  const queryClient = useQueryClient();

  const [title, setTitle] = useState(note?.title ?? "");
  const [content, setContent] = useState(note?.content ?? "");
  const [noteType, setNoteType] = useState<NoteType>(note?.note_type ?? "fleeting");
  const [paraCategory, setParaCategory] = useState<ParaCategory | "">(note?.para_category ?? "");
  const [tags, setTags] = useState<string[]>(note?.tags ?? []);
  const [tagInput, setTagInput] = useState("");
  const [sourceUrl, setSourceUrl] = useState(note?.source_url ?? "");
  const [slug, setSlug] = useState(note?.slug ?? "");
  const [aliasesInput, setAliasesInput] = useState((note?.aliases ?? []).join(", "));
  const [kind, setKind] = useState<NoteKind | "note">(note?.kind ?? "note");
  const [frontmatterText, setFrontmatterText] = useState(
    JSON.stringify(note?.frontmatter ?? {}, null, 2),
  );
  const [templateKey, setTemplateKey] = useState<keyof typeof NOTE_TEMPLATES>("blank");
  const [validationError, setValidationError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: (data: CreateNoteData) => createNote(data),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ["notes"] });
      onSaved(created);
    },
  });

  const updateMutation = useMutation({
    mutationFn: (data: UpdateNoteData) => updateNote(note!.id, data),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["notes"] });
      queryClient.invalidateQueries({ queryKey: ["note", note!.id] });
      onSaved(updated);
    },
  });

  const isSaving = createMutation.isPending || updateMutation.isPending;
  const error = createMutation.error || updateMutation.error;

  const handleAddTag = useCallback(
    (input: string) => {
      const tag = input.trim().toLowerCase();
      if (tag && !tags.includes(tag)) {
        setTags((prev) => [...prev, tag]);
      }
      setTagInput("");
    },
    [tags],
  );

  const handleRemoveTag = useCallback((tag: string) => {
    setTags((prev) => prev.filter((t) => t !== tag));
  }, []);

  const applyTemplate = useCallback((key: keyof typeof NOTE_TEMPLATES) => {
    const template = NOTE_TEMPLATES[key];
    setTemplateKey(key);
    setTitle(template.title);
    setContent(template.content);
    setNoteType(template.note_type);
    setParaCategory(template.para_category);
    setKind(template.kind);
    setAliasesInput(template.aliases.join(", "));
    setFrontmatterText(JSON.stringify(template.frontmatter, null, 2));
    setValidationError(null);
  }, []);

  const handleSubmit = useCallback(
    (event?: FormEvent) => {
      event?.preventDefault();
      if (!title.trim() || !content.trim()) return;

      const aliases = aliasesInput
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean);

      let parsedFrontmatter: Record<string, unknown> | undefined;
      if (frontmatterText.trim()) {
        try {
          const parsed = JSON.parse(frontmatterText);
          if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
            setValidationError("Frontmatter must be a JSON object.");
            return;
          }
          parsedFrontmatter = parsed as Record<string, unknown>;
        } catch {
          setValidationError("Frontmatter must be valid JSON.");
          return;
        }
      }

      setValidationError(null);

      const payload: UpdateNoteData = {
        title: title.trim(),
        content: content.trim(),
        note_type: noteType,
        para_category: paraCategory || undefined,
        tags,
        source_url: sourceUrl.trim() || undefined,
        slug: slug.trim() || undefined,
        aliases,
        kind,
        frontmatter: parsedFrontmatter,
      };

      if (isEditing) {
        updateMutation.mutate(payload);
        return;
      }
      createMutation.mutate(payload as CreateNoteData);
    },
    [
      aliasesInput,
      content,
      createMutation,
      frontmatterText,
      isEditing,
      kind,
      noteType,
      paraCategory,
      slug,
      sourceUrl,
      tags,
      title,
      updateMutation,
    ],
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />

      <div className="relative z-10 mx-4 flex max-h-[90vh] w-full max-w-3xl flex-col rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] shadow-xl">
        <div className="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-6 py-4">
          <h2 className="text-base font-semibold text-[var(--color-fg-primary)]">
            {isEditing ? "Edit Note" : "New Note"}
          </h2>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        </div>

        <form
          onSubmit={handleSubmit}
          className="flex flex-1 flex-col gap-4 overflow-y-auto px-6 py-4"
        >
          {!isEditing ? (
            <div>
              <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                Template
              </label>
              <select
                value={templateKey}
                onChange={(event) =>
                  applyTemplate(event.target.value as keyof typeof NOTE_TEMPLATES)
                }
                className={selectClass}
              >
                {Object.entries(NOTE_TEMPLATES).map(([key, template]) => (
                  <option key={key} value={key}>
                    {template.label}
                  </option>
                ))}
              </select>
            </div>
          ) : null}

          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
              Title <span className="text-[var(--color-error-500)]">*</span>
            </label>
            <Input
              placeholder="Note title..."
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              autoFocus
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                Note Type
              </label>
              <select
                value={noteType}
                onChange={(event) => setNoteType(event.target.value as NoteType)}
                className={selectClass}
              >
                {NOTE_TYPES.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                PARA Category
              </label>
              <select
                value={paraCategory}
                onChange={(event) => setParaCategory(event.target.value as ParaCategory | "")}
                className={selectClass}
              >
                <option value="">None</option>
                {PARA_CATEGORIES.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                Kind
              </label>
              <select
                value={kind}
                onChange={(event) => setKind(event.target.value as NoteKind | "note")}
                className={selectClass}
              >
                {NOTE_KINDS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
                Slug
              </label>
              <Input
                placeholder="optional-slug"
                value={slug}
                onChange={(event) => setSlug(event.target.value)}
              />
            </div>
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
              Aliases
            </label>
            <Input
              placeholder="Comma-separated aliases"
              value={aliasesInput}
              onChange={(event) => setAliasesInput(event.target.value)}
            />
          </div>

          <div className="flex-1">
            <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
              Content <span className="text-[var(--color-error-500)]">*</span>
            </label>
            <textarea
              placeholder="Write your note... (Markdown + wiki-links supported)"
              value={content}
              onChange={(event) => setContent(event.target.value)}
              rows={12}
              className={cn(
                "flex w-full rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 py-2 text-sm text-[var(--color-fg-primary)] shadow-sm transition-colors",
                "placeholder:text-[var(--color-fg-tertiary)]",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-border-focus)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-bg-base)]",
                "resize-y",
              )}
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
              Tags
            </label>
            <div className="flex gap-2">
              <Input
                placeholder="Add a tag..."
                value={tagInput}
                onChange={(event) => setTagInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    handleAddTag(tagInput);
                  }
                }}
              />
              <Button
                variant="outline"
                size="sm"
                type="button"
                onClick={() => handleAddTag(tagInput)}
              >
                <Plus className="h-3.5 w-3.5" />
                Add
              </Button>
            </div>
            {tags.length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {tags.map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex items-center gap-1 rounded-[var(--radius-full)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-2 py-0.5 text-xs text-[var(--color-fg-secondary)]"
                  >
                    {tag}
                    <button
                      type="button"
                      onClick={() => handleRemoveTag(tag)}
                      className="cursor-pointer text-[var(--color-fg-tertiary)] hover:text-[var(--color-fg-primary)]"
                      aria-label={`Remove tag ${tag}`}
                    >
                      &times;
                    </button>
                  </span>
                ))}
              </div>
            ) : null}
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
              Properties (JSON frontmatter)
            </label>
            <textarea
              value={frontmatterText}
              onChange={(event) => setFrontmatterText(event.target.value)}
              rows={6}
              className={cn(
                "flex w-full rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 py-2 font-mono text-xs text-[var(--color-fg-primary)] shadow-sm transition-colors",
                "placeholder:text-[var(--color-fg-tertiary)]",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-border-focus)] focus-visible:ring-offset-1 focus-visible:ring-offset-[var(--color-bg-base)]",
                "resize-y",
              )}
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--color-fg-secondary)]">
              Source URL
            </label>
            <Input
              type="url"
              placeholder="https://..."
              value={sourceUrl}
              onChange={(event) => setSourceUrl(event.target.value)}
            />
          </div>

          {validationError || error ? (
            <p className="text-xs text-[var(--color-error-500)]">
              {validationError ?? error?.message ?? "Failed to save note"}
            </p>
          ) : null}
        </form>

        <div className="flex items-center justify-end gap-2 border-t border-[var(--color-border-subtle)] px-6 py-4">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={isSaving}>
            Cancel
          </Button>
          <Button
            size="sm"
            className="gap-1.5"
            onClick={() => handleSubmit()}
            loading={isSaving}
            disabled={!title.trim() || !content.trim()}
          >
            <Save className="h-3.5 w-3.5" />
            {isEditing ? "Update" : "Create"}
          </Button>
        </div>
      </div>
    </div>
  );
}

export { NoteEditor };
export type { NoteEditorProps };
