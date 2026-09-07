#!/usr/bin/env python3
"""
EVIL MCP server — ENG-1226340 sanitization test fixture (STANDALONE).

Fully self-contained copy of mcp_server_2026.py (2026-07-28 protocol,
session-less, dual-stack legacy fallback) with hostile data baked in:
  * tool / prompt / resource names containing JSON injection, newlines,
    control chars, HTML, unicode/RTL/emoji, and an oversized (10KB) name
  * serverInfo.name is ALWAYS hostile
  * response headers (Mcp-Name / Mcp-Method) are pre-sanitized so hostile
    names don't break HTTP header encoding

Run:
  python mcp_server_evil.py          # PORT env, default 10002

Drive it with:
  python mcp_sanitize_tests.py --url http://localhost:10002/mcp
  python mcp_sanitize_tests.py --url http://localhost:10002/mcp --proxy http://10.156.22.20:8081

Deploy note: run this as a SEPARATE service from the clean server — the
hostile serverInfo would poison the proxy's cached server name otherwise.
"""

import asyncio
import json
import os
import time
import uuid
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

PROTOCOL_VERSION = "2026-07-28"
SERVER_NAME = 'evil-srv","injected":"yes\n<script>alert(1)</script>'   # ALWAYS hostile
SERVER_VERSION = "1.0.0"
PORT = int(os.environ.get("PORT", "10002"))

# Meta keys used by the 2026-07-28 spec.
META_PROTOCOL = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
META_CLIENT_CAPS = "io.modelcontextprotocol/clientCapabilities"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"

# Legacy (pre-2026) protocol versions this server can fall back to.
LEGACY_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
SUPPORTED_VERSIONS = [PROTOCOL_VERSION] + LEGACY_VERSIONS

# session_id -> {"version": str, "created": float}  (legacy session-based clients)
SESSIONS: dict = {}

# ---------------------------------------------------------------------------
# Data used by tools/resources (DLP-relevant payloads)
# ---------------------------------------------------------------------------

EICAR = r"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

EMPLOYEES = [
    {"id": 101, "name": "Alice Johnson", "role": "Software Engineer", "department": "Engineering", "email": "alice.johnson@bobsbank.net", "location": "New York", "ssn": "123-45-6789"},
    {"id": 102, "name": "Bob Smith", "role": "QA Engineer", "department": "Quality Assurance", "email": "bob.smith@bobsbank.net", "location": "San Francisco", "ssn": "987-65-4321"},
    {"id": 103, "name": "Charlie Brown", "role": "Product Manager", "department": "Product", "email": "charlie.brown@bobsbank.net", "location": "London", "ssn": "555-22-3333"},
    {"id": 104, "name": "Diana Prince", "role": "DevOps Engineer", "department": "Infrastructure", "email": "diana.prince@bobsbank.net", "location": "Berlin", "ssn": "111-22-3333"},
    {"id": 105, "name": "Ethan Hunt", "role": "Security Analyst", "department": "Cybersecurity", "email": "ethan.hunt@bobsbank.net", "location": "Singapore", "ssn": "444-55-6666"},
]

PCI_CARDS = [
    {"brand": "Visa", "number": "4111111111111111"},
    {"brand": "Mastercard", "number": "5555555555554444"},
    {"brand": "Amex", "number": "378282246310005"},
    {"brand": "Discover", "number": "6011111111111117"},
]

CONFIDENTIAL = "Bob's Bank is planning to acquire Fabio Insurance in February 2026"

# ---------------------------------------------------------------------------
# Tools (normal + EVIL sanitization fixtures)
# ---------------------------------------------------------------------------

def _text(*parts) -> dict:
    return {"type": "text", "text": " ".join(str(p) for p in parts)}

