import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT_CHATGPT = Path.home() / "obsidian-brain" / "01-conversations" / "chatgpt"


def _slug(text, max_len=50):
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:max_len].strip("-")


def _unique_path(folder, stem):
    path = folder / f"{stem}.md"
    n = 2
    while path.exists():
        path = folder / f"{stem}-{n}.md"
        n += 1
    return path


def _ordered_messages(mapping, current_node=None):
    # Walk up the parent chain from the active leaf to the root.
    if current_node not in mapping:
        current_node = next(
            (nid for nid, node in mapping.items() if not node.get("children")),
            None,
        )
    chain = []
    node_id = current_node
    while node_id in mapping:
        chain.append(node_id)
        node_id = mapping[node_id].get("parent")
    chain.reverse()

    messages = []
    for node_id in chain:
        msg = mapping[node_id].get("message")
        if not msg:
            continue
        role = msg.get("author", {}).get("role", "")
        parts = msg.get("content", {}).get("parts", [])
        text = " ".join(p for p in parts if isinstance(p, str)).strip()
        if role in ("user", "assistant") and text:
            messages.append((role, text))

    return messages


def convert(export_path):
    VAULT_CHATGPT.mkdir(parents=True, exist_ok=True)
    convos = json.loads(Path(export_path).read_text())
    saved, skipped = 0, 0

    for convo in convos:
        messages = _ordered_messages(convo.get("mapping", {}), convo.get("current_node"))
        if not messages:
            skipped += 1
            continue

        ts = convo.get("create_time") or 0
        date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        title = convo.get("title", "untitled")
        fname = _unique_path(VAULT_CHATGPT, f"{date}-{_slug(title)}")

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
