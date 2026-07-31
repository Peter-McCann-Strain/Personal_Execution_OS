import {
  useState,
  useRef,
  useEffect,
  useCallback,
  type KeyboardEvent,
  type ChangeEvent,
  type FormEvent,
} from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Send, GraduationCap, User, MessageCircle, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { BloomIndicator, BloomBadge } from "./bloom-indicator";
import {
  sendTutorialTurn,
  endTutorial,
  type TutorialDetail,
  type TutorialTurnResponse,
  type TranscriptTurn,
  type BloomLevel,
  type TutorialPhase,
} from "@/api/tutorials";

// ─── Transcript Message ─────────────────────────────────────

interface TranscriptMessageProps {
  turn: TranscriptTurn;
}

function TranscriptMessage({ turn }: TranscriptMessageProps) {
  const isTutor = turn.speaker === "tutor";

  return (
    <div className={cn("flex gap-3", isTutor ? "justify-start" : "flex-row-reverse")}>
      {/* Avatar */}
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
          isTutor
            ? "bg-[var(--color-info-50)] text-[var(--color-info-500)]"
            : "bg-[var(--color-bg-overlay)] text-[var(--color-fg-tertiary)]",
        )}
      >
        {isTutor ? <GraduationCap className="h-4 w-4" /> : <User className="h-4 w-4" />}
      </div>

      {/* Message bubble */}
      <div
        className={cn(
          "max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed",
          isTutor
            ? "rounded-bl-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] text-[var(--color-fg-primary)]"
            : "rounded-br-md bg-[var(--color-info-500)] text-[var(--color-fg-on-accent)]",
        )}
      >
        <p className="whitespace-pre-wrap">{turn.content}</p>
        {turn.bloom_level && isTutor && (
          <div className="mt-2">
            <BloomBadge level={turn.bloom_level} />
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Tutorial Session ───────────────────────────────────────

interface TutorialSessionProps {
  tutorial: TutorialDetail;
  onBack: () => void;
  onComplete: () => void;
}

function TutorialSession({ tutorial, onBack, onComplete }: TutorialSessionProps) {
  const queryClient = useQueryClient();
  const [transcript, setTranscript] = useState<TranscriptTurn[]>(tutorial.transcript ?? []);
  const [phase, setPhase] = useState<TutorialPhase>(tutorial.phase);
  const [currentBloom, setCurrentBloom] = useState<BloomLevel | null>(
    tutorial.bloom_end ?? tutorial.bloom_start ?? null,
  );
  const [turnCount, setTurnCount] = useState(tutorial.turn_count);
  const [inputValue, setInputValue] = useState("");
  const [analysis, setAnalysis] = useState(tutorial.analysis);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [transcript, scrollToBottom]);

  // ─── Send Turn Mutation ───────────────────────────────────
  const turnMutation = useMutation({
    mutationFn: (message: string) => sendTutorialTurn(tutorial.id, message),
    onMutate: (message: string) => {
      // Optimistically add student message
      const studentTurn: TranscriptTurn = {
        speaker: "student",
        content: message,
        turn: turnCount + 1,
      };
      setTranscript((prev) => [...prev, studentTurn]);
      setTurnCount((prev) => prev + 1);
    },
    onSuccess: (response: TutorialTurnResponse) => {
      // Add tutor response
      const tutorTurn: TranscriptTurn = {
        speaker: response.speaker,
        content: response.content,
        phase: response.phase,
        turn: response.turn,
        bloom_level: response.bloom_level,
      };
      setTranscript((prev) => [...prev, tutorTurn]);
      if (response.phase) setPhase(response.phase);
      if (response.bloom_level) setCurrentBloom(response.bloom_level);
      if (response.turn) setTurnCount(response.turn);
      if (response.analysis) setAnalysis(response.analysis);

      // Invalidate queries to refresh list
      queryClient.invalidateQueries({ queryKey: ["tutorials"] });
    },
    onError: (error: Error) => {
      // Remove optimistic student message
      setTranscript((prev) => prev.slice(0, -1));
      setTurnCount((prev) => prev - 1);
      toast.error(error.message || "Failed to send message");
    },
  });

  // ─── End Tutorial Mutation ────────────────────────────────
  const endMutation = useMutation({
    mutationFn: () => endTutorial(tutorial.id),
    onSuccess: (response: TutorialTurnResponse) => {
      if (response.content) {
        const closingTurn: TranscriptTurn = {
          speaker: response.speaker,
          content: response.content,
          phase: response.phase,
        };
        setTranscript((prev) => [...prev, closingTurn]);
      }
      setPhase("complete");
      if (response.analysis) setAnalysis(response.analysis);
      queryClient.invalidateQueries({ queryKey: ["tutorials"] });
      toast.success("Tutorial completed");
      onComplete();
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to end tutorial");
    },
  });

  // ─── Input Handlers ──────────────────────────────────────
  const resizeTextarea = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, []);

  const handleChange = useCallback(
    (e: ChangeEvent<HTMLTextAreaElement>) => {
      setInputValue(e.target.value);
      resizeTextarea();
    },
    [resizeTextarea],
  );

  const handleSubmit = useCallback(
    (e?: FormEvent) => {
      e?.preventDefault();
      const trimmed = inputValue.trim();
      if (!trimmed || turnMutation.isPending) return;
      turnMutation.mutate(trimmed);
      setInputValue("");
      requestAnimationFrame(() => {
        const el = textareaRef.current;
        if (el) el.style.height = "auto";
      });
    },
    [inputValue, turnMutation],
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

  const canSend = inputValue.trim().length > 0 && !turnMutation.isPending;
  const isActive = phase === "dialogue";

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] px-4 py-3">
        <div className="mx-auto max-w-3xl">
          <div className="flex items-center justify-between">
            <div className="flex-1 min-w-0">
              <h2 className="truncate text-sm font-semibold text-[var(--color-fg-primary)]">
                {tutorial.topic}
              </h2>
              <div className="mt-1 flex items-center gap-3 text-xs text-[var(--color-fg-tertiary)]">
                <span className="flex items-center gap-1">
                  <MessageCircle className="h-3 w-3" />
                  Turn {turnCount}
                </span>
                <span
                  className={cn(
                    "flex items-center gap-1 rounded-[var(--radius-full)] px-2 py-0.5 text-[10px] font-medium",
                    phase === "dialogue"
                      ? "bg-[var(--color-info-50)] text-[var(--color-info-900)]"
                      : "bg-[var(--color-success-50)] text-[var(--color-success-900)]",
                  )}
                >
                  {phase === "dialogue" ? "In Progress" : "Complete"}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {isActive && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => endMutation.mutate()}
                  loading={endMutation.isPending}
                >
                  End Tutorial
                </Button>
              )}
              <Button variant="ghost" size="sm" onClick={onBack}>
                Back
              </Button>
            </div>
          </div>

          {/* Bloom indicator */}
          {currentBloom && (
            <div className="mt-3">
              <BloomIndicator current={currentBloom} compact showLabels={false} />
            </div>
          )}
        </div>
      </div>

      {/* Transcript */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        <div className="mx-auto flex max-w-3xl flex-col gap-4">
          {transcript.map((turn, i) => (
            <TranscriptMessage key={i} turn={turn} />
          ))}

          {/* Typing indicator */}
          {turnMutation.isPending && (
            <div className="flex gap-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--color-info-50)] text-[var(--color-info-500)]">
                <GraduationCap className="h-4 w-4" />
              </div>
              <div className="rounded-2xl rounded-bl-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] px-4 py-3">
                <div className="flex items-center gap-1.5">
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--color-fg-tertiary)]" />
                  <span className="text-xs text-[var(--color-fg-tertiary)]">Thinking...</span>
                </div>
              </div>
            </div>
          )}

          {/* Analysis summary (when complete) */}
          {phase === "complete" && analysis && (
            <div className="mt-4 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] p-4">
              <h3 className="mb-3 text-sm font-semibold text-[var(--color-fg-primary)]">
                Session Analysis
              </h3>
              {analysis.summary && (
                <p className="mb-3 text-sm text-[var(--color-fg-secondary)]">{analysis.summary}</p>
              )}
              <div className="grid grid-cols-3 gap-3 text-center">
                <div className="rounded-[var(--radius-md)] bg-[var(--color-bg-surface)] p-2">
                  <div className="text-lg font-bold text-[var(--color-fg-primary)]">
                    {analysis.knowledge_gaps_addressed}/{analysis.knowledge_gaps_found}
                  </div>
                  <div className="text-[10px] text-[var(--color-fg-tertiary)]">Gaps Addressed</div>
                </div>
                <div className="rounded-[var(--radius-md)] bg-[var(--color-bg-surface)] p-2">
                  <div className="text-lg font-bold text-[var(--color-fg-primary)]">
                    {Math.round(analysis.speaking_ratio_student_pct)}%
                  </div>
                  <div className="text-[10px] text-[var(--color-fg-tertiary)]">Student Ratio</div>
                </div>
                <div className="rounded-[var(--radius-md)] bg-[var(--color-bg-surface)] p-2">
                  <div className="text-lg font-bold text-[var(--color-fg-primary)]">
                    {analysis.bloom_progression.length}
                  </div>
                  <div className="text-[10px] text-[var(--color-fg-tertiary)]">Bloom Levels</div>
                </div>
              </div>
              {analysis.strengths && analysis.strengths.length > 0 && (
                <div className="mt-3">
                  <h4 className="mb-1 text-xs font-medium text-[var(--color-success-500)]">
                    Strengths
                  </h4>
                  <ul className="space-y-0.5 text-xs text-[var(--color-fg-secondary)]">
                    {analysis.strengths.map((s, i) => (
                      <li key={i} className="flex items-start gap-1.5">
                        <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[var(--color-success-500)]" />
                        {s}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {analysis.areas_for_improvement && analysis.areas_for_improvement.length > 0 && (
                <div className="mt-3">
                  <h4 className="mb-1 text-xs font-medium text-[var(--color-warning-500)]">
                    Areas for Improvement
                  </h4>
                  <ul className="space-y-0.5 text-xs text-[var(--color-fg-secondary)]">
                    {analysis.areas_for_improvement.map((a, i) => (
                      <li key={i} className="flex items-start gap-1.5">
                        <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[var(--color-warning-500)]" />
                        {a}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input area (only when active) */}
      {isActive && (
        <div className="border-t border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] px-4 py-3">
          <form onSubmit={handleSubmit} className="mx-auto flex max-w-3xl items-end gap-3">
            <div className="relative flex-1">
              <textarea
                ref={textareaRef}
                value={inputValue}
                onChange={handleChange}
                onKeyDown={handleKeyDown}
                placeholder="Share your thinking..."
                disabled={turnMutation.isPending}
                rows={1}
                className={cn(
                  "w-full resize-none rounded-xl border border-[var(--color-border-default)] bg-[var(--color-bg-base)] px-4 py-3 text-sm text-[var(--color-fg-primary)] outline-none",
                  "placeholder:text-[var(--color-fg-tertiary)]",
                  "focus:border-[var(--color-border-focus)] focus:ring-2 focus:ring-[var(--color-border-focus)]/30",
                  "disabled:cursor-not-allowed disabled:opacity-60",
                )}
                style={{
                  maxHeight: "160px",
                  minHeight: "44px",
                  transition:
                    "height 100ms ease-out, border-color 150ms ease, box-shadow 150ms ease",
                }}
              />
            </div>
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
              aria-label="Send response"
            >
              <Send className="h-4 w-4" />
            </button>
          </form>
        </div>
      )}
    </div>
  );
}

export { TutorialSession, TranscriptMessage };
export type { TutorialSessionProps };
