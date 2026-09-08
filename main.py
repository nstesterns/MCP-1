"""
MCP server with ALL capabilities for Postman + Claude Desktop testing.

Two ways to interact:
  1. MCP protocol  → POST http://localhost:10000/mcp
  2. REST API      → GET http://localhost:10000/api/*        (plain JSON, for Postman)

Includes:
  - All 9 notification type test tools (test_1 through test_9)
  - REST API endpoints for Postman
  - Completion handler (autocomplete)
  - Resource subscribe/unsubscribe handlers
  - Roots list tool
  - Original tools (greet, add, elicitation, etc.)

Run:
    python mcp_server_postman.py
"""

import asyncio
import time
import json
from typing import Optional
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

mcp = FastMCP("Demo-All-Notifications")


# =============================================================================
# HELPER: NotificationCollector — captures notifications for inline response
# =============================================================================

class NotificationCollector:
    """Stores notifications so they appear inline in the tool response."""

    def __init__(self):
        self.notifications: list[dict] = []

    def add(self, notif_type: str, **kwargs):
        entry = {"type": notif_type, "timestamp": time.time(), **kwargs}
        self.notifications.append(entry)
        print(f"[NOTIF] {notif_type}: {json.dumps(kwargs, default=str)}")

    def snapshot(self) -> list[dict]:
        return list(self.notifications)


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
async def handle_completion(ref, argument, context) -> Optional[Completion]:
    """Provide autocomplete suggestions for prompts and resource templates."""

    if isinstance(ref, PromptReference) and ref.name == "greet_user":
        if argument.name == "style":
            styles = ["friendly", "formal", "casual"]
            matches = [s for s in styles if s.startswith(argument.value)]
            return Completion(values=matches, total=len(matches), hasMore=False)
        if argument.name == "name":
            names = ["Jaden", "Alice", "Bob", "Charlie"]
            matches = [n for n in names if n.lower().startswith(argument.value.lower())]
            return Completion(values=matches, total=len(matches), hasMore=False)

    if isinstance(ref, PromptReference) and ref.name == "pii_pci_analyzer":
        if argument.name == "category":
            categories = ["pii", "pci", "phi"]
            matches = [c for c in categories if c.startswith(argument.value.lower())]
            return Completion(values=matches, total=len(matches), hasMore=False)

    if isinstance(ref, ResourceTemplateReference):
        if argument.name == "name":
            suggestions = ["World", "test", "eicar", "Jaden", "Alice"]
            matches = [s for s in suggestions if s.lower().startswith(argument.value.lower())]
            return Completion(values=matches, total=len(matches), hasMore=False)

    return None


# =============================================================================
# NOTIFICATION TEST TOOLS (test_1 through test_9)
# =============================================================================


@mcp.tool()
async def test_1_progress(ctx: Context = None) -> dict:
    """
    Test: ProgressNotification during execution.
    Returns progress steps inline in the response.
    """
    nc = NotificationCollector()
    steps = 5
    for i in range(1, steps + 1):
        progress_pct = (i / steps) * 100
        msg = f"Step {i}/{steps} ({progress_pct:.0f}%)"
        nc.add("ProgressNotification", progress=progress_pct, total=100, message=msg)
        if ctx:
            await ctx.report_progress(progress=progress_pct, total=100, message=msg)
        await asyncio.sleep(0.3)
    return {
        "status": "ok",
        "description": "ProgressNotification test — 5 steps",
        "notifications_sent": nc.snapshot(),
    }


@mcp.tool()
async def test_2_logging(ctx: Context = None) -> dict:
    """
    Test: LoggingMessageNotification at all severity levels.
    """
    nc = NotificationCollector()
    for level in ["debug", "info", "notice", "warning", "error", "critical"]:
        data = f"Log message at {level.upper()} level"
        nc.add("LoggingMessageNotification", level=level, logger="demo-logger", data=data)
        if ctx:
            await ctx.session.send_log_message(level=level, data=data, logger="demo-logger")
    return {
        "status": "ok",
        "description": "LoggingMessageNotification — all 6 levels",
        "notifications_sent": nc.snapshot(),
    }


