import { useEffect, useRef, useCallback, useState } from "react";
import type { ChatMessage as ChatMessageType } from "@/types";
import { ChatMessage } from "./chat-message";
import { StreamingIndicator } from "./streaming-indicator";
import { ChevronDown } from "lucide-react";

/**
 * Groups messages by date label: "Today", "Yesterday", or a formatted date string.
 */
function getDateLabel(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const messageDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diffDays = Math.floor((today.getTime() - messageDate.getTime()) / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  return date.toLocaleDateString(undefined, {
    weekday: "long",
    month: "short",
    day: "numeric",
  });
}

interface MessageGroup {
  label: string;
  messages: ChatMessageType[];
}

function groupMessagesByDate(messages: ChatMessageType[]): MessageGroup[] {
  const groups: MessageGroup[] = [];
  let currentLabel = "";

  for (const message of messages) {
    const label = getDateLabel(message.timestamp);
    if (label !== currentLabel) {
      currentLabel = label;
      groups.push({ label, messages: [message] });
    } else {
      groups[groups.length - 1].messages.push(message);
    }
  }

  return groups;
}

const SUGGESTED_PROMPTS = [
  { label: "How am I feeling this week?", icon: "diary" },
  { label: "What's on my calendar today?", icon: "tools" },
  { label: "Summarise my open commitments", icon: "review" },
  { label: "Draft a follow-up email to...", icon: "comms" },
] as const;

interface ChatMessagesProps {
  messages: ChatMessageType[];
  isStreaming: boolean;
  onSendPrompt?: (prompt: string) => void;
}

export function ChatMessages({ messages, isStreaming, onSendPrompt }: ChatMessagesProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const isNearBottomRef = useRef(true);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    bottomRef.current?.scrollIntoView({ behavior });
  }, []);

  const handleScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const distanceFromBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight;
    const nearBottom = distanceFromBottom < 100;
    isNearBottomRef.current = nearBottom;
    setShowScrollButton(!nearBottom && messages.length > 0);
  }, [messages.length]);

  // Auto-scroll on new messages if user is near the bottom
  useEffect(() => {
    if (isNearBottomRef.current) {
      scrollToBottom("smooth");
    }
  }, [messages, scrollToBottom]);

  // Auto-scroll on streaming updates if near bottom
  useEffect(() => {
    if (isStreaming && isNearBottomRef.current) {
      requestAnimationFrame(() => {
        scrollToBottom("smooth");
      });
    }
  }, [isStreaming, messages, scrollToBottom]);

  const groups = groupMessagesByDate(messages);

  return (
    <div ref={containerRef} className="relative flex-1 overflow-y-auto" onScroll={handleScroll}>
      <div className="mx-auto flex max-w-[720px] flex-col gap-4 py-6">
        {messages.length === 0 && !isStreaming && (
          <div className="flex flex-col items-center justify-center px-4 py-16">
            <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-[var(--color-bg-elevated)]">
              <svg
                className="h-7 w-7 text-[var(--color-fg-tertiary)]"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
              >
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
            <p className="text-base font-semibold text-[var(--color-fg-primary)]">
              How can I help?
            </p>
            <p className="mt-1 text-sm text-[var(--color-fg-tertiary)]">
              Ask anything — it&apos;ll be routed to the right specialist.
            </p>
            {onSendPrompt && (
              <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-md">
                {SUGGESTED_PROMPTS.map((prompt) => (
                  <button
                    key={prompt.label}
                    type="button"
                    onClick={() => onSendPrompt(prompt.label)}
                    className="flex items-center gap-2 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-3 py-2.5 text-left text-sm text-[var(--color-fg-secondary)] transition-all hover:border-[var(--color-border-strong)] hover:bg-[var(--color-bg-elevated)] hover:text-[var(--color-fg-primary)] cursor-pointer"
                  >
                    <span className="truncate">{prompt.label}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {groups.map((group) => (
          <div key={group.label} className="flex flex-col gap-4">
            {/* Date separator */}
            <div className="flex items-center gap-3 px-4 py-1">
              <div className="h-px flex-1 bg-[var(--color-border-subtle)]" />
              <span className="text-[10px] font-medium uppercase tracking-wider text-[var(--color-fg-tertiary)]">
                {group.label}
              </span>
              <div className="h-px flex-1 bg-[var(--color-border-subtle)]" />
            </div>

            {group.messages.map((msg) => (
              <ChatMessage key={msg.id} message={msg} />
            ))}
          </div>
        ))}

        {/* Streaming indicator - shown when waiting for first token */}
        {isStreaming && messages.length > 0 && !messages[messages.length - 1]?.isStreaming && (
          <div className="flex justify-start px-4">
            <div className="rounded-2xl rounded-bl-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] px-4 py-3">
              <StreamingIndicator />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Scroll to bottom button */}
      {showScrollButton && (
        <button
          type="button"
          className="fixed bottom-24 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-1.5 text-xs font-medium text-[var(--color-fg-secondary)] shadow-lg transition-all hover:scale-105"
          onClick={() => scrollToBottom("smooth")}
        >
          <ChevronDown className="h-3.5 w-3.5" />
          New messages
        </button>
      )}
    </div>
  );
}
