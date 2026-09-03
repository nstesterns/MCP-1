"""
MCP server with dedicated REST API endpoints for Postman testing.

Two ways to interact:
  1. MCP protocol  → POST http://localhost:10000/mcp           (SSE-streamed, for Claude)
  2. REST API      → GET/POST http://localhost:10000/api/*     (plain JSON, for Postman)

Run:
    python mcp_server_postman.py
Starts on http://0.0.0.0:10000    (change PORT in .env or set PORT env var)
"""

import asyncio
import time
import json
from starlette.requests import Request
from starlette.responses import JSONResponse
from mcp.server.fastmcp import FastMCP, Context
from mcp.types import (
    ElicitResult,
    GetPromptResult,
    CreateMessageRequest,
    SamplingMessage,
    TextContent,
    Completion,
    ResourceTemplateReference,
    PromptReference,
)
from dotenv import load_dotenv
import os
import uvicorn

load_dotenv()
port = int(os.environ.get("PORT", 10000))

mcp = FastMCP("Demo-Postman")


# =============================================================================
# RESOURCE SUBSCRIPTIONS — enables ResourceUpdatedNotification to work
# =============================================================================

@mcp._mcp_server.subscribe_resource()
async def handle_subscribe(uri: str) -> None:
    """Acknowledge resource subscription."""
    pass


@mcp._mcp_server.unsubscribe_resource()
async def handle_unsubscribe(uri: str) -> None:
    """Acknowledge resource unsubscription."""
    pass


# =============================================================================
# COMPLETION HANDLER — enables completion/complete (autocomplete)
# =============================================================================

@mcp.completion()
async def handle_completion(ref, argument, context) -> Completion | None:
    """Provide autocomplete suggestions for prompts and resource templates."""

    # greet_user prompt — suggest style and name values
    if isinstance(ref, PromptReference) and ref.name == "greet_user":
        if argument.name == "style":
            styles = ["friendly", "formal", "casual"]
            matches = [s for s in styles if s.startswith(argument.value)]
            return Completion(values=matches, total=len(matches), hasMore=False)
        if argument.name == "name":
            names = ["Jaden", "Alice", "Bob", "Charlie"]
            matches = [n for n in names if n.lower().startswith(argument.value.lower())]
            return Completion(values=matches, total=len(matches), hasMore=False)

    # pii_pci_analyzer prompt — suggest category values
    if isinstance(ref, PromptReference) and ref.name == "pii_pci_analyzer":
        if argument.name == "category":
            categories = ["pii", "pci", "phi"]
            matches = [c for c in categories if c.startswith(argument.value.lower())]
            return Completion(values=matches, total=len(matches), hasMore=False)

    # greeting://{name} resource template
    if isinstance(ref, ResourceTemplateReference):
        if argument.name == "name":
            suggestions = ["World", "test", "eicar", "Jaden", "Alice"]
            matches = [s for s in suggestions if s.lower().startswith(argument.value.lower())]
            return Completion(values=matches, total=len(matches), hasMore=False)

    return None


# =============================================================================
# REST API ENDPOINTS — Plain JSON, no SSE, perfect for Postman
# =============================================================================

@mcp.custom_route("/api/ping", methods=["GET"])
async def api_ping(request: Request) -> JSONResponse:
    """Health check."""
    return JSONResponse({"status": "ok", "server": "mcp-postman-demo"})


@mcp.custom_route("/api/test/progress", methods=["GET", "POST"])
async def api_test_progress(request: Request) -> JSONResponse:
    """
    Simulates ProgressNotification during a long-running operation.
    Returns all progress steps inline.
    """
    notifications = []
    steps = 5
    for i in range(1, steps + 1):
        progress_pct = round((i / steps) * 100, 1)
        msg = f"Step {i}/{steps} ({progress_pct:.0f}%)"
        notifications.append({
            "type": "ProgressNotification",
            "step": i,
            "progress": progress_pct,
            "total": 100,
            "message": msg,
        })
        await asyncio.sleep(0.3)

    return JSONResponse({
        "status": "ok",
        "description": "ProgressNotification — 5 steps simulated",
        "notifications": notifications,
        "count": len(notifications),
    })


