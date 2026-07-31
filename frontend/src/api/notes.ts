import { api, apiPath, getWithQuery } from "./client";
import { API_PATHS } from "./generated/paths";
import type { Note, NoteCanvas, NoteGraph, PaginatedResponse } from "@/types";

export interface NoteListParams {
  limit?: number;
  offset?: number;
  search?: string;
  note_type?: Note["note_type"];
  para_category?: Note["para_category"];
  kind?: Note["kind"];
}

export interface SearchNotesParams {
  q: string;
  limit?: number;
}

export interface CreateNoteData {
  title: string;
  content: string;
  note_type: Note["note_type"];
  para_category?: Note["para_category"];
  tags?: string[];
  source_url?: string;
  slug?: string;
  aliases?: string[];
  kind?: Note["kind"];
  daily_date?: string;
  frontmatter?: Record<string, unknown>;
}

export type UpdateNoteData = Partial<CreateNoteData>;

export interface LinkedNote extends Note {
  link_reason: string | null;
  similarity_score: number | null;
  link_type: string | null;
  origin: string | null;
}

export interface CreateNoteLinkData {
  target_note_id: string;
  link_reason?: string;
  similarity_score?: number;
  auto_discovered?: boolean;
  link_type?: string;
  origin?: string;
}

export interface NoteGraphParams {
  note_id?: string;
  depth?: 1 | 2;
  limit?: number;
  kind?: Note["kind"];
}

export interface UpsertDailyNoteData {
  title?: string;
  content: string;
  tags?: string[];
  frontmatter?: Record<string, unknown>;
}

export interface CreateNoteCanvasData {
  title: string;
  description?: string;
  primary_note_id?: string;
  nodes?: Array<Record<string, unknown>>;
  edges?: Array<Record<string, unknown>>;
  viewport?: Record<string, unknown>;
}

export type UpdateNoteCanvasData = Partial<CreateNoteCanvasData>;

export async function listNotes(params: NoteListParams = {}): Promise<PaginatedResponse<Note>> {
  return getWithQuery<PaginatedResponse<Note>, NoteListParams>(apiPath(API_PATHS.apiNotes), params);
}

export async function searchNotes(q: string, limit?: number): Promise<Note[]> {
  return getWithQuery<Note[], SearchNotesParams>(apiPath(API_PATHS.apiNotesSearch), { q, limit });
}

export async function getNoteGraph(params: NoteGraphParams = {}): Promise<NoteGraph> {
  return getWithQuery<NoteGraph, NoteGraphParams>(apiPath(API_PATHS.apiNotesGraph), params);
}

export async function createNote(data: CreateNoteData): Promise<Note> {
  return api.post<Note>(apiPath(API_PATHS.apiNotes), data);
}

export async function getNote(id: string): Promise<Note> {
  return api.get<Note>(apiPath(API_PATHS.apiNotesByNoteId, { note_id: id }));
}

export async function updateNote(id: string, data: UpdateNoteData): Promise<Note> {
  return api.patch<Note>(apiPath(API_PATHS.apiNotesByNoteId, { note_id: id }), data);
}

export async function deleteNote(id: string): Promise<void> {
  return api.delete(apiPath(API_PATHS.apiNotesByNoteId, { note_id: id }));
}

export async function getLinkedNotes(noteId: string): Promise<LinkedNote[]> {
  return api.get<LinkedNote[]>(apiPath(API_PATHS.apiNotesByNoteIdLinks, { note_id: noteId }));
}

export async function getBacklinkedNotes(noteId: string): Promise<LinkedNote[]> {
  return api.get<LinkedNote[]>(apiPath(API_PATHS.apiNotesByNoteIdBacklinks, { note_id: noteId }));
}

export async function getUnlinkedMentions(noteId: string, limit = 10): Promise<LinkedNote[]> {
  return getWithQuery<LinkedNote[], { limit: number }>(
    apiPath(API_PATHS.apiNotesByNoteIdUnlinkedMentions, { note_id: noteId }),
    { limit },
  );
}

export async function createNoteLink(noteId: string, data: CreateNoteLinkData): Promise<void> {
  return api.post(apiPath(API_PATHS.apiNotesByNoteIdLinks, { note_id: noteId }), data);
}

export async function getDailyNote(noteDate: string): Promise<Note> {
  return api.get<Note>(apiPath(API_PATHS.apiNotesDailyByNoteDate, { note_date: noteDate }));
}

export async function upsertDailyNote(noteDate: string, data: UpsertDailyNoteData): Promise<Note> {
  return api.post<Note>(apiPath(API_PATHS.apiNotesDailyByNoteDate, { note_date: noteDate }), data);
}

export async function listNoteCanvases(
  limit = 25,
  offset = 0,
): Promise<PaginatedResponse<NoteCanvas>> {
  return getWithQuery<PaginatedResponse<NoteCanvas>, { limit: number; offset: number }>(
    apiPath(API_PATHS.apiNoteCanvases),
    { limit, offset },
  );
}

export async function getNoteCanvas(canvasId: string): Promise<NoteCanvas> {
  return api.get<NoteCanvas>(apiPath(API_PATHS.apiNoteCanvasesByCanvasId, { canvas_id: canvasId }));
}

export async function createNoteCanvas(data: CreateNoteCanvasData): Promise<NoteCanvas> {
  return api.post<NoteCanvas>(apiPath(API_PATHS.apiNoteCanvases), data);
}

export async function updateNoteCanvas(
  canvasId: string,
  data: UpdateNoteCanvasData,
): Promise<NoteCanvas> {
  return api.patch<NoteCanvas>(
    apiPath(API_PATHS.apiNoteCanvasesByCanvasId, { canvas_id: canvasId }),
    data,
  );
}
