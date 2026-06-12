/**
 * Integration tests for SP5 Task 5: user-auth enforcement wired into the
 * interactive WebSocket server. Mirrors the real-server harness in
 * tests/server-protocol.test.ts but injects a stub TokenVerifier.
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join, dirname } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";

import type { TokenVerifier, VerifiedIdentity } from "../src/server/user-auth/token-verifier.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

function makeTempDir(): string {
  return mkdtempSync(join(tmpdir(), "ac-user-auth-"));
}

/** Stub verifier: accepts only the token "good". */
const stubVerifier: TokenVerifier = {
  async verify(token: string): Promise<VerifiedIdentity> {
    if (token !== "good") {
      throw new Error("invalid token");
    }
    return { subject: "u1", email: undefined, groups: [] };
  },
};

interface BufferedSocket {
  send: (payload: Record<string, unknown>) => void;
  collect: () => Record<string, unknown>[];
  until: (
    predicate: (messages: Record<string, unknown>[]) => boolean,
    timeoutMs?: number,
  ) => Promise<void>;
  close: () => void;
}

async function openSocket(url: string): Promise<BufferedSocket> {
  const { WebSocket } = await import("ws");
  const ws = new WebSocket(url);
  const received: Record<string, unknown>[] = [];

  ws.on("message", (data) => {
    received.push(JSON.parse(data.toString()) as Record<string, unknown>);
  });

  await new Promise<void>((resolve, reject) => {
    ws.once("open", () => resolve());
    ws.once("error", (err) => reject(err));
  });

  return {
    send(payload) {
      ws.send(JSON.stringify(payload));
    },
    collect() {
      return received;
    },
    async until(predicate, timeoutMs = 5000) {
      const started = Date.now();
      while (!predicate(received)) {
        if (Date.now() - started > timeoutMs) {
          throw new Error("Timed out waiting for condition");
        }
        await new Promise((resolve) => setTimeout(resolve, 25));
      }
    },
    close() {
      ws.close();
    },
  };
}

function hasAuthRequiredError(messages: Record<string, unknown>[]): boolean {
  return messages.some(
    (msg) =>
      msg.type === "error" &&
      typeof msg.message === "string" &&
      msg.message.includes("authentication required"),
  );
}

describe("user-auth enforcement (ws integration)", () => {
  let dir: string;

  beforeEach(() => {
    dir = makeTempDir();
  });
  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  async function makeServer(opts: { withVerifier: boolean }) {
    const { RunManager, InteractiveServer } = await import("../src/server/index.js");
    const mgr = new RunManager({
      dbPath: join(dir, "test.db"),
      migrationsDir: join(__dirname, "..", "migrations"),
      runsRoot: join(dir, "runs"),
      knowledgeRoot: join(dir, "knowledge"),
      providerType: "deterministic",
    });
    const server = new InteractiveServer({
      runManager: mgr,
      port: 0,
      ...(opts.withVerifier ? { userVerifier: stubVerifier } : {}),
    });
    await server.start();
    return server;
  }

  it("rejects a command sent before authenticate when auth is enabled", async () => {
    const server = await makeServer({ withVerifier: true });
    const socket = await openSocket(server.url);
    try {
      socket.send({ type: "start_run", scenario: "x", generations: 1 });
      await socket.until((messages) => hasAuthRequiredError(messages));
      expect(hasAuthRequiredError(socket.collect())).toBe(true);
    } finally {
      socket.close();
      await server.stop();
    }
  }, 15000);

  it("passes the gate after authenticate when auth is enabled", async () => {
    const server = await makeServer({ withVerifier: true });
    const socket = await openSocket(server.url);
    try {
      socket.send({ type: "authenticate", token: "good" });
      // Expect a non-error success (ack).
      await socket.until((messages) =>
        messages.some((msg) => msg.type === "ack" && msg.action === "authenticate"),
      );
      expect(hasAuthRequiredError(socket.collect())).toBe(false);

      const sawAckAt = socket.collect().length;
      socket.send({ type: "start_run", scenario: "x", generations: 1 });
      // Wait for the server to respond to start_run (any message past the ack).
      await socket.until((messages) => messages.length > sawAckAt);
      // The auth gate must NOT have blocked it (other engine errors are fine).
      expect(hasAuthRequiredError(socket.collect())).toBe(false);
    } finally {
      socket.close();
      await server.stop();
    }
  }, 15000);

  it("does not gate commands when no verifier is configured", async () => {
    const server = await makeServer({ withVerifier: false });
    const socket = await openSocket(server.url);
    try {
      socket.send({ type: "start_run", scenario: "x", generations: 1 });
      // Wait for any server response to the command.
      await socket.until((messages) =>
        messages.some(
          (msg) => msg.type === "run_accepted" || msg.type === "error" || msg.type === "event",
        ),
      );
      expect(hasAuthRequiredError(socket.collect())).toBe(false);
    } finally {
      socket.close();
      await server.stop();
    }
  }, 15000);
});

describe("user-auth enforcement (HTTP integration)", () => {
  let dir: string;

  beforeEach(() => {
    dir = makeTempDir();
  });
  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  async function makeServer(opts: { withVerifier: boolean }) {
    const { RunManager, InteractiveServer } = await import("../src/server/index.js");
    const mgr = new RunManager({
      dbPath: join(dir, "test.db"),
      migrationsDir: join(__dirname, "..", "migrations"),
      runsRoot: join(dir, "runs"),
      knowledgeRoot: join(dir, "knowledge"),
      providerType: "deterministic",
    });
    const server = new InteractiveServer({
      runManager: mgr,
      port: 0,
      ...(opts.withVerifier ? { userVerifier: stubVerifier } : {}),
    });
    await server.start();
    return server;
  }

  // A real mutating route the server serves: PUT /api/notebooks/:sessionId.
  const mutatingRoute = (server: { port: number }) =>
    `http://localhost:${server.port}/api/notebooks/test-session`;

  it("returns 401 for a mutating request without Authorization when auth is enabled", async () => {
    const server = await makeServer({ withVerifier: true });
    try {
      const res = await fetch(mutatingRoute(server), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      expect(res.status).toBe(401);
      const body = (await res.json()) as Record<string, unknown>;
      expect(body.error).toBe("authentication required");
    } finally {
      await server.stop();
    }
  }, 15000);

  it("does not return 401 for a mutating request with a valid Bearer token", async () => {
    const server = await makeServer({ withVerifier: true });
    try {
      const res = await fetch(mutatingRoute(server), {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: "Bearer good" },
        body: JSON.stringify({}),
      });
      // The auth gate passed; any other status from the route is acceptable.
      expect(res.status).not.toBe(401);
    } finally {
      await server.stop();
    }
  }, 15000);

  it("does not gate mutating HTTP requests when no verifier is configured", async () => {
    const server = await makeServer({ withVerifier: false });
    try {
      const res = await fetch(mutatingRoute(server), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      // Today's behavior: no auth gate, so not a gate-level 401.
      expect(res.status).not.toBe(401);
    } finally {
      await server.stop();
    }
  }, 15000);
});
