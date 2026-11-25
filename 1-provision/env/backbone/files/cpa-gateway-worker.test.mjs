import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { createGatewayHandler } from "./cpa-gateway-worker.js";

const GITHUB_ISSUER = "https://token.actions.githubusercontent.com";
const GITHUB_JWKS_URL = `${GITHUB_ISSUER}/.well-known/jwks`;

function b64uJson(obj) {
  return Buffer.from(JSON.stringify(obj), "utf8").toString("base64url");
}

function b64uBytes(bytes) {
  return Buffer.from(bytes).toString("base64url");
}

async function generateSigningKeyPair(kid) {
  const kp = await crypto.subtle.generateKey(
    {
      name: "RSASSA-PKCS1-v1_5",
      modulusLength: 2048,
      publicExponent: new Uint8Array([1, 0, 1]),
      hash: "SHA-256",
    },
    true,
    ["sign", "verify"]
  );
  const publicJwk = await crypto.subtle.exportKey("jwk", kp.publicKey);
  publicJwk.kid = kid;
  publicJwk.use = "sig";
  publicJwk.alg = "RS256";
  return { privateKey: kp.privateKey, publicJwk };
}

async function signJwt({ header, payload, privateKey }) {
  const encodedHeader = b64uJson(header);
  const encodedPayload = b64uJson(payload);
  const signingInput = `${encodedHeader}.${encodedPayload}`;
  if (!privateKey) {
    return `${signingInput}.ZmFrZXNpZw`;
  }
  const sig = await crypto.subtle.sign(
    { name: "RSASSA-PKCS1-v1_5" },
    privateKey,
    new TextEncoder().encode(signingInput)
  );
  return `${signingInput}.${b64uBytes(sig)}`;
}

function makeBaseEnv(overrides = {}) {
  return {
    OIDC_AUDIENCE: "https://cpa-gw.bhyoo.com",
    ALLOWED_OWNER_ID: "4602209",
    ALLOWED_REPOS: "isac322/flareway,isac322/homelab",
    ORIGIN_BASE_URL: "https://cpa-origin.bhyoo.com",
    TOKEN_TTL_SECONDS: "2700",
    TOKEN_SIGNING_SECRET: "unit-test-hmac-signing-secret-0123456789abcdef",
    CF_ACCESS_CLIENT_ID: "cf-access-client-id-value",
    CF_ACCESS_CLIENT_SECRET: "cf-access-client-secret-value",
    ...overrides,
  };
}

function makeValidClaims(nowSec, overrides = {}) {
  return {
    iss: GITHUB_ISSUER,
    aud: "https://cpa-gw.bhyoo.com",
    sub: "repo:isac322/flareway:ref:refs/heads/main",
    repository: "isac322/flareway",
    repository_owner_id: "4602209",
    run_id: "123456789",
    iat: nowSec - 5,
    nbf: nowSec - 5,
    exp: nowSec + 300,
    ...overrides,
  };
}