@mcp.custom_route("/api/test/logging", methods=["GET", "POST"])
async def api_test_logging(request: Request) -> JSONResponse:
    """Sends LoggingMessageNotification at all 6 severity levels."""
    notifications = []
    for level in ["debug", "info", "notice", "warning", "error", "critical"]:
        notifications.append({
            "type": "LoggingMessageNotification",
            "level": level,
            "logger": "demo-logger",
            "data": f"Log message at {level.upper()} level",
        })

    return JSONResponse({
        "status": "ok",
        "description": "LoggingMessageNotification — all 6 levels",
        "notifications": notifications,
        "count": len(notifications),
    })


@mcp.custom_route("/api/test/tool-list-changed", methods=["GET", "POST"])
async def api_test_tool_list_changed(request: Request) -> JSONResponse:
    """Sends ToolListChangedNotification."""
    return JSONResponse({
        "status": "ok",
        "description": "ToolListChangedNotification — client should re-fetch tools/list",
        "notifications": [{
            "type": "ToolListChangedNotification",
            "info": "The server's tool list has changed. Client should call tools/list again.",
        }],
    })


@mcp.custom_route("/api/test/resource-list-changed", methods=["GET", "POST"])
async def api_test_resource_list_changed(request: Request) -> JSONResponse:
    """Sends ResourceListChangedNotification."""
    return JSONResponse({
        "status": "ok",
        "description": "ResourceListChangedNotification — client should re-fetch resources/list",
        "notifications": [{
            "type": "ResourceListChangedNotification",
            "info": "The server's resource list has changed. Client should call resources/list again.",
        }],
    })


@mcp.custom_route("/api/test/prompt-list-changed", methods=["GET", "POST"])
async def api_test_prompt_list_changed(request: Request) -> JSONResponse:
    """Sends PromptListChangedNotification."""
    return JSONResponse({
        "status": "ok",
        "description": "PromptListChangedNotification — client should re-fetch prompts/list",
        "notifications": [{
            "type": "PromptListChangedNotification",
            "info": "The server's prompt list has changed. Client should call prompts/list again.",
        }],
    })


@mcp.custom_route("/api/test/resource-updated", methods=["GET", "POST"])
async def api_test_resource_updated(request: Request) -> JSONResponse:
    """Sends ResourceUpdatedNotification for a given URI."""
    uri = request.query_params.get("uri", "greeting://test")
    return JSONResponse({
        "status": "ok",
        "description": f"ResourceUpdatedNotification — resource '{uri}' was updated",
        "notifications": [{
            "type": "ResourceUpdatedNotification",
            "uri": uri,
            "info": "If subscribed, client should re-read this resource.",
        }],
    })


@mcp.custom_route("/api/test/elicit-complete", methods=["GET", "POST"])
async def api_test_elicit_complete(request: Request) -> JSONResponse:
    """Sends ElicitCompleteNotification."""
    outcome = request.query_params.get("outcome", "accept")
    return JSONResponse({
        "status": "ok",
        "description": f"ElicitCompleteNotification — outcome='{outcome}'",
        "notifications": [{
            "type": "ElicitCompleteNotification",
            "outcome": outcome,
            "result": {"submitted_by": "test-user", "approved": True} if outcome == "accept" else None,
        }],
    })


@mcp.custom_route("/api/test/burst", methods=["GET", "POST"])
async def api_test_burst(request: Request) -> JSONResponse:
    """
    BURST TEST — sends ALL 7 notification types in one response.
    This is the quickest way to see every notification at once.
    """
    notifications = [
        {"type": "ProgressNotification",         "progress": 50, "total": 100, "message": "Burst at 50%"},
        {"type": "LoggingMessageNotification",   "level": "info", "logger": "burst", "data": "Burst log message"},
        {"type": "ToolListChangedNotification",  "info": "tools/list is stale"},
        {"type": "ResourceListChangedNotification", "info": "resources/list is stale"},
        {"type": "PromptListChangedNotification",    "info": "prompts/list is stale"},
        {"type": "ResourceUpdatedNotification",  "uri": "greeting://test"},
        {"type": "ElicitCompleteNotification",   "outcome": "accept", "result": {"burst": True}},
    ]
    return JSONResponse({
        "status": "ok",
        "description": "BURST: all 7 notification types in one response",
        "notifications": notifications,
        "count": len(notifications),
        "types_covered": [
            "InitializedNotification  (auto, on connect)",
            "ProgressNotification",
            "LoggingMessageNotification",
            "ToolListChangedNotification",
            "ResourceListChangedNotification",
            "PromptListChangedNotification",
            "ResourceUpdatedNotification",
            "CancelledNotification    (client→server, see /api/test/cancellation-hint)",
            "ElicitCompleteNotification",
        ],
    })


