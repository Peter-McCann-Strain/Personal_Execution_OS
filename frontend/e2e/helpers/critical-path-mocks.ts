import type { Page, Route } from "@playwright/test";

function jsonHeaders() {
  return {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-cache",
  };
}

async function fulfillJson(route: Route, data: unknown, status = 200) {
  await route.fulfill({
    status,
    headers: jsonHeaders(),
    body: JSON.stringify(data),
  });
}

async function fulfillSse(route: Route, body: string) {
  await route.fulfill({
    status: 200,
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache",
      connection: "keep-alive",
    },
    body,
  });
}

const IDEMPOTENT_POST_PATHS = new Set([
  "/api/commitments",
  "/api/contacts",
  "/api/content-assets",
  "/api/decisions",
  "/api/goals",
  "/api/habits",
  "/api/note-canvases",
  "/api/notes",
  "/api/projects",
  "/api/reviews/generate",
  "/api/saved-memories",
  "/api/saved-memories/merge",
  "/api/scheduled-actions",
]);

function protectedPostRequiresIdempotency(pathname: string, method: string) {
  if (method !== "POST") {
    return false;
  }

  return (
    IDEMPOTENT_POST_PATHS.has(pathname) ||
    /^\/api\/contacts\/[^/]+\/interactions$/.test(pathname) ||
    /^\/api\/content-assets\/[^/]+\/source-pack$/.test(pathname) ||
    /^\/api\/epics\/[^/]+\/milestones$/.test(pathname) ||
    /^\/api\/habits\/[^/]+\/complete$/.test(pathname) ||
    /^\/api\/notes\/daily\/[^/]+$/.test(pathname) ||
    /^\/api\/notes\/[^/]+\/links$/.test(pathname) ||
    /^\/api\/project-drafts\/[^/]+\/apply$/.test(pathname) ||
    /^\/api\/projects\/[^/]+\/epics$/.test(pathname) ||
    /^\/api\/scheduled-actions\/[^/]+\/run$/.test(pathname)
  );
}

function asNow(daysAgo: number): string {
  const date = new Date();
  date.setDate(date.getDate() - daysAgo);
  return date.toISOString();
}

function asTodayAt(hour: number, minute = 0): string {
  const date = new Date();
  date.setHours(hour, minute, 0, 0);
  return date.toISOString();
}