TOOLS = {
    "greet": {
        "description": "Greet someone (no LLM sampling in the new protocol).",
        "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        "handler": lambda a: _text("Hello,", a.get("name", "World")),
    },
    "add": {
        "description": "Add two numbers.",
        "inputSchema": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]},
        "handler": lambda a: _text(int(a.get("a", 0)) + int(a.get("b", 0))),
    },
    "get_eicar": {
        "description": "Return the EICAR anti-malware test string.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: _text(EICAR),
    },
    "get_employees": {
        "description": "Return employee records containing PII.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: _text(json.dumps({"employees": EMPLOYEES})),
    },
    "get_pci": {
        "description": "Return sample PCI card numbers.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: _text(json.dumps({"cards": PCI_CARDS})),
    },
    "get_confidential": {
        "description": "Return confidential M&A text.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: _text(CONFIDENTIAL),
    },
    "test_progress": {
        "description": "Progress demo (steps reported inline).",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: _text("Progress: 5/5 steps complete (100%)"),
    },
    "test_logging": {
        "description": "Logging demo (log levels reported inline).",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: _text("Logs emitted at debug/info/notice/warning/error/critical"),
    },
    "list_templates": {
        "description": "List registered resource URI templates.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: _text("Available templates: greeting://{name}"),
    },
    # ---- MRTR / elicitation (best-effort input_required shape) ----
    "elicit_feedback": {
        "description": "Ask the client a question via input_required (MRTR).",
        "inputSchema": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
        "result_type": "input_required",
        "handler": lambda a: {
            "kind": "elicitation",
            "message": a.get("question", "Please provide feedback"),
            "schema": {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
        },
    },
    "collect_user_info": {
        "description": "Request user info via input_required (MRTR).",
        "inputSchema": {"type": "object", "properties": {}},
        "result_type": "input_required",
        "handler": lambda a: {
            "kind": "elicitation",
            "message": "Please provide your name and preferred language.",
            "schema": {"type": "object", "properties": {"name": {"type": "string"}, "language": {"type": "string"}}, "required": ["name", "language"]},
        },
    },
    # ---- EVIL fixtures (ENG-1226340) ----
    'evil_inj","injected":"yes': {
        "description": "JSON injection attempt via tool name.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: _text("evil inj ok"),
    },
    "evil_newline\nforged-log-line": {
        "description": "Newline injection in tool name.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: _text("evil newline ok"),
    },
    "evil_html_<script>alert(1)</script>": {
        "description": "HTML/JS injection in tool name.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: _text("evil html ok"),
    },
    "evil_ctrl_\x00\x01\x1f": {
        "description": "Control characters in tool name.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: _text("evil ctrl ok"),
    },
    "evil_unicode_\u202e\u263a\U0001F680": {
        "description": "Unicode / RTL override / emoji in tool name.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: _text("evil unicode ok"),
    },
    "evil_long_" + "A" * 10000: {
        "description": "Oversized (10KB) tool name.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: _text("evil long ok"),
    },
}

# ---------------------------------------------------------------------------
# Resources / prompts (normal + EVIL fixtures)
# ---------------------------------------------------------------------------

RESOURCES = {
    "greeting://test":     {"name": "get_greeting_test",   "description": "A test greeting.",                 "mimeType": "text/plain",       "text": "Hello, test!",                     "cacheScope": "public"},
    "greeting://eicar":    {"name": "get_greeting_eicar",  "description": "EICAR anti-malware test string.",  "mimeType": "text/plain",       "text": EICAR,                              "cacheScope": "public"},
    "confidential://news": {"name": "get_confidential_news","description": "Confidential M&A news.",          "mimeType": "text/plain",       "text": CONFIDENTIAL,                       "cacheScope": "private"},
    "employees://details": {"name": "get_employee_details","description": "Employee records (contains PII).", "mimeType": "application/json", "text": json.dumps({"employees": EMPLOYEES}), "cacheScope": "private"},
    "pci://sample":        {"name": "get_pci_sample",      "description": "Sample PCI card numbers.",         "mimeType": "application/json", "text": json.dumps({"cards": PCI_CARDS}),     "cacheScope": "private"},
    # ---- EVIL fixtures (ENG-1226340) ----
    'evilres://inj","x":"y': {"name": 'evil_res","injected":"1', "description": "JSON injection via resource name/uri.", "mimeType": "text/plain", "text": "evil resource",  "cacheScope": "public"},
    "evilres://new\nline":   {"name": "evil_res_new\nline",     "description": "Newline in resource name/uri.",        "mimeType": "text/plain", "text": "evil resource 2", "cacheScope": "public"},
}