@mcp.custom_route("/api/test/cancellation-hint", methods=["GET"])
async def api_test_cancellation_hint(request: Request) -> JSONResponse:
    """Shows how to test CancelledNotification from Postman."""
    return JSONResponse({
        "description": "To test CancelledNotification, you need two requests:",
        "step_1": "POST /mcp — call the 'cancellable_op' tool (takes ~10 seconds)",
        "step_2": "While step 1 is running, POST /mcp with this body:",
        "cancel_body": {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {
                "requestId": "<replace-with-request-id-from-step-1>",
                "reason": "User cancelled"
            }
        },
        "note": "Postman can't easily do this because SSE is needed. Use curl or a script for this test.",
    })


@mcp.custom_route("/api/summary", methods=["GET"])
async def api_summary(request: Request) -> JSONResponse:
    """Full summary of all notification endpoints."""
    return JSONResponse({
        "server": "MCP Notification Test Server",
        "endpoints": {
            "GET /api/ping":                            "Health check",
            "GET /api/summary":                         "This page",
            "",
            "GET /api/test/progress":                   "ProgressNotification — 5-step progress",
            "GET /api/test/logging":                    "LoggingMessageNotification — 6 levels",
            "GET /api/test/tool-list-changed":          "ToolListChangedNotification",
            "GET /api/test/resource-list-changed":      "ResourceListChangedNotification",
            "GET /api/test/prompt-list-changed":        "PromptListChangedNotification",
            "GET /api/test/resource-updated?uri=...":   "ResourceUpdatedNotification",
            "GET /api/test/elicit-complete?outcome=...":"ElicitCompleteNotification",
            "GET /api/test/burst":                      "ALL 7 notifications in one call",
            "GET /api/test/cancellation-hint":           "How to test CancelledNotification",
        },
    })


# =============================================================================
# MCP TOOLS — for Claude Desktop compatibility
# =============================================================================

@mcp.tool()
async def cancellable_op(ctx: Context = None) -> str:
    """
    Long-running tool (10 sec) that can be cancelled.
    Send CancelledNotification while this runs to test cancellation.
    """
    for i in range(1, 11):
        if ctx:
            await ctx.report_progress(progress=i, total=10, message=f"Step {i}/10")
        await asyncio.sleep(1.0)
    return "Completed all 10 steps without cancellation."


@mcp.tool()
async def greet(name: str = "World", ctx: Context = None) -> str:
    """Greet someone using LLM sampling"""
    result = await ctx.session.create_message(
        CreateMessageRequest(
            messages=[
                SamplingMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"Write a short, warm greeting for someone named {name}.",
                    ),
                )
            ],
            systemPrompt="You are a friendly assistant. Keep it to one sentence.",
            maxTokens=100,
        )
    )
    return result.content.text


@mcp.tool()
async def add(a: int, b: int, ctx: Context = None) -> str:
    """Add two numbers and explain the result via LLM"""
    result = await ctx.session.create_message(
        CreateMessageRequest(
            messages=[
                SamplingMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"Explain in one friendly sentence what {a} + {b} equals.",
                    ),
                )
            ],
            maxTokens=60,
        )
    )
    return result.content.text


# =============================================================================
# RESOURCES
# =============================================================================

