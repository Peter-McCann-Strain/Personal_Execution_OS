import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChevronDown, ChevronRight, Bot, User, Workflow } from "lucide-react";
import type { ChatMessage as ChatMessageType } from "@/types";
import { cn, formatRelativeTime } from "@/lib/utils";
import { AgentBadge } from "@/components/ui/badge";
import { useAppStore } from "@/stores/app";

interface ToolCall {
  name: string;
  result?: string;
}

interface Citation {
  source_id: string;
  source_type: string;
  label?: string;
  excerpt?: string;
  url?: string;
}

function parseToolCalls(metadata?: Record<string, unknown>): ToolCall[] {
  if (!metadata?.tool_calls) return [];
  const raw = metadata.tool_calls;
  if (!Array.isArray(raw)) return [];
  return raw.map((tc) => {
    if (typeof tc === "object" && tc !== null) {
      const obj = tc as Record<string, unknown>;
      return {
        name: typeof obj.name === "string" ? obj.name : "unknown",
        result: typeof obj.result === "string" ? obj.result : undefined,
      };
    }
    return { name: String(tc) };
  });
}

function parseCitations(metadata?: Record<string, unknown>): Citation[] {
  if (!metadata?.citations) return [];
  const raw = metadata.citations;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((citation) => {
    if (typeof citation !== "object" || citation === null) {
      return [];
    }
    const obj = citation as Record<string, unknown>;
    const sourceId = typeof obj.source_id === "string" ? obj.source_id : "";
    if (!sourceId) {
      return [];
    }
    return [
      {
        source_id: sourceId,
        source_type: typeof obj.source_type === "string" ? obj.source_type : "external",
        label: typeof obj.label === "string" ? obj.label : undefined,
        excerpt: typeof obj.excerpt === "string" ? obj.excerpt : undefined,
        url: typeof obj.url === "string" ? obj.url : undefined,
      },
    ];
  });
}

interface ToolCallItemProps {
  tool: ToolCall;
}

function ToolCallItem({ tool }: ToolCallItemProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border-b border-[var(--color-border-subtle)] last:border-b-0">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-[var(--color-fg-secondary)] transition-colors hover:opacity-80"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown className="h-3 w-3 shrink-0" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0" />
        )}
        <span className="font-mono">{tool.name}</span>
      </button>
      {expanded && tool.result && (
        <div className="px-3 pb-2">
          <pre className="overflow-x-auto rounded bg-[var(--color-bg-base)] p-2 text-xs font-mono text-[var(--color-fg-secondary)] whitespace-pre-wrap">
            {tool.result}
          </pre>
        </div>
      )}
    </div>
  );
}

interface ChatMessageProps {
  message: ChatMessageType;
}