RESOURCE_TEMPLATES = [
    {"name": "get_greeting", "uriTemplate": "greeting://{name}", "description": "Get a personalized greeting.", "mimeType": "text/plain"},
]

PROMPTS = {
    "greet_user": {
        "description": "A prompt asking for a greeting.",
        "text": "Write a warm greeting for {name} in a {style} style.",
        "arguments": [
            {"name": "name",  "description": "Who to greet",                            "required": True},
            {"name": "style", "description": "Greeting style (friendly/formal/casual)", "required": False},
        ],
    },
    "pii_pci_analyzer": {
        "description": "A prompt for detecting PII/PCI/PHI.",
        "text": "Identify PII/PCI/PHI in: {text}",
        "arguments": [
            {"name": "text",     "description": "Text to analyze",        "required": True},
            {"name": "category", "description": "Category (pii/pci/phi)", "required": False},
        ],
    },
    # ---- EVIL fixture (ENG-1226340) ----
    'evil_prompt","injected":"yes': {
        "description": "Prompt name with JSON injection attempt.",
        "text": "Say hi to {name}.",
        "arguments": [{"name": "name", "description": "name", "required": False}],
    },
}

# Advertised in initialize / server/discover.
CAPABILITIES = {
    "tools": {"listChanged": False},
    "resources": {"subscribe": False, "listChanged": False},
    "prompts": {"listChanged": False},
    "completions": {},
}

# ---------------------------------------------------------------------------
# JSON-RPC core
# ---------------------------------------------------------------------------

def make_result(result_obj, meta=True, version=PROTOCOL_VERSION):
    """Wrap a protocol result; 2026 adds resultType + serverInfo meta,
    legacy versions get the classic unwrapped shape."""
    if version == PROTOCOL_VERSION:
        if "resultType" not in result_obj:
            result_obj["resultType"] = "complete"
        if meta and "_meta" not in result_obj:
            result_obj["_meta"] = {META_SERVER_INFO: {"name": SERVER_NAME, "version": SERVER_VERSION}}
    return result_obj

async def call_handler(handler, args):
    r = handler(args)
    if asyncio.iscoroutine(r):
        r = await r
    return r

def _tools_list():
    return [
        {
            "name": name,
            "title": name,
            "description": spec["description"],
            "inputSchema": spec["inputSchema"],
        }
        for name, spec in TOOLS.items()
    ]

def _resources_list():
    return [
        {"uri": u, "name": r["name"], "title": r["name"],
         "description": r["description"], "mimeType": r["mimeType"]}
        for u, r in RESOURCES.items()
    ]

def _templates_list():
    return [
        {**t, "title": t["name"]}
        for t in RESOURCE_TEMPLATES
    ]

def _prompts_list():
    return [
        {"name": k, "title": k, "description": v["description"], "arguments": v.get("arguments", [])}
        for k, v in PROMPTS.items()
    ]

