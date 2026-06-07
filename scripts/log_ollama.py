import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path

VAULT_INBOX = Path.home() / "obsidian-brain" / "00-inbox"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = "qwen3-coder-next"


def ask(prompt, model=DEFAULT_MODEL):
    messages = [{"role": "user", "content": prompt}]
    return chat(messages, model)


def chat(messages, model=DEFAULT_MODEL):
    body = json.dumps({"model": model, "messages": messages, "stream": False}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())

    reply = data["message"]["content"]
    _save(messages, reply, model)
    return reply


def _save(messages, reply, model):
    VAULT_INBOX.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    fname = VAULT_INBOX / f"{now.strftime('%Y%m%d-%H%M%S')}-ollama.md"

    lines = []
    for m in messages:
        role = "**You:**" if m["role"] == "user" else f"**{model}:**"
        lines.append(f"{role} {m['content']}\n")
    lines.append(f"**{model}:** {reply}")

    content = f"""---
date: {now.strftime('%Y-%m-%d')}
source: ollama
model: {model}
tags: []
summary: ""
project: ""
---

{"".join(lines)}
"""
    fname.write_text(content)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python log_ollama.py 'your prompt here'")
        sys.exit(1)
    print(ask(" ".join(sys.argv[1:])))
