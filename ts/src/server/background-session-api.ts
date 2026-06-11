import {
  buildBackgroundSessionDetail,
  buildBackgroundSessionSummary,
  type BackgroundSessionSummary,
} from "../session/background-session-read-model.js";
import { normalizeBackgroundSessionTimeline } from "../session/background-session-events.js";
import type { RuntimeSessionEventLog } from "../session/runtime-events.js";
import type { RuntimeSessionReadStore } from "../session/runtime-session-read-model.js";

export interface BackgroundSessionApiResponse {
  status: number;
  body: unknown;
}

export interface BackgroundSessionApiRoutes {
  list(query: URLSearchParams): BackgroundSessionApiResponse;
  getBySessionId(sessionId: string): BackgroundSessionApiResponse;
}

type BackgroundSessionReadStore = RuntimeSessionReadStore & {
  listChildren?: (parentSessionId: string) => RuntimeSessionEventLog[];
  close?: () => void;
};

export function buildBackgroundSessionApiRoutes(opts: {
  openStore: () => BackgroundSessionReadStore;
}): BackgroundSessionApiRoutes {
  return {
    list: (query) => {
      const limit = readLimit(query);
      if (!limit.ok) {
        return { status: 422, body: { detail: limit.error } };
      }
      return withStore(opts.openStore, (store) => ({
        status: 200,
        body: {
          sessions: store
            .list({ limit: limit.value })
            .map((runtimeSession) => summarizeBackgroundSessionFromStore(store, runtimeSession)),
        },
      }));
    },
    getBySessionId: (sessionId) => {
      const cleanSessionId = sessionId.trim();
      if (!cleanSessionId) {
        return { status: 422, body: { detail: "session_id is required" } };
      }
      return withStore(opts.openStore, (store) => {
        const runtimeSession = store.load(cleanSessionId);
        if (!runtimeSession) {
          return {
            status: 404,
            body: {
              detail: `Background session '${cleanSessionId}' not found`,
              session_id: cleanSessionId,
            },
          };
        }
        const childSessions = listChildren(store, runtimeSession.sessionId);
        return {
          status: 200,
          body: {
            ...buildBackgroundSessionDetail({ runtimeSession, childSessions }),
            normalized_events: normalizeBackgroundSessionTimeline(runtimeSession),
          },
        };
      });
    },
  };
}

function summarizeBackgroundSessionFromStore(
  store: BackgroundSessionReadStore,
  runtimeSession: RuntimeSessionEventLog,
): BackgroundSessionSummary {
  return buildBackgroundSessionSummary({
    runtimeSession,
    childSessions: listChildren(store, runtimeSession.sessionId),
  });
}

function listChildren(
  store: BackgroundSessionReadStore,
  parentSessionId: string,
): RuntimeSessionEventLog[] {
  return store.listChildren?.(parentSessionId) ?? [];
}

function withStore(
  openStore: () => BackgroundSessionReadStore,
  fn: (store: BackgroundSessionReadStore) => BackgroundSessionApiResponse,
): BackgroundSessionApiResponse {
  const store = openStore();
  try {
    return fn(store);
  } finally {
    store.close?.();
  }
}

type ReadLimitResult = { ok: true; value: number } | { ok: false; error: string };

function readLimit(query: URLSearchParams): ReadLimitResult {
  const raw = query.get("limit");
  if (raw === null || raw.trim() === "") {
    return { ok: true, value: 50 };
  }
  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    return { ok: false, error: "limit must be a positive integer" };
  }
  return { ok: true, value: parsed };
}
