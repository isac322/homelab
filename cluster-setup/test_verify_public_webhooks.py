"""Offline contract and regression tests for cluster-setup/verify-public-webhooks.py.

Run: python3 -B -m unittest -v cluster-setup/test_verify_public_webhooks.py
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_SCRIPT_PATH = Path(__file__).resolve().with_name("verify-public-webhooks.py")


def target_script_path() -> Path:
    override = os.environ.get("VERIFY_PUBLIC_WEBHOOKS_PATH")
    return Path(override).resolve() if override else DEFAULT_SCRIPT_PATH


def load_verifier_module(script_path: Path | None = None) -> ModuleType:
    path = script_path or target_script_path()
    spec = importlib.util.spec_from_file_location("verify_public_webhooks_under_test", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Unable to load module spec from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for idx, ch in enumerate(line):
        if escaped:
            escaped = False
            continue
        if in_double and ch == "\\":
            escaped = True
            continue
        if ch == "'" and not in_double:
            if in_single and idx + 1 < len(line) and line[idx + 1] == "'":
                continue
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if idx == 0 or line[idx - 1].isspace():
                return line[:idx]
    if in_single or in_double:
        raise ValueError(f"Unclosed quote in YAML line: {line!r}")
    return line


def _find_colon_outside_quotes(text: str) -> int:
    in_single = False
    in_double = False
    escaped = False
    for idx, ch in enumerate(text):
        if escaped:
            escaped = False
            continue
        if in_double and ch == "\\":
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == ":" and not in_single and not in_double:
            if idx + 1 == len(text) or text[idx + 1].isspace():
                return idx
    return -1


def _parse_scalar(raw: str) -> object:
    token = raw.strip()
    if not token:
        raise ValueError("Expected YAML scalar")
    if token.startswith(("&", "*", "!", "|", ">", "{")):
        raise ValueError(f"Unsupported YAML syntax: {token!r}")
    if token.startswith("["):
        if not token.endswith("]"):
            raise ValueError(f"Multiline or unclosed flow sequence: {token!r}")
        inner = token[1:-1].strip()
        if not inner:
            return []
        items: list[object] = []
        current: list[str] = []
        in_single = False
        in_double = False
        escaped = False
        for ch in inner:
            if escaped:
                current.append(ch)
                escaped = False
                continue
            if in_double and ch == "\\":
                current.append(ch)
                escaped = True
                continue
            if ch == "'" and not in_double:
                in_single = not in_single
                current.append(ch)
            elif ch == '"' and not in_single:
                in_double = not in_double
                current.append(ch)
            elif ch == "," and not in_single and not in_double:
                items.append(_parse_scalar("".join(current)))
                current = []
            else:
                current.append(ch)
        if in_single or in_double:
            raise ValueError(f"Unclosed quote in flow sequence: {token!r}")
        items.append(_parse_scalar("".join(current)))
        return items
    if token.startswith("'"):
        idx = 1
        chars: list[str] = []
        while idx < len(token):
            ch = token[idx]
            if ch == "'":
                if idx + 1 < len(token) and token[idx + 1] == "'":
                    chars.append("'")
                    idx += 2
                    continue
                if token[idx + 1 :].strip():
                    raise ValueError(f"Trailing characters after single-quoted scalar: {token!r}")
                return "".join(chars)
            chars.append(ch)
            idx += 1
        raise ValueError(f"Unclosed single quote: {token!r}")
    if token.startswith('"'):
        idx = 1
        chars = []
        escapes = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
        while idx < len(token):
            ch = token[idx]
            if ch == "\\":
                idx += 1
                if idx >= len(token):
                    raise ValueError(f"Dangling backslash escape: {token!r}")
                chars.append(escapes.get(token[idx], token[idx]))
                idx += 1
                continue
            if ch == '"':
                if token[idx + 1 :].strip():
                    raise ValueError(f"Trailing characters after double-quoted scalar: {token!r}")
                return "".join(chars)
            chars.append(ch)
            idx += 1
        raise ValueError(f"Unclosed double quote: {token!r}")
    if token == "true":
        return True
    if token == "false":
        return False
    if token in ("null", "~"):
        return None
    if re.fullmatch(r"-?[0-9]+", token):
        return int(token)
    if "&" in token or "*" in token or "{" in token or "}" in token:
        raise ValueError(f"Unsupported YAML inline token: {token!r}")
    return token


def _parse_block(lines: list[tuple[int, str]], start: int, min_indent: int) -> tuple[object, int]:
    indent0, text0 = lines[start]
    if text0 == "-" or text0.startswith("- "):
        result_list: list[object] = []
        idx = start
        while idx < len(lines):
            indent, text = lines[idx]
            if indent < indent0:
                break
            if indent > indent0:
                raise ValueError(f"Unexpected indentation at line {text!r}")
            if not (text == "-" or text.startswith("- ")):
                break
            after = text[1:].lstrip() if len(text) > 1 else ""
            idx += 1
            if not after:
                if idx < len(lines) and lines[idx][0] > indent:
                    val, idx = _parse_block(lines, idx, indent + 1)
                    result_list.append(val)
                else:
                    result_list.append(None)
                continue
            colon_pos = _find_colon_outside_quotes(after)
            if colon_pos >= 0:
                first_key_indent = indent + (len(text) - len(text[1:].lstrip()))
                item_dict: dict[str, object] = {}
                key = str(_parse_scalar(after[:colon_pos]) if after[:colon_pos].strip()[:1] in ("'", '"') else after[:colon_pos].strip())
                val_raw = after[colon_pos + 1 :].strip()
                if val_raw:
                    item_dict[key] = _parse_scalar(val_raw)
                elif idx < len(lines) and lines[idx][0] > first_key_indent:
                    val, idx = _parse_block(lines, idx, first_key_indent + 1)
                    item_dict[key] = val
                elif idx < len(lines) and lines[idx][0] == first_key_indent and (
                    lines[idx][1] == "-" or lines[idx][1].startswith("- ")
                ):
                    val, idx = _parse_block(lines, idx, first_key_indent)
                    item_dict[key] = val
                else:
                    item_dict[key] = None
                while idx < len(lines) and lines[idx][0] == first_key_indent:
                    m_indent, m_text = lines[idx]
                    if m_text == "-" or m_text.startswith("- "):
                        break
                    m_colon = _find_colon_outside_quotes(m_text)
                    if m_colon < 0:
                        raise ValueError(f"Expected mapping entry at {m_text!r}")
                    m_key = str(_parse_scalar(m_text[:m_colon]) if m_text[:m_colon].strip()[:1] in ("'", '"') else m_text[:m_colon].strip())
                    if m_key == "<<":
                        raise ValueError("Unsupported YAML merge key '<<'")
                    if m_key in item_dict:
                        raise ValueError(f"Duplicate YAML mapping key {m_key!r}")
                    m_val_raw = m_text[m_colon + 1 :].strip()
                    idx += 1
                    if m_val_raw:
                        item_dict[m_key] = _parse_scalar(m_val_raw)
                    elif idx < len(lines) and lines[idx][0] > m_indent:
                        val, idx = _parse_block(lines, idx, m_indent + 1)
                        item_dict[m_key] = val
                    elif idx < len(lines) and lines[idx][0] == m_indent and (
                        lines[idx][1] == "-" or lines[idx][1].startswith("- ")
                    ):
                        val, idx = _parse_block(lines, idx, m_indent)
                        item_dict[m_key] = val
                    else:
                        item_dict[m_key] = None
                if idx < len(lines) and lines[idx][0] > indent and lines[idx][0] != first_key_indent:
                    raise ValueError(f"Invalid dedent inside sequence item: {lines[idx][1]!r}")
                result_list.append(item_dict)
            else:
                result_list.append(_parse_scalar(after))
        return result_list, idx

    result_map: dict[str, object] = {}
    idx = start
    while idx < len(lines):
        indent, text = lines[idx]
        if indent < indent0:
            break
        if indent > indent0:
            raise ValueError(f"Unexpected indentation at line {text!r}")
        if text == "-" or text.startswith("- "):
            break
        colon_pos = _find_colon_outside_quotes(text)
        if colon_pos < 0:
            raise ValueError(f"Expected YAML key: value mapping line, got {text!r}")
        raw_key = text[:colon_pos].strip()
        key = str(_parse_scalar(raw_key) if raw_key[:1] in ("'", '"') else raw_key)
        if key == "<<":
            raise ValueError("Unsupported YAML merge key '<<'")
        if key in result_map:
            raise ValueError(f"Duplicate YAML mapping key {key!r}")
        val_raw = text[colon_pos + 1 :].strip()
        idx += 1
        if val_raw:
            result_map[key] = _parse_scalar(val_raw)
        elif idx < len(lines) and lines[idx][0] > indent:
            val, idx = _parse_block(lines, idx, indent + 1)
            result_map[key] = val
        elif idx < len(lines) and lines[idx][0] == indent and (
            lines[idx][1] == "-" or lines[idx][1].startswith("- ")
        ):
            val, idx = _parse_block(lines, idx, indent)
            result_map[key] = val
        else:
            result_map[key] = None
        if idx < len(lines) and indent < lines[idx][0] < indent0:
            raise ValueError(f"Invalid dedent to column {lines[idx][0]} at {lines[idx][1]!r}")
    return result_map, idx


def parse_yaml_documents(text: str) -> list[dict[str, object]]:
    docs_raw: list[list[tuple[int, str]]] = [[]]
    for raw_line in text.splitlines():
        if "\t" in raw_line[: len(raw_line) - len(raw_line.lstrip("\t "))]:
            raise ValueError("Tabs are forbidden in YAML indentation")
        stripped = _strip_comment(raw_line).rstrip()
        if not stripped.strip():
            continue
        content = stripped.lstrip(" ")
        indent = len(stripped) - len(content)
        if content.startswith("%"):
            raise ValueError(f"YAML directives are unsupported: {content!r}")
        if indent == 0 and content == "---":
            if docs_raw[-1]:
                docs_raw.append([])
            continue
        if indent == 0 and content == "...":
            if docs_raw[-1]:
                docs_raw.append([])
            continue
        docs_raw[-1].append((indent, content))
    parsed: list[dict[str, object]] = []
    for doc_lines in docs_raw:
        if not doc_lines:
            continue
        obj, end_idx = _parse_block(doc_lines, 0, 0)
        if end_idx != len(doc_lines):
            raise ValueError(f"Trailing unparsed YAML line: {doc_lines[end_idx]!r}")
        if not isinstance(obj, dict):
            raise ValueError(f"Expected top-level YAML mapping document, got {type(obj).__name__}")
        parsed.append(obj)
    return parsed


def condition_entry(cond_type: str, status: str, observed_generation: int | object | None, *, include_observed: bool = True) -> dict[str, object]:
    entry: dict[str, object] = {"type": cond_type, "status": status}
    if include_observed:
        entry["observedGeneration"] = observed_generation
    return entry


def make_cilium_gateway(
    name: str,
    gateway_class_name: object = "cilium-access-log",
    *,
    generation: object = 1,
    accepted: str | None = "True",
    accepted_obs: object = 1,
    programmed: str | None = "True",
    programmed_obs: object = 1,
    include_spec: bool = True,
    include_class_name: bool = True,
) -> dict[str, object]:
    conditions: list[dict[str, object]] = []
    if accepted is not None:
        conditions.append(
            condition_entry("Accepted", accepted, accepted_obs, include_observed=(accepted_obs is not ...))
        )
    if programmed is not None:
        conditions.append(
            condition_entry("Programmed", programmed, programmed_obs, include_observed=(programmed_obs is not ...))
        )
    metadata: dict[str, object] = {"name": name, "namespace": "ingress-ctrl"}
    if generation is not ...:
        metadata["generation"] = generation
    obj: dict[str, object] = {"metadata": metadata, "status": {"conditions": conditions}}
    if include_spec:
        spec: dict[str, object] = {}
        if include_class_name:
            spec["gatewayClassName"] = gateway_class_name
        obj["spec"] = spec
    return obj


def make_gateway_class(
    name: str,
    *,
    controller_name: str = "io.cilium/gateway-controller",
    generation: object = 1,
    accepted: str | None = "True",
    accepted_obs: object = 1,
) -> dict[str, object]:
    conditions: list[dict[str, object]] = []
    if accepted is not None:
        conditions.append(condition_entry("Accepted", accepted, accepted_obs))
    metadata: dict[str, object] = {"name": name}
    if generation is not ...:
        metadata["generation"] = generation
    return {
        "metadata": metadata,
        "spec": {"controllerName": controller_name},
        "status": {"conditions": conditions},
    }


def make_healthy_cluster_state() -> dict[str, object]:
    argocd_secret = b"argocd-test-secret"
    issue_secret = b"issue-agent-test-secret"
    return {
        "objects": {
            ("flareway-system", "gateway", "public-webhooks"): {
                "metadata": {"name": "public-webhooks", "namespace": "flareway-system", "generation": 1},
                "spec": {"gatewayClassName": "flareway"},
                "status": {
                    "conditions": [
                        condition_entry("Accepted", "True", 1),
                        condition_entry("Programmed", "True", 1),
                    ]
                },
            },
            ("flareway-system", "cloudflaretunnel", "public-webhooks"): {
                "metadata": {"name": "public-webhooks", "namespace": "flareway-system", "generation": 1},
                "status": {
                    "conditions": [
                        condition_entry("Ready", "True", 1),
                        condition_entry("DNSReady", "True", 1),
                    ]
                },
            },
            ("flareway-system", "pods", None): {
                "items": [
                    {
                        "metadata": {"name": "flareway-controller-manager"},
                        "spec": {
                            "nodeName": "n2p2",
                            "containers": [
                                {
                                    "name": "manager",
                                    "resources": {"requests": {"cpu": "100m", "memory": "64Mi"}, "limits": {"memory": "128Mi"}},
                                }
                            ],
                        },
                        "status": {"containerStatuses": [{"name": "manager", "ready": True}]},
                    },
                    {
                        "metadata": {"name": "flareway-gw-public-webhooks-1"},
                        "spec": {
                            "nodeName": "n2p1",
                            "containers": [
                                {
                                    "name": "cloudflared",
                                    "resources": {"requests": {"cpu": "100m", "memory": "24Mi"}, "limits": {"memory": "48Mi"}},
                                },
                                {
                                    "name": "envoy",
                                    "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"memory": "256Mi"}},
                                },
                            ],
                        },
                        "status": {
                            "containerStatuses": [
                                {"name": "cloudflared", "ready": True},
                                {"name": "envoy", "ready": True},
                            ]
                        },
                    },
                ]
            },
            ("argocd", "httproute", "argocd-webhook"): {
                "metadata": {"name": "argocd-webhook", "namespace": "argocd", "generation": 1},
                "status": {
                    "parents": [
                        {
                            "controllerName": "flareway.bhyoo.com/gateway-controller",
                            "parentRef": {"name": "public-webhooks", "namespace": "flareway-system"},
                            "conditions": [
                                condition_entry("Accepted", "True", 1),
                                condition_entry("ResolvedRefs", "True", 1),
                            ],
                        }
                    ]
                },
            },
            ("issue-agent", "httproute", "issue-agent-webhook"): {
                "metadata": {"name": "issue-agent-webhook", "namespace": "issue-agent", "generation": 1},
                "status": {
                    "parents": [
                        {
                            "controllerName": "flareway.bhyoo.com/gateway-controller",
                            "parentRef": {"name": "public-webhooks", "namespace": "flareway-system"},
                            "conditions": [
                                condition_entry("Accepted", "True", 1),
                                condition_entry("ResolvedRefs", "True", 1),
                            ],
                        }
                    ]
                },
            },
            ("argocd", "secret", "argocd-secret"): {
                "metadata": {"name": "argocd-secret", "namespace": "argocd"},
                "data": {"webhook.github.secret": base64.b64encode(argocd_secret).decode("ascii")},
            },
            ("issue-agent", "secret", "issue-agent-webhook"): {
                "metadata": {"name": "issue-agent-webhook", "namespace": "issue-agent"},
                "data": {"secret": base64.b64encode(issue_secret).decode("ascii")},
            },
            ("ingress-ctrl", "gateway", "bhyoo-gateway"): make_cilium_gateway("bhyoo-gateway", "cilium-access-log", generation=4, accepted_obs=4, programmed_obs=4),
            ("ingress-ctrl", "gateway", "nas-gateway"): make_cilium_gateway("nas-gateway", "cilium-access-log", generation=2, accepted_obs=2, programmed_obs=2),
            (None, "gatewayclass", "cilium"): make_gateway_class("cilium"),
            (None, "gatewayclass", "cilium-access-log"): make_gateway_class("cilium-access-log"),
        },
        "errors": {},
        "secrets_by_host": {
            ("argocd-webhook.bhyoo.com", "/api/webhook"): argocd_secret,
            ("issue-agent-webhook.bhyoo.com", "/webhooks/github"): issue_secret,
        },
    }


KUBECTL_SHIM_SOURCE = """#!{python}
import json
import os
import sys

