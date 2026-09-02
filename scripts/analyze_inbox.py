#!/usr/bin/env python3
"""Analyze notes in 00-inbox/: summarize, tag, then file into 01-conversations/<source>/."""

import json
import os
import re
import shutil
import sys
import urllib.request
from pathlib import Path

try:
    from .repair_continuations import rewrite_continuation_text
    from .hub_router import Router
except ImportError:
    from repair_continuations import rewrite_continuation_text
    from hub_router import Router

VAULT = Path(os.environ.get("VAULT", Path.home() / "obsidian-brain"))
INBOX = VAULT / "00-inbox"
CONVERSATIONS = VAULT / "01-conversations"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
MAX_CHARS = 6000

SOURCE_DEST = {
    "claude-ai": "claude",
    "claude-api": "claude",
    "claude-code": "claude-code",
    "codex": "codex",
    "ollama": "local",
    "chatgpt": "chatgpt",
    "antigravity": "antigravity",
}

PROMPT = """You are organizing an AI conversation note. Read the conversation and respond with ONLY a JSON object, no other text:
{{"title": "<short descriptive title, max 8 words>", "summary": "<2-3 sentence summary of what was discussed>", "tags": ["tag1", "tag2"]}}
Tags: 3 to 6 lowercase topic tags, hyphens instead of spaces.

Conversation:
{body}"""


_STOP = {"a", "an", "the", "of", "on", "in", "to", "for", "and", "or", "with",
         "is", "are", "how", "what", "why", "my", "vs", "at", "by", "from"}


def _summary_slug(title, max_words=4):
    words = [w for w in re.findall(r"[a-z0-9]+", title.lower())]
    kept = [w for w in words if w not in _STOP] or words
    return "-".join(kept[:max_words])


# Longest first: "-claude-code" must win over "-claude-ai" on a claude-code stem.
_SOURCE_TOKENS = ("claude-code", "claude-api", "claude-ai", "antigravity", "perplexity",
                  "chatgpt", "codex", "ollama")
_CONTINUED_RE = re.compile(r"(-continued-\d+)$")


def _filed_name(stem, slug):
    """Build the filed name, replacing any topic the capture already put there.

    The transcript converters name a session "<date>-<source>-<topic>". Appending
    the analyzed topic to that stated it twice and produced 110-character
    filenames like "...-log-appcom-log-application-internship-tracker". QuickAdd
    writes a bare "<date>-claude-ai" with no topic, so there the slug is simply
    appended and nothing is lost.
    """
    if not slug:
        return None
    continued = ""
    match = _CONTINUED_RE.search(stem)
    if match:
        # The revision marker identifies a delta capture; it must survive.
        continued = match.group(1)
        stem = stem[: match.start()]
    for token in _SOURCE_TOKENS:
        marker = "-" + token
        index = stem.find(marker)
        if index != -1:
            stem = stem[: index + len(marker)]
            break
    return f"{stem}-{slug}{continued}.md"


def _unique(folder, name):
    dest = folder / name
    n = 2
    while dest.exists():
        dest = folder / f"{dest.stem}-{n}{dest.suffix}"
        n += 1
    return dest


def _rewrite_inbound_continuations(old_stem, new_stem):
    """Repoint child captures when triage renames their parent capture."""
    if old_stem == new_stem:
        return []
    changed = []
    paths = list(INBOX.glob("*.md")) + list(CONVERSATIONS.rglob("*.md"))
    for child in paths:
        text = child.read_text(encoding="utf-8", errors="replace")
        rewritten, pointer_count = rewrite_continuation_text(
            text, new_stem, old_target=old_stem)
        if not pointer_count:
            continue
        child.write_text(rewritten, encoding="utf-8")
        changed.append((child, pointer_count))
    return changed


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
    order = [
        "date", "source", "model", "title", "summary", "tags", "project",
        "session_id", "capture_revision", "capture_until", "continuation_of",
    ]
    lines = ["---"]
    for key in order:
        if key == "tags":
            lines.append("tags: [" + ", ".join(result["tags"]) + "]")
        elif key in fm:
            lines.append(f"{key}: {fm[key]}")
    lines.append("---")
    return "\n".join(lines) + "\n" + body