@mcp.tool()
async def test_3_tool_list_changed(ctx: Context = None) -> dict:
    """
    Test: ToolListChangedNotification.
    Client should re-fetch tools/list after this.
    """
    nc = NotificationCollector()
    nc.add("ToolListChangedNotification", info="Client should re-fetch tools/list")
    if ctx:
        await ctx.session.send_tool_list_changed()
    return {
        "status": "ok",
        "description": "ToolListChangedNotification sent",
        "notifications_sent": nc.snapshot(),
    }


@mcp.tool()
async def test_4_resource_list_changed(ctx: Context = None) -> dict:
    """
    Test: ResourceListChangedNotification.
    Client should re-fetch resources/list after this.
    """
    nc = NotificationCollector()
    nc.add("ResourceListChangedNotification", info="Client should re-fetch resources/list")
    if ctx:
        await ctx.session.send_resource_list_changed()
    return {
        "status": "ok",
        "description": "ResourceListChangedNotification sent",
        "notifications_sent": nc.snapshot(),
    }


@mcp.tool()
async def test_5_prompt_list_changed(ctx: Context = None) -> dict:
    """
    Test: PromptListChangedNotification.
    Client should re-fetch prompts/list after this.
    """
    nc = NotificationCollector()
    nc.add("PromptListChangedNotification", info="Client should re-fetch prompts/list")
    if ctx:
        await ctx.session.send_prompt_list_changed()
    return {
        "status": "ok",
        "description": "PromptListChangedNotification sent",
        "notifications_sent": nc.snapshot(),
    }


@mcp.tool()
async def test_6_resource_updated(
    resource_uri: str = "greeting://test",
    ctx: Context = None,
) -> dict:
    """
    Test: ResourceUpdatedNotification for a given URI.
    If the client subscribed to this resource, it will re-read it.
    """
    nc = NotificationCollector()
    nc.add("ResourceUpdatedNotification", uri=resource_uri)
    if ctx:
        await ctx.session.send_resource_updated(uri=resource_uri)
    return {
        "status": "ok",
        "description": f"ResourceUpdatedNotification sent for {resource_uri}",
        "notifications_sent": nc.snapshot(),
    }


@mcp.tool()
async def test_7_cancellable(ctx: Context = None) -> dict:
    """
    Test: Long-running operation that respects CancelledNotification.
    10 steps at 1 second each — cancel mid-way to test cancellation.
    """
    nc = NotificationCollector()
    try:
        for i in range(1, 11):
            nc.add("ProgressNotification", progress=i, total=10, message=f"Cancellable step {i}/10")
            if ctx:
                await ctx.report_progress(progress=i, total=10, message=f"Cancellable step {i}/10")
            await asyncio.sleep(1.0)
        return {
            "status": "ok",
            "description": "Completed all 10 steps (not cancelled)",
            "notifications_sent": nc.snapshot(),
        }
    except Exception as e:
        nc.add("CancelledNotification", reason=str(e))
        return {
            "status": "cancelled",
            "description": f"Request cancelled at step {i}",
            "notifications_sent": nc.snapshot(),
        }


@mcp.tool()
async def test_8_elicit_complete(
    outcome: str = "accept",
    ctx: Context = None,
) -> dict:
    """
    Test: ElicitCompleteNotification.
    outcome = 'accept' or 'decline'.
    """
    nc = NotificationCollector()
    nc.add("ElicitCompleteNotification", outcome=outcome)
    if ctx:
        try:
            if outcome == "accept":
                await ctx.session.send_elicit_complete(
                    outcome="accept",
                    result={"submitted_by": "test-user", "approved": True},
                )
            else:
                await ctx.session.send_elicit_complete(outcome="decline")
        except AttributeError:
            # Fallback for older MCP SDK
            from mcp.types import ElicitCompleteNotification, ElicitCompleteNotificationParams
            await ctx.session.send_notification(
                ElicitCompleteNotification(
                    method="notifications/elicitation/complete",
                    params=ElicitCompleteNotificationParams(
                        outcome="accept" if outcome == "accept" else "decline",
                        result={"submitted_by": "test-user", "approved": True} if outcome == "accept" else None,
                    ),
                )
            )
    return {
        "status": "ok",
        "description": f"ElicitCompleteNotification sent with outcome='{outcome}'",
        "notifications_sent": nc.snapshot(),
    }


