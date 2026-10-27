#!/usr/bin/env python3
"""Publish the prompts to the brand site (brand.unocha.org, Frontify).

Builds the prompts (scripts/build.py), then writes into the blocks listed in frontify.json:
the section heading, the introduction, and for each job one custom "AI prompt" block: its
Humanitarian Icon, title, summary, example requests and copy button. Only blocks whose
content changed are written, and each write is read back to confirm it landed.

    python3 scripts/publish_frontify.py --target test            # the hidden test page
    python3 scripts/publish_frontify.py --target live --dry-run  # show what would change
    python3 scripts/publish_frontify.py --target test --create-missing

--create-missing builds any part of the layout that frontify.json has no block for yet
(a new job, or a new target) and saves the new block ids into frontify.json. Run it on a
Mac and commit frontify.json; GitHub Actions only updates existing blocks.

Needs FRONTIFY_TOKEN: a Frontify personal access token (GitHub secret in Actions).
Standard library only.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402

ROOT = build.ROOT
CONFIG = ROOT / "frontify.json"
PAGE = ROOT / "prompts" / "page.toml"
BASE = "https://brand.unocha.org"

# Block type ids (public API) — the REST marketplace app ids are 2044620 and 3307325.
TEXT_TYPE = "cl5wda7mi00010tw8zxxf6g0c"
DIVIDER_TYPE = "cl5w9yz1l00010lw8dvragbie"
ICONS = "https://raw.githubusercontent.com/UN-OCHA/humanitarian-icons-2026-BDU/main/svg"
TEXT_LAYOUT = {"columnNumber": "1", "isColumnGutterCustom": False, "columnGutterSimple": "Auto"}
# House convention: dashed dividers between subsections inside a section.
DIVIDER = {"isLine": "Solid", "isWidthCustom": False, "widthSimple": "100%", "alignment": "Left",
           "isHeightCustom": False, "heightSimple": "Small", "style": "Dashed", "thickness": "1px"}


# ---------- Frontify API ----------

def _token() -> str:
    tok = os.environ.get("FRONTIFY_TOKEN", "").strip()
    if not tok:
        raise SystemExit("FRONTIFY_TOKEN is not set (a Frontify personal access token).")
    return tok


def _call(method: str, path: str, body: dict | None = None, beta: bool = False) -> dict:
    headers = {"Authorization": f"Bearer {_token()}", "Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if beta:
        headers["X-Frontify-Beta"] = "enabled"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        # 401/403 means the token is wrong or expired: stop, never work around it.
        raise SystemExit(f"Frontify {method} {path} failed: HTTP {e.code} {e.read()[:300]!r}")


def gql(query: str, variables: dict) -> dict:
    r = _call("POST", "/graphql", {"query": query, "variables": variables}, beta=True)
    if r.get("errors"):
        raise SystemExit(f"Frontify GraphQL error: {r['errors']}")
    return r["data"]


def opaque(identifier: int, type_: str) -> str:
    return base64.b64encode(json.dumps({"identifier": identifier, "type": type_},
                                       separators=(",", ":")).encode()).decode()


def unopaque(value: str) -> int:
    return int(json.loads(base64.b64decode(value))["identifier"])


def block_settings(block_id: int) -> dict:
    return (_call("GET", f"/api/document-block/{block_id}").get("data") or {}).get("settings") or {}


def write_block(block_id: int, settings: dict) -> None:
    _call("POST", f"/api/document-block/{block_id}", {"settings": settings})


def create_block(section_id: int, type_id: str, settings: dict, after: str) -> int:
    d = gql("mutation M($i: CreateGuidelinePageBlockInput!) { createGuidelinePageBlock(input: $i) { block { id } } }",
            {"i": {"blockTypeId": type_id, "settings": settings, "sectionId": str(section_id),
                   "afterElementId": after}})
    return unopaque(d["createGuidelinePageBlock"]["block"]["id"])


def copy_block(source_id: int, section_id: int, after_block_id: int) -> int:
    """The custom AI prompt block can't be created through the public API ("This block type
    cannot be created via the API"), but an existing one can be copied over REST."""
    after_el = (_call("GET", f"/api/document-block/{after_block_id}").get("data") or {})["section_element_id"]
    d = _call("POST", f"/api/document-block/{source_id}/copy",
              {"target_section_id": section_id, "after_section_element_id": after_el})
    return int(d["data"]["id"])


