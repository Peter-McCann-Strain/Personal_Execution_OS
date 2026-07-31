import { api, apiPath } from "./client";
import { API_PATHS } from "./generated/paths";
import type { ChatRequest, ChatResponse, MessageSource } from "@/types";

export async function sendChatMessage(
  content: string,
  source: MessageSource = "api",
): Promise<ChatResponse> {
  const payload: ChatRequest = { content, source };
  return api.post<ChatResponse>(apiPath(API_PATHS.apiChat), payload);
}

export interface ContextSection {
  name: string;
  tokens: number;
  itemCount: number | null;
  present: boolean;
}

export interface DurableMemoryCandidate {
  category: string;
  excerpt: string;
  sourceRole: string;
}

export interface ContextInspection {
  engine: string;
  historySummarized: boolean;
  prunedMessages: number;
  prunedCharacters: number;
  durableMemoryCandidates: DurableMemoryCandidate[];
  ragChunksIncluded: number;
  ragChunksFiltered: number;
  totalTokensEstimate: number;
  sections: ContextSection[];
}

export interface ContextInspectResponse {
  request_id: string;
  inspection: ContextInspection;
}

export function inspectChatContext(
  content: string,
  source: MessageSource = "api",
): Promise<ContextInspectResponse> {
  return api.post<ContextInspectResponse>(apiPath(API_PATHS.apiChatContextInspect), {
    content,
    source,
  });
}