export function ChatMessage({ message }: ChatMessageProps) {
  const toolCalls = parseToolCalls(message.metadata);
  const citations = parseCitations(message.metadata);
  const openRightPanel = useAppStore((s) => s.openRightPanel);
  const setInspectedAgentRunId = useAppStore((s) => s.setInspectedAgentRunId);
  const workflowId =
    typeof message.metadata?.workflow_id === "string" ? message.metadata.workflow_id : null;

  // System message
  if (message.role === "system") {
    return (
      <div className="flex justify-center px-4 py-1">
        <span className="text-xs italic text-[var(--color-fg-tertiary)]">{message.content}</span>
      </div>
    );
  }

  // User message
  if (message.role === "user") {
    return (
      <div className="group flex justify-end px-4">
        <div className="relative max-w-[85%] rounded-2xl rounded-br-md bg-[var(--color-bg-wash)] px-4 py-3">
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <p className="text-sm text-[var(--color-fg-primary)] whitespace-pre-wrap">
                {message.content}
              </p>
            </div>
            <User className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-fg-tertiary)] opacity-0 transition-opacity group-hover:opacity-60" />
          </div>
          <div className="mt-1 text-right text-[10px] text-[var(--color-fg-tertiary)] opacity-0 transition-opacity group-hover:opacity-100">
            {formatRelativeTime(message.timestamp)}
          </div>
        </div>
      </div>
    );
  }

  // Assistant message
  return (
    <div className="group flex justify-start px-4">
      <div className="relative max-w-[85%] rounded-2xl rounded-bl-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] px-4 py-3">
        {/* Agent badge */}
        <div className="mb-2 flex items-center gap-2">
          {message.agent ? (
            <AgentBadge agent={message.agent} />
          ) : (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-fg-secondary)]">
              <Bot className="h-3.5 w-3.5" />
              Assistant
            </span>
          )}
        </div>

        {/* Tool calls */}
        {toolCalls.length > 0 && (
          <div className="mb-3 overflow-hidden rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-base)]">
            {toolCalls.map((tool, i) => (
              <ToolCallItem key={`${tool.name}-${i}`} tool={tool} />
            ))}
          </div>
        )}

        {workflowId && (
          <button
            type="button"
            onClick={() => {
              setInspectedAgentRunId(workflowId);
              openRightPanel("agent-run");
            }}
            className="mb-3 inline-flex items-center gap-1.5 rounded-full border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-2.5 py-1 text-[11px] font-medium text-[var(--color-fg-secondary)] transition-colors hover:text-[var(--color-fg-primary)]"
          >
            <Workflow className="h-3.5 w-3.5" />
            Inspect run
          </button>
        )}

        {/* Markdown content */}
        <div className="prose-chat text-sm text-[var(--color-fg-primary)]">
          <Markdown
            remarkPlugins={[remarkGfm]}
            components={{
              p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
              h1: ({ children }) => (
                <h1 className="mb-2 mt-3 text-base font-semibold first:mt-0">{children}</h1>
              ),
              h2: ({ children }) => (
                <h2 className="mb-2 mt-3 text-sm font-semibold first:mt-0">{children}</h2>
              ),
              h3: ({ children }) => (
                <h3 className="mb-1 mt-2 text-sm font-medium first:mt-0">{children}</h3>
              ),
              ul: ({ children }) => <ul className="mb-2 list-disc pl-4 space-y-0.5">{children}</ul>,
              ol: ({ children }) => (
                <ol className="mb-2 list-decimal pl-4 space-y-0.5">{children}</ol>
              ),
              li: ({ children }) => <li className="leading-relaxed">{children}</li>,
              code: ({ className, children, ...props }) => {
                const isBlock = className?.includes("language-");
                if (isBlock) {
                  return (
                    <pre className="my-2 overflow-x-auto rounded-lg bg-[var(--color-bg-base)] p-3 text-xs font-mono text-[var(--color-fg-secondary)]">
                      <code className={className} {...props}>
                        {children}
                      </code>
                    </pre>
                  );
                }
                return (
                  <code
                    className="rounded bg-[var(--color-bg-elevated)] px-1 py-0.5 text-xs font-mono text-[var(--color-fg-primary)]"
                    {...props}
                  >
                    {children}
                  </code>
                );
              },
              blockquote: ({ children }) => (
                <blockquote className="my-2 border-l-2 border-[var(--color-border-strong)] pl-3 italic text-[var(--color-fg-secondary)]">
                  {children}
                </blockquote>
              ),
              a: ({ children, href }) => (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[var(--color-info-500)] underline decoration-1 underline-offset-2 transition-opacity hover:opacity-80"
                >
                  {children}
                </a>
              ),
              table: ({ children }) => (
                <div className="my-2 overflow-x-auto">
                  <table className="w-full border-collapse border-[var(--color-border-subtle)] text-xs">
                    {children}
                  </table>
                </div>
              ),
              th: ({ children }) => (
                <th className="border border-[var(--color-border-subtle)] bg-[var(--color-bg-elevated)] px-2 py-1 text-left font-medium">
                  {children}
                </th>
              ),
              td: ({ children }) => (
                <td className="border border-[var(--color-border-subtle)] px-2 py-1">{children}</td>
              ),
              strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
              hr: () => <hr className="my-3 border-[var(--color-border-subtle)]" />,
            }}
          >
            {message.content}
          </Markdown>

          {/* Streaming cursor */}
          {message.isStreaming && (
            <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-[var(--color-fg-primary)] align-text-bottom" />
          )}
        </div>

        {citations.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {citations.map((citation) => {
              const label = citation.label || citation.source_type.replaceAll("_", " ");
              const content = (
                <>
                  <span className="font-medium">{label}</span>
                  {citation.excerpt ? (
                    <span className="max-w-[220px] truncate text-[var(--color-fg-tertiary)]">
                      {citation.excerpt}
                    </span>
                  ) : null}
                </>
              );

              if (citation.url) {
                return (
                  <a
                    key={`${citation.source_type}-${citation.source_id}`}
                    href={citation.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex max-w-full items-center gap-2 rounded-full border border-[var(--color-border-default)] bg-[var(--color-bg-base)] px-3 py-1 text-[11px] text-[var(--color-fg-secondary)] transition-colors hover:text-[var(--color-fg-primary)]"
                    title={citation.excerpt || label}
                  >
                    {content}
                  </a>
                );
              }

              return (
                <div
                  key={`${citation.source_type}-${citation.source_id}`}
                  className="inline-flex max-w-full items-center gap-2 rounded-full border border-[var(--color-border-default)] bg-[var(--color-bg-base)] px-3 py-1 text-[11px] text-[var(--color-fg-secondary)]"
                  title={citation.excerpt || label}
                >
                  {content}
                </div>
              );
            })}
          </div>
        )}

        {/* Timestamp on hover */}
        <div
          className={cn(
            "mt-2 flex items-center gap-1.5 text-[10px] text-[var(--color-fg-tertiary)] transition-opacity",
            "opacity-0 group-hover:opacity-100",
          )}
        >
          <span>{formatRelativeTime(message.timestamp)}</span>
          {message.agent && (
            <>
              <span>·</span>
              <span className="capitalize">{message.agent}</span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