@mcp.tool()
async def test_9_burst(ctx: Context = None) -> dict:
    """
    Test: ALL notification types in rapid succession (burst test).
    """
    nc = NotificationCollector()

    nc.add("ProgressNotification", progress=50, total=100, message="Burst at 50%")
    if ctx:
        await ctx.report_progress(progress=50, total=100)

    nc.add("LoggingMessageNotification", level="info", data="Burst log")
    if ctx:
        await ctx.session.send_log_message(level="info", data="Burst log")

    nc.add("ToolListChangedNotification")
    if ctx:
        await ctx.session.send_tool_list_changed()

    nc.add("ResourceListChangedNotification")
    if ctx:
        await ctx.session.send_resource_list_changed()

    nc.add("PromptListChangedNotification")
    if ctx:
        await ctx.session.send_prompt_list_changed()

    nc.add("ResourceUpdatedNotification", uri="greeting://test")
    if ctx:
        await ctx.session.send_resource_updated(uri="greeting://test")

    nc.add("ElicitCompleteNotification", outcome="accept")
    if ctx:
        try:
            await ctx.session.send_elicit_complete(outcome="accept", result={"burst": True})
        except AttributeError:
            from mcp.types import ElicitCompleteNotification, ElicitCompleteNotificationParams
            await ctx.session.send_notification(
                ElicitCompleteNotification(
                    method="notifications/elicitation/complete",
                    params=ElicitCompleteNotificationParams(outcome="accept", result={"burst": True}),
                )
            )

    nc.add("ProgressNotification", progress=100, total=100, message="Burst complete")
    if ctx:
        await ctx.report_progress(progress=100, total=100)

    return {
        "status": "ok",
        "description": "Burst: all 7 notification types in rapid succession",
        "notifications_sent": nc.snapshot(),
    }


# =============================================================================
# REST API ENDPOINTS — Plain JSON, no SSE, perfect for Postman
# =============================================================================

@mcp.custom_route("/api/ping", methods=["GET"])
async def api_ping(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "mcp-all-notifications"})


@mcp.custom_route("/api/summary", methods=["GET"])
async def api_summary(request: Request) -> JSONResponse:
    return JSONResponse({
        "server": "MCP Notification Test Server",
        "mcp_tools": [
            "test_1_progress           — ProgressNotification",
            "test_2_logging            — LoggingMessageNotification (6 levels)",
            "test_3_tool_list_changed   — ToolListChangedNotification",
            "test_4_resource_list_changed — ResourceListChangedNotification",
            "test_5_prompt_list_changed — PromptListChangedNotification",
            "test_6_resource_updated    — ResourceUpdatedNotification",
            "test_7_cancellable         — CancelledNotification (10s, cancellable)",
            "test_8_elicit_complete     — ElicitCompleteNotification",
            "test_9_burst               — ALL 7 notifications in one call",
        ],
        "rest_endpoints": [
            "GET /api/ping",
            "GET /api/summary",
            "GET /api/test/progress",
            "GET /api/test/logging",
            "GET /api/test/tool-list-changed",
            "GET /api/test/resource-list-changed",
            "GET /api/test/prompt-list-changed",
            "GET /api/test/resource-updated?uri=...",
            "GET /api/test/elicit-complete?outcome=...",
            "GET /api/test/burst",
        ],
    })


@mcp.custom_route("/api/test/progress", methods=["GET", "POST"])
async def api_test_progress(request: Request) -> JSONResponse:
    notifications = []
    steps = 5
    for i in range(1, steps + 1):
        progress_pct = round((i / steps) * 100, 1)
        notifications.append({
            "type": "ProgressNotification", "step": i,
            "progress": progress_pct, "total": 100,
            "message": f"Step {i}/{steps} ({progress_pct:.0f}%)",
        })
        await asyncio.sleep(0.3)
    return JSONResponse({"status": "ok", "notifications": notifications, "count": len(notifications)})


