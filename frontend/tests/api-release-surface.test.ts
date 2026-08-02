import { afterEach, describe, expect, test, vi } from "vitest";

import {
  createCoreDataExport,
  downloadCoreDataExport,
  listCoreDataExports,
} from "@/api/account-data";
import { getCurrentPrincipal } from "@/api/account";
import {
  approveAgentRunRequest,
  getAgentRun,
  getAgentRuns,
  rejectAgentRunRequest,
} from "@/api/agent-runs";
import {
  changeOwnerPassword,
  getCurrentSession,
  getSetupStatus,
  initializeOwner,
  loginWithPassword,
  logoutCurrentSession,
  revokeAllOwnerSessions,
} from "@/api/auth";
import { api, apiPath } from "@/api/client";
import {
  deleteConnectorAccount,
  listConnectorAccounts,
  listConnectorDocuments,
  listConnectorSyncJobs,
  startGoogleOAuth,
  syncConnectorAccount,
  updateConnectorAccount,
} from "@/api/connectors";
import {
  createContentAsset,
  generateContentAssetSourcePack,
  getContentAssets,
  updateContentAsset,
} from "@/api/content-assets";
import { API_PATHS } from "@/api/generated/paths";
import { getEntities, searchMemory } from "@/api/memory";
import { getAssistantNativeEvalSummary, getAssistantNativeMetrics } from "@/api/monitoring";
import {
  createNote,
  createNoteCanvas,
  createNoteLink,
  deleteNote,
  getBacklinkedNotes,
  getDailyNote,
  getLinkedNotes,
  getNote,
  getNoteCanvas,
  getNoteGraph,
  getUnlinkedMentions,
  listNoteCanvases,
  listNotes,
  searchNotes,
  updateNote,
  updateNoteCanvas,
  upsertDailyNote,
} from "@/api/notes";
import {
  applyProjectDraft,
  createProject,
  getProject,
  getProjectDrafts,
  getProjects,
  updateTask,
} from "@/api/projects";
import {
  createSavedMemory,
  deleteSavedMemory,
  listSavedMemories,
  mergeSavedMemories,
  updateSavedMemory,
} from "@/api/saved-memories";
import {
  createScheduledAction,
  deleteScheduledAction,
  listScheduledActionRuns,
  listScheduledActions,
  runScheduledActionNow,
  updateScheduledAction,
} from "@/api/scheduled-actions";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("release-surface API clients", () => {
  test("account export, principal, and local-auth clients preserve paths and credential bodies", async () => {
    const principal = {
      subject: "owner",
      user_id: "user-1",
      account_id: "account-1",
      role: "owner",
      plan: "community",
      scopes: ["account:user"],
      auth_method: "local_owner",
    };
    const getSpy = vi
      .spyOn(api, "get")
      .mockResolvedValue({} as never)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce({ format: "personal-execution-os.core-data-export.v1" })
      .mockResolvedValueOnce(principal);
    const postSpy = vi
      .spyOn(api, "post")
      .mockResolvedValue({} as never)
      .mockResolvedValueOnce({ id: "export-1", status: "queued" });

    const exports = await listCoreDataExports();
    const created = await createCoreDataExport();
    const downloaded = await downloadCoreDataExport("export id/with spaces");
    const currentPrincipal = await getCurrentPrincipal();
    await getSetupStatus();
    await initializeOwner("initial-password");
    await loginWithPassword("current-password");
    await getCurrentSession();
    await logoutCurrentSession();
    await changeOwnerPassword("current-password", "replacement-password");
    await revokeAllOwnerSessions("replacement-password");

    expect(exports).toEqual([]);
    expect(created).toEqual(expect.objectContaining({ id: "export-1", status: "queued" }));
    expect(downloaded).toEqual({
      format: "personal-execution-os.core-data-export.v1",
    });
    expect(currentPrincipal).toBe(principal);

    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiAccountCoreDataExports));
    expect(getSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiAccountCoreDataExportsByExportIdDownload, {
        export_id: "export id/with spaces",
      }),
    );
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiAccountMe));
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiSetupStatus));
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiAuthSession));

    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiAccountCoreDataExports));
    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiSetupInitialize), {
      password: "initial-password",
    });
    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiAuthLogin), {
      password: "current-password",
    });
    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiAuthLogout));
    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiAuthChangePassword), {
      current_password: "current-password",
      new_password: "replacement-password",
    });
    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiAuthSessionsRevokeAll), {
      current_password: "replacement-password",
    });
  });

  test("agent-run clients cover default and filtered lists plus encoded approval actions", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({} as never);
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({} as never);

    await getAgentRuns();
    await getAgentRuns({ limit: 20, offset: 10, status: "waiting_for_approval" });
    await getAgentRun("workflow/with spaces");
    await approveAgentRunRequest("workflow/with spaces", "approval one");
    await rejectAgentRunRequest("workflow/with spaces", "approval two");

    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiAgentRuns), {});
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiAgentRuns), {
      limit: 20,
      offset: 10,
      status: "waiting_for_approval",
    });
    expect(getSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiAgentRunsByWorkflowId, {
        workflow_id: "workflow/with spaces",
      }),
    );
    expect(postSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiAgentRunsByWorkflowIdApprovalsByApprovalIdApprove, {
        workflow_id: "workflow/with spaces",
        approval_id: "approval one",
      }),
    );
    expect(postSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiAgentRunsByWorkflowIdApprovalsByApprovalIdReject, {
        workflow_id: "workflow/with spaces",
        approval_id: "approval two",
      }),
    );
  });

  test("connector clients preserve optional defaults, filters, OAuth encoding, and mutation bodies", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({} as never);
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({} as never);
    const patchSpy = vi.spyOn(api, "patch").mockResolvedValue({} as never);
    const deleteSpy = vi.spyOn(api, "delete").mockResolvedValue(undefined);
    const updateData = {
      display_name: "Primary Gmail",
      sync_enabled: false,
    };

    await listConnectorAccounts();
    await startGoogleOAuth("gmail & calendar");
    await updateConnectorAccount("account/one", updateData);
    await deleteConnectorAccount("account/one");
    await syncConnectorAccount("account/one");
    await syncConnectorAccount("account/one", {
      sync_type: "incremental",
      max_items: 250,
    });
    await listConnectorSyncJobs();
    await listConnectorDocuments();
    await listConnectorDocuments({
      limit: 25,
      offset: 5,
      account_id: "account/one",
      source_type: "gmail_message",
      search: "launch plan",
    });

    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiConnectorsAccounts));
    expect(postSpy).toHaveBeenCalledWith(
      `${apiPath(API_PATHS.apiConnectorsOauthGoogleStart)}?connector_type=gmail%20%26%20calendar`,
      undefined,
    );
    expect(patchSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiConnectorsAccountsByAccountId, {
        account_id: "account/one",
      }),
      updateData,
    );
    expect(deleteSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiConnectorsAccountsByAccountId, {
        account_id: "account/one",
      }),
    );
    expect(postSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiConnectorsAccountsByAccountIdSync, {
        account_id: "account/one",
      }),
      {},
    );
    expect(postSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiConnectorsAccountsByAccountIdSync, {
        account_id: "account/one",
      }),
      { sync_type: "incremental", max_items: 250 },
    );
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiConnectorsSyncJobs));
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiConnectorsDocuments), {});
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiConnectorsDocuments), {
      limit: 25,
      offset: 5,
      account_id: "account/one",
      source_type: "gmail_message",
      search: "launch plan",
    });
  });

  test("note clients cover collection, graph, links, daily-note, and canvas contracts", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({} as never);
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({} as never);
    const patchSpy = vi.spyOn(api, "patch").mockResolvedValue({} as never);
    const deleteSpy = vi.spyOn(api, "delete").mockResolvedValue(undefined);
    const createData = {
      title: "Release map",
      content: "Milestones and risks",
      note_type: "research" as const,
      para_category: "project" as const,
      tags: ["release"],
      slug: "release-map",
      aliases: ["Launch map"],
      kind: "note" as const,
      frontmatter: { owner: "team" },
    };
    const linkData = {
      target_note_id: "note two",
      link_reason: "Shared release context",
      similarity_score: 0.82,
      auto_discovered: false,
      link_type: "manual",
      origin: "manual",
    };
    const dailyData = {
      title: "Daily note",
      content: "Progress update",
      tags: ["daily"],
      frontmatter: { energy: 7 },
    };
    const canvasData = {
      title: "Launch canvas",
      description: "Dependencies",
      primary_note_id: "note one",
      nodes: [{ id: "node-1" }],
      edges: [{ id: "edge-1" }],
      viewport: { x: 0, y: 0, zoom: 1 },
    };

    await listNotes();
    await listNotes({
      limit: 20,
      offset: 5,
      search: "launch",
      note_type: "research",
      para_category: "project",
      kind: "note",
    });
    await searchNotes("release map");
    await searchNotes("release map", 6);
    await getNoteGraph();
    await getNoteGraph({ note_id: "note one", depth: 2, limit: 40, kind: "moc" });
    await createNote(createData);
    await getNote("note one");
    await updateNote("note one", { title: "Updated release map" });
    await deleteNote("note one");
    await getLinkedNotes("note one");
    await getBacklinkedNotes("note one");
    await getUnlinkedMentions("note one");
    await getUnlinkedMentions("note one", 3);
    await createNoteLink("note one", linkData);
    await getDailyNote("2026-08-02");
    await upsertDailyNote("2026-08-02", dailyData);
    await listNoteCanvases();
    await listNoteCanvases(5, 10);
    await getNoteCanvas("canvas one");
    await createNoteCanvas(canvasData);
    await updateNoteCanvas("canvas one", {
      description: "Updated dependencies",
      viewport: { x: 10, y: 20, zoom: 1.5 },
    });

    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiNotes), {});
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiNotes), {
      limit: 20,
      offset: 5,
      search: "launch",
      note_type: "research",
      para_category: "project",
      kind: "note",
    });
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiNotesSearch), {
      q: "release map",
    });
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiNotesSearch), {
      q: "release map",
      limit: 6,
    });
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiNotesGraph), {});
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiNotesGraph), {
      note_id: "note one",
      depth: 2,
      limit: 40,
      kind: "moc",
    });
    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiNotes), createData);
    expect(getSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiNotesByNoteId, { note_id: "note one" }),
    );
    expect(patchSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiNotesByNoteId, { note_id: "note one" }),
      { title: "Updated release map" },
    );
    expect(deleteSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiNotesByNoteId, { note_id: "note one" }),
    );
    expect(getSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiNotesByNoteIdLinks, { note_id: "note one" }),
    );
    expect(getSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiNotesByNoteIdBacklinks, { note_id: "note one" }),
    );
    expect(getSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiNotesByNoteIdUnlinkedMentions, {
        note_id: "note one",
      }),
      { limit: 10 },
    );
    expect(getSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiNotesByNoteIdUnlinkedMentions, {
        note_id: "note one",
      }),
      { limit: 3 },
    );
    expect(postSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiNotesByNoteIdLinks, { note_id: "note one" }),
      linkData,
    );
    expect(getSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiNotesDailyByNoteDate, {
        note_date: "2026-08-02",
      }),
    );
    expect(postSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiNotesDailyByNoteDate, {
        note_date: "2026-08-02",
      }),
      dailyData,
    );
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiNoteCanvases), {
      limit: 25,
      offset: 0,
    });
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiNoteCanvases), {
      limit: 5,
      offset: 10,
    });
    expect(getSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiNoteCanvasesByCanvasId, {
        canvas_id: "canvas one",
      }),
    );
    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiNoteCanvases), canvasData);
    expect(patchSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiNoteCanvasesByCanvasId, {
        canvas_id: "canvas one",
      }),
      {
        description: "Updated dependencies",
        viewport: { x: 10, y: 20, zoom: 1.5 },
      },
    );
  });

  test("project clients cover list defaults, drafts, application, and task updates", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({} as never);
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({} as never);
    const patchSpy = vi.spyOn(api, "patch").mockResolvedValue({} as never);
    const createData = {
      title: "Public preview",
      description: "Prepare the supported release",
      appetite: "medium" as const,
      deadline: "2026-08-31T17:00:00Z",
    };
    const taskUpdate = {
      title: "Verify release",
      description: "Run the complete release gate",
      status: "in_progress" as const,
      estimate_hours: 3,
      actual_hours: 1,
      wsjf_score: 8,
      context_tags: ["release", "quality"],
      blocked_reason: "",
      dependency_task_ids: ["task zero"],
    };

    await getProjects();
    await getProjects({
      limit: 12,
      offset: 6,
      sort: "deadline",
      order: "asc",
      status: "active",
      appetite: "medium",
    });
    await getProject("project one");
    await createProject(createData);
    await getProjectDrafts();
    await getProjectDrafts({
      limit: 10,
      offset: 2,
      status: "ready",
      user_id: "user one",
    });
    await applyProjectDraft("draft one");
    await updateTask("task one", taskUpdate);

    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiProjects), {});
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiProjects), {
      limit: 12,
      offset: 6,
      sort: "deadline",
      order: "asc",
      status: "active",
      appetite: "medium",
    });
    expect(getSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiProjectsByProjectId, { project_id: "project one" }),
    );
    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiProjects), createData);
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiProjectDrafts), {});
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiProjectDrafts), {
      limit: 10,
      offset: 2,
      status: "ready",
      user_id: "user one",
    });
    expect(postSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiProjectDraftsByDraftIdApply, {
        draft_id: "draft one",
      }),
    );
    expect(patchSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiTasksByTaskId, { task_id: "task one" }),
      taskUpdate,
    );
  });

  test("content-asset and saved-memory clients preserve filters, bodies, and encoded identifiers", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({} as never);
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({} as never);
    const patchSpy = vi.spyOn(api, "patch").mockResolvedValue({} as never);
    const deleteSpy = vi.spyOn(api, "delete").mockResolvedValue(undefined);
    const assetData = {
      title: "Launch brief",
      note_id: "note one",
      project_id: "project one",
      asset_type: "brief",
      status: "draft",
      source_pack: { sources: ["research"] },
      template_prompt: "Summarize the release evidence",
      run_notes: "Prefer primary sources",
      metadata: { audience: "public" },
    };
    const memoryData = {
      title: "Release preference",
      content: "Lead with evidence",
      scope: "project" as const,
      scope_key: "project one",
      source_type: "note",
      source_id: "note one",
      provenance: { captured_by: "owner" },
      pinned: true,
      auto_captured: false,
    };

    await getContentAssets();
    await getContentAssets({
      asset_type: "brief",
      status: "draft",
      note_id: "note one",
      limit: 15,
      offset: 5,
    });
    await createContentAsset(assetData);
    await generateContentAssetSourcePack("asset/with spaces");
    await updateContentAsset("asset/with spaces", {
      title: "Updated launch brief",
      status: "ready",
      metadata: { reviewed: true },
    });

    await listSavedMemories();
    await listSavedMemories({
      limit: 20,
      offset: 10,
      search: "release",
      scope: "project",
      state: "active",
    });
    await createSavedMemory(memoryData);
    await mergeSavedMemories({
      target_memory_id: "memory one",
      source_memory_ids: ["memory two", "memory three"],
    });
    await updateSavedMemory("memory/with spaces", {
      title: "Confirmed release preference",
      state: "active",
      confirm_now: true,
      mark_used: true,
    });
    await deleteSavedMemory("memory/with spaces");

    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiContentAssets), {});
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiContentAssets), {
      asset_type: "brief",
      status: "draft",
      note_id: "note one",
      limit: 15,
      offset: 5,
    });
    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiContentAssets), assetData);
    expect(postSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiContentAssetsByAssetIdSourcePack, {
        asset_id: "asset/with spaces",
      }),
    );
    expect(patchSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiContentAssetsByAssetId, {
        asset_id: "asset/with spaces",
      }),
      {
        title: "Updated launch brief",
        status: "ready",
        metadata: { reviewed: true },
      },
    );

    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiSavedMemories), {});
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiSavedMemories), {
      limit: 20,
      offset: 10,
      search: "release",
      scope: "project",
      state: "active",
    });
    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiSavedMemories), memoryData);
    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiSavedMemoriesMerge), {
      target_memory_id: "memory one",
      source_memory_ids: ["memory two", "memory three"],
    });
    expect(patchSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiSavedMemoriesByMemoryId, {
        memory_id: "memory/with spaces",
      }),
      {
        title: "Confirmed release preference",
        state: "active",
        confirm_now: true,
        mark_used: true,
      },
    );
    expect(deleteSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiSavedMemoriesByMemoryId, {
        memory_id: "memory/with spaces",
      }),
    );
  });

  test("scheduled-action, object-memory, and assistant-native clients cover both optional branches", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({} as never);
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({} as never);
    const patchSpy = vi.spyOn(api, "patch").mockResolvedValue({} as never);
    const deleteSpy = vi.spyOn(api, "delete").mockResolvedValue(undefined);
    const actionData = {
      title: "Morning release review",
      prompt: "Review launch risks and next actions",
      schedule_type: "daily" as const,
      schedule_config: { hour: 8 },
      timezone: "Europe/London",
      delivery_channel: "web" as const,
      status: "active" as const,
    };
    const memoryQuery = {
      query: "What risks are unresolved?",
      sensitive_mode: true,
      suppressed_sources: ["connector:personal-email"],
    };

    await listScheduledActions();
    await listScheduledActions({ limit: 20, offset: 5, status: "active" });
    await createScheduledAction(actionData);
    await updateScheduledAction("action/with spaces", {
      title: "Updated morning review",
      status: "paused",
    });
    await deleteScheduledAction("action/with spaces");
    await runScheduledActionNow("action/with spaces");
    await listScheduledActionRuns();
    await listScheduledActionRuns("action/with spaces");

    await searchMemory(memoryQuery);
    await getEntities();
    await getAssistantNativeMetrics();
    await getAssistantNativeEvalSummary();

    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiScheduledActions), {});
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiScheduledActions), {
      limit: 20,
      offset: 5,
      status: "active",
    });
    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiScheduledActions), actionData);
    expect(patchSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiScheduledActionsByActionId, {
        action_id: "action/with spaces",
      }),
      { title: "Updated morning review", status: "paused" },
    );
    expect(deleteSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiScheduledActionsByActionId, {
        action_id: "action/with spaces",
      }),
    );
    expect(postSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiScheduledActionsByActionIdRun, {
        action_id: "action/with spaces",
      }),
    );
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiScheduledActionsRuns), {});
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiScheduledActionsRuns), {
      action_id: "action/with spaces",
    });

    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiSearch), memoryQuery);
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiEntities));
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiOpsAssistantNativeMetrics));
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiOpsAssistantNativeEvals));
  });
});