def set_heading(heading_id: int, title: str) -> None:
    gql("mutation M($i: UpdateGuidelinePageHeadingInput!) { updateGuidelinePageHeading(input: $i) { heading { id } } }",
        {"i": {"id": opaque(heading_id, "guideline-page-heading"), "data": {"title": title}}})


# ---------- What the page should say ----------

def rich(text: str) -> list[dict]:
    """Plain text with **bold** spans -> Slate text leaves."""
    leaves = []
    for i, part in enumerate(re.split(r"\*\*", text)):
        if part:
            leaves.append({"text": part, "bold": True} if i % 2 else {"text": part})
    return leaves or [{"text": ""}]


def slate(nodes: list[dict]) -> str:
    return json.dumps(nodes, ensure_ascii=False, separators=(",", ":"))


def intro_settings(page: dict) -> dict:
    return {**TEXT_LAYOUT, "content": slate([{"type": "p", "children": rich(p)} for p in page["intro"]])}


_icons: dict[str, str] = {}


def icon_svg(name: str) -> str:
    """The Humanitarian Icon's SVG, from its public repo. It is stored in the block, so the brand
    site never loads it from GitHub; a wrong name stops the publish rather than showing no icon."""
    if name not in _icons:
        url = f"{ICONS}/{name}.svg"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                svg = resp.read().decode("utf-8").strip()
        except urllib.error.HTTPError as e:
            raise SystemExit(f"Humanitarian Icon '{name}' not found ({url}: HTTP {e.code}). "
                             f"Names are Hyphen-Case, e.g. Water-source.")
        if "<svg" not in svg[:300]:
            raise SystemExit(f"{url} is not an SVG")
        _icons[name] = svg
    return _icons[name]


def prompt_settings(job: build.Job, prompt: str, page: dict) -> dict:
    """One block per job: icon, title, summary, two example requests, and the copy button."""
    return {"title": job.title,
            "summary": job.summary,
            "examplesLabel": page["examples_label"],
            "examples": "\n".join(job.examples[:2]),
            "iconName": job.icon or "",
            "iconSvg": icon_svg(job.icon) if job.icon else "",
            "buttonLabel": page["button_label"].format(title=job.title.lower()),
            "confirmationText": page["confirmation"],
            "promptText": prompt,
            "helperText": ""}


def same(current: dict, wanted: dict) -> bool:
    for key, value in wanted.items():
        have = current.get(key)
        if key == "content":  # compare the Slate tree, not its spelling
            try:
                have = json.loads(have or "null")
                value = json.loads(value)
            except ValueError:
                pass
        if have != value:
            return False
    return True


def sync(block_id: int, wanted: dict, label: str, dry: bool) -> bool:
    current = block_settings(block_id)
    if same(current, wanted):
        print(f"  same     {label}")
        return False
    print(f"  {'would update' if dry else 'update  '} {label}")
    if not dry:
        write_block(block_id, {**current, **wanted})
        if not same(block_settings(block_id), wanted):
            raise SystemExit(f"{label}: block {block_id} did not take the new content")
    return True


# ---------- Main ----------

def prompt_source(config: dict) -> int:
    """An existing AI prompt block to copy: any button already listed, else the fallback."""
    for t in config["targets"].values():
        for ids in t["jobs"].values():
            if ids.get("prompt_block"):
                return ids["prompt_block"]
    return config["prompt_block_source"]


