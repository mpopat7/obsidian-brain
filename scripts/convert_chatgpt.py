import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT_CHATGPT = Path.home() / "obsidian-brain" / "01-conversations" / "chatgpt"


def _slug(text, max_len=50):
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return text[:max_len]


def _ordered_messages(mapping):
    # Find root node (no parent or parent not in mapping)
    root = next(
        nid for nid, node in mapping.items()
        if not node.get("parent") or node["parent"] not in mapping
    )

    messages = []
    node_id = root
    while node_id:
        node = mapping[node_id]
        msg = node.get("message")
        if msg:
            role = msg.get("author", {}).get("role", "")
            parts = msg.get("content", {}).get("parts", [])
            text = " ".join(p for p in parts if isinstance(p, str)).strip()
            if role in ("user", "assistant") and text:
                messages.append((role, text))
        children = node.get("children", [])
        node_id = children[-1] if children else None

    return messages


def convert(export_path):
    VAULT_CHATGPT.mkdir(parents=True, exist_ok=True)
    convos = json.loads(Path(export_path).read_text())
    saved, skipped = 0, 0

    for convo in convos:
        messages = _ordered_messages(convo.get("mapping", {}))
        if not messages:
            skipped += 1
            continue

        ts = convo.get("create_time") or 0
        date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        dt_prefix = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
        title = convo.get("title", "untitled")
        fname = VAULT_CHATGPT / f"{dt_prefix}-{_slug(title)}.md"

        lines = []
        for role, text in messages:
            label = "**You:**" if role == "user" else "**ChatGPT:**"
            lines.append(f"{label} {text}\n")

        content = f"""---
date: {date}
source: chatgpt
model: gpt
tags: []
summary: ""
project: ""
title: "{title}"
---

{"".join(lines)}
"""
        fname.write_text(content)
        saved += 1

    print(f"Done — {saved} conversations saved to {VAULT_CHATGPT}, {skipped} skipped (empty).")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python convert_chatgpt.py conversations.json")
        sys.exit(1)
    convert(sys.argv[1])