@mcp.custom_route("/api/test/logging", methods=["GET", "POST"])
async def api_test_logging(request: Request) -> JSONResponse:
    notifications = []
    for level in ["debug", "info", "notice", "warning", "error", "critical"]:
        notifications.append({
            "type": "LoggingMessageNotification", "level": level,
            "logger": "demo-logger", "data": f"Log at {level.upper()}",
        })
    return JSONResponse({"status": "ok", "notifications": notifications, "count": len(notifications)})


@mcp.custom_route("/api/test/tool-list-changed", methods=["GET", "POST"])
async def api_test_tool_list_changed(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "notifications": [{"type": "ToolListChangedNotification"}]})


@mcp.custom_route("/api/test/resource-list-changed", methods=["GET", "POST"])
async def api_test_resource_list_changed(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "notifications": [{"type": "ResourceListChangedNotification"}]})


@mcp.custom_route("/api/test/prompt-list-changed", methods=["GET", "POST"])
async def api_test_prompt_list_changed(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "notifications": [{"type": "PromptListChangedNotification"}]})


@mcp.custom_route("/api/test/resource-updated", methods=["GET", "POST"])
async def api_test_resource_updated(request: Request) -> JSONResponse:
    uri = request.query_params.get("uri", "greeting://test")
    return JSONResponse({"status": "ok", "notifications": [{"type": "ResourceUpdatedNotification", "uri": uri}]})


@mcp.custom_route("/api/test/elicit-complete", methods=["GET", "POST"])
async def api_test_elicit_complete(request: Request) -> JSONResponse:
    outcome = request.query_params.get("outcome", "accept")
    result = {"submitted_by": "test-user", "approved": True} if outcome == "accept" else None
    return JSONResponse({"status": "ok", "notifications": [{"type": "ElicitCompleteNotification", "outcome": outcome, "result": result}]})


@mcp.custom_route("/api/test/burst", methods=["GET", "POST"])
async def api_test_burst(request: Request) -> JSONResponse:
    notifications = [
        {"type": "ProgressNotification", "progress": 50, "total": 100},
        {"type": "LoggingMessageNotification", "level": "info", "data": "Burst"},
        {"type": "ToolListChangedNotification"},
        {"type": "ResourceListChangedNotification"},
        {"type": "PromptListChangedNotification"},
        {"type": "ResourceUpdatedNotification", "uri": "greeting://test"},
        {"type": "ElicitCompleteNotification", "outcome": "accept"},
    ]
    return JSONResponse({"status": "ok", "notifications": notifications, "count": len(notifications)})


# =============================================================================
# ORIGINAL TOOLS
# =============================================================================

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


@mcp.tool()
async def list_roots(ctx: Context = None) -> str:
    """List root directories from the client (calls roots/list)."""
    result = await ctx.session.list_roots()
    if result.roots:
        roots = [f"{r.uri} ({r.name or 'unnamed'})" for r in result.roots]
        return f"Root directories: {', '.join(roots)}"
    return "No roots available from client."


@mcp.tool()
async def list_templates(ctx: Context = None) -> str:
    """List all registered resource URI templates"""
    templates = await ctx.session.list_resource_templates()
    names = [t.uriTemplate for t in templates.resourceTemplates]
    return f"Available templates: {', '.join(names)}"


# =============================================================================
# RESOURCES
# =============================================================================

@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
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


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print(f"""
{'='*65}
  MCP Notification Server — Complete Edition
{'='*65}

  MCP Tools (POST /mcp):
    test_1_progress           test_2_logging
    test_3_tool_list_changed  test_4_resource_list_changed
    test_5_prompt_list_changed test_6_resource_updated
    test_7_cancellable        test_8_elicit_complete
    test_9_burst              greet / add / list_roots / list_templates

  REST API (GET /api/*):
    /api/summary              /api/test/burst
    /api/test/progress        /api/test/logging
    ... see /api/summary for all

  New capabilities:
    resources/subscribe       resources/unsubscribe
    completion/complete       roots/list
{'='*65}
""")
    uvicorn.run(mcp.streamable_http_app, host="0.0.0.0", port=port)