export async function installCriticalPathMocks(page: Page) {
  await page.route(/\/api\/.*/, async (route) => {
    const { pathname } = new URL(route.request().url());
    const method = route.request().method();

    if (!pathname.startsWith("/api/")) {
      await route.fallback();
      return;
    }

    if (
      protectedPostRequiresIdempotency(pathname, method) &&
      !route.request().headers()["idempotency-key"]
    ) {
      await fulfillJson(route, { detail: "Idempotency-Key header required" }, 400);
      return;
    }

    if (pathname === "/api/setup/status") {
      await fulfillJson(route, {
        initialized: new URL(page.url()).pathname !== "/setup",
        auth_mode: "local_owner",
      });
      return;
    }

    if (pathname === "/api/auth/session") {
      await fulfillJson(route, {
        authenticated: true,
        subject: "local-owner",
        role: "owner",
        expires_at: asNow(-1),
      });
      return;
    }

    if (pathname === "/api/dashboard/stats") {
      await fulfillJson(route, {
        mood: {
          value: 7.8,
          label: "Today's Mood",
          trend: 0.6,
          sparkline: [6.8, 7.1, 7.4, 7.5, 7.7, 7.8],
          subLabel: "Stable and rising",
          status: "available",
          message: null,
        },
        projects: {
          value: 4,
          label: "Active Projects",
          trend: 1,
          sparkline: [2, 3, 3, 4, 4, 4],
          subLabel: "Steady delivery",
          status: "available",
          message: null,
        },
        emails: {
          value: 9,
          label: "Unread Emails",
          trend: -2,
          sparkline: [15, 14, 12, 11, 10, 9],
          subLabel: "Inbox under control",
          status: "available",
          message: null,
        },
        events: {
          value: 2,
          label: "Events Today",
          trend: 0,
          sparkline: [1, 1, 2, 2, 2, 2],
          subLabel: "Two scheduled events",
          status: "available",
          message: null,
        },
      });
      return;
    }

    if (pathname === "/api/calendar/events") {
      await fulfillJson(route, [
        {
          id: "cal-today-1",
          summary: "Planning review",
          start: asTodayAt(9, 0),
          end: asTodayAt(9, 30),
          location: null,
          description: null,
          attendees: [],
        },
        {
          id: "cal-today-2",
          summary: "Deep work block",
          start: asTodayAt(11, 0),
          end: asTodayAt(12, 0),
          location: null,
          description: null,
          attendees: [],
        },
      ]);
      return;
    }

    if (pathname === "/api/commitments/open") {
      await fulfillJson(route, [
        {
          id: "commitment-open-1",
          verbatim_text: "Send the revised launch brief by noon",
          normalized_action: "Send the revised launch brief",
          who_committed: "me",
          who_to: "product team",
          temporal_expression_raw: "today at noon",
          temporal_normalized: asTodayAt(12, 0),
          commitment_type: "promise",
          confidence_score: 0.93,
          status: "acknowledged",
          created_at: asNow(1),
          updated_at: asNow(0),
        },
        {
          id: "commitment-open-2",
          verbatim_text: "Check the finance renewal notes",
          normalized_action: "Check the finance renewal notes",
          who_committed: "me",
          who_to: null,
          temporal_expression_raw: "this afternoon",
          temporal_normalized: asTodayAt(15, 0),
          commitment_type: "reminder",
          confidence_score: 0.88,
          status: "detected",
          created_at: asNow(2),
          updated_at: asNow(0),
        },
      ]);
      return;
    }

    if (pathname === "/api/commitments/overdue") {
      await fulfillJson(route, [
        {
          id: "commitment-overdue-1",
          verbatim_text: "Reply to Maria about the design review",
          normalized_action: "Reply to Maria about the design review",
          who_committed: "me",
          who_to: "Maria",
          temporal_expression_raw: "yesterday",
          temporal_normalized: asNow(1),
          commitment_type: "promise",
          confidence_score: 0.91,
          status: "acknowledged",
          created_at: asNow(3),
          updated_at: asNow(1),
        },
      ]);
      return;
    }

    if (/^\/api\/commitments\/[^/]+\/status$/.test(pathname)) {
      await fulfillJson(route, {
        id: pathname.split("/")[3],
        verbatim_text: "Reply to Maria about the design review",
        normalized_action: "Reply to Maria about the design review",
        who_committed: "me",
        who_to: "Maria",
        temporal_expression_raw: "yesterday",
        temporal_normalized: asNow(1),
        commitment_type: "promise",
        confidence_score: 0.91,
        status: "completed",
        created_at: asNow(3),
        updated_at: asNow(0),
      });
      return;
    }

    if (pathname === "/api/habits") {
      await fulfillJson(route, [
        {
          id: "habit-1",
          name: "Evening review",
          description: "Close the day and capture loose ends",
          frequency: "daily",
          frequency_days: null,
          current_streak: 6,
          longest_streak: 14,
          total_completions: 42,
          last_completed_at: asNow(2),
          active: true,
          tags: ["review"],
          created_at: asNow(30),
        },
      ]);
      return;
    }

    if (/^\/api\/habits\/[^/]+\/complete$/.test(pathname)) {
      await fulfillJson(route, {
        id: "habit-log-1",
        habit_id: pathname.split("/")[3],
        completed_at: asNow(0),
        note: null,
        source: "api",
      });
      return;
    }

    if (pathname === "/api/dashboard/briefing") {
      await fulfillJson(route, {
        greeting: {
          greeting: "Good morning",
          dateString: "Tuesday 7 April 2026",
          cognitiveLoad: 4,
          summary: "Steady context with a clear priority stack.",
        },
        schedule: [
          {
            id: "cal-1",
            summary: "Standup with the product team",
            start: "2026-04-07T09:00:00.000Z",
            end: "2026-04-07T09:30:00.000Z",
            location: null,
            description: null,
            attendees: [],
          },
          {
            id: "cal-2",
            summary: "Deep work: agent routing",
            start: "2026-04-07T10:00:00.000Z",
            end: "2026-04-07T11:30:00.000Z",
            location: null,
            description: null,
            attendees: [],
          },
        ],
        notifications: [
          {
            id: "notif-1",
            category: "task",
            priority: "P0",
            message: "Follow up on the deployment review.",
            created_at: asNow(0),
            dismissed: false,
          },
          {
            id: "notif-2",
            category: "calendar",
            priority: "P1",
            message: "Calendar conflict detected at 15:00.",
            created_at: asNow(1),
            dismissed: false,
          },
        ],
        content: [
          {
            title: "OpenClaw context compaction notes",
            source: "Research digest",
            url: "https://example.com/context",
            relevance: 0.91,
          },
          {
            title: "Agent runtime hardening checklist",
            source: "Internal memo",
            url: "https://example.com/runtime",
            relevance: 0.84,
          },
        ],
        status: "ready",
        notices: [
          {
            source: "calendar",
            status: "available",
            message: "Calendar sync is healthy",
          },
          {
            source: "notifications",
            status: "available",
            message: "Priority notifications loaded",
          },
        ],
      });
      return;
    }

    if (pathname === "/api/dashboard/diary/recent") {
      await fulfillJson(route, [
        {
          id: "episode-1",
          content: "Captured a strong plan for the next release.",
          summary: "Captured a strong plan for the next release.",
          episode_type: "diary",
          para_category: "project",
          mood_score: 7.4,
          energy_rating: 6.9,
          tags: ["release", "planning"],
          people_mentioned: [],
          source: "api",
          created_at: asNow(0),
        },
        {
          id: "episode-2",
          content: "Worked through the remaining coverage gaps.",
          summary: "Worked through the remaining coverage gaps.",
          episode_type: "diary",
          para_category: "area",
          mood_score: 7.1,
          energy_rating: 6.4,
          tags: ["quality", "tests"],
          people_mentioned: [],
          source: "api",
          created_at: asNow(1),
        },
      ]);
      return;
    }

    if (pathname === "/api/episodes/stats") {
      await fulfillJson(route, {
        totalEntries: 0,
        averageMood: null,
        averageEnergy: null,
        moodTrend: [],
        tagFrequency: [],
        paraDistribution: [],
      });
      return;
    }

    if (pathname === "/api/episodes") {
      await fulfillJson(route, {
        items: [],
        total: 0,
        page: 1,
        page_size: 20,
        has_more: false,
      });
      return;
    }

    if (pathname === "/api/saved-memories") {
      await fulfillJson(route, {
        items: [],
        total: 0,
        page: 1,
        page_size: 12,
        has_more: false,
      });
      return;
    }

    if (pathname === "/api/goals") {
      await fulfillJson(route, {
        items: [
          {
            id: "goal-1",
            title: "Finish phase 4 quality gates",
            goal_type: "project",
            parent_id: null,
            priority: 1,
            status: "active",
            progress: 72,
            deadline: asTodayAt(18, 0),
            evidence: [],
            created_at: asNow(14),
            updated_at: asNow(0),
          },
          {
            id: "goal-2",
            title: "Rebuild the personal operating system",
            goal_type: "area",
            parent_id: null,
            priority: 2,
            status: "active",
            progress: 28,
            deadline: asNow(-7),
            evidence: [],
            created_at: asNow(21),
            updated_at: asNow(2),
          },
        ],
        total: 2,
        page: 1,
        page_size: 100,
        has_more: false,
      });
      return;
    }

    if (pathname === "/api/project-drafts") {
      await fulfillJson(route, {
        items: [],
        total: 0,
        page: 1,
        page_size: 50,
        has_more: false,
      });
      return;
    }

    if (pathname === "/api/projects") {
      await fulfillJson(route, {
        items: [
          {
            id: "project-1",
            title: "Assistant frontend quality pass",
            description: "Tighten dashboard, navigation, and personal planning flows.",
            status: "in-progress",
            appetite: "medium",
            deadline: asTodayAt(17, 0),
            created_at: asNow(10),
            updated_at: asNow(0),
            epics: [
              {
                id: "epic-1",
                project_id: "project-1",
                title: "Workbench",
                description: null,
                sort_order: 1,
                created_at: asNow(10),
                milestones: [
                  {
                    id: "milestone-1",
                    epic_id: "epic-1",
                    title: "Saved views",
                    success_criteria: "Unified records render as list, board, and timeline.",
                    sort_order: 1,
                    created_at: asNow(8),
                    tasks: [
                      {
                        id: "task-1",
                        milestone_id: "milestone-1",
                        title: "Wire Workbench route and navigation",
                        description: null,
                        status: "done",
                        estimate_hours: 1,
                        actual_hours: 1,
                        wsjf_score: 8,
                        complexity: "low",
                        context_tags: ["frontend"],
                        blocked_reason: null,
                        dependency_task_ids: [],
                        sort_order: 1,
                        started_at: asNow(1),
                        completed_at: asNow(0),
                        created_at: asNow(8),
                      },
                      {
                        id: "task-2",
                        milestone_id: "milestone-1",
                        title: "Add saved view filtering",
                        description: "Support Today, At Risk, Projects, Knowledge, and All views.",
                        status: "in_progress",
                        estimate_hours: 2,
                        actual_hours: null,
                        wsjf_score: 13,
                        complexity: "medium",
                        context_tags: ["frontend", "views"],
                        blocked_reason: null,
                        dependency_task_ids: [],
                        sort_order: 2,
                        started_at: asNow(0),
                        completed_at: null,
                        created_at: asNow(8),
                      },
                    ],
                  },
                ],
              },
            ],
          },
        ],
        total: 1,
        page: 1,
        page_size: 50,
        has_more: false,
      });
      return;
    }

    if (pathname === "/api/notes") {
      await fulfillJson(route, {
        items: [
          {
            id: "note-1",
            title: "Personal Execution OS frontend notes",
            slug: "execution-os-frontend-notes",
            aliases: [],
            kind: "note",
            daily_date: null,
            frontmatter: {},
            content: "A workbench should support saved views, filtering, and rapid triage.",
            note_type: "permanent",
            para_category: "resource",
            progressive_summary_level: 1,
            executive_summary: "Saved views and quick switching are the main UX gap.",
            source_url: null,
            tags: ["frontend", "workbench"],
            created_at: asNow(4),
            updated_at: asNow(0),
          },
        ],
        total: 1,
        page: 1,
        page_size: 60,
        has_more: false,
      });
      return;
    }

    if (pathname === "/api/dashboard/goals") {
      await fulfillJson(route, [
        {
          id: "goal-1",
          title: "Finish phase 4 quality gates",
          goal_type: "project",
          parent_id: null,
          priority: 1,
          status: "active",
          progress: 72,
          deadline: null,
          evidence: [],
          created_at: asNow(14),
          updated_at: asNow(0),
        },
        {
          id: "goal-2",
          title: "Ship world-class runtime scaffolding",
          goal_type: "project",
          parent_id: null,
          priority: 1,
          status: "active",
          progress: 88,
          deadline: null,
          evidence: [],
          created_at: asNow(14),
          updated_at: asNow(0),
        },
      ]);
      return;
    }

    if (pathname === "/api/dashboard/activity/recent") {
      await fulfillJson(route, [
        {
          id: "action-1",
          agent_name: "review",
          action_type: "review_comparison",
          model_used: "claude-sonnet-4.5",
          tokens_in: 842,
          tokens_out: 221,
          cost_usd: 0.042,
          duration_ms: 1840,
          input_summary: "Compared open review items",
          output_summary: "Approved the latest plan changes.",
          trace_id: "trace-1",
          created_at: asNow(0),
        },
        {
          id: "action-2",
          agent_name: "memory",
          action_type: "context_flush",
          model_used: "claude-sonnet-4.5",
          tokens_in: 613,
          tokens_out: 142,
          cost_usd: 0.028,
          duration_ms: 1125,
          input_summary: "Flushed durable memory candidates",
          output_summary: "Stored decision and preference updates.",
          trace_id: "trace-2",
          created_at: asNow(1),
        },
      ]);
      return;
    }

    if (pathname === "/api/dashboard/trends/mood-energy") {
      await fulfillJson(route, [
        {
          date: "2026-04-01",
          mood: 6.1,
          energy: 5.9,
        },
        {
          date: "2026-04-02",
          mood: 6.6,
          energy: 6.2,
        },
        {
          date: "2026-04-03",
          mood: 6.9,
          energy: 6.5,
        },
        {
          date: "2026-04-04",
          mood: 7.0,
          energy: 6.6,
        },
        {
          date: "2026-04-05",
          mood: 7.4,
          energy: 6.8,
        },
        {
          date: "2026-04-06",
          mood: 7.8,
          energy: 7.1,
        },
      ]);
      return;
    }

    if (pathname === "/api/monitoring/prompt-versions") {
      await fulfillJson(route, [
        {
          kind: "supervisor",
          agent: "supervisor",
          prompt_version: "supervisor.v12",
          prompt_source: "prompts/supervisor/v12.md",
          model_policy: "claude-sonnet-4.5",
          eval_rubric_id: "supervisor.v3",
          memory_namespace: "supervisor",
          confirmation_policy: "on_mutation",
          allowed_tool_patterns: ["api:*", "db:*"],
        },
        {
          kind: "specialist",
          agent: "memory",
          prompt_version: "memory.v8",
          prompt_source: "prompts/memory/v8.md",
          model_policy: "claude-sonnet-4.5",
          eval_rubric_id: "memory.v4",
          memory_namespace: "memory",
          confirmation_policy: "always",
          allowed_tool_patterns: ["memory:*", "search:*"],
        },
        {
          kind: "specialist",
          agent: "research",
          prompt_version: null,
          prompt_source: "prompts/research/draft.md",
          model_policy: "claude-sonnet-4.5",
          eval_rubric_id: null,
          memory_namespace: "research",
          confirmation_policy: null,
          allowed_tool_patterns: [],
        },
      ]);
      return;
    }

    if (pathname === "/api/chat/context-inspect") {
      await fulfillJson(route, {
        request_id: "req-ctx-1",
        inspection: {
          engine: "hierarchical",
          historySummarized: true,
          prunedMessages: 2,
          prunedCharacters: 420,
          durableMemoryCandidates: [
            {
              category: "preference",
              excerpt: "User prefers a fast, practical execution cadence.",
              sourceRole: "user",
            },
            {
              category: "decision",
              excerpt: "Keep Python as the agent runtime and React as the UI.",
              sourceRole: "assistant",
            },
          ],
          ragChunksIncluded: 4,
          ragChunksFiltered: 1,
          totalTokensEstimate: 6142,
          sections: [
            { name: "system", tokens: 820, itemCount: 1, present: true },
            { name: "summary", tokens: 560, itemCount: 1, present: true },
            { name: "recent_history", tokens: 1740, itemCount: 8, present: true },
            { name: "retrieval", tokens: 720, itemCount: 4, present: true },
            { name: "durable_memory", tokens: 420, itemCount: 2, present: true },
            { name: "budget", tokens: 1882, itemCount: null, present: true },
          ],
        },
      });
      return;
    }

    if (pathname === "/api/chat/stream") {
      await fulfillSse(
        route,
        [
          `event: message_start`,
          `data: ${JSON.stringify({ request_id: "req-chat-1", source: "api" })}`,
          "",
          `event: agent`,
          `data: ${JSON.stringify({ agent: "communications" })}`,
          "",
          `event: token`,
          `data: ${JSON.stringify({ content: "Here is a concise plan." })}`,
          "",
          `event: tool_status`,
          `data: ${JSON.stringify({
            tool_calls: [{ name: "calendar.lookup", result: "2 upcoming events" }],
            tool_count: 1,
            errors: 0,
          })}`,
          "",
          `event: message_end`,
          `data: ${JSON.stringify({
            content: "Here is a concise plan.",
            agent: "communications",
            metadata: {
              tool_calls: [{ name: "calendar.lookup", result: "2 upcoming events" }],
            },
          })}`,
          "",
        ].join("\n"),
      );
      return;
    }

    if (pathname === "/api/runtime/stream") {
      await fulfillSse(
        route,
        [
          "event: runtime_open",
          `data: ${JSON.stringify({ request_id: "runtime-e2e-1" })}`,
          "",
          "event: runtime_heartbeat",
          `data: ${JSON.stringify({ status: "ok" })}`,
          "",
        ].join("\n"),
      );
      return;
    }

    if (pathname === "/api/ops/assistant-native-metrics") {
      await fulfillJson(route, {
        generated_at: asNow(0),
        interaction_sample_size: 24,
        continuity_resolution_count: 18,
        continuity_retry_replayed_count: 3,
        continuity_duplicate_prevented_count: 2,
        continuity_note_reference_resolved_count: 9,
        assistant_receipt_count: 17,
        pending_action_cleared_count: 5,
        project_draft_created_interaction_count: 4,
        project_drafts_total: 8,
        project_drafts_applied: 5,
        notes_total: 37,
        daily_notes_total: 12,
        moc_notes_total: 4,
        canvases_total: 3,
        note_links_total: 22,
        wiki_links_total: 9,
        manual_links_total: 8,
        semantic_links_total: 14,
        content_assets_total: 11,
        content_assets_ready_total: 4,
        content_assets_in_progress_total: 3,
        content_assets_needs_review_total: 2,
        content_assets_done_total: 2,
        notebooklm_podcast_total: 1,
        saved_memories_total: 18,
        pinned_memories_total: 6,
        connector_accounts_total: 3,
        connector_documents_total: 128,
        scheduled_actions_total: 7,
        scheduled_actions_active_total: 5,
        scheduled_action_runs_total: 42,
        approval_requests_pending_total: 1,
        browser_sessions_total: 6,
      });
      return;
    }

    if (pathname === "/api/ops/assistant-native-evals") {
      await fulfillJson(route, {
        generated_at: asNow(0),
        dataset_id: "assistant-native-smoke",
        version: "2026-04-24",
        dataset_path: "tests/fixtures/assistant-native.jsonl",
        passing: true,
        case_count: 6,
        pass_count: 6,
        pass_rate: 1,
        baseline_pass_count: 4,
        baseline_pass_rate: 0.67,
        baseline_lift: 0.33,
        minimum_pass_rate_target: 0.9,
        minimum_baseline_lift_target: 0.1,
        minimum_case_count_target: 5,
        failing_case_ids: [],
        asset_errors: [],
        cases: [],
      });
      return;
    }

    if (pathname === "/api/scheduled-actions/runs") {
      await fulfillJson(route, []);
      return;
    }

    if (pathname === "/api/scheduled-actions") {
      await fulfillJson(route, {
        items: [],
        total: 0,
        limit: 25,
        offset: 0,
        has_more: false,
      });
      return;
    }

    if (pathname === "/api/entities/relationships") {
      await fulfillJson(route, []);
      return;
    }

    if (pathname === "/api/entities") {
      await fulfillJson(route, []);
      return;
    }

    if (pathname === "/api/note-canvases") {
      await fulfillJson(route, {
        items: [],
        total: 0,
        limit: 25,
        offset: 0,
        has_more: false,
      });
      return;
    }

    if (pathname === "/api/reviews") {
      await fulfillJson(route, {
        items: [],
        total: 0,
        limit: 25,
        offset: 0,
        has_more: false,
      });
      return;
    }

    if (pathname === "/api/decisions/due-review") {
      await fulfillJson(route, []);
      return;
    }

    if (pathname === "/api/decisions") {
      await fulfillJson(route, {
        items: [],
        total: 0,
        limit: 25,
        offset: 0,
        has_more: false,
      });
      return;
    }

    if (pathname === "/api/contacts") {
      await fulfillJson(route, {
        items: [],
        total: 0,
        limit: 50,
        offset: 0,
        has_more: false,
      });
      return;
    }

    if (pathname === "/api/email/inbox") {
      await fulfillJson(route, {
        items: [],
        total: 0,
        limit: 50,
        offset: 0,
        has_more: false,
      });
      return;
    }

    if (pathname === "/api/tutorials") {
      await fulfillJson(route, {
        items: [],
        total: 0,
        limit: 25,
        offset: 0,
        has_more: false,
      });
      return;
    }

    if (pathname === "/api/content-assets") {
      await fulfillJson(route, {
        items: [],
        total: 0,
        limit: 50,
        offset: 0,
        has_more: false,
      });
      return;
    }

    if (pathname === "/api/notifications/push/config") {
      await fulfillJson(route, {
        enabled: false,
        public_key: null,
        active_subscription_count: 0,
      });
      return;
    }

    if (pathname === "/api/notifications/push/subscriptions") {
      await fulfillJson(route, []);
      return;
    }

    if (pathname === "/api/agent-runs") {
      await fulfillJson(route, {
        items: [],
        total: 0,
        limit: 12,
        offset: 0,
        has_more: false,
      });
      return;
    }

    if (pathname === "/api/notifications/unread-count") {
      await fulfillJson(route, {
        total: 3,
        hasP0: true,
        hasP1: true,
      });
      return;
    }

    if (pathname === "/api/notifications") {
      await fulfillJson(route, {
        items: [],
        total: 0,
        page: 1,
        page_size: 5,
      });
      return;
    }

    throw new Error(`Unhandled API mock: ${pathname}`);
  });

  await page.route("**/health**", async (route) => {
    const { pathname } = new URL(route.request().url());

    if (pathname !== "/health" && pathname !== "/health/preflight") {
      await route.fallback();
      return;
    }

    if (pathname === "/health") {
      await fulfillJson(route, {
        status: "ok",
        services: {
          database: { status: "ok", message: "Healthy" },
          redis: { status: "ok", message: "Healthy" },
          ollama: { status: "unknown", message: "Not configured" },
          anthropic: { status: "ok", message: "Configured" },
          google_calendar: { status: "unknown", message: "Not configured" },
          gmail: { status: "unknown", message: "Not configured" },
          tavily: { status: "unknown", message: "Not configured" },
          posthog: { status: "ok", message: "Telemetry enabled" },
          sentry: { status: "ok", message: "Telemetry enabled" },
          telegram: { status: "ok", message: "Webhook healthy" },
        },
      });
      return;
    }

    if (pathname === "/health/preflight") {
      await fulfillJson(route, {
        status: "ok",
        generated_at: "2026-04-07T10:00:00.000Z",
        checks: [
          {
            name: "database_connection",
            status: "ok",
            message: "PostgreSQL is reachable",
            required: true,
            details: { pool: "ready" },
          },
          {
            name: "redis_connection",
            status: "ok",
            message: "Redis is reachable",
            required: true,
            details: { pool: "ready" },
          },
          {
            name: "mcp_servers",
            status: "warn",
            message: "Some optional MCP servers are not configured",
            required: false,
            details: { configured: 3, expected: 5 },
          },
        ],
      });
      return;
    }

    throw new Error(`Unhandled health mock: ${pathname}`);
  });
}
