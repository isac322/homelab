const GITHUB_ISSUER = "https://token.actions.githubusercontent.com";
const GITHUB_JWKS_URL = `${GITHUB_ISSUER}/.well-known/jwks`;
const GRANT_TYPE_TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange";
const SUBJECT_TOKEN_TYPE_JWT = "urn:ietf:params:oauth:token-type:jwt";
const JWKS_CACHE_TTL_MS = 10 * 60 * 1000;
const CLOCK_SKEW_SECONDS = 30;
const DEFAULT_TOKEN_TTL_SECONDS = 2700;

const textEncoder = new TextEncoder();
const textDecoder = new TextDecoder();

function jsonResponse(body, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
      ...extraHeaders,
    },
  });
}

function base64UrlEncode(bytes) {
  const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let binary = "";
  for (let i = 0; i < arr.length; i += 1) {
    binary += String.fromCharCode(arr[i]);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlDecode(str) {
  if (typeof str !== "string" || !/^[A-Za-z0-9_-]+$/.test(str)) {
    throw new Error("invalid base64url segment");
  }
  const padded = str.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((str.length + 3) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function parseAllowedRepos(raw) {
  if (typeof raw !== "string" || !raw.trim()) {
    return new Set();
  }
  return new Set(
    raw
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean)
  );
}

function hasUnsafeRawPath(rawUrl) {
  const schemeIdx = rawUrl.indexOf("://");
  const afterScheme = schemeIdx >= 0 ? rawUrl.slice(schemeIdx + 3) : rawUrl;
  const slashIdx = afterScheme.indexOf("/");
  if (slashIdx < 0) return false;
  let pathPart = afterScheme.slice(slashIdx);
  const cutIdx = pathPart.search(/[?#]/);
  if (cutIdx >= 0) {
    pathPart = pathPart.slice(0, cutIdx);
  }
  if (pathPart.includes("\\") || /%5c/i.test(pathPart)) {
    return true;
  }
  const normalizedSegments = pathPart
    .split("/")
    .map((seg) => {
      try {
        return decodeURIComponent(seg);
      } catch {
        return null;
      }
    });
  if (normalizedSegments.some((seg) => seg === null || seg === ".." || seg === ".")) {
    return true;
  }
  return false;
}

function isAllowedModelPath(pathname) {
  return (
    pathname === "/v1/responses" ||
    pathname.startsWith("/v1/responses/") ||
    pathname === "/v1/models" ||
    pathname.startsWith("/v1/models/")
  );
}

async function importHmacKey(secret, usage) {
  return crypto.subtle.importKey(
    "raw",
    textEncoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    [usage]
  );
}

export function createGatewayHandler(deps = {}) {
  const fetchFn = deps.fetchFn || ((...args) => fetch(...args));
  const nowFn = deps.nowFn || (() => Date.now());

  let cachedJwks = null;
  let cachedJwksExpiresAt = 0;
  let inFlightJwks = null;

  async function loadJwks(forceRefresh = false) {
    const nowMs = nowFn();
    if (!forceRefresh && cachedJwks && nowMs < cachedJwksExpiresAt) {
      return cachedJwks;
    }
    if (!forceRefresh && inFlightJwks) {
      return inFlightJwks;
    }
    inFlightJwks = (async () => {
      const resp = await fetchFn(GITHUB_JWKS_URL, {
        method: "GET",
        headers: { Accept: "application/json" },
      });
      if (!resp.ok) {
        throw new Error(`JWKS fetch failed: HTTP ${resp.status}`);
      }
      const data = await resp.json();
      if (!data || !Array.isArray(data.keys)) {
        throw new Error("JWKS payload missing keys array");
      }
      cachedJwks = data.keys;
      cachedJwksExpiresAt = nowFn() + JWKS_CACHE_TTL_MS;
      return cachedJwks;
    })();
    try {
      return await inFlightJwks;
    } finally {
      inFlightJwks = null;
    }
  }

  async function findVerificationKey(kid) {
    let keys = await loadJwks(false);
    let jwk = keys.find((k) => k && k.kid === kid && k.kty === "RSA");
    if (!jwk) {
      keys = await loadJwks(true);
      jwk = keys.find((k) => k && k.kid === kid && k.kty === "RSA");
    }
    if (!jwk) {
      return null;
    }
    return crypto.subtle.importKey(
      "jwk",
      jwk,
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
      false,
      ["verify"]
    );
  }

  async function verifyGitHubOidcJwt(jwt, env) {
    const parts = jwt.split(".");
    if (parts.length !== 3 || parts.some((p) => !p)) {
      return { ok: false, status: 401, error: "invalid_token" };
    }
    let header;
    let claims;
    let sigBytes;
    try {
      header = JSON.parse(textDecoder.decode(base64UrlDecode(parts[0])));
      claims = JSON.parse(textDecoder.decode(base64UrlDecode(parts[1])));
      sigBytes = base64UrlDecode(parts[2]);
    } catch {
      return { ok: false, status: 401, error: "malformed_jwt" };
    }

    if (!header || header.alg !== "RS256" || typeof header.kid !== "string" || !header.kid) {
      return { ok: false, status: 401, error: "unsupported_jwt_header" };
    }

    let cryptoKey;
    try {
      cryptoKey = await findVerificationKey(header.kid);
    } catch {
      return { ok: false, status: 502, error: "jwks_unavailable" };
    }
    if (!cryptoKey) {
      return { ok: false, status: 401, error: "unknown_key_id" };
    }

    const signingInput = textEncoder.encode(`${parts[0]}.${parts[1]}`);
    const sigValid = await crypto.subtle.verify(
      { name: "RSASSA-PKCS1-v1_5" },
      cryptoKey,
      sigBytes,
      signingInput
    );
    if (!sigValid) {
      return { ok: false, status: 401, error: "invalid_signature" };
    }

    if (!claims || typeof claims !== "object") {
      return { ok: false, status: 401, error: "invalid_claims" };
    }
    if (claims.iss !== GITHUB_ISSUER) {
      return { ok: false, status: 401, error: "invalid_issuer" };
    }

    const expectedAudience = (env.OIDC_AUDIENCE || "").trim();
    const audList = Array.isArray(claims.aud)
      ? claims.aud
      : typeof claims.aud === "string"
        ? [claims.aud]
        : [];
    if (!expectedAudience || !audList.includes(expectedAudience)) {
      return { ok: false, status: 401, error: "invalid_audience" };
    }

    const nowSec = Math.floor(nowFn() / 1000);
    if (typeof claims.exp !== "number" || !Number.isFinite(claims.exp) || nowSec > claims.exp + CLOCK_SKEW_SECONDS) {
      return { ok: false, status: 401, error: "token_expired" };
    }
    if (claims.nbf !== undefined) {
      if (typeof claims.nbf !== "number" || !Number.isFinite(claims.nbf) || claims.nbf > nowSec + CLOCK_SKEW_SECONDS) {
        return { ok: false, status: 401, error: "token_not_yet_valid" };
      }
    }
    if (claims.iat !== undefined) {
      if (typeof claims.iat !== "number" || !Number.isFinite(claims.iat) || claims.iat > nowSec + CLOCK_SKEW_SECONDS) {
        return { ok: false, status: 401, error: "invalid_iat" };
      }
    }

    const allowedOwnerId = (env.ALLOWED_OWNER_ID || "").trim();
    if (!allowedOwnerId || String(claims.repository_owner_id ?? "") !== allowedOwnerId) {
      return { ok: false, status: 403, error: "owner_not_allowed" };
    }

    const allowedRepos = parseAllowedRepos(env.ALLOWED_REPOS);
    if (typeof claims.repository !== "string" || !allowedRepos.has(claims.repository)) {
      return { ok: false, status: 403, error: "repository_not_allowed" };
    }

    return { ok: true, claims };
  }

  async function issueShortLivedToken(claims, env) {
    const signingSecret = env.TOKEN_SIGNING_SECRET;
    if (!signingSecret) {
      throw new Error("TOKEN_SIGNING_SECRET is not configured");
    }
    const parsedTtl = Number.parseInt(String(env.TOKEN_TTL_SECONDS || DEFAULT_TOKEN_TTL_SECONDS), 10);
    const ttlSeconds = Number.isFinite(parsedTtl) && parsedTtl > 0 ? parsedTtl : DEFAULT_TOKEN_TTL_SECONDS;
    const nowSec = Math.floor(nowFn() / 1000);
    const payload = {
      v: 1,
      iss: (env.OIDC_AUDIENCE || "").trim(),
      repo: claims.repository,
      owner_id: String(claims.repository_owner_id),
      run_id: claims.run_id !== undefined ? String(claims.run_id) : "",
      iat: nowSec,
      exp: nowSec + ttlSeconds,
    };
    const payloadB64 = base64UrlEncode(textEncoder.encode(JSON.stringify(payload)));
    const unsigned = `v1.${payloadB64}`;
    const key = await importHmacKey(signingSecret, "sign");
    const sig = await crypto.subtle.sign("HMAC", key, textEncoder.encode(unsigned));
    return {
      accessToken: `${unsigned}.${base64UrlEncode(sig)}`,
      ttlSeconds,
    };
  }

  async function verifyBearerToken(authHeader, env) {
    const signingSecret = env.TOKEN_SIGNING_SECRET;
    if (!signingSecret) {
      return { ok: false, status: 500, error: "misconfigured_gateway" };
    }
    if (typeof authHeader !== "string") {
      return { ok: false, status: 401, error: "missing_authorization" };
    }
    const match = /^Bearer\s+(\S+)$/i.exec(authHeader.trim());
    if (!match) {
      return { ok: false, status: 401, error: "invalid_authorization_scheme" };
    }
    const token = match[1];
    const parts = token.split(".");
    if (parts.length !== 3 || parts[0] !== "v1" || !parts[1] || !parts[2]) {
      return { ok: false, status: 401, error: "invalid_token_format" };
    }

    let sigBytes;
    let payload;
    try {
      sigBytes = base64UrlDecode(parts[2]);
      payload = JSON.parse(textDecoder.decode(base64UrlDecode(parts[1])));
    } catch {
      return { ok: false, status: 401, error: "malformed_token" };
    }

    const key = await importHmacKey(signingSecret, "verify");
    const validSig = await crypto.subtle.verify(
      "HMAC",
      key,
      sigBytes,
      textEncoder.encode(`${parts[0]}.${parts[1]}`)
    );
    if (!validSig) {
      return { ok: false, status: 401, error: "invalid_token_signature" };
    }

    const nowSec = Math.floor(nowFn() / 1000);
    if (!payload || payload.v !== 1 || typeof payload.exp !== "number" || payload.exp <= nowSec) {
      return { ok: false, status: 401, error: "token_expired" };
    }

    const allowedRepos = parseAllowedRepos(env.ALLOWED_REPOS);
    if (typeof payload.repo !== "string" || !allowedRepos.has(payload.repo)) {
      return { ok: false, status: 403, error: "repository_not_allowed" };
    }
    const allowedOwnerId = (env.ALLOWED_OWNER_ID || "").trim();
    if (!allowedOwnerId || payload.owner_id !== allowedOwnerId) {
      return { ok: false, status: 403, error: "owner_not_allowed" };
    }
    return { ok: true, payload };
  }

  async function handleTokenExchange(request, env) {
    if (request.method !== "POST") {
      return jsonResponse({ error: "method_not_allowed" }, 403);
    }
    let bodyText;
    try {
      bodyText = await request.text();
    } catch {
      return jsonResponse({ error: "invalid_request" }, 400);
    }
    const params = new URLSearchParams(bodyText);
    if (
      params.get("grant_type") !== GRANT_TYPE_TOKEN_EXCHANGE ||
      params.get("subject_token_type") !== SUBJECT_TOKEN_TYPE_JWT
    ) {
      return jsonResponse({ error: "unsupported_grant_type" }, 400);
    }
    const subjectToken = params.get("subject_token") || "";
    if (!subjectToken) {
      return jsonResponse({ error: "missing_subject_token" }, 400);
    }

    const verification = await verifyGitHubOidcJwt(subjectToken, env);
    if (!verification.ok) {
      return jsonResponse({ error: verification.error }, verification.status);
    }

    if (!env.TOKEN_SIGNING_SECRET || !env.CF_ACCESS_CLIENT_ID || !env.CF_ACCESS_CLIENT_SECRET || !env.ORIGIN_BASE_URL) {
      return jsonResponse({ error: "gateway_misconfigured" }, 500);
    }

    const { accessToken, ttlSeconds } = await issueShortLivedToken(verification.claims, env);
    return jsonResponse({
      access_token: accessToken,
      token_type: "Bearer",
      expires_in: ttlSeconds,
    });
  }

  async function handleModelProxy(request, url, env) {
    if (request.method !== "GET" && request.method !== "POST") {
      return jsonResponse({ error: "forbidden" }, 403);
    }
    if (!isAllowedModelPath(url.pathname)) {
      return jsonResponse({ error: "forbidden" }, 403);
    }

    const authCheck = await verifyBearerToken(request.headers.get("Authorization"), env);
    if (!authCheck.ok) {
      return jsonResponse({ error: authCheck.error }, authCheck.status);
    }

    if (!env.CF_ACCESS_CLIENT_ID || !env.CF_ACCESS_CLIENT_SECRET || !env.ORIGIN_BASE_URL) {
      return jsonResponse({ error: "gateway_misconfigured" }, 500);
    }

    const outHeaders = new Headers();
    for (const [name, value] of request.headers.entries()) {
      const lower = name.toLowerCase();
      if (
        lower === "authorization" ||
        lower === "cookie" ||
        lower === "host" ||
        lower.startsWith("cf-access-")
      ) {
        continue;
      }
      outHeaders.set(name, value);
    }
    outHeaders.set("CF-Access-Client-Id", env.CF_ACCESS_CLIENT_ID);
    outHeaders.set("CF-Access-Client-Secret", env.CF_ACCESS_CLIENT_SECRET);

    const originUrl = new URL(`${url.pathname}${url.search}`, env.ORIGIN_BASE_URL);
    const init = {
      method: request.method,
      headers: outHeaders,
      redirect: "manual",
    };
    if (request.method === "POST") {
      init.body = request.body;
      init.duplex = "half";
    }
    return fetchFn(originUrl.toString(), init);
  }

  return {
    async fetch(request, env) {
      if (hasUnsafeRawPath(request.url)) {
        return jsonResponse({ error: "forbidden" }, 403);
      }
      let url;
      try {
        url = new URL(request.url);
      } catch {
        return jsonResponse({ error: "invalid_request" }, 400);
      }
      if (url.pathname === "/oidc/v1/token") {
        return handleTokenExchange(request, env);
      }
      return handleModelProxy(request, url, env);
    },
  };
}

const defaultHandler = createGatewayHandler();

export default {
  fetch(request, env, ctx) {
    return defaultHandler.fetch(request, env, ctx);
  },
};
