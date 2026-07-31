import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Search, Scissors, Database } from "lucide-react";
import { inspectChatContext } from "@/api/chat";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

function ContextInspector() {
  const [draft, setDraft] = useState(
    "Summarize what context would be injected if I asked about my current priorities.",
  );

  const inspection = useMutation({
    mutationFn: (content: string) => inspectChatContext(content),
  });

  const data = inspection.data?.inspection;

  return (
    <div className="flex flex-col gap-6">
      <Card padding="none">
        <CardHeader>
          <CardTitle>Context Inspector</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-[var(--color-fg-secondary)]">
            Inspect the exact context budget the backend would assemble before routing a message.
          </p>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            className="min-h-28 w-full rounded-[var(--radius-md)] border border-[var(--color-border-default)] bg-[var(--color-bg-base)] px-3 py-2 text-sm text-[var(--color-fg-primary)] outline-none transition-colors focus:border-[var(--color-border-focus)]"
            placeholder="Type a message to inspect its assembled context..."
          />
          <div className="flex items-center gap-3">
            <Button
              onClick={() => inspection.mutate(draft)}
              loading={inspection.isPending}
              disabled={!draft.trim()}
            >
              Inspect Context
            </Button>
            {inspection.isError && (
              <span className="text-sm text-[var(--color-error-500)]">
                {(inspection.error as Error).message}
              </span>
            )}
          </div>
        </CardContent>
      </Card>

      {data && (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <Card>
              <div className="flex items-center gap-3">
                <Search className="h-5 w-5 text-[var(--color-info-500)]" />
                <div>
                  <p className="text-xs uppercase tracking-wide text-[var(--color-fg-tertiary)]">
                    Total Budget
                  </p>
                  <p className="text-2xl font-semibold text-[var(--color-fg-primary)]">
                    {data.totalTokensEstimate}
                  </p>
                </div>
              </div>
            </Card>
            <Card>
              <div className="flex items-center gap-3">
                <Scissors className="h-5 w-5 text-[var(--color-warning-500)]" />
                <div>
                  <p className="text-xs uppercase tracking-wide text-[var(--color-fg-tertiary)]">
                    Pruned
                  </p>
                  <p className="text-2xl font-semibold text-[var(--color-fg-primary)]">
                    {data.prunedMessages}
                  </p>
                  <p className="text-xs text-[var(--color-fg-secondary)]">
                    {data.prunedCharacters} chars removed
                  </p>
                </div>
              </div>
            </Card>
            <Card>
              <div className="flex items-center gap-3">
                <Database className="h-5 w-5 text-[var(--color-agent-memory)]" />
                <div>
                  <p className="text-xs uppercase tracking-wide text-[var(--color-fg-tertiary)]">
                    Durable Candidates
                  </p>
                  <p className="text-2xl font-semibold text-[var(--color-fg-primary)]">
                    {data.durableMemoryCandidates.length}
                  </p>
                  <p className="text-xs text-[var(--color-fg-secondary)]">
                    {data.ragChunksIncluded} retrieved / {data.ragChunksFiltered} filtered
                  </p>
                </div>
              </div>
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.2fr_0.8fr]">
            <Card padding="none">
              <CardHeader>
                <CardTitle>Context Sections</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {data.sections.map((section) => (
                  <div
                    key={section.name}
                    className="flex items-center justify-between rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-base)] px-3 py-2"
                  >
                    <div>
                      <p className="text-sm font-medium capitalize text-[var(--color-fg-primary)]">
                        {section.name.replace("_", " ")}
                      </p>
                      <p className="text-xs text-[var(--color-fg-secondary)]">
                        {section.present ? "Included" : "Omitted"}
                        {section.itemCount != null ? ` · ${section.itemCount} item(s)` : ""}
                      </p>
                    </div>
                    <span className="text-sm font-semibold tabular-nums text-[var(--color-fg-primary)]">
                      {section.tokens} tok
                    </span>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card padding="none">
              <CardHeader>
                <CardTitle>Memory Flush Candidates</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {data.durableMemoryCandidates.length === 0 ? (
                  <p className="text-sm text-[var(--color-fg-secondary)]">
                    No durable memory candidates were detected for this prompt.
                  </p>
                ) : (
                  data.durableMemoryCandidates.map((candidate, index) => (
                    <div
                      key={`${candidate.category}-${index}`}
                      className="rounded-[var(--radius-md)] border border-[var(--color-border-subtle)] bg-[var(--color-bg-base)] px-3 py-2"
                    >
                      <p className="text-xs uppercase tracking-wide text-[var(--color-fg-tertiary)]">
                        {candidate.category} · {candidate.sourceRole}
                      </p>
                      <p className="mt-1 text-sm text-[var(--color-fg-primary)]">
                        {candidate.excerpt}
                      </p>
                    </div>
                  ))
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

export { ContextInspector };