function makeExchangeRequest(subjectToken) {
  const form = new URLSearchParams({
    grant_type: "urn:ietf:params:oauth:grant-type:token-exchange",
    subject_token_type: "urn:ietf:params:oauth:token-type:jwt",
    subject_token: subjectToken,
  });
  return new Request("https://cpa-gw.bhyoo.com/oidc/v1/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  });
}

describe("cpa-gateway-worker", () => {
  it("exchanges valid GitHub OIDC JWT and proxies /v1/models + /v1/responses SSE without leaking caller creds", async () => {
    let nowMs = 1_800_000_000_000;
    const { privateKey, publicJwk } = await generateSigningKeyPair("key-1");
    const originCalls = [];

    const handler = createGatewayHandler({
      nowFn: () => nowMs,
      fetchFn: async (url, init = {}) => {
        if (url === GITHUB_JWKS_URL) {
          return new Response(JSON.stringify({ keys: [publicJwk] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        originCalls.push({ url, method: init.method, headers: new Headers(init.headers), body: init.body });
        if (url === "https://cpa-origin.bhyoo.com/v1/models") {
          return new Response(JSON.stringify({ object: "list", data: [{ id: "gpt-6.2-sol" }] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url === "https://cpa-origin.bhyoo.com/v1/responses") {
          const stream = new ReadableStream({
            start(controller) {
              controller.enqueue(new TextEncoder().encode("data: {\"type\":\"response.completed\"}\n\n"));
              controller.close();
            },
          });
          return new Response(stream, {
            status: 200,
            headers: { "Content-Type": "text/event-stream" },
          });
        }
        throw new Error(`unexpected fetch url: ${url}`);
      },
    });

    const env = makeBaseEnv();
    const jwt = await signJwt({
      header: { alg: "RS256", typ: "JWT", kid: "key-1" },
      payload: makeValidClaims(Math.floor(nowMs / 1000)),
      privateKey,
    });

    const exchangeResp = await handler.fetch(makeExchangeRequest(jwt), env);
    assert.equal(exchangeResp.status, 200);
    assert.equal(exchangeResp.headers.get("Cache-Control"), "no-store");
    const tokenBody = await exchangeResp.json();
    assert.equal(tokenBody.token_type, "Bearer");
    assert.equal(tokenBody.expires_in, 2700);
    assert.match(tokenBody.access_token, /^v1\./);
    assert.equal(originCalls.length, 0);

    const modelsResp = await handler.fetch(
      new Request("https://cpa-gw.bhyoo.com/v1/models", {
        method: "GET",
        headers: {
          Authorization: `Bearer ${tokenBody.access_token}`,
          Cookie: "session=caller-secret",
          "CF-Access-Client-Id": "spoofed",
          "CF-Access-Client-Secret": "spoofed",
        },
      }),
      env
    );
    assert.equal(modelsResp.status, 200);
    const modelsJson = await modelsResp.json();
    assert.equal(modelsJson.data[0].id, "gpt-6.2-sol");

    const responsesResp = await handler.fetch(
      new Request("https://cpa-gw.bhyoo.com/v1/responses", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${tokenBody.access_token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ model: "gpt-6.2-sol", stream: true }),
      }),
      env
    );
    assert.equal(responsesResp.status, 200);
    assert.match(await responsesResp.text(), /response\.completed/);

    assert.equal(originCalls.length, 2);
    for (const call of originCalls) {
      assert.equal(call.headers.get("CF-Access-Client-Id"), env.CF_ACCESS_CLIENT_ID);
      assert.equal(call.headers.get("CF-Access-Client-Secret"), env.CF_ACCESS_CLIENT_SECRET);
      assert.equal(call.headers.get("Authorization"), null);
      assert.equal(call.headers.get("Cookie"), null);
    }
  });

  it("rejects untrusted owner, disallowed repo, wrong aud/iss, expired JWT, forged signature, and alg:none with zero origin calls", async () => {
    const nowMs = 1_800_000_000_000;
    const nowSec = Math.floor(nowMs / 1000);
    const { privateKey, publicJwk } = await generateSigningKeyPair("key-1");
    const otherKey = await generateSigningKeyPair("key-1");
    let originCalls = 0;

    const handler = createGatewayHandler({
      nowFn: () => nowMs,
      fetchFn: async (url) => {
        if (url === GITHUB_JWKS_URL) {
          return new Response(JSON.stringify({ keys: [publicJwk] }), { status: 200 });
        }
        originCalls += 1;
        return new Response("unexpected", { status: 500 });
      },
    });
    const env = makeBaseEnv();

    const cases = [
      {
        label: "wrong repository_owner_id",
        jwt: await signJwt({
          header: { alg: "RS256", kid: "key-1" },
          payload: makeValidClaims(nowSec, { repository_owner_id: "9999999" }),
          privateKey,
        }),
        expectedStatuses: [403],
      },
      {
        label: "disallowed repository",
        jwt: await signJwt({
          header: { alg: "RS256", kid: "key-1" },
          payload: makeValidClaims(nowSec, { repository: "attacker/evil" }),
          privateKey,
        }),
        expectedStatuses: [403],
      },
      {
        label: "wrong audience",
        jwt: await signJwt({
          header: { alg: "RS256", kid: "key-1" },
          payload: makeValidClaims(nowSec, { aud: "https://other.example.com" }),
          privateKey,
        }),
        expectedStatuses: [401],
      },
      {
        label: "wrong issuer",
        jwt: await signJwt({
          header: { alg: "RS256", kid: "key-1" },
          payload: makeValidClaims(nowSec, { iss: "https://evil.example.com" }),
          privateKey,
        }),
        expectedStatuses: [401],
      },
      {
        label: "expired JWT past 30s skew",
        jwt: await signJwt({
          header: { alg: "RS256", kid: "key-1" },
          payload: makeValidClaims(nowSec, { exp: nowSec - 60 }),
          privateKey,
        }),
        expectedStatuses: [401],
      },
      {
        label: "forged signature",
        jwt: await signJwt({
          header: { alg: "RS256", kid: "key-1" },
          payload: makeValidClaims(nowSec),
          privateKey: otherKey.privateKey,
        }),
        expectedStatuses: [401],
      },
      {
        label: "alg none",
        jwt: await signJwt({
          header: { alg: "none", kid: "key-1" },
          payload: makeValidClaims(nowSec),
          privateKey: null,
        }),
        expectedStatuses: [401],
      },
    ];

    for (const c of cases) {
      const resp = await handler.fetch(makeExchangeRequest(c.jwt), env);
      assert.ok(c.expectedStatuses.includes(resp.status), `${c.label}: got ${resp.status}`);
    }
    assert.equal(originCalls, 0);
  });

  it("refreshes JWKS once when encountering an unknown kid", async () => {
    const nowMs = 1_800_000_000_000;
    const nowSec = Math.floor(nowMs / 1000);
    const key1 = await generateSigningKeyPair("key-1");
    const key2 = await generateSigningKeyPair("key-2");
    let jwksFetchCount = 0;

    const handler = createGatewayHandler({
      nowFn: () => nowMs,
      fetchFn: async (url) => {
        assert.equal(url, GITHUB_JWKS_URL);
        jwksFetchCount += 1;
        const keys = jwksFetchCount === 1 ? [key1.publicJwk] : [key1.publicJwk, key2.publicJwk];
        return new Response(JSON.stringify({ keys }), { status: 200 });
      },
    });
    const env = makeBaseEnv();

    const jwt1 = await signJwt({
      header: { alg: "RS256", kid: "key-1" },
      payload: makeValidClaims(nowSec),
      privateKey: key1.privateKey,
    });
    assert.equal((await handler.fetch(makeExchangeRequest(jwt1), env)).status, 200);
    assert.equal(jwksFetchCount, 1);

    const jwt2 = await signJwt({
      header: { alg: "RS256", kid: "key-2" },
      payload: makeValidClaims(nowSec),
      privateKey: key2.privateKey,
    });
    assert.equal((await handler.fetch(makeExchangeRequest(jwt2), env)).status, 200);
    assert.equal(jwksFetchCount, 2);
  });

  it("rejects expired or tampered short-lived bearer tokens with 401 and zero origin calls", async () => {
    let nowMs = 1_800_000_000_000;
    const { privateKey, publicJwk } = await generateSigningKeyPair("key-1");
    let originCalls = 0;

    const handler = createGatewayHandler({
      nowFn: () => nowMs,
      fetchFn: async (url) => {
        if (url === GITHUB_JWKS_URL) {
          return new Response(JSON.stringify({ keys: [publicJwk] }), { status: 200 });
        }
        originCalls += 1;
        return new Response("ok", { status: 200 });
      },
    });
    const env = makeBaseEnv({ TOKEN_TTL_SECONDS: "60" });
    const jwt = await signJwt({
      header: { alg: "RS256", kid: "key-1" },
      payload: makeValidClaims(Math.floor(nowMs / 1000)),
      privateKey,
    });
    const { access_token: token } = await (await handler.fetch(makeExchangeRequest(jwt), env)).json();

    const parts = token.split(".");
    const tamperedSig = `${parts[0]}.${parts[1]}.${parts[2].slice(0, -2)}AA`;
    const tamperedResp = await handler.fetch(
      new Request("https://cpa-gw.bhyoo.com/v1/models", {
        headers: { Authorization: `Bearer ${tamperedSig}` },
      }),
      env
    );
    assert.equal(tamperedResp.status, 401);

    nowMs += 61_000;
    const expiredResp = await handler.fetch(
      new Request("https://cpa-gw.bhyoo.com/v1/models", {
        headers: { Authorization: `Bearer ${token}` },
      }),
      env
    );
    assert.equal(expiredResp.status, 401);
    assert.equal(originCalls, 0);
  });

  it("blocks disallowed paths, path traversal, and disallowed HTTP methods with 403 and zero origin calls", async () => {
    const nowMs = 1_800_000_000_000;
    const { privateKey, publicJwk } = await generateSigningKeyPair("key-1");
    let originCalls = 0;

    const handler = createGatewayHandler({
      nowFn: () => nowMs,
      fetchFn: async (url) => {
        if (url === GITHUB_JWKS_URL) {
          return new Response(JSON.stringify({ keys: [publicJwk] }), { status: 200 });
        }
        originCalls += 1;
        return new Response("unexpected", { status: 500 });
      },
    });
    const env = makeBaseEnv();
    const jwt = await signJwt({
      header: { alg: "RS256", kid: "key-1" },
      payload: makeValidClaims(Math.floor(nowMs / 1000)),
      privateKey,
    });
    const { access_token: token } = await (await handler.fetch(makeExchangeRequest(jwt), env)).json();

    const blockedRequests = [
      new Request("https://cpa-gw.bhyoo.com/v1/chat/completions", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: "{}",
      }),
      new Request("https://cpa-gw.bhyoo.com/admin", {
        method: "GET",
        headers: { Authorization: `Bearer ${token}` },
      }),
      new Request("https://cpa-gw.bhyoo.com/v1/models/../admin", {
        method: "GET",
        headers: { Authorization: `Bearer ${token}` },
      }),
      {
        url: "https://cpa-gw.bhyoo.com/../v1/models",
        method: "GET",
        headers: new Headers({ Authorization: `Bearer ${token}` }),
      },
      {
        url: "https://cpa-gw.bhyoo.com/%2e%2e/v1/models",
        method: "GET",
        headers: new Headers({ Authorization: `Bearer ${token}` }),
      },
      new Request("https://cpa-gw.bhyoo.com/v1/models", {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      }),
      new Request("https://cpa-gw.bhyoo.com/v1/models2", {
        method: "GET",
        headers: { Authorization: `Bearer ${token}` },
      }),
    ];

    for (const req of blockedRequests) {
      const resp = await handler.fetch(req, env);
      assert.equal(resp.status, 403, `expected 403 for ${req.method} ${req.url}, got ${resp.status}`);
    }
    assert.equal(originCalls, 0);
  });
});
