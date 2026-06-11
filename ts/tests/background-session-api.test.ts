import { describe, expect, it, vi } from "vitest";

import { buildBackgroundSessionApiRoutes } from "../src/server/background-session-api.ts";
import { RuntimeSessionEventLog, RuntimeSessionEventType } from "../src/session/runtime-events.js";

function createLog(sessionId = "run:abc:runtime"): RuntimeSessionEventLog {
  return RuntimeSessionEventLog.fromJSON({
    sessionId,
    parentSessionId: "",
    taskId: "task-abc",
    workerId: "worker-1",
    metadata: {
      goal: "autoctx run support_triage",
      runId: "abc",
      status: "running",
    },
    createdAt: "2026-04-10T00:00:00.000Z",
    updatedAt: "2026-04-10T00:00:02.000Z",
    events: [
      {
        eventId: "event-1",
        sessionId,
        sequence: 0,
        eventType: RuntimeSessionEventType.PROMPT_SUBMITTED,
        timestamp: "2026-04-10T00:00:01.000Z",
        payload: { role: "default", requestId: "req-1", prompt: "SECRET_VALUE" },
        parentSessionId: "",
        taskId: "task-abc",
        workerId: "worker-1",
      },
    ],
  });
}

function createChildLog(): RuntimeSessionEventLog {
  return RuntimeSessionEventLog.fromJSON({
    sessionId: "task:run:abc:runtime:child-1",
    parentSessionId: "run:abc:runtime",
    taskId: "child-1",
    workerId: "worker-child",
    metadata: { goal: "Inspect failing test", runId: "abc", status: "completed" },
    createdAt: "2026-04-10T00:00:03.000Z",
    updatedAt: "2026-04-10T00:00:04.000Z",
    events: [],
  });
}

describe("background session HTTP API routes", () => {
  it("lists background session summaries from runtime-session stores", () => {
    const close = vi.fn();
    const list = vi.fn(() => [createLog()]);
    const load = vi.fn();
    const listChildren = vi.fn(() => [createChildLog()]);
    const api = buildBackgroundSessionApiRoutes({
      openStore: () => ({ list, load, listChildren, close }),
    });

    const response = api.list(new URLSearchParams("limit=5"));

    expect(response.status).toBe(200);
    expect(list).toHaveBeenCalledWith({ limit: 5 });
    expect(close).toHaveBeenCalled();
    expect(response.body).toEqual({
      sessions: [
        expect.objectContaining({
          session_id: "run:abc:runtime",
          runtime_session_id: "run:abc:runtime",
          run_id: "abc",
          task_id: "task-abc",
          status: "running",
          event_count: 1,
          child_session_count: 1,
        }),
      ],
    });
  });

  it("reads a detail view with child summaries and normalized events", () => {
    const load = vi.fn((sessionId: string) => createLog(sessionId));
    const listChildren = vi.fn(() => [createChildLog()]);
    const api = buildBackgroundSessionApiRoutes({
      openStore: () => ({ list: vi.fn(), load, listChildren }),
    });

    const response = api.getBySessionId("run:abc:runtime");
    const body = response.body as Record<string, unknown>;

    expect(response.status).toBe(200);
    expect(load).toHaveBeenCalledWith("run:abc:runtime");
    expect(body.summary).toMatchObject({ session_id: "run:abc:runtime" });
    expect(body.child_sessions).toEqual([
      expect.objectContaining({
        session_id: "task:run:abc:runtime:child-1",
        status: "completed",
      }),
    ]);
    expect(body.normalized_events).toEqual([
      expect.objectContaining({ event: "prompt_started", source_event_type: "prompt_submitted" }),
    ]);
    expect(JSON.stringify(body)).not.toContain("SECRET_VALUE");
  });

  it("returns stable validation and not-found responses", () => {
    const api = buildBackgroundSessionApiRoutes({
      openStore: () => ({ list: vi.fn(), load: vi.fn(() => null) }),
    });

    expect(api.list(new URLSearchParams("limit=0"))).toEqual({
      status: 422,
      body: { detail: "limit must be a positive integer" },
    });
    expect(api.getBySessionId("   ")).toEqual({
      status: 422,
      body: { detail: "session_id is required" },
    });
    expect(api.getBySessionId("missing")).toEqual({
      status: 404,
      body: { detail: "Background session 'missing' not found", session_id: "missing" },
    });
  });
});
