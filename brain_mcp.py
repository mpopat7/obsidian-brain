#!/usr/bin/env python3
"""Read-only MCP server exposing the Obsidian brain vault to Claude Code.

Stdlib-only. Speaks newline-delimited JSON-RPC 2.0 over stdio (MCP stdio
transport). Exposes three read tools — search_notes, read_note, list_notes —
all confined under the vault root. No write capability by design.

Run: python3 brain_mcp.py [vault_path]   (default: ~/obsidian-brain)
"""
import json
import os
import sys

VAULT = os.path.realpath(
    sys.argv[1] if len(sys.argv) > 1
    else os.environ.get("BRAIN_VAULT", os.path.expanduser("~/obsidian-brain"))
)
SKIP_DIRS = {".obsidian", ".git", ".trash", "node_modules"}
PROTOCOL = "2024-11-05"

TOOLS = [
    {
        "name": "search_notes",
        "description": "Full-text search the Obsidian brain vault. Returns matching "
                       "notes with line snippets. Use for finding context on a topic, "
                       "person, project, or [[link]] target.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Case-insensitive substring to find."},
                "max_results": {"type": "integer", "description": "Max matching notes (default 20)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_note",
        "description": "Read one note's full contents. Path is relative to the vault root "
                       "(e.g. '05-context/about-me.md').",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Vault-relative path to a .md note."}},
            "required": ["path"],
        },
    },
    {
        "name": "list_notes",
        "description": "List markdown notes in the vault, optionally under a subfolder "
                       "(e.g. '03-projects').",
        "inputSchema": {
            "type": "object",
            "properties": {"subdir": {"type": "string", "description": "Optional vault-relative subfolder."}},
        },
    },
]


def _safe(rel):
    p = os.path.realpath(os.path.join(VAULT, rel))
    if p != VAULT and not p.startswith(VAULT + os.sep):
        raise ValueError("path escapes vault")
    return p


def _walk():
    for root, dirs, files in os.walk(VAULT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(".md"):
                yield os.path.join(root, f)


def tool_search_notes(query, max_results=20):
    q = query.lower()
    hits = []
    for path in _walk():
        try:
            with open(path, encoding="utf-8") as fh:
                lines = fh.readlines()
        except (OSError, UnicodeDecodeError):
            continue
        matched = [(i + 1, ln.rstrip()) for i, ln in enumerate(lines) if q in ln.lower()]
        if matched:
            rel = os.path.relpath(path, VAULT)
            snippet = "\n".join("  L{}: {}".format(n, t[:200]) for n, t in matched[:5])
            hits.append("### {}\n{}".format(rel, snippet))
            if len(hits) >= max_results:
                break
    return "\n\n".join(hits) if hits else "No notes match {!r}.".format(query)


def tool_read_note(path):
    p = _safe(path)
    if not os.path.isfile(p):
        return "Not found: {}".format(path)
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def tool_list_notes(subdir=""):
    base = _safe(subdir) if subdir else VAULT
    out = sorted(os.path.relpath(p, VAULT) for p in _walk() if p.startswith(base))
    return "\n".join(out) if out else "(no notes)"


DISPATCH = {
    "search_notes": tool_search_notes,
    "read_note": tool_read_note,
    "list_notes": tool_list_notes,
}


def handle(req):
    method, mid = req.get("method"), req.get("id")
    if method == "initialize":
        ver = (req.get("params") or {}).get("protocolVersion", PROTOCOL)
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": ver,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "brain", "version": "1.0.0"},
        }}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = req.get("params") or {}
        fn = DISPATCH.get(params.get("name"))
        if not fn:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
        try:
            text = fn(**(params.get("arguments") or {}))
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
        except Exception as e:  # surface tool errors to the model, don't crash the server
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": "error: {}".format(e)}], "isError": True}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if mid is None:
        return None  # notification (e.g. notifications/initialized) — no reply
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
