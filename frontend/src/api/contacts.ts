import { api, apiPath, getWithQuery } from "./client";
import { API_PATHS } from "./generated/paths";
import type { Contact, ContactSearchResult, Interaction, PaginatedResponse } from "@/types";

export interface GetContactsParams {
  tags?: string[];
  score_min?: number;
  score_max?: number;
  sort?: "score_asc" | "score_desc" | "last_interaction" | "name";
  search?: string;
  limit?: number;
  offset?: number;
}

export interface CreateContactData {
  first_name: string;
  last_name?: string;
  email?: string;
  tags?: string[];
  how_we_met?: string;
  interaction_frequency_days?: number;
}

export interface LogInteractionData {
  interaction_type: "call" | "email" | "coffee" | "message";
  direction: "incoming" | "outgoing";
  channel?: "manual" | "gmail" | "calendar";
  summary: string;
  topics?: string[];
  interaction_at?: string;
}

export async function getContacts(params?: GetContactsParams): Promise<PaginatedResponse<Contact>> {
  return getWithQuery<PaginatedResponse<Contact>, GetContactsParams>(
    apiPath(API_PATHS.apiContacts),
    params,
  );
}

export async function getContact(id: string): Promise<Contact> {
  return api.get<Contact>(apiPath(API_PATHS.apiContactsByContactId, { contact_id: id }));
}

export async function createContact(data: CreateContactData): Promise<Contact> {
  return api.post<Contact>(apiPath(API_PATHS.apiContacts), data);
}

export async function getContactInteractions(contactId: string): Promise<Interaction[]> {
  return api.get<Interaction[]>(
    apiPath(API_PATHS.apiContactsByContactIdInteractions, {
      contact_id: contactId,
    }),
  );
}

export async function logInteraction(
  contactId: string,
  data: LogInteractionData,
): Promise<Interaction> {
  return api.post<Interaction>(
    apiPath(API_PATHS.apiContactsByContactIdInteractions, {
      contact_id: contactId,
    }),
    data,
  );
}

export async function searchContacts(query: string): Promise<ContactSearchResult[]> {
  return api.get<ContactSearchResult[]>(apiPath(API_PATHS.apiContactsSearch), {
    q: query,
  });
}

export async function getDecayingContacts(): Promise<Contact[]> {
  return api.get<Contact[]>(apiPath(API_PATHS.apiContactsDecaying));
}
