import { create } from "zustand";
import type { ChatMessage } from "@/types";

interface ChatState {
  messages: ChatMessage[];
  isStreaming: boolean;
  activeAgent: string | null;

  addMessage: (message: ChatMessage) => void;
  updateLastMessage: (content: string) => void;
  patchLastMessage: (patch: Partial<ChatMessage>) => void;
  finalizeLastMessage: () => void;
  setStreaming: (streaming: boolean) => void;
  setActiveAgent: (agent: string | null) => void;
  clearMessages: () => void;
}

export const useChatStore = create<ChatState>()((set) => ({
  messages: [],
  isStreaming: false,
  activeAgent: null,

  addMessage: (message) => set((s) => ({ messages: [...s.messages, message] })),

  updateLastMessage: (content) =>
    set((s) => {
      const messages = [...s.messages];
      const last = messages[messages.length - 1];
      if (last && last.role === "assistant") {
        messages[messages.length - 1] = { ...last, content };
      }
      return { messages };
    }),

  patchLastMessage: (patch) =>
    set((s) => {
      const messages = [...s.messages];
      const last = messages[messages.length - 1];
      if (last && last.role === "assistant") {
        messages[messages.length - 1] = { ...last, ...patch };
      }
      return { messages };
    }),

  finalizeLastMessage: () =>
    set((s) => {
      const messages = [...s.messages];
      const last = messages[messages.length - 1];
      if (last && last.role === "assistant") {
        messages[messages.length - 1] = { ...last, isStreaming: false };
      }
      return { messages };
    }),

  setStreaming: (streaming) => set({ isStreaming: streaming }),
  setActiveAgent: (agent) => set({ activeAgent: agent }),
  clearMessages: () => set({ messages: [] }),
}));