state_path = os.environ["FAKE_KUBECTL_STATE"]
journal_path = os.environ["FAKE_KUBECTL_JOURNAL"]
argv = sys.argv[1:]
with open(journal_path, "a", encoding="utf-8") as jf:
    jf.write(json.dumps(argv) + "\\n")

with open(state_path, "r", encoding="utf-8") as sf:
    state = json.load(sf)

ns = None
idx = 0
rest = []
while idx < len(argv):
    tok = argv[idx]
    if tok == "--context":
        idx += 2
        continue
    if tok == "-n":
        ns = argv[idx + 1]
        idx += 2
        continue
    if tok == "-o":
        idx += 2
        continue
    rest.append(tok)
    idx += 1

if len(rest) < 2 or rest[0] != "get":
    sys.stderr.write(f"unsupported fake kubectl args: {{argv!r}}\\n")
    sys.exit(2)

kind = rest[1]
name = rest[2] if len(rest) > 2 else None
key = f"{{ns or ''}}|{{kind}}|{{name or ''}}"

if key in state.get("raw_stdout", {{}}):
    sys.stdout.write(state["raw_stdout"][key])
    sys.exit(0)

if key in state.get("errors", {{}}):
    err = state["errors"][key]
    sys.stderr.write(err.get("stderr", "error") + "\\n")
    sys.exit(int(err.get("code", 1)))

