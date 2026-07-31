import { useState, useCallback } from "react";
import { useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Search, Mail, Wand2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { PageError } from "@/components/ui/page-error";
import { PageTransition } from "@/components/ui/page-transition";
import { EmailList } from "@/components/email/email-list";
import { EmailDetail } from "@/components/email/email-detail";
import { getEmails } from "@/api/email";
import { useDebounce } from "@/hooks/use-debounce";
import { useAppStore } from "@/stores/app";
import type { Email, TriageCategory } from "@/types";

// ─── Triage Filter Options ──────────────────────────────────

const triageOptions: Array<{ value: TriageCategory | "ALL"; label: string }> = [
  { value: "ALL", label: "All" },
  { value: "ACTION_REQUIRED", label: "Action" },
  { value: "URGENT", label: "Urgent" },
  { value: "FYI", label: "FYI" },
  { value: "DELEGATE", label: "Delegate" },
  { value: "ARCHIVE", label: "Archive" },
];

// ─── Main Page ───────────────────────────────────────────────

function EmailPage() {
  const navigate = useNavigate();
  const openRightPanel = useAppStore((s) => s.openRightPanel);
  const setInspectedEmail = useAppStore((s) => s.setInspectedEmail);
  const [search, setSearch] = useState("");
  const [triageFilter, setTriageFilter] = useState<TriageCategory | "ALL">("ALL");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [selectedEmail, setSelectedEmail] = useState<Email | null>(null);

  const debouncedSearch = useDebounce(search, 300);

  const emailsQuery = useQuery({
    queryKey: ["emails", { search: debouncedSearch, triageFilter, unreadOnly }],
    queryFn: () =>
      getEmails({
        search: debouncedSearch || undefined,
        triage: triageFilter !== "ALL" ? triageFilter : undefined,
        unread_only: unreadOnly || undefined,
        limit: 50,
      }),
  });

  const emails = emailsQuery.data?.items ?? [];

  const handleSelectEmail = useCallback(
    (email: Email) => {
      setSelectedEmail(email);
      setInspectedEmail(email);
      openRightPanel("email");
    },
    [openRightPanel, setInspectedEmail],
  );

  const handleTriageAll = useCallback(() => {
    const prompt = [
      "Triage my email inbox.",
      "Group the most important unread messages into urgent, action-required, delegate, FYI, and archive.",
      "Give me the next three replies or actions to take.",
    ].join(" ");
    navigate(`/chat?prompt=${encodeURIComponent(prompt)}`);
  }, [navigate]);

  return (
    <PageTransition>
      <div className="flex h-full flex-col">
        {/* Toolbar */}
        <div className="flex flex-col gap-2 border-b border-[var(--color-border-subtle)] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-base font-semibold text-[var(--color-fg-primary)]">Email</h1>
            {/* Search */}
            <div className="relative max-w-xs flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-fg-tertiary)]" />
              <Input
                placeholder="Search emails..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" className="gap-1.5" onClick={handleTriageAll}>
              <Wand2 className="h-3.5 w-3.5" />
              Triage All
            </Button>
            <span className="hidden text-xs text-[var(--color-fg-tertiary)] sm:inline">
              Read-only inbox
            </span>
          </div>
        </div>

        {/* Filter Bar */}
        <div className="flex items-center gap-3 border-b border-[var(--color-border-subtle)] px-4 py-2">
          {/* Triage segmented control */}
          <SegmentedControl
            value={triageFilter}
            onChange={setTriageFilter}
            options={triageOptions}
            label="Email triage filter"
          />

          {/* Unread only toggle */}
          <button
            onClick={() => setUnreadOnly(!unreadOnly)}
            aria-pressed={unreadOnly}
            aria-label="Show unread emails only"
            className={cn(
              "rounded-[var(--radius-full)] border px-3 py-1 text-xs font-medium transition-colors",
              unreadOnly
                ? "border-[var(--color-info-500)] bg-[var(--color-info-50)] text-[var(--color-info-900)]"
                : "border-[var(--color-border-default)] text-[var(--color-fg-secondary)] hover:border-[var(--color-border-strong)]",
            )}
          >
            Unread Only
          </button>
        </div>

        {/* Main content: two-panel layout */}
        <div className="flex flex-1 overflow-hidden">
          {/* Email list */}
          <div
            className={cn(
              "flex-shrink-0 overflow-y-auto border-r border-[var(--color-border-subtle)]",
              selectedEmail ? "hidden w-[380px] sm:block" : "w-full sm:w-[380px]",
            )}
          >
            {emailsQuery.isError ? (
              <PageError
                message={emailsQuery.error?.message ?? "Failed to load emails"}
                onRetry={() => emailsQuery.refetch()}
                context="your emails"
                icon={Mail}
              />
            ) : emailsQuery.isLoading ? (
              <div className="flex flex-col gap-2 p-4">
                {Array.from({ length: 6 }).map((_, i) => (
                  <Skeleton key={i} className="h-20 w-full" />
                ))}
              </div>
            ) : (
              <EmailList
                emails={emails}
                selectedId={selectedEmail?.id ?? null}
                onSelectEmail={handleSelectEmail}
              />
            )}
          </div>

          {/* Email detail */}
          <div className="flex-1 overflow-hidden">
            {selectedEmail ? (
              <EmailDetail email={selectedEmail} />
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-[var(--color-fg-tertiary)]">
                <p className="text-sm">Select an email to view</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </PageTransition>
  );
}

export { EmailPage };
