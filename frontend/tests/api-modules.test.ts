import { afterEach, describe, expect, test, vi } from "vitest";

import { API_PATHS } from "@/api/generated/paths";
import { inspectChatContext, sendChatMessage } from "@/api/chat";
import {
  getActiveGoals,
  getDashboardStats,
  getMorningBriefing,
  getMoodEnergyTrends,
  getRecentAgentActivity,
  getRecentDiaryEntries,
} from "@/api/dashboard";
import {
  getAgentActions,
  getAgentComparison,
  getChannelMetrics,
  getEvalOutcomes,
  getHealth,
  getInteractionDetail,
  getLLMStats,
  getPreflightReport,
  getPromptVersions,
  getSecurityMetrics,
  getQualityScores,
  getTelegramWebhookStatus,
  getTraceDetail,
  getTraceSummaries,
} from "@/api/monitoring";
import { createProject, getProject, getProjects, updateTask } from "@/api/projects";
import { deleteScheduledAction, updateScheduledAction } from "@/api/scheduled-actions";
import {
  deleteWebPushSubscription,
  getWebPushConfig,
  listWebPushSubscriptions,
  registerWebPushSubscription,
} from "@/api/notifications";
import { mergeSavedMemories, updateSavedMemory } from "@/api/saved-memories";
import { absolutePath, api, apiPath } from "@/api/client";

afterEach(() => {
  vi.restoreAllMocks();
});