async def dispatch(method, params, request_meta, ctx):
    """Return a JSON-RPC result dict, or raise RuntimeError for errors."""
    params = params or {}
    version = ctx["version"]
    mr = lambda obj, meta=True: make_result(obj, meta=meta, version=version)
    print(f"[{version}] <- {method}  _meta={json.dumps(request_meta, default=str)[:200]}")

    if method == "initialize":
        requested = params.get("protocolVersion", LEGACY_VERSIONS[0])
        negotiated = requested if requested in SUPPORTED_VERSIONS else LEGACY_VERSIONS[0]
        ctx["version"] = negotiated
        return {
            "protocolVersion": negotiated,
            "capabilities": CAPABILITIES,
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }

    if method == "ping":
        return mr({})

    if method == "server/discover":
        return mr({
            "supportedVersions": SUPPORTED_VERSIONS,
            "capabilities": CAPABILITIES,
            "instructions": "EVIL demo MCP server (ENG-1226340 fixture). Speaks 2026-07-28; "
                            "legacy clients may connect via the classic initialize handshake.",
            "ttlMs": 3600000,
            "cacheScope": "public",
        })

    if method == "tools/list":
        return mr({
            "tools": _tools_list(),
            "ttlMs": 60000,
            "cacheScope": "public",
        })

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})
        input_responses = params.get("inputResponses")
        if name not in TOOLS:
            raise RuntimeError(f"Tool not found: {name}")
        spec = TOOLS[name]
        if spec.get("result_type") == "input_required" and not input_responses:
            payload = await call_handler(spec["handler"], arguments)
            if version == PROTOCOL_VERSION:
                return mr({
                    "resultType": "input_required",
                    "inputRequests": [{
                        "id": str(uuid.uuid4()),
                        "kind": payload.get("kind", "elicitation"),
                        "message": payload.get("message", ""),
                        "schema": payload.get("schema", {}),
                    }],
                })
            return mr({"content": [_text(payload.get("message", ""))]})
        if input_responses:
            content = [_text("Received input:", json.dumps(input_responses))]
        else:
            out = await call_handler(spec["handler"], arguments)
            content = out if isinstance(out, list) else [out]
            if isinstance(out, dict) and "type" in out:
                content = [out]
        return mr({"content": content})

    if method == "resources/list":
        return mr({"resources": _resources_list(), "ttlMs": 60000, "cacheScope": "public"})

    if method == "resources/templates/list":
        return mr({"resourceTemplates": _templates_list(), "ttlMs": 60000, "cacheScope": "public"})

    if method == "resources/read":
        uri = params.get("uri", "")
        r = RESOURCES.get(uri)
        if not r:
            raise RuntimeError(f"Resource not found: {uri}")
        return mr({
            "contents": [{"uri": uri, "mimeType": r["mimeType"], "text": r["text"]}],
            "ttlMs": 60000,
            "cacheScope": r.get("cacheScope", "private"),
        })

    if method == "prompts/list":
        return mr({"prompts": _prompts_list(), "ttlMs": 60000, "cacheScope": "public"})

    if method == "prompts/get":
        name = params.get("name", "")
        p = PROMPTS.get(name)
        if not p:
            raise RuntimeError(f"Prompt not found: {name}")
        txt = p["text"]
        try:
            txt = txt.format(**params.get("arguments", {}))
        except Exception:
            pass
        return mr({"description": p["description"], "messages": [{"role": "user", "content": {"type": "text", "text": txt}}],
                   "ttlMs": 60000, "cacheScope": "public"})

    if method == "completion/complete":
        ref = params.get("ref", {})
        argument = params.get("argument", {})
        arg_name, arg_value = argument.get("name", ""), argument.get("value", "")
        values = []
        if ref.get("type") == "ref/prompt":
            if ref.get("name") == "greet_user":
                if arg_name == "style":
                    values = [s for s in ["friendly", "formal", "casual"] if s.startswith(arg_value)]
                elif arg_name == "name":
                    values = [n for n in ["Jaden", "Alice", "Bob", "Charlie"] if n.lower().startswith(arg_value.lower())]
            elif ref.get("name") == "pii_pci_analyzer" and arg_name == "category":
                values = [c for c in ["pii", "pci", "phi"] if c.startswith(arg_value.lower())]
        elif ref.get("type") == "ref/resource" and arg_name == "name":
            values = [s for s in ["World", "test", "eicar", "Jaden", "Alice"] if s.lower().startswith(arg_value.lower())]
        return mr({"completion": {"values": values, "total": len(values), "hasMore": False}})

    if method == "subscriptions/listen":
        return mr({"subscriptionId": str(uuid.uuid4())})

    raise RuntimeError(f"Unknown method: {method}")

# ---------------------------------------------------------------------------
# HTTP app
# ---------------------------------------------------------------------------

def _hval(v):
    """Header values must be latin-1 with no control chars (CR/LF, emoji, etc.)."""
    return "".join(c if 32 <= ord(c) <= 255 else "?" for c in str(v))

