#!/usr/bin/env python3
"""
ENG-1226340 — QA driver for event-field sanitization.

Sends MCP traffic whose string fields contain hostile values, so the proxy's
event writer can be checked for proper sanitization of:
  - clientInfo.name / clientCapabilities   (request params._meta)
  - protocolVersion                        (request params._meta)
  - serverInfo.name                        (result _meta; start server with EVIL_SERVERINFO=1)
  - tool / prompt / resource names         (evil fixtures in mcp_server_2026.py)

Usage:
    python mcp_sanitize_tests.py                                  # local server on :10001
    python mcp_sanitize_tests.py --url https://test-mcp-1-n7g2.onrender.com/mcp
    python mcp_sanitize_tests.py --proxy http://10.156.22.20:8081 # through Netskope

Verify afterwards in the emitted events (SkopeIT / debug log event JSON):
  * event JSON is still well-formed (no broken quoting)
  * newlines/control chars are escaped or stripped
  * no injected keys appear (e.g. no "injected" field)
  * oversized names are truncated to a sane length
"""

import argparse
import json

import requests

requests.packages.urllib3.disable_warnings()

EVIL_CLIENT_NAME = 'evil-client","injected":"yes\n<script>alert(1)</script>'
EVIL_VERSION = '2026-07-28","injected":"yes\n\x00\x01'


def meta(client_name="sanitize-qa", version="2026-07-28"):
    return {
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": version,
            "io.modelcontextprotocol/clientInfo": {"name": client_name, "version": "1.0"},
            "io.modelcontextprotocol/clientCapabilities": {"elicitation": {"form": {}}, "sampling": {}},
        }
    }


def call(url, proxies, method, params, rid):
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
    r = requests.post(url, json=body, timeout=(5, 20), verify=False, proxies=proxies,
                      headers={"Content-Type": "application/json",
                               "Accept": "application/json, text/event-stream",
                               "mcp-protocol-version": "2026-07-28"})
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"_raw": r.text[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:10001/mcp")
    ap.add_argument("--proxy", help="explicit proxy, e.g. http://10.156.22.20:8081")
    args = ap.parse_args()
    proxies = {"http": args.proxy, "https": args.proxy} if args.proxy else None
    url = args.url

    print(f"target: {url}  proxy: {args.proxy or 'none'}\n")

    rid = 0
    def nxt():
        nonlocal rid; rid += 1; return rid

    # 1) Normal discovery — find the evil fixture names
    sc, disc = call(url, proxies, "server/discover", meta(), nxt())
    print(f"[1] server/discover -> {sc}")

    # 2) tools/list — evil tool names ride in the result
    sc, tl = call(url, proxies, "tools/list", meta(), nxt())
    tools = [t["name"] for t in tl.get("result", {}).get("tools", [])]
    evil_tools = [t for t in tools if t.startswith("evil_")]
    print(f"[2] tools/list -> {sc}; {len(tools)} tools, evil fixtures: {len(evil_tools)}")

    # 3) tools/call each evil tool (tool NAME is written to events)
    for name in evil_tools:
        sc, _ = call(url, proxies, "tools/call", {**meta(), "name": name, "arguments": {}}, nxt())
        print(f"[3] tools/call {name[:40]!r}{'...' if len(name) > 40 else ''} -> {sc}")

    # 4) prompts/list + prompts/get on the evil prompt
    sc, pl = call(url, proxies, "prompts/list", meta(), nxt())
    evil_prompts = [p["name"] for p in pl.get("result", {}).get("prompts", []) if p["name"].startswith("evil_")]
    print(f"[4] prompts/list -> {sc}; evil prompts: {len(evil_prompts)}")
    for name in evil_prompts:
        sc, _ = call(url, proxies, "prompts/get", {**meta(), "name": name, "arguments": {"name": "x"}}, nxt())
        print(f"[4] prompts/get {name[:40]!r} -> {sc}")

    # 5) resources/list + resources/read on evil resources
    sc, rl = call(url, proxies, "resources/list", meta(), nxt())
    evil_res = [r["uri"] for r in rl.get("result", {}).get("resources", []) if r["uri"].startswith("evilres://")]
    print(f"[5] resources/list -> {sc}; evil resources: {len(evil_res)}")
    for uri in evil_res:
        sc, _ = call(url, proxies, "resources/read", {**meta(), "uri": uri}, nxt())
        print(f"[5] resources/read {uri[:40]!r} -> {sc}")

    # 6) Hostile CLIENT-side identity fields (clientInfo.name + protocolVersion)
    sc, _ = call(url, proxies, "tools/list", meta(client_name=EVIL_CLIENT_NAME), nxt())
    print(f"[6] tools/list with evil clientInfo.name -> {sc}")
    sc, _ = call(url, proxies, "tools/list", meta(version=EVIL_VERSION), nxt())
    print(f"[6] tools/list with evil protocolVersion -> {sc}")

    print("""
Done. Now check the proxy events for these transactions:
  - event JSON parses cleanly (no broken quotes)
  - no 'injected' key anywhere
  - newlines/control chars escaped or stripped
  - names like 'evil_long_AAAA...' truncated
  - serverInfo.name sanitized too (if server started with EVIL_SERVERINFO=1)
""")


if __name__ == "__main__":
    main()
