import { api, apiPath } from "./client";
import { API_PATHS } from "./generated/paths";
import type { Commitment } from "@/types";

// ─── Fetch Open Commitments ────────────────────────────────

export function getOpenCommitments(limit: number = 20): Promise<Commitment[]> {
  return api.get<Commitment[]>(apiPath(API_PATHS.apiCommitmentsOpen), { limit });
}

// ─── Fetch Overdue Commitments ─────────────────────────────

export function getOverdueCommitments(): Promise<Commitment[]> {
  return api.get<Commitment[]>(apiPath(API_PATHS.apiCommitmentsOverdue));
}

// ─── Update Commitment Status ──────────────────────────────

export function updateCommitmentStatus(id: string, status: string): Promise<Commitment> {
  return api.patch<Commitment>(
    apiPath(API_PATHS.apiCommitmentsByCommitmentIdStatus, {
      commitment_id: id,
    }),
    { status },
  );
}