async def mcp_endpoint(request: Request):
    body = await request.body()
    try:
        msg = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}, status_code=400)

    params = msg.get("params") or {}
    req_meta = params.get("_meta", {})
    rpc_id = msg.get("id")
    method = msg.get("method")

    # ---- version / session detection --------------------------------------
    session_id = request.headers.get("mcp-session-id")
    if method == "initialize":
        session_id = str(uuid.uuid4())
        ctx = {"version": LEGACY_VERSIONS[0], "session_id": session_id}
        SESSIONS[session_id] = {"version": ctx["version"], "created": time.time()}
    elif session_id and session_id in SESSIONS:
        ctx = {"version": SESSIONS[session_id]["version"], "session_id": session_id}
    else:
        version = req_meta.get(META_PROTOCOL, PROTOCOL_VERSION)
        ctx = {"version": version if version in SUPPORTED_VERSIONS else PROTOCOL_VERSION,
               "session_id": None}

    # NOTE: header values are sanitized (_hval) because tool/method names may
    # contain control chars / unicode that are illegal in HTTP headers.
    headers = {"MCP-Protocol-Version": _hval(ctx["version"])}
    if ctx["session_id"]:
        headers["Mcp-Session-Id"] = _hval(ctx["session_id"])
    if method:
        headers["Mcp-Method"] = _hval(method)
    if method == "tools/call" and params.get("name"):
        headers["Mcp-Name"] = _hval(params.get("name"))

    if "id" not in msg:
        return Response(b"", status_code=202, headers=headers)

    try:
        result = await dispatch(method, params, req_meta, ctx)
        if ctx["session_id"]:
            SESSIONS[ctx["session_id"]]["version"] = ctx["version"]
            headers["MCP-Protocol-Version"] = _hval(ctx["version"])
        resp = {"jsonrpc": "2.0", "id": rpc_id, "result": result}
        return JSONResponse(resp, headers=headers)
    except RuntimeError as e:
        return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": str(e)}}, headers=headers)

# ---- REST API (Postman) ----

def api_ping(_):
    return JSONResponse({"status": "ok", "server": "mcp-2026-07-28-EVIL"})

def api_summary(_):
    return JSONResponse({
        "protocol": PROTOCOL_VERSION,
        "server": "EVIL (ENG-1226340 fixture)",
        "mcp_tools": sorted(TOOLS.keys()),
        "resources": sorted(RESOURCES.keys()),
        "prompts": sorted(PROMPTS.keys()),
        "rest_endpoints": ["/api/ping", "/api/summary", "/api/employees", "/api/pci", "/api/eicar", "/api/confidential"],
    })

def api_employees(_):
    return JSONResponse({"employees": EMPLOYEES})

def api_pci(_):
    return JSONResponse({"cards": PCI_CARDS})

def api_eicar(_):
    return JSONResponse({"eicar": EICAR})

def api_confidential(_):
    return JSONResponse({"confidential": CONFIDENTIAL})

app = Starlette(routes=[
    Route("/mcp", mcp_endpoint, methods=["POST"]),
    Route("/api/ping", api_ping, methods=["GET"]),
    Route("/api/summary", api_summary, methods=["GET"]),
    Route("/api/employees", api_employees, methods=["GET"]),
    Route("/api/pci", api_pci, methods=["GET"]),
    Route("/api/eicar", api_eicar, methods=["GET"]),
    Route("/api/confidential", api_confidential, methods=["GET"]),
])

import uvicorn

if __name__ == "__main__":
    tools = ", ".join(sorted(TOOLS.keys())).encode("ascii", "backslashreplace").decode()
    print(f"""
{'=' * 68}
  EVIL MCP Server — ENG-1226340 sanitization fixture (2026-07-28)
{'=' * 68}
  Endpoint:   http://0.0.0.0:{PORT}/mcp
  Protocol:   {PROTOCOL_VERSION} (fallback: {', '.join(LEGACY_VERSIONS)})
  serverInfo: ALWAYS hostile -> {SERVER_NAME.encode('ascii', 'backslashreplace').decode()!r}

  Evil fixtures: 6 tools, 2 resources, 1 prompt
  Tools: {tools}
  REST API:   GET /api/summary
{'=' * 68}
""")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
