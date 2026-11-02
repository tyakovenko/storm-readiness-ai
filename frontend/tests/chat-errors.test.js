import assert from "node:assert/strict";
import test from "node:test";

import { chatErrorMessage, DEFAULT_CHAT_ERROR } from "../src/components/chatErrors.js";

function response(body) {
  return new Response(JSON.stringify(body), { status: 503, headers: { "Content-Type": "application/json" } });
}

test("maps the API quota error without exposing provider details", async () => {
  const message = await chatErrorMessage(response({ error: "model_quota_exhausted", retry_after: 17 }));
  assert.match(message, /usage limit/);
  assert.doesNotMatch(message, /17|provider/i);
});

test("accepts FastAPI detail-shaped provider errors", async () => {
  const message = await chatErrorMessage(response({ detail: { error: "model_timeout" } }));
  assert.match(message, /too long to respond/);
});

test("falls back safely for unknown and malformed error bodies", async () => {
  assert.equal(await chatErrorMessage(response({ error: "private provider response" })), DEFAULT_CHAT_ERROR);
  assert.equal(await chatErrorMessage(response({ error: "toString" })), DEFAULT_CHAT_ERROR);
  assert.equal(await chatErrorMessage({ json: async () => { throw new Error("invalid JSON"); } }), DEFAULT_CHAT_ERROR);
});