@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting"""
    return f"Hello, {name}!"


@mcp.resource("greeting://eicar")
def get_greeting_eicar() -> str:
    return r"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


@mcp.resource("greeting://test")
def get_greeting_test() -> str:
    return "Hello, test!"


@mcp.resource("confidential://news")
def get_confidential_news() -> str:
    return "Bob's Bank is planning to acquire Fabio Insurance in February 2026"


@mcp.resource("employees://details")
def get_employee_details() -> dict:
    employees = [
        {"id": 101, "name": "Alice Johnson", "role": "Software Engineer", "department": "Engineering", "email": "alice.johnson@bobsbank.net", "location": "New York"},
        {"id": 102, "name": "Bob Smith", "role": "QA Engineer", "department": "Quality Assurance", "email": "bob.smith@bobsbank.net", "location": "San Francisco"},
        {"id": 103, "name": "Charlie Brown", "role": "Product Manager", "department": "Product", "email": "charlie.brown@bobsbank.net", "location": "London"},
        {"id": 104, "name": "Diana Prince", "role": "DevOps Engineer", "department": "Infrastructure", "email": "diana.prince@bobsbank.net", "location": "Berlin"},
        {"id": 105, "name": "Ethan Hunt", "role": "Security Analyst", "department": "Cybersecurity", "email": "ethan.hunt@bobsbank.net", "location": "Singapore"},
        {"id": 106, "name": "Fiona Gallagher", "role": "Data Scientist", "department": "Data Analytics", "email": "fiona.gallagher@bobsbank.net", "location": "Toronto"},
        {"id": 107, "name": "George Miller", "role": "UI/UX Designer", "department": "Design", "email": "george.miller@bobsbank.net", "location": "Sydney"},
        {"id": 108, "name": "Hannah Lee", "role": "Frontend Developer", "department": "Engineering", "email": "hannah.lee@bobsbank.net", "location": "Tokyo"},
        {"id": 109, "name": "Ian Wright", "role": "Backend Developer", "department": "Engineering", "email": "ian.wright@bobsbank.net", "location": "Dublin"},
        {"id": 110, "name": "Julia Roberts", "role": "HR Manager", "department": "Human Resources", "email": "julia.roberts@bobsbank.net", "location": "Amsterdam"},
    ]
    return {"employees": employees}


# =============================================================================
# PROMPTS
# =============================================================================

@mcp.prompt()
def greet_user(name: str = "Jaden", style: str = "friendly") -> GetPromptResult:
    styles = {
        "friendly": "Please write a warm, friendly greeting",
        "formal": "Please write a formal, professional greeting",
        "casual": "Please write a casual, relaxed greeting",
    }
    prompt_text = f"{styles.get(style, styles['friendly'])} for someone named {name}."
    return GetPromptResult(
        description="A prompt that asks for a specific style of greeting.",
        messages=[{"role": "user", "content": {"type": "text", "text": prompt_text}}],
        metadata={"style": style},
    )


@mcp.prompt()
def pii_pci_analyzer(text: str, category: str = "pii") -> GetPromptResult:
    categories = {
        "pii": "Identify PII (Personally Identifiable Information) in the text.",
        "pci": "Identify PCI (Payment Card Information) in the text.",
        "phi": "Identify PHI (Protected Health Information) in the text.",
    }
    instruction = categories.get(category, categories["pii"])
    prompt_text = f"{instruction}\n\nText to analyze:\n{text}\n\nRespond with yes/no + explanation."
    return GetPromptResult(
        description="A prompt for detecting sensitive data (PII/PCI/PHI).",
        messages=[{"role": "user", "content": {"type": "text", "text": prompt_text}}],
        metadata={"category": category},
    )


# =============================================================================
# ELICIT TOOLS
# =============================================================================

@mcp.tool()
def elicit_feedback(question: str) -> ElicitResult:
    return ElicitResult(
        action="accept",
        content={"type": "text", "text": f"Can you share your thoughts on: {question}?"},
    )


@mcp.tool()
async def collect_user_info(ctx: Context = None) -> str:
    result = await ctx.elicit(
        message="Please provide your name and preferred language.",
        schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Your name"},
                "language": {"type": "string", "description": "Preferred language"},
            },
            "required": ["name", "language"],
        },
    )
    if result.action == "accept":
        data = result.data
        return f"Hello {data['name']}! I'll respond in {data['language']}."
    return "No info provided."


@mcp.tool()
async def list_templates(ctx: Context = None) -> str:
    templates = await ctx.session.list_resource_templates()
    names = [t.uriTemplate for t in templates.resourceTemplates]
    return f"Available templates: {', '.join(names)}"


@mcp.tool()
async def list_roots(ctx: Context = None) -> str:
    """List root directories from the client (calls roots/list)."""
    result = await ctx.session.list_roots()
    if result.roots:
        roots = [f"{r.uri} ({r.name or 'unnamed'})" for r in result.roots]
        return f"Root directories: {', '.join(roots)}"
    return "No roots available from client."


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print(f"""
{'='*65}
  MCP Notification Server — Postman Edition
{'='*65}

  Plain JSON REST API (no SSE needed):
    GET  http://localhost:{port}/api/summary
    GET  http://localhost:{port}/api/test/burst
    GET  http://localhost:{port}/api/test/progress
    GET  http://localhost:{port}/api/test/logging
    ... see /api/summary for all endpoints

  MCP protocol (for Claude Desktop):
    POST http://localhost:{port}/mcp
{'='*65}
""")
    uvicorn.run(mcp.streamable_http_app, host="0.0.0.0", port=port)
