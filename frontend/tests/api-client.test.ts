import { afterEach, describe, expect, it, vi } from "vitest";
import { api, apiPath, absolutePath, buildQueryParams, getWithQuery, ApiError } from "@/api/client";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  sessionStorage.clear();
  document.cookie = "peos_csrf=; Max-Age=0; Path=/";
});

describe("api/client helpers", () => {
  it("buildQueryParams strips empty values and normalizes supported types", () => {
    expect(
      buildQueryParams({
        emptyString: "",
        nullish: null,
        undefinedValue: undefined,
        truthyBoolean: true,
        falseBoolean: false,
        numbers: 42,
        emptyArray: [],
        tags: ["alpha", "beta"],
        name: "Alice",
      }),
    ).toEqual({
      truthyBoolean: 1,
      falseBoolean: 0,
      numbers: 42,
      tags: "alpha,beta",
      name: "Alice",
    });
  });

  it("apiPath strips the API prefix and encodes route params", () => {
    expect(apiPath("/api/goals/{goal_id}", { goal_id: "abc 123" })).toBe("/goals/abc%20123");
  });

  it("absolutePath preserves the API prefix and encodes route params", () => {
    expect(absolutePath("/api/goals/{goal_id}", { goal_id: "abc 123" })).toBe(
      "/api/goals/abc%20123",
    );
  });

  it("keeps non-api paths and raw paths unchanged when no params are provided", () => {
    expect(apiPath("/goals/{goal_id}", { goal_id: 42 })).toBe("/goals/42");
    expect(apiPath("/notes")).toBe("/notes");
    expect(absolutePath("/notes")).toBe("/notes");
  });

  it("api.get appends query params and omits the JSON content type header", async () => {
    sessionStorage.setItem("api_key", "test-key");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await api.get<{ ok: boolean }>("/goals", {
      limit: 10,
      search: "abc",
      includeArchived: false,
      skipMe: undefined,
    });

    expect(result).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/goals?limit=10&search=abc&includeArchived=false");
    expect(init).toMatchObject({
      credentials: "same-origin",
      headers: {
        "X-API-Key": "test-key",
      },
    });
    expect((init as RequestInit).headers).not.toHaveProperty("Content-Type");
  });

  it("getWithQuery skips missing params and normalizes populated query objects", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await getWithQuery("/notes");
    await getWithQuery("/notes", {
      q: "roadmap",
      limit: 10,
      tags: ["alpha", "beta"],
      includeArchived: false,
      skipMe: undefined,
    });

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("http://localhost:3000/api/notes");
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain(
      "/api/notes?q=roadmap&limit=10&tags=alpha%2Cbeta&includeArchived=0",
    );
  });

  it("api.post sends JSON with content type and idempotency headers", async () => {
    document.cookie = "peos_csrf=csrf-test-token; Path=/";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "1" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.post("/goals", { title: "Ship it" });

    const [, init] = fetchMock.mock.calls[0];
    expect(init).toMatchObject({
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": "csrf-test-token",
        "Idempotency-Key": expect.any(String),
      },
      body: JSON.stringify({ title: "Ship it" }),
    });
  });

  it("api.post accepts a deterministic idempotency key", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "1" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.post("/goals", { title: "Ship it" }, { idempotencyKey: "fixed-key" });

    const [, init] = fetchMock.mock.calls[0];
    expect(init).toMatchObject({
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": "fixed-key",
      },
      body: JSON.stringify({ title: "Ship it" }),
    });
  });

  it("omits JSON bodies for post and put when none are provided, and serializes patch bodies", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await api.post("/goals");
    await api.put("/goals/1");
    await api.patch("/goals/1", { title: "Updated" });

    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: "POST",
      body: undefined,
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": expect.any(String),
      },
    });
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({
      method: "PUT",
      body: undefined,
      headers: { "Content-Type": "application/json" },
    });
    expect(fetchMock.mock.calls[2]?.[1]).toMatchObject({
      method: "PATCH",
      body: JSON.stringify({ title: "Updated" }),
      headers: { "Content-Type": "application/json" },
    });
  });

  it("api.put and api.patch send JSON bodies, and omit undefined bodies", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await api.put("/goals/1", { title: "Updated" });
    await api.patch("/goals/1");

    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: "PUT",
      body: JSON.stringify({ title: "Updated" }),
      headers: { "Content-Type": "application/json" },
    });
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({
      method: "PATCH",
      body: undefined,
      headers: { "Content-Type": "application/json" },
    });
  });

  it("api.delete accepts empty responses", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(null, {
        status: 204,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.delete("/goals/123")).resolves.toBeUndefined();
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: "DELETE",
      credentials: "same-origin",
    });
  });

  it("wraps failed responses as ApiError and extracts detail fields", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: { message: "Goal not found" } }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.get("/goals/123")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      message: JSON.stringify({ message: "Goal not found" }),
    });
  });

  it("extracts string detail fields from JSON error bodies", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Bad input" }), {
        status: 422,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.get("/goals/123")).rejects.toMatchObject({
      name: "ApiError",
      status: 422,
      message: "Bad input",
    });
  });

  it("preserves plain-text error bodies and accepts empty content-length responses", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response("plain failure", {
          status: 400,
          headers: { "content-type": "text/plain" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(null, {
          status: 200,
          headers: { "content-length": "0" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.get("/notes/1")).rejects.toMatchObject({
      name: "ApiError",
      status: 400,
      message: "plain failure",
    });
    await expect(api.patch("/notes/1")).resolves.toBeUndefined();
  });

  it("falls back to a network ApiError on TypeError", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.get("/goals")).rejects.toMatchObject({
      name: "ApiError",
      status: 0,
      message: "Network error — check your connection",
    });
  });

  it("rethrows non-network fetch failures unchanged", async () => {
    const failure = new Error("boom");
    const fetchMock = vi.fn().mockRejectedValue(failure);
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.get("/goals")).rejects.toBe(failure);
  });

  it("creates ApiError instances directly", () => {
    const err = new ApiError(500, "boom");
    expect(err).toBeInstanceOf(Error);
    expect(err).toMatchObject({ name: "ApiError", status: 500, message: "boom" });
  });
});
