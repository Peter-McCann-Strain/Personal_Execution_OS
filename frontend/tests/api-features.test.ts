import { afterEach, describe, expect, test, vi } from "vitest";

import { API_PATHS } from "@/api/generated/paths";
import { api, apiPath } from "@/api/client";
import { getEvents, getFreeSlots } from "@/api/calendar";
import {
  getOpenCommitments,
  getOverdueCommitments,
  updateCommitmentStatus,
} from "@/api/commitments";
import {
  createContact,
  getContact,
  getContactInteractions,
  getContacts,
  getDecayingContacts,
  logInteraction,
  searchContacts,
} from "@/api/contacts";
import {
  createDecision,
  getDecision,
  getDecisions,
  getDecisionsDueReview,
  recordOutcome,
} from "@/api/decisions";
import { getEmail, getEmails } from "@/api/email";
import {
  deleteEpisode,
  getEpisode,
  getEpisodes,
  getEpisodesByDateRange,
  getEpisodeStats,
  updateEpisode,
} from "@/api/episodes";
import {
  createGoal,
  deleteGoal,
  getChildGoals,
  getGoal,
  getGoals,
  updateGoalProgress,
} from "@/api/goals";
import { completeHabit, createHabit, getHabit, getHabitLogs, getHabits } from "@/api/habits";
import {
  getEntities,
  getEntity,
  getEntityRelationships,
  getRelatedEntities,
  searchMemory,
} from "@/api/memory";
import {
  createNote,
  createNoteLink,
  deleteNote,
  getLinkedNotes,
  getNote,
  searchNotes,
  updateNote,
} from "@/api/notes";
import {
  dismissAllNotifications,
  dismissNotification,
  getNotifications,
  getUnreadCount,
  markAllRead,
} from "@/api/notifications";
import { generateReview, getReview, getReviews } from "@/api/reviews";
import {
  endTutorial,
  getTutorial,
  getTutorials,
  sendTutorialTurn,
  startTutorial,
} from "@/api/tutorials";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("feature API wrappers", () => {
  test("calendar and commitments wrappers map cleanly onto api methods", async () => {
    const getSpy = vi
      .spyOn(api, "get")
      .mockResolvedValue({} as never)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([]);
    const patchSpy = vi.spyOn(api, "patch").mockResolvedValue({} as never);

    await getEvents("2026-04-01", "2026-04-02");
    await getFreeSlots({ duration_minutes: 30, days_ahead: 2 });
    await getOpenCommitments(12);
    await getOverdueCommitments();
    await updateCommitmentStatus("commitment-1", "done");

    expect(getSpy).toHaveBeenNthCalledWith(1, apiPath(API_PATHS.apiCalendarEvents), {
      start: "2026-04-01",
      end: "2026-04-02",
    });
    expect(getSpy).toHaveBeenNthCalledWith(2, apiPath(API_PATHS.apiCalendarFreeSlots), {
      duration_minutes: 30,
      days_ahead: 2,
    });
    expect(getSpy).toHaveBeenNthCalledWith(3, apiPath(API_PATHS.apiCommitmentsOpen), { limit: 12 });
    expect(getSpy).toHaveBeenNthCalledWith(4, apiPath(API_PATHS.apiCommitmentsOverdue));
    expect(patchSpy).toHaveBeenNthCalledWith(
      1,
      apiPath(API_PATHS.apiCommitmentsByCommitmentIdStatus, {
        commitment_id: "commitment-1",
      }),
      { status: "done" },
    );
  });

  test("contacts, memory, and notes wrappers pass the correct paths and params", async () => {
    const getSpy = vi
      .spyOn(api, "get")
      .mockResolvedValue({} as never)
      .mockResolvedValueOnce({ items: [], total: 0, offset: 0, limit: 20, has_more: false })
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce({});
    const postSpy = vi
      .spyOn(api, "post")
      .mockResolvedValue({} as never)
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce(undefined);
    const patchSpy = vi.spyOn(api, "patch").mockResolvedValue({} as never);
    const deleteSpy = vi.spyOn(api, "delete").mockResolvedValue(undefined);

    await getContacts({ tags: ["friend", "work"], limit: 5 });
    await getContact("contact-1");
    await createContact({ first_name: "Ada", tags: ["friend"] });
    await getContactInteractions("contact-1");
    await logInteraction("contact-1", {
      interaction_type: "call",
      direction: "incoming",
      summary: "Catch-up",
    });
    await searchContacts("Ada");
    await getDecayingContacts();

    await searchMemory("quarterly plan");
    await getEntities({ entity_type: "person", limit: 4 });
    await getEntityRelationships();
    await getEntity("entity-1");
    await getRelatedEntities("entity-1");

    await searchNotes("roadmap", 3);
    await createNote({ title: "Roadmap", content: "Text", note_type: "research" });
    await getNote("note-1");
    await updateNote("note-1", { title: "Updated" });
    await deleteNote("note-1");
    await getLinkedNotes("note-1");
    await createNoteLink("note-1", { target_note_id: "note-2", auto_discovered: true });

    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiContacts), {
      tags: "friend,work",
      limit: 5,
    });
    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiContacts), {
      first_name: "Ada",
      tags: ["friend"],
    });
    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiSearch), {
      query: "quarterly plan",
    });
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiEntities), {
      entity_type: "person",
      limit: 4,
    });
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiNotesSearch), {
      q: "roadmap",
      limit: 3,
    });
    expect(patchSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiNotesByNoteId, { note_id: "note-1" }),
      { title: "Updated" },
    );
    expect(deleteSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiNotesByNoteId, { note_id: "note-1" }),
    );
  });

  test("decision, review, and notification wrappers target the correct endpoints", async () => {
    const getSpy = vi
      .spyOn(api, "get")
      .mockResolvedValue({} as never)
      .mockResolvedValueOnce({ items: [], total: 0, offset: 0, limit: 10, has_more: false })
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce({ items: [], total: 0, offset: 0, limit: 10, has_more: false })
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce({ items: [], total: 0, offset: 0, limit: 10, has_more: false })
      .mockResolvedValueOnce({ total: 3, hasP0: true, hasP1: false });
    const postSpy = vi
      .spyOn(api, "post")
      .mockResolvedValue({} as never)
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce({});
    const patchSpy = vi
      .spyOn(api, "patch")
      .mockResolvedValue({} as never)
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(undefined);

    await getDecisions({ status: "pending_review", limit: 10 });
    await getDecisionsDueReview();
    await getDecision("decision-1");
    await createDecision({ title: "Hire", decision_made: "Yes" });
    await recordOutcome("decision-1", { actual_outcome: "Good", outcome_rating: 5 });

    await getReviews({ review_type: "weekly", limit: 5 });
    await getReview("review-1");
    await generateReview("quarterly");

    await getNotifications({ priority: ["p0", "p1"], group_by: "priority" });
    await dismissNotification("notification-1");
    await dismissAllNotifications();
    await markAllRead();
    await getUnreadCount();

    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiDecisions), {
      status: "pending_review",
      limit: 10,
    });
    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiDecisions), {
      title: "Hire",
      decision_made: "Yes",
    });
    expect(patchSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiDecisionsByDecisionIdOutcome, { decision_id: "decision-1" }),
      { actual_outcome: "Good", outcome_rating: 5 },
    );
    expect(postSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiReviewsGenerate), {
      type: "quarterly",
    });
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiNotifications), {
      priority: "p0,p1",
      group_by: "priority",
    });
  });

  test("email, episodes, goals, and habits wrappers forward ids and payloads", async () => {
    const getSpy = vi
      .spyOn(api, "get")
      .mockResolvedValue({} as never)
      .mockResolvedValueOnce({ items: [], total: 0, offset: 0, limit: 5, has_more: false })
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce({ items: [], total: 0, offset: 0, limit: 5, has_more: false })
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce({ items: [], total: 0, offset: 0, limit: 5, has_more: false })
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([]);
    const postSpy = vi
      .spyOn(api, "post")
      .mockResolvedValue({} as never)
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce({});
    const patchSpy = vi
      .spyOn(api, "patch")
      .mockResolvedValue({} as never)
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce({});
    vi.spyOn(api, "delete").mockResolvedValueOnce(undefined).mockResolvedValueOnce(undefined);

    await getEmails({ unread_only: true, limit: 5 });
    await getEmail("email-1");

    await getEpisodes({ tags: ["focus"], people: ["Ada"] });
    await getEpisode("episode-1");
    await getEpisodeStats(14);
    await getEpisodesByDateRange("2026-04-01", "2026-04-07");
    await updateEpisode("episode-1", { content: "Updated" });
    await deleteEpisode("episode-1");

    await getGoals({ status: "active", order: "desc" });
    await getGoal("goal-1");
    await updateGoalProgress("goal-1", 80);
    await createGoal({ title: "Ship", priority: 1 });
    await getChildGoals("goal-1");
    await deleteGoal("goal-1");

    await getHabits();
    await createHabit({ name: "Run", tags: ["health"] });
    await getHabit("habit-1");
    await completeHabit("habit-1");
    await completeHabit("habit-1", "Done");
    await getHabitLogs("habit-1");
    await getHabitLogs("habit-1", 7);

    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiEmailInbox), {
      unread_only: 1,
      limit: 5,
    });
    expect(getSpy).toHaveBeenCalledWith(apiPath(API_PATHS.apiEpisodes), {
      tags: "focus",
      people: "Ada",
    });
    expect(patchSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiGoalsByGoalId, { goal_id: "goal-1" }),
      { progress: 80 },
    );
    expect(postSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiHabitsByHabitIdComplete, { habit_id: "habit-1" }),
      { note: "Done" },
    );
    expect(postSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiHabitsByHabitIdComplete, { habit_id: "habit-1" }),
    );
    expect(getSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiHabitsByHabitIdLogs, { habit_id: "habit-1" }),
    );
    expect(getSpy).toHaveBeenCalledWith(
      apiPath(API_PATHS.apiHabitsByHabitIdLogs, { habit_id: "habit-1" }),
      { days: 7 },
    );
  });

  test("tutorial wrappers hit the expected endpoints", async () => {
    const getSpy = vi
      .spyOn(api, "get")
      .mockResolvedValue({} as never)
      .mockResolvedValueOnce({ items: [], total: 0, offset: 0, limit: 5, has_more: false })
      .mockResolvedValueOnce({});
    const postSpy = vi
      .spyOn(api, "post")
      .mockResolvedValue({} as never)
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce({});

    await getTutorials({ limit: 5 });
    await getTutorial("tutorial-1");
    await startTutorial("tutorial-1");
    await sendTutorialTurn("tutorial-1", "My answer");
    await endTutorial("tutorial-1");

    expect(getSpy).toHaveBeenNthCalledWith(1, apiPath(API_PATHS.apiTutorials), { limit: 5 });
    expect(getSpy).toHaveBeenNthCalledWith(
      2,
      apiPath(API_PATHS.apiTutorialsByTutorialId, { tutorial_id: "tutorial-1" }),
    );
    expect(postSpy).toHaveBeenNthCalledWith(
      1,
      apiPath(API_PATHS.apiTutorialsByTutorialIdStart, { tutorial_id: "tutorial-1" }),
    );
    expect(postSpy).toHaveBeenNthCalledWith(
      2,
      apiPath(API_PATHS.apiTutorialsByTutorialIdTurn, { tutorial_id: "tutorial-1" }),
      { message: "My answer" },
    );
    expect(postSpy).toHaveBeenNthCalledWith(
      3,
      apiPath(API_PATHS.apiTutorialsByTutorialIdEnd, { tutorial_id: "tutorial-1" }),
    );
  });
});
