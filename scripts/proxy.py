#!/usr/bin/env python3
"""
Ollama logging proxy.
Intercepts all Ollama API traffic and saves conversations to ~/obsidian-brain/00-inbox/.

Usage:
  python scripts/proxy.py

Then point your Ollama clients to http://localhost:11435 instead of 11434.

Environment variables:
  OLLAMA_PROXY_PORT  Port to listen on (default: 11435)
  OLLAMA_BACKEND     Ollama server to forward to (default: http://localhost:11434)
"""

import http.server
import json
import os
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path

PROXY_PORT = int(os.environ.get("OLLAMA_PROXY_PORT", "11435"))
OLLAMA_BACKEND = os.environ.get("OLLAMA_BACKEND", "http://localhost:11434")
VAULT_INBOX = Path.home() / "obsidian-brain" / "00-inbox"
MAC_SYNC = os.environ.get("MAC_SYNC", "milen@100.113.183.4:/Users/milen/obsidian-brain/00-inbox/")

LOGGED_PATHS = {"/api/chat", "/api/generate"}


class OllamaProxy(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self._forward(body=None)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        self._forward(body=body)

    def _forward(self, body):
        url = f"{OLLAMA_BACKEND}{self.path}"
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("host", "content-length")}

        should_log = self.command == "POST" and self.path in LOGGED_PATHS

        # Force non-streaming so we can capture the full response before logging
        if should_log and body:
            try:
                data = json.loads(body)
                data["stream"] = False
                body = json.dumps(data).encode()
                headers["content-length"] = str(len(body))
            except json.JSONDecodeError:
                pass

        req = urllib.request.Request(url, data=body, headers=headers, method=self.command)

        try:
            with urllib.request.urlopen(req) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                skip = {"transfer-encoding", "content-encoding", "content-length"}
                for key, val in resp.getheaders():
                    if key.lower() not in skip:
                        self.send_header(key, val)
                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)

            if should_log and body:
                try:
                    _save(self.path, json.loads(body), json.loads(resp_body))
                except Exception as e:
                    with open("/tmp/ollama-proxy.log", "a") as f:
                        f.write(f"SAVE ERROR: {e}\n")

        except Exception as e:
            self.send_error(502, str(e))

    def log_message(self, format, *args):
        with open("/tmp/ollama-proxy.log", "a") as f:
            f.write(f"{self.command} {self.path}\n")


def _save(path, req, resp):
    VAULT_INBOX.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    model = req.get("model", "unknown")
    fname = VAULT_INBOX / f"{now.strftime('%Y%m%d-%H%M%S')}-ollama.md"

    lines = []
    if path == "/api/chat":
        for m in req.get("messages", []):
            label = "**You:**" if m.get("role") == "user" else f"**{model}:**"
            lines.append(f"{label} {m.get('content', '')}\n\n")
        reply = resp.get("message", {}).get("content", "")
        lines.append(f"**{model}:** {reply}")
    elif path == "/api/generate":
        lines.append(f"**You:** {req.get('prompt', '')}\n\n")
        lines.append(f"**{model}:** {resp.get('response', '')}")

    if not lines:
        return

    fname.write_text(f"""---
date: {now.strftime('%Y-%m-%d')}
source: ollama
model: {model}
tags: []
summary: ""
project: ""
---

{"".join(lines)}
""")
    with open("/tmp/ollama-proxy.log", "a") as f:
        f.write(f"Saved: {fname.name}\n")
    subprocess.Popen(
        ["rsync", "-az", str(VAULT_INBOX) + "/", MAC_SYNC],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


if __name__ == "__main__":
    server = http.server.HTTPServer(("0.0.0.0", PROXY_PORT), OllamaProxy)
    print(f"Proxy listening on :{PROXY_PORT} → {OLLAMA_BACKEND}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nProxy stopped.")
