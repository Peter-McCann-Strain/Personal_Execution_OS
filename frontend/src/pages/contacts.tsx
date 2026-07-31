import { useState, useMemo, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, Users, SlidersHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { PageError } from "@/components/ui/page-error";
import { PageHeader } from "@/components/ui/page-header";
import { PageTransition } from "@/components/ui/page-transition";
import { EmptyState } from "@/components/ui/empty-state";
import { SortMenu } from "@/components/ui/sort-menu";
import { ContactCard } from "@/components/contacts/contact-card";
import { ContactDetail } from "@/components/contacts/contact-detail";
import { getContacts } from "@/api/contacts";
import { useDebounce } from "@/hooks/use-debounce";
import type { Contact } from "@/types";

// ─── Sort Options ────────────────────────────────────────────

type SortOption = "score_asc" | "score_desc" | "last_interaction" | "name";

const sortOptions: { value: SortOption; label: string }[] = [
  { value: "score_asc", label: "Score (Low first)" },
  { value: "score_desc", label: "Score (High first)" },
  { value: "last_interaction", label: "Last Interaction" },
  { value: "name", label: "Name" },
];

// ─── Main Page ───────────────────────────────────────────────

function ContactsPage() {
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortOption>("score_asc");
  const [showFilters, setShowFilters] = useState(false);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [scoreMin, setScoreMin] = useState(0);
  const [scoreMax, setScoreMax] = useState(100);
  const [selectedContactId, setSelectedContactId] = useState<string | null>(null);

  const debouncedSearch = useDebounce(search, 300);

  const contactsQuery = useQuery({
    queryKey: ["contacts", { search: debouncedSearch, sort, selectedTags, scoreMin, scoreMax }],
    queryFn: () =>
      getContacts({
        search: debouncedSearch || undefined,
        sort,
        tags: selectedTags.length > 0 ? selectedTags : undefined,
        score_min: scoreMin > 0 ? scoreMin : undefined,
        score_max: scoreMax < 100 ? scoreMax : undefined,
        limit: 50,
      }),
  });

  const contacts = useMemo(() => contactsQuery.data?.items ?? [], [contactsQuery.data?.items]);

  // Collect all unique tags for the filter
  const allTags = useMemo(() => {
    const tagSet = new Set<string>();
    contacts.forEach((c) => c.tags.forEach((t) => tagSet.add(t)));
    return Array.from(tagSet).sort();
  }, [contacts]);

  const toggleTag = useCallback((tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );
  }, []);

  const handleSelectContact = useCallback((contact: Contact) => {
    setSelectedContactId(contact.id);
  }, []);

  // ─── Detail View ─────────────────────────────────────────
  if (selectedContactId) {
    return (
      <ContactDetail contactId={selectedContactId} onBack={() => setSelectedContactId(null)} />
    );
  }

  // ─── List View ───────────────────────────────────────────
  return (
    <PageTransition>
      <div className="flex flex-col gap-4 p-6">
        {/* Header */}
        <PageHeader
          title="Contacts"
          subtitle="Read-only contact and interaction history"
          icon={Users}
        />

        {/* Toolbar */}
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          {/* Search */}
          <div className="relative max-w-sm flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-fg-tertiary)]" />
            <Input
              placeholder="Search contacts..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9"
            />
          </div>

          {/* Sort dropdown */}
          <SortMenu
            value={sort}
            options={sortOptions}
            onChange={setSort}
            buttonLabel={sortOptions.find((opt) => opt.value === sort)?.label ?? "Sort"}
            buttonAriaLabel="Sort contacts"
            widthClassName="w-48"
          />

          {/* Filter toggle */}
          <Button
            variant={showFilters ? "default" : "outline"}
            size="sm"
            className="gap-1.5"
            onClick={() => setShowFilters(!showFilters)}
          >
            <SlidersHorizontal className="h-3.5 w-3.5" />
            Filters
            {selectedTags.length > 0 && (
              <span className="ml-1 flex h-4 w-4 items-center justify-center rounded-full bg-[var(--color-info-500)] text-[10px] text-white">
                {selectedTags.length}
              </span>
            )}
          </Button>
        </div>

        {/* Filter Panel */}
        {showFilters && (
          <div className="rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4">
            <div className="flex flex-col gap-4">
              {/* Tags */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--color-fg-secondary)]">
                  Tags
                </label>
                <div className="flex flex-wrap gap-1.5">
                  {allTags.length === 0 ? (
                    <span className="text-xs text-[var(--color-fg-tertiary)]">
                      No tags available
                    </span>
                  ) : (
                    allTags.map((tag) => (
                      <button
                        key={tag}
                        onClick={() => toggleTag(tag)}
                        className={cn(
                          "rounded-[var(--radius-full)] border px-2.5 py-0.5 text-xs font-medium transition-colors",
                          selectedTags.includes(tag)
                            ? "border-[var(--color-info-500)] bg-[var(--color-info-50)] text-[var(--color-info-900)]"
                            : "border-[var(--color-border-default)] text-[var(--color-fg-secondary)] hover:border-[var(--color-border-strong)]",
                        )}
                      >
                        {tag}
                      </button>
                    ))
                  )}
                </div>
              </div>

              {/* Score range */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--color-fg-secondary)]">
                  Health Score Range: {scoreMin} – {scoreMax}
                </label>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={scoreMin}
                    onChange={(e) => setScoreMin(Math.min(Number(e.target.value), scoreMax))}
                    className="flex-1 accent-[var(--color-info-500)]"
                  />
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={scoreMax}
                    onChange={(e) => setScoreMax(Math.max(Number(e.target.value), scoreMin))}
                    className="flex-1 accent-[var(--color-info-500)]"
                  />
                </div>
              </div>

              {/* Clear */}
              <div className="flex justify-end">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setSelectedTags([]);
                    setScoreMin(0);
                    setScoreMax(100);
                  }}
                >
                  Clear All
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Active filter badges */}
        {selectedTags.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-[var(--color-fg-tertiary)]">Active:</span>
            {selectedTags.map((tag) => (
              <Badge
                key={tag}
                variant="info"
                size="sm"
                className="cursor-pointer"
                onClick={() => toggleTag(tag)}
              >
                {tag} &times;
              </Badge>
            ))}
          </div>
        )}

        {/* Error state */}
        {contactsQuery.isError && (
          <PageError
            message={contactsQuery.error?.message ?? "Failed to load contacts"}
            onRetry={() => contactsQuery.refetch()}
            context="your contacts"
            icon={Users}
          />
        )}

        {/* Contact Grid */}
        {!contactsQuery.isError && contactsQuery.isLoading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-48 w-full" />
            ))}
          </div>
        ) : !contactsQuery.isError && contacts.length === 0 ? (
          <EmptyState
            icon={Search}
            title="No contacts found"
            action={search ? { label: "Clear search", onClick: () => setSearch("") } : undefined}
          />
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {contacts.map((contact) => (
              <ContactCard key={contact.id} contact={contact} onSelect={handleSelectContact} />
            ))}
          </div>
        )}
      </div>
    </PageTransition>
  );
}

export { ContactsPage };
