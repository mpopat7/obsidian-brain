#!/usr/bin/env python3
"""Analyze notes in 00-inbox/: summarize, tag, then file into 01-conversations/<source>/."""

import json
import os
import re
import shutil
import sys
import urllib.request
from pathlib import Path

VAULT = Path(os.environ.get("VAULT", Path.home() / "obsidian-brain"))
INBOX = VAULT / "00-inbox"
CONVERSATIONS = VAULT / "01-conversations"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
MAX_CHARS = 6000

SOURCE_DEST = {
    "claude-ai": "claude",
    "claude-api": "claude",
    "ollama": "local",
    "chatgpt": "chatgpt",
}

PROMPT = """You are organizing an AI conversation note. Read the conversation and respond with ONLY a JSON object, no other text:
{{"title": "<short descriptive title, max 8 words>", "summary": "<2-3 sentence summary of what was discussed>", "tags": ["tag1", "tag2"]}}
Tags: 3 to 6 lowercase topic tags, hyphens instead of spaces.

Conversation:
{body}"""


def parse_note(path):
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            fm[key.strip()] = val.strip()
    return fm, m.group(2)


def ask_ollama(prompt):
    body = json.dumps({"model": MODEL, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(f"{OLLAMA_HOST}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())["response"]


def analyze(body):
    raw = ask_ollama(PROMPT.format(body=body[:MAX_CHARS]))
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    data = json.loads(match.group(0))
    return {
        "title": str(data.get("title", "")).strip(),
        "summary": str(data.get("summary", "")).strip(),
        "tags": [t for t in (re.sub(r"[^a-z0-9-]", "", str(x).lower()).strip("-")
                              for x in data.get("tags", [])) if t],
    }


def rebuild(fm, result, body):
    fm["title"] = result["title"]
    fm["summary"] = result["summary"]
    order = ["date", "source", "model", "title", "summary", "tags", "project"]
    lines = ["---"]
    for key in order:
        if key == "tags":
            lines.append("tags: [" + ", ".join(result["tags"]) + "]")
        elif key in fm:
            lines.append(f"{key}: {fm[key]}")
    lines.append("---")
    return "\n".join(lines) + "\n" + body


def analyze_inbox():
    results = {}
    for path in sorted(INBOX.glob("*.md")):
        if path.name.startswith("_"):
            continue
        fm, body = parse_note(path)
        if not body.strip():
            results[path.name] = "EMPTY"
            continue
        dest_sub = SOURCE_DEST.get(fm.get("source", ""))
        if not dest_sub:
            results[path.name] = "SKIPPED (unknown source)"
            continue
        try:
            result = analyze(body)
        except Exception as e:
            results[path.name] = f"FAILED ({e})"
            continue
        if not result:
            results[path.name] = "FAILED (no JSON)"
            continue
        path.write_text(rebuild(fm, result, body))
        dest = CONVERSATIONS / dest_sub / path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))
        results[path.name] = f"ANALYZED -> {dest_sub}"
    return results


if __name__ == "__main__":
    results = analyze_inbox()
    if not results:
        print("Inbox empty — nothing to analyze.")
        sys.exit(0)
    for name, outcome in results.items():
        print(f"{outcome:28} {name}")
    print(f"\n{sum(1 for o in results.values() if o.startswith('ANALYZED'))}/{len(results)} filed.")