#: Marks a link this script wrote, so triage can tell an auto-route from a
#: curated link and replace it without guessing. Same idea as relate_notes'
#: score comments.
ROUTED_MARKER = "<!-- routed: {tier} {confidence:.2f} -->"


def hub_link_section(hub, tier, confidence):
    return "\n## Links\n- [[{}]]  {}\n".format(
        hub, ROUTED_MARKER.format(tier=tier, confidence=confidence))


def add_hub_link(text, router):
    """Append a `## Links` section routing this note to a hub.

    This is what stops a filed capture from being born a satellite: filing and
    linking become one step instead of two, only one of which was automatic.
    Returns (text, hub, tier) — or (text, None, None) if the note already has a
    real link, since a curated link always outranks a routed one.
    """
    body = re.sub(r"`[^`\n]*`", " ", re.sub(r"```.*?```", " ", text, flags=re.S))
    existing = {l.split("|")[0].split("#")[0].strip()
                for l in re.findall(r"\[\[([^\[\]\n]+)\]\]", body)}
    if existing & set(router.hubs):
        return text, None, None

    fm_match = re.match(r"^---\n(.*?)\n---", text, re.S)
    front = fm_match.group(1) if fm_match else ""
    tag_match = re.search(r"tags:\s*\[(.*?)\]", front, re.S)
    tags = [t.strip() for t in tag_match.group(1).split(",") if t.strip()] if tag_match else []

    def field(name):
        hit = re.search(r"^%s:\s*(.*)$" % name, front, re.M)
        return hit.group(1).strip().strip('"').strip() if hit else ""

    hub, confidence, tier = router.route(tags, field("title"), field("summary"),
                                         field("project"))
    return text.rstrip("\n") + "\n" + hub_link_section(hub, tier, confidence), hub, tier


def analyze_inbox():
    results = {}
    try:
        router = Router(VAULT)
    except Exception as e:
        print(f"hub router unavailable ({e}) — notes will be filed unlinked.",
              file=sys.stderr)
        router = None
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
        filed_text = rebuild(fm, result, body)
        routed_hub = routed_tier = None
        if router is not None:
            filed_text, routed_hub, routed_tier = add_hub_link(filed_text, router)
        path.write_text(filed_text)
        name = _filed_name(path.stem, _summary_slug(result["title"])) or path.name
        (CONVERSATIONS / dest_sub).mkdir(parents=True, exist_ok=True)
        dest = _unique(CONVERSATIONS / dest_sub, name)
        shutil.move(str(path), str(dest))
        _rewrite_inbound_continuations(path.stem, dest.stem)
        outcome = f"ANALYZED -> {dest_sub}/{dest.name}"
        if routed_hub:
            outcome += f"  [[{routed_hub}]] ({routed_tier})"
        results[path.name] = outcome
    return results


if __name__ == "__main__":
    results = analyze_inbox()
    if not results:
        print("Inbox empty — nothing to analyze.")
        sys.exit(0)
    for name, outcome in results.items():
        print(f"{outcome:28} {name}")
    print(f"\n{sum(1 for o in results.values() if o.startswith('ANALYZED'))}/{len(results)} filed.")
    if any(o.startswith("ANALYZED") for o in results.values()):
        print("\nLinking notes (relate_notes)...")
        try:
            from relate_notes import relate, CONVERSATIONS as CONV
            relate(CONV, k=5, floor=0.62, apply=True)
        except Exception as e:
            print(f"  relate_notes skipped ({e}) — run scripts/relate_notes.py "
                  "--apply manually when the embedding host is reachable.")