function makeJsonResponse(body: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

describe("frontend API modules", () => {
  test("chat API wrappers call the expected endpoints", async () => {
    const postSpy = vi
      .spyOn(api, "post")
      .mockResolvedValueOnce({ content: "reply", agent: "tools", metadata: {} })
      .mockResolvedValueOnce({
        request_id: "req-1",
        inspection: {
          engine: "hierarchical",
          historySummarized: false,
          prunedMessages: 0,
          prunedCharacters: 0,
          durableMemoryCandidates: [],
          ragChunksIncluded: 1,
          ragChunksFiltered: 0,
          totalTokensEstimate: 120,
          sections: [],
        },
      });

    await sendChatMessage("Plan my day", "voice");
    await inspectChatContext("Plan my day", "telegram");

    expect(postSpy).toHaveBeenNthCalledWith(1, apiPath(API_PATHS.apiChat), {
      content: "Plan my day",
      source: "voice",
    });
    expect(postSpy).toHaveBeenNthCalledWith(2, apiPath(API_PATHS.apiChatContextInspect), {
      content: "Plan my day",
      source: "telegram",
    });
  });

  test("dashboard API wrappers delegate through api.get with query params", async () => {
    const getSpy = vi
      .spyOn(api, "get")
      .mockResolvedValueOnce({ mood: {}, projects: {}, emails: {}, events: {} })
      .mockResolvedValueOnce({
        greeting: {},
        schedule: [],
        notifications: [],
        content: [],
        status: "ready",
        notices: [],
      })
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([]);

    await getDashboardStats();
    await getMorningBriefing();
    await getMoodEnergyTrends(14);
    await getRecentDiaryEntries(4);
    await getActiveGoals(6);
    await getRecentAgentActivity(8);

    expect(getSpy).toHaveBeenNthCalledWith(1, apiPath(API_PATHS.apiDashboardStats));
    expect(getSpy).toHaveBeenNthCalledWith(2, apiPath(API_PATHS.apiDashboardBriefing));
    expect(getSpy).toHaveBeenNthCalledWith(3, apiPath(API_PATHS.apiDashboardTrendsMoodEnergy), {
      days: 14,
    });
    expect(getSpy).toHaveBeenNthCalledWith(4, apiPath(API_PATHS.apiDashboardDiaryRecent), {
      limit: 4,
    });
    expect(getSpy).toHaveBeenNthCalledWith(5, apiPath(API_PATHS.apiDashboardGoals), {
      status: "active",
      limit: 6,
    });
    expect(getSpy).toHaveBeenNthCalledWith(6, apiPath(API_PATHS.apiDashboardActivityRecent), {
      limit: 8,
    });
  });

  test("monitoring health and preflight wrappers use absolute fetch paths", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(makeJsonResponse({ ok: true, services: { api: true } }))
      .mockResolvedValueOnce(
        makeJsonResponse({
          status: "warn",
          generated_at: "2026-04-07T12:00:00Z",
          checks: [],
        }),
      );

    await getHealth();
    await getPreflightReport();

    expect(fetchSpy).toHaveBeenNthCalledWith(1, absolutePath(API_PATHS.health), {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    expect(fetchSpy).toHaveBeenNthCalledWith(2, absolutePath(API_PATHS.healthPreflight), {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
  });

  test("monitoring health wrappers raise on non-ok responses", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response("boom", { status: 503 }))
      .mockResolvedValueOnce(new Response("fail", { status: 500 }));

    await expect(getHealth()).rejects.toThrow("Health check failed: 503");
    await expect(getPreflightReport()).rejects.toThrow("Preflight check failed: 500");

    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  test("monitoring API wrappers delegate through api.get with transformed params", async () => {
    const getSpy = vi
      .spyOn(api, "get")
      .mockResolvedValue({ status: "ok" } as never)
      .mockResolvedValueOnce({ items: [], total: 0, offset: 5, limit: 10, has_more: false })
      .mockResolvedValueOnce({
        cost: {},
        cost_trend: [],
        cost_by_model: [],
        cost_by_agent: [],
        tokens: {},
        latency_by_agent: [],
      })
      .mockResolvedValueOnce({ summaries: [], usage_distribution: [] })
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce({ id: "interaction-1" })
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce({ trace_id: "trace-1", spans: [] })
      .mockResolvedValueOnce({ generated_at: "2026-04-09T09:00:00Z" });

    await getAgentActions({
      limit: 10,
      offset: 5,
      agent: "memory",
      sort: "slowest",
      date_from: "2026-04-01",
    });
    await getLLMStats("30d");
    await getAgentComparison("today");
    await getPromptVersions();
    await getInteractionDetail("interaction-1");
    await getQualityScores({
      start: "2026-04-01",
      end: "2026-04-07",
      agent: "review",
    });
    await getTraceSummaries(12);
    await getEvalOutcomes(8);
    await getChannelMetrics(250);
    await getTraceDetail("trace-1");
    await getTelegramWebhookStatus();
    await getSecurityMetrics();

    expect(getSpy).toHaveBeenNthCalledWith(1, apiPath(API_PATHS.apiMonitoringActions), {
      limit: 10,
      offset: 5,
      agent: "memory",
      sort: "slowest",
      date_from: "2026-04-01",
    });
    expect(getSpy).toHaveBeenNthCalledWith(2, apiPath(API_PATHS.apiMonitoringLlmStats), {
      period: "30d",
    });
    expect(getSpy).toHaveBeenNthCalledWith(3, apiPath(API_PATHS.apiMonitoringAgentComparison), {
      period: "today",
    });
    expect(getSpy).toHaveBeenNthCalledWith(4, apiPath(API_PATHS.apiMonitoringPromptVersions));
    expect(getSpy).toHaveBeenNthCalledWith(
      5,
      apiPath(API_PATHS.apiMonitoringInteractionsByInteractionId, {
        interaction_id: "interaction-1",
      }),
    );
    expect(getSpy).toHaveBeenNthCalledWith(6, apiPath(API_PATHS.apiMonitoringQualityScores), {
      start: "2026-04-01",
      end: "2026-04-07",
      agent: "review",
    });
    expect(getSpy).toHaveBeenNthCalledWith(7, apiPath(API_PATHS.apiMonitoringTraces), {
      limit: 12,
    });
    expect(getSpy).toHaveBeenNthCalledWith(8, apiPath(API_PATHS.apiMonitoringEvalOutcomes), {
      limit: 8,
    });
    expect(getSpy).toHaveBeenNthCalledWith(9, apiPath(API_PATHS.apiMonitoringChannelMetrics), {
      limit: 250,
    });
    expect(getSpy).toHaveBeenNthCalledWith(
      10,
      apiPath(API_PATHS.apiMonitoringTracesByTraceId, {
        trace_id: "trace-1",
      }),
    );
    expect(getSpy).toHaveBeenNthCalledWith(11, apiPath(API_PATHS.apiMonitoringTelegramWebhook));
    expect(getSpy).toHaveBeenNthCalledWith(12, apiPath(API_PATHS.apiOpsSecurityMetrics));
  });

  test("projects API wrappers call the correct endpoints", async () => {
    const getSpy = vi
      .spyOn(api, "get")
      .mockResolvedValueOnce({ items: [], total: 0, offset: 0, limit: 5, has_more: false })
      .mockResolvedValueOnce({ id: "project-1" });
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ id: "project-2" });
    const patchSpy = vi.spyOn(api, "patch").mockResolvedValue({ id: "task-1" });

    await getProjects({
      limit: 5,
      sort: "deadline",
      order: "asc",
      status: "planning",
      appetite: "small",
    });
    await getProject("project-1");
    await createProject({
      title: "New project",
      appetite: "medium",
      deadline: "2026-05-01T12:00:00Z",
    });
    await updateTask("task-1", {
      title: "Refine scope",
      status: "in-progress",
      context_tags: ["focus"],
    });

    expect(getSpy).toHaveBeenNthCalledWith(1, apiPath(API_PATHS.apiProjects), {
      limit: 5,
      sort: "deadline",
      order: "asc",
      status: "planning",
      appetite: "small",
    });
    expect(getSpy).toHaveBeenNthCalledWith(
      2,
      apiPath(API_PATHS.apiProjectsByProjectId, { project_id: "project-1" }),
    );
    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiProjects), {
      title: "New project",
      appetite: "medium",
      deadline: "2026-05-01T12:00:00Z",
    });
    expect(patchSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiTasksByTaskId, { task_id: "task-1" }),
      {
        title: "Refine scope",
        status: "in-progress",
        context_tags: ["focus"],
      },
    );
  });

  test("saved-memory and scheduled-action mutation wrappers call the correct endpoints", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ id: "memory-1" });
    const patchSpy = vi
      .spyOn(api, "patch")
      .mockResolvedValueOnce({ id: "memory-1" })
      .mockResolvedValueOnce({ id: "action-1" });
    const deleteSpy = vi.spyOn(api, "delete").mockResolvedValue(undefined);

    await mergeSavedMemories({
      target_memory_id: "memory-1",
      source_memory_ids: ["memory-2", "memory-3"],
    });
    await updateSavedMemory("memory-1", {
      title: "Writing preference",
      mark_used: true,
    });
    await updateScheduledAction("action-1", {
      title: "Morning pulse",
      status: "paused",
    });
    await deleteScheduledAction("action-1");

    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiSavedMemoriesMerge), {
      target_memory_id: "memory-1",
      source_memory_ids: ["memory-2", "memory-3"],
    });
    expect(patchSpy).toHaveBeenNthCalledWith(
      1,
      apiPath(API_PATHS.apiSavedMemoriesByMemoryId, { memory_id: "memory-1" }),
      {
        title: "Writing preference",
        mark_used: true,
      },
    );
    expect(patchSpy).toHaveBeenNthCalledWith(
      2,
      apiPath(API_PATHS.apiScheduledActionsByActionId, { action_id: "action-1" }),
      {
        title: "Morning pulse",
        status: "paused",
      },
    );
    expect(deleteSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiScheduledActionsByActionId, { action_id: "action-1" }),
    );
  });

  test("web-push API wrappers call the correct endpoints", async () => {
    const getSpy = vi
      .spyOn(api, "get")
      .mockResolvedValueOnce({
        enabled: true,
        public_key: "public-key",
        active_subscription_count: 1,
      })
      .mockResolvedValueOnce([
        {
          id: "subscription-1",
          status: "active",
        },
      ]);
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ id: "subscription-1" });
    const deleteSpy = vi.spyOn(api, "delete").mockResolvedValue(undefined);

    await getWebPushConfig();
    await listWebPushSubscriptions();
    await registerWebPushSubscription({
      endpoint: "https://push.example/subscription",
      keys: {
        auth: "auth-key",
        p256dh: "p256dh-key",
      },
    });
    await deleteWebPushSubscription("subscription-1");

    expect(getSpy).toHaveBeenNthCalledWith(1, apiPath(API_PATHS.apiNotificationsPushConfig));
    expect(getSpy).toHaveBeenNthCalledWith(2, apiPath(API_PATHS.apiNotificationsPushSubscriptions));
    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiNotificationsPushSubscriptions), {
      endpoint: "https://push.example/subscription",
      keys: {
        auth: "auth-key",
        p256dh: "p256dh-key",
      },
    });
    expect(deleteSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiNotificationsPushSubscriptionsBySubscriptionId, {
        subscription_id: "subscription-1",
      }),
    );
  });
});
