import { useEffect } from "react";
import { useSearchParams } from "react-router";
import { ChatMessages } from "@/components/chat/chat-messages";
import { ChatInput } from "@/components/chat/chat-input";
import { Button } from "@/components/ui/button";
import { PageTransition } from "@/components/ui/page-transition";
import { useChat } from "@/hooks/use-chat";

const MEMORY_SOURCE_CONTROLS = [
  { key: "saved_memory", label: "Saved memories" },
  { key: "connector_document", label: "Connector data" },
  { key: "note", label: "Notes" },
  { key: "episode", label: "Recent chat" },
] as const;

export function ChatPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const {
    messages,
    isStreaming,
    inputValue,
    setInputValue,
    sendMessage,
    stopStreaming,
    sensitiveMode,
    suppressedSources,
    toggleSensitiveMode,
    toggleSuppressedSource,
  } = useChat();

  useEffect(() => {
    const prompt = searchParams.get("prompt");
    if (!prompt) return;
    setInputValue(prompt);
    setSearchParams({}, { replace: true });
  }, [searchParams, setInputValue, setSearchParams]);

  return (
    <PageTransition>
      <div
        className="flex h-full flex-col"
        style={{ minHeight: "calc(100dvh - var(--header-height, 48px))" }}
      >
        <ChatMessages messages={messages} isStreaming={isStreaming} onSendPrompt={sendMessage} />
        <div className="border-t border-[var(--color-border-subtle)] bg-[var(--color-bg-base)] px-4 py-3">
          <div className="mx-auto flex max-w-[720px] flex-wrap items-center gap-2">
            <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-[var(--color-fg-tertiary)]">
              Memory controls
            </span>
            <Button
              type="button"
              size="sm"
              variant={sensitiveMode ? "default" : "outline"}
              onClick={toggleSensitiveMode}
            >
              Sensitive mode
            </Button>
            {MEMORY_SOURCE_CONTROLS.map((control) => {
              const suppressed = suppressedSources.includes(control.key);
              return (
                <Button
                  key={control.key}
                  type="button"
                  size="sm"
                  variant={suppressed ? "default" : "outline"}
                  onClick={() => toggleSuppressedSource(control.key)}
                >
                  {suppressed ? `Hidden: ${control.label}` : control.label}
                </Button>
              );
            })}
          </div>
        </div>
        <ChatInput
          value={inputValue}
          onChange={setInputValue}
          onSend={sendMessage}
          onStop={stopStreaming}
          isStreaming={isStreaming}
        />
      </div>
    </PageTransition>
  );
}