if key not in state.get("objects", {{}}):
    sys.stderr.write(f'Error from server (NotFound): {{kind}} "{{name}}" not found\\n')
    sys.exit(1)

sys.stdout.write(json.dumps(state["objects"][key]))
"""


class _FakeHTTPResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class WebhookVerifierBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.tmp = Path(self.temp_dir.name)
        self.state_path = self.tmp / "state.json"
        self.journal_path = self.tmp / "journal.jsonl"
        shim_path = self.tmp / "kubectl"
        shim_path.write_text(KUBECTL_SHIM_SOURCE.format(python=sys.executable), encoding="utf-8")
        shim_path.chmod(shim_path.stat().st_mode | stat.S_IXUSR)
        self.state = make_healthy_cluster_state()
        self.mod = load_verifier_module()

    def write_state(self) -> None:
        serialized = {
            "objects": {
                f"{ns or ''}|{kind}|{name or ''}": val
                for (ns, kind, name), val in self.state["objects"].items()
            },
            "errors": {
                f"{ns or ''}|{kind}|{name or ''}": val
                for (ns, kind, name), val in self.state["errors"].items()
            },
            "raw_stdout": {
                f"{ns or ''}|{kind}|{name or ''}": val
                for (ns, kind, name), val in self.state.get("raw_stdout", {}).items()
            },
        }
        self.state_path.write_text(json.dumps(serialized), encoding="utf-8")

    def read_journal(self) -> list[list[str]]:
        if not self.journal_path.exists():
            return []
        return [json.loads(line) for line in self.journal_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _fake_urlopen(self, req: urllib.request.Request, timeout: int = 45) -> _FakeHTTPResponse:
        parsed = urllib.parse.urlparse(req.full_url)
        host = parsed.netloc
        path = parsed.path
        expected = self.state["secrets_by_host"].get((host, path))
        if expected is None:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b"not found"))
        sig = req.headers.get("X-hub-signature-256", "")
        good = "sha256=" + hmac.new(expected, req.data or b"", hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good):
            raise urllib.error.HTTPError(
                req.full_url,
                401,
                "Unauthorized",
                {},
                io.BytesIO(b'{"status":"bad_signature"}'),
            )
        if host.startswith("issue-agent-webhook."):
            return _FakeHTTPResponse(200, b'{"status":"pong"}')
        return _FakeHTTPResponse(200, b"ok")

    def run_main(self) -> str:
        self.write_state()
        buf = io.StringIO()
        env_patch = {
            "PATH": f"{self.tmp}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_KUBECTL_STATE": str(self.state_path),
            "FAKE_KUBECTL_JOURNAL": str(self.journal_path),
        }
        with (
            patch.dict(os.environ, env_patch),
            patch.object(sys, "argv", ["verify-public-webhooks.py", "--context", "test-ctx"]),
            patch.object(urllib.request, "urlopen", side_effect=self._fake_urlopen),
            contextlib.redirect_stdout(buf),
        ):
            self.mod.main()
        return buf.getvalue()


class VerifyPublicWebhooksContractTests(WebhookVerifierBase):
    def test_qa01_cilium_access_log_gateways_pass_and_cache_gatewayclass(self) -> None:
        out = self.run_main()
        self.assertIn("PASS Flareway resources, placement, and Cilium Gateways", out)
        gwc_calls = [argv for argv in self.read_journal() if "gatewayclass" in argv]
        self.assertEqual(len(gwc_calls), 1)
        self.assertEqual(gwc_calls[0], ["--context", "test-ctx", "get", "gatewayclass", "cilium-access-log", "-o", "json"])

    def test_qa02_healthy_control_default_cilium_class_passes(self) -> None:
        self.state["objects"][("ingress-ctrl", "gateway", "bhyoo-gateway")] = make_cilium_gateway("bhyoo-gateway", "cilium")
        self.state["objects"][("ingress-ctrl", "gateway", "nas-gateway")] = make_cilium_gateway("nas-gateway", "cilium")
        out = self.run_main()
        self.assertIn("PASS Flareway resources, placement, and Cilium Gateways", out)

    def test_qa03_mixed_cilium_canary_classes_pass(self) -> None:
        self.state["objects"][("ingress-ctrl", "gateway", "bhyoo-gateway")] = make_cilium_gateway("bhyoo-gateway", "cilium")
        self.state["objects"][("ingress-ctrl", "gateway", "nas-gateway")] = make_cilium_gateway("nas-gateway", "cilium-access-log")
        out = self.run_main()
        self.assertIn("PASS Flareway resources, placement, and Cilium Gateways", out)
        gwc_names = [argv[argv.index("gatewayclass") + 1] for argv in self.read_journal() if "gatewayclass" in argv]
        self.assertEqual(sorted(gwc_names), ["cilium", "cilium-access-log"])

    def test_qa04_cilium_gateway_rejected_when_accepted_false(self) -> None:
        self.state["objects"][("ingress-ctrl", "gateway", "bhyoo-gateway")] = make_cilium_gateway(
            "bhyoo-gateway", "cilium", accepted="False", programmed="True"
        )
        self.state["objects"][("ingress-ctrl", "gateway", "nas-gateway")] = make_cilium_gateway("nas-gateway", "cilium")
        with self.assertRaises(RuntimeError) as ctx:
            self.run_main()
        self.assertIn("bhyoo-gateway", str(ctx.exception))
        self.assertIn("Accepted", str(ctx.exception))

    def test_qa05a_stale_gatewayclass_observed_generation_rejected(self) -> None:
        self.state["objects"][("ingress-ctrl", "gateway", "bhyoo-gateway")] = make_cilium_gateway("bhyoo-gateway", "cilium")
        self.state["objects"][("ingress-ctrl", "gateway", "nas-gateway")] = make_cilium_gateway("nas-gateway", "cilium")
        self.state["objects"][(None, "gatewayclass", "cilium")] = make_gateway_class("cilium", generation=2, accepted_obs=1)
        with self.assertRaises(RuntimeError) as ctx:
            self.run_main()
        self.assertIn("cilium", str(ctx.exception))

    def test_qa05b_unaccepted_gatewayclass_rejected(self) -> None:
        self.state["objects"][("ingress-ctrl", "gateway", "bhyoo-gateway")] = make_cilium_gateway("bhyoo-gateway", "cilium")
        self.state["objects"][("ingress-ctrl", "gateway", "nas-gateway")] = make_cilium_gateway("nas-gateway", "cilium")
        self.state["objects"][(None, "gatewayclass", "cilium")] = make_gateway_class("cilium", accepted="False")
        with self.assertRaises(RuntimeError) as ctx:
            self.run_main()
        self.assertIn("cilium", str(ctx.exception))

    def test_qa06_non_cilium_gatewayclass_controller_rejected(self) -> None:
        self.state["objects"][("ingress-ctrl", "gateway", "bhyoo-gateway")] = make_cilium_gateway("bhyoo-gateway", "cilium")
        self.state["objects"][("ingress-ctrl", "gateway", "nas-gateway")] = make_cilium_gateway("nas-gateway", "cilium")
        self.state["objects"][(None, "gatewayclass", "cilium")] = make_gateway_class(
            "cilium", controller_name="flareway.bhyoo.com/gateway-controller"
        )
        with self.assertRaises(RuntimeError) as ctx:
            self.run_main()
        self.assertIn("flareway.bhyoo.com/gateway-controller", str(ctx.exception))

    def test_qa07a_main_rejects_null_and_bool_generation(self) -> None:
        self.state["objects"][("ingress-ctrl", "gateway", "bhyoo-gateway")] = make_cilium_gateway(
            "bhyoo-gateway", "cilium", generation=None, accepted_obs=..., programmed_obs=...
        )
        self.state["objects"][("ingress-ctrl", "gateway", "nas-gateway")] = make_cilium_gateway("nas-gateway", "cilium")
        with self.assertRaises(RuntimeError):
            self.run_main()

        self.journal_path.unlink(missing_ok=True)
        self.state["objects"][("ingress-ctrl", "gateway", "bhyoo-gateway")] = make_cilium_gateway(
            "bhyoo-gateway", "cilium", generation=True, accepted_obs=1, programmed_obs=1
        )
        with self.assertRaises(RuntimeError):
            self.run_main()

    def test_qa07b_converged_rejects_invalid_types_and_nulls(self) -> None:
        bad_resources = [
            {"metadata": {}, "status": {"conditions": [{"type": "Ready", "status": "True"}]}},
            {"metadata": {"generation": None}, "status": {"conditions": [{"type": "Ready", "status": "True", "observedGeneration": None}]}},
            {"metadata": {"generation": True}, "status": {"conditions": [{"type": "Ready", "status": "True", "observedGeneration": 1}]}},
            {"metadata": {"generation": 1}, "status": {"conditions": [{"type": "Ready", "status": "True", "observedGeneration": True}]}},
            {"metadata": {"generation": "1"}, "status": {"conditions": [{"type": "Ready", "status": "True", "observedGeneration": "1"}]}},
            {"metadata": {"generation": 1}, "status": {"conditions": [{"type": "Ready", "status": "True", "observedGeneration": 1.0}]}},
            {"metadata": {"generation": 0}, "status": {"conditions": [{"type": "Ready", "status": "True", "observedGeneration": 0}]}},
            {"metadata": {"generation": -1}, "status": {"conditions": [{"type": "Ready", "status": "True", "observedGeneration": -1}]}},
            {"metadata": {"generation": 1}, "status": None},
            {"metadata": {"generation": 1}, "status": {"conditions": None}},
            {"metadata": {"generation": 1}, "status": {"conditions": ["not-a-dict"]}},
        ]
        for res in bad_resources:
            self.assertFalse(self.mod.converged(res, "Ready"))
        self.assertTrue(
            self.mod.converged(
                {"metadata": {"generation": 2}, "status": {"conditions": [condition_entry("Ready", "True", 2)]}},
                "Ready",
            )
        )

    def test_qa08_invalid_gateway_class_names_fail_before_kubectl(self) -> None:
        bad_gateways = [
            make_cilium_gateway("bhyoo-gateway", include_spec=False),
            make_cilium_gateway("bhyoo-gateway", include_class_name=False),
            make_cilium_gateway("bhyoo-gateway", None),
            make_cilium_gateway("bhyoo-gateway", 123),
            make_cilium_gateway("bhyoo-gateway", ""),
            make_cilium_gateway("bhyoo-gateway", "   "),
            make_cilium_gateway("bhyoo-gateway", "-n"),
            make_cilium_gateway("bhyoo-gateway", "ns/bad"),
        ]
        for gw in bad_gateways:
            self.journal_path.unlink(missing_ok=True)
            self.state["objects"][("ingress-ctrl", "gateway", "bhyoo-gateway")] = gw
            with self.assertRaises(RuntimeError) as ctx:
                self.run_main()
            self.assertIn("bhyoo-gateway", str(ctx.exception))
            self.assertIn("gatewayClassName", str(ctx.exception))
            gwc_calls = [argv for argv in self.read_journal() if "gatewayclass" in argv]
            self.assertEqual(gwc_calls, [
                ["--context", "test-ctx", "get", "gatewayclass", "cilium-access-log", "-o", "json"]
            ])

    def test_qa09a_gatewayclass_forbidden_and_notfound_surface_stderr(self) -> None:
        self.state["objects"][("ingress-ctrl", "gateway", "bhyoo-gateway")] = make_cilium_gateway("bhyoo-gateway", "cilium")
        self.state["objects"][("ingress-ctrl", "gateway", "nas-gateway")] = make_cilium_gateway("nas-gateway", "cilium")
        self.state["errors"][(None, "gatewayclass", "cilium")] = {
            "code": 1,
            "stderr": 'Error from server (Forbidden): gatewayclasses.gateway.networking.k8s.io "cilium" is forbidden',
        }
        with self.assertRaises(RuntimeError) as ctx:
            self.run_main()
        self.assertIn("Forbidden", str(ctx.exception))
        self.assertIn("cilium", str(ctx.exception))

        self.journal_path.unlink(missing_ok=True)
        self.state["errors"][(None, "gatewayclass", "cilium")] = {
            "code": 1,
            "stderr": 'Error from server (NotFound): gatewayclasses.gateway.networking.k8s.io "cilium" not found',
        }
        with self.assertRaises(RuntimeError) as ctx2:
            self.run_main()
        self.assertIn("NotFound", str(ctx2.exception))

    def test_qa09b_kubectl_surfaces_stderr_and_redacts_invalid_json_stdout(self) -> None:
        self.state["errors"][("ingress-ctrl", "gateway", "bhyoo-gateway")] = {
            "code": 1,
            "stderr": 'Error from server (NotFound): gateways.gateway.networking.k8s.io "bhyoo-gateway" not found',
        }
        with self.assertRaises(RuntimeError) as ctx:
            self.run_main()
        self.assertIn("NotFound", str(ctx.exception))

        self.state["errors"].clear()
        canary_secret = "CANARY_RAW_SECRET_NOT_FOR_ERROR"
        self.state["raw_stdout"] = {("issue-agent", "secret", "issue-agent-webhook"): f'{{"data": "{canary_secret}"'}
        self.write_state()
        env_patch = {
            "PATH": f"{self.tmp}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_KUBECTL_STATE": str(self.state_path),
            "FAKE_KUBECTL_JOURNAL": str(self.journal_path),
        }
        with patch.dict(os.environ, env_patch):
            with self.assertRaises(RuntimeError) as ctx2:
                self.mod.kubectl("test-ctx", "-n", "issue-agent", "get", "secret", "issue-agent-webhook")
        self.assertNotIn(canary_secret, str(ctx2.exception))

    def test_qa10a_aggregates_failures_across_both_cilium_gateways(self) -> None:
        self.state["objects"][("ingress-ctrl", "gateway", "bhyoo-gateway")] = make_cilium_gateway(
            "bhyoo-gateway", "cilium", accepted="True", programmed="False"
        )
        self.state["objects"][("ingress-ctrl", "gateway", "nas-gateway")] = make_cilium_gateway(
            "nas-gateway", "cilium-access-log", accepted="True", programmed="False"
        )
        with self.assertRaises(RuntimeError) as ctx:
            self.run_main()
        msg = str(ctx.exception)
        self.assertIn("bhyoo-gateway", msg)
        self.assertIn("nas-gateway", msg)
        gw_gets = [argv for argv in self.read_journal() if argv[2:4] == ["-n", "ingress-ctrl"]]
        self.assertEqual(len(gw_gets), 2)

    def test_qa10b_early_gateway_error_does_not_skip_second_gateway(self) -> None:
        self.state["errors"][("ingress-ctrl", "gateway", "bhyoo-gateway")] = {
            "code": 1,
            "stderr": 'Error from server (NotFound): gateways.gateway.networking.k8s.io "bhyoo-gateway" not found',
        }
        self.state["objects"][("ingress-ctrl", "gateway", "nas-gateway")] = make_cilium_gateway(
            "nas-gateway", "cilium-access-log", accepted="True", programmed="False"
        )
        with self.assertRaises(RuntimeError) as ctx:
            self.run_main()
        msg = str(ctx.exception)
        self.assertIn("bhyoo-gateway", msg)
        self.assertIn("nas-gateway", msg)

    def test_qa10c_shared_failing_gatewayclass_queried_once_diagnoses_both(self) -> None:
        self.state["objects"][(None, "gatewayclass", "cilium-access-log")] = make_gateway_class(
            "cilium-access-log", accepted="False"
        )
        with self.assertRaises(RuntimeError) as ctx:
            self.run_main()
        msg = str(ctx.exception)
        self.assertIn("bhyoo-gateway", msg)
        self.assertIn("nas-gateway", msg)
        gwc_calls = [argv for argv in self.read_journal() if "gatewayclass" in argv]
        self.assertEqual(len(gwc_calls), 1)

    def test_qa11_gatewayclass_cache_is_scoped_per_invocation(self) -> None:
        self.run_main()
        self.journal_path.unlink(missing_ok=True)
        self.state["objects"][(None, "gatewayclass", "cilium-access-log")] = make_gateway_class(
            "cilium-access-log", accepted="False"
        )
        with self.assertRaises(RuntimeError):
            self.run_main()
        gwc_calls = [argv for argv in self.read_journal() if "gatewayclass" in argv]
        self.assertEqual(len(gwc_calls), 1)

    def test_qa12_secrets_not_exposed_in_stdout_or_errors(self) -> None:
        canary = "TOP_SECRET_WEBHOOK_VALUE_XYZ"
        canary_b64 = base64.b64encode(canary.encode("ascii")).decode("ascii")
        self.state["objects"][("issue-agent", "secret", "issue-agent-webhook")] = {
            "metadata": {"name": "issue-agent-webhook", "namespace": "issue-agent"},
            "data": {"secret": canary_b64},
        }
        self.state["secrets_by_host"][("issue-agent-webhook.bhyoo.com", "/webhooks/github")] = canary.encode("ascii")
        out = self.run_main()
        self.assertNotIn(canary, out)
        self.assertNotIn(canary_b64, out)

        self.state["objects"][("ingress-ctrl", "gateway", "bhyoo-gateway")] = make_cilium_gateway(
            "bhyoo-gateway", "cilium-access-log", programmed="False"
        )
        with self.assertRaises(RuntimeError) as ctx:
            self.run_main()
        self.assertNotIn(canary, str(ctx.exception))
        self.assertNotIn(canary_b64, str(ctx.exception))

    def test_qa12a_yaml_subset_parser_positives_and_fail_loud_negatives(self) -> None:
        repo_root = target_script_path().parent.parent
        gatewayclass_docs = parse_yaml_documents(
            (repo_root / "apps/objects/cilium-gateway/gatewayclass.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(len(gatewayclass_docs), 2)
        self.assertEqual(gatewayclass_docs[0]["spec"]["telemetry"]["accessLogs"][0]["targets"], ["HTTP"])
        self.assertEqual(
            gatewayclass_docs[0]["spec"]["telemetry"]["accessLogs"][0]["json"]["method"],
            "%REQUEST_HEADER(:METHOD)%",
        )

        bad_inputs = [
            "a:\n\tb: 1\n",
            "a: &anchor val\n",
            "a: *alias\n",
            "<<: *base\n",
            "a: |\n  line\n",
            "a: >\n  line\n",
            "a: {b: 1}\n",
            "%YAML 1.2\n---\na: 1\n",
            "a: !tag val\n",
            "a: 1\na: 2\n",
            'a: "unclosed\n',
            "a: 'foo' trailing\n",
            "a:\n  b:\n   c: 1\n d: 2\n",
        ]
        for bad in bad_inputs:
            with self.assertRaises(ValueError):
                parse_yaml_documents(bad)

    def test_qa12b_repo_manifests_feed_main_without_mismatch(self) -> None:
        repo_root = target_script_path().parent.parent
        gwc_docs = parse_yaml_documents(
            (repo_root / "apps/objects/cilium-gateway/gatewayclass.yaml").read_text(encoding="utf-8")
        )
        gw_docs = parse_yaml_documents(
            (repo_root / "apps/objects/cilium-gateway/gateway.yaml").read_text(encoding="utf-8")
        )
        nas_docs = parse_yaml_documents(
            (repo_root / "apps/objects/cilium-gateway/nas-gateway.yaml").read_text(encoding="utf-8")
        )
        gwc = next(d for d in gwc_docs if d.get("kind") == "GatewayClass")
        cfg = next(d for d in gwc_docs if d.get("kind") == "CiliumGatewayClassConfig")
        self.assertEqual(gwc["spec"]["controllerName"], "io.cilium/gateway-controller")
        self.assertEqual(gwc["spec"]["parametersRef"]["name"], cfg["metadata"]["name"])
        for gw in (gw_docs[0], nas_docs[0]):
            cert_ref = gw["spec"]["listeners"][0]["tls"]["certificateRefs"][0]
            self.assertEqual(cert_ref["group"], "")
            self.assertEqual(cert_ref["name"], "wildcard-bhyoo-com-tls")
            self.assertEqual(gw["spec"]["gatewayClassName"], gwc["metadata"]["name"])

        self.state["objects"][("ingress-ctrl", "gateway", "bhyoo-gateway")] = make_cilium_gateway(
            gw_docs[0]["metadata"]["name"], gw_docs[0]["spec"]["gatewayClassName"], generation=4, accepted_obs=4, programmed_obs=4
        )
        self.state["objects"][("ingress-ctrl", "gateway", "nas-gateway")] = make_cilium_gateway(
            nas_docs[0]["metadata"]["name"], nas_docs[0]["spec"]["gatewayClassName"], generation=2, accepted_obs=2, programmed_obs=2
        )
        self.state["objects"][(None, "gatewayclass", gwc["metadata"]["name"])] = make_gateway_class(
            gwc["metadata"]["name"], controller_name=str(gwc["spec"]["controllerName"])
        )
        out = self.run_main()
        self.assertIn("PASS Flareway resources, placement, and Cilium Gateways", out)

    def test_qa13_readme_documents_gatewayclass_and_secret_permissions(self) -> None:
        repo_root = target_script_path().parent.parent
        readme_lines = (repo_root / "README.md").read_text(encoding="utf-8").splitlines()
        line = next((l for l in readme_lines if "verify-public-webhooks.py" in l), "")
        self.assertIn("Secret", line)
        self.assertIn("GatewayClass", line)


if __name__ == "__main__":
    unittest.main()