def create_missing(config: dict, target: dict, jobs: list[build.Job], prompts: dict, page: dict, save) -> None:
    if not target.get("section_id"):
        d = gql("mutation M($i: CreateGuidelinePageSectionInput!) { createGuidelinePageSection(input: $i) { section { id } } }",
                {"i": {"pageId": str(target["page_id"])}})
        target["section_id"] = unopaque(d["createGuidelinePageSection"]["section"]["id"])
        print(f"  created  section {target['section_id']}")
        save()
    if not target.get("heading_id"):
        d = gql("mutation M($i: CreateGuidelinePageHeadingInput!) { createGuidelinePageHeading(input: $i) { heading { id } } }",
                {"i": {"sectionId": str(target["section_id"]), "title": page["heading"]}})
        target["heading_id"] = unopaque(d["createGuidelinePageHeading"]["heading"]["id"])
        print(f"  created  heading {target['heading_id']}")
        save()
    if not target.get("intro_block"):
        target["intro_block"] = create_block(target["section_id"], TEXT_TYPE, intro_settings(page),
                                             opaque(target["heading_id"], "guideline-page-heading"))
        print(f"  created  introduction {target['intro_block']}")
        save()
    after = target["intro_block"]
    for i, job in enumerate(jobs):
        ids = target["jobs"].setdefault(job.slug, {})
        if not ids.get("prompt_block"):
            if i > 0 and not ids.get("divider_block"):
                ids["divider_block"] = create_block(target["section_id"], DIVIDER_TYPE, DIVIDER,
                                                    opaque(after, "guideline-page-block"))
                save()
            if ids.get("divider_block"):
                after = ids["divider_block"]
            ids["prompt_block"] = copy_block(prompt_source(config), target["section_id"], after)
            save()
            write_block(ids["prompt_block"], {**block_settings(ids["prompt_block"]),
                                              **prompt_settings(job, prompts[job.slug], page)})
            print(f"  created  {job.slug}: block {ids['prompt_block']}")
        after = ids["prompt_block"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target", required=True, help="a target in frontify.json: test or live")
    ap.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    ap.add_argument("--create-missing", action="store_true", help="create blocks frontify.json has no id for")
    args = ap.parse_args()

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if args.target not in config["targets"]:
        raise SystemExit(f"no target '{args.target}' in frontify.json")
    target = config["targets"][args.target]
    page = tomllib.loads(PAGE.read_text(encoding="utf-8"))
    prompts = build.build(write=False)
    jobs = build.load_jobs()
    print(f"\nTarget: {args.target} (page {target['page_id']})")

    def save() -> None:  # after every creation, so a failure never leaves blocks nobody knows about
        CONFIG.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.create_missing and not args.dry_run:
        create_missing(config, target, jobs, prompts, page, save)
        print("  saved block ids to frontify.json — commit it")

    missing = [j.slug for j in jobs if not target["jobs"].get(j.slug, {}).get("prompt_block")]
    if missing or not target.get("intro_block"):
        raise SystemExit(f"frontify.json has no blocks on '{args.target}' for: {', '.join(missing) or 'the introduction'}. "
                         f"Run on a Mac: python3 scripts/publish_frontify.py --target {args.target} --create-missing")
    gone = set(target["jobs"]) - {j.slug for j in jobs}
    for slug in sorted(gone):
        print(f"  warning: '{slug}' is in frontify.json but has no job file. Delete its blocks on the page, "
              f"then remove it from frontify.json.")

    if not args.dry_run:
        set_heading(target["heading_id"], page["heading"])
    sync(target["intro_block"], intro_settings(page), "introduction", args.dry_run)
    for job in jobs:
        ids = target["jobs"][job.slug]
        sync(ids["prompt_block"], prompt_settings(job, prompts[job.slug], page), job.slug, args.dry_run)
    print("Done.")


if __name__ == "__main__":
    main()
