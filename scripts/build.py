#!/usr/bin/env python3
"""Assemble the OCHA AI prompts from their parts and check them.

prompts/core.md       the common core, shared by every prompt. Slots: {{task}}, {{job}}, {{examples}}
prompts/jobs/*.md     one file per job: TOML front matter (between +++ lines), then the job rules
prompts/links.toml    every URL, by name; the parts write {{link:name}}

Writes dist/<slug>.txt, one finished prompt per job, and fails (exit 1) when a prompt breaks a check.
Standard library only (Python 3.11+), so it runs the same on a Mac and in GitHub Actions.
"""
from __future__ import annotations

import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "prompts" / "core.md"
JOBS = ROOT / "prompts" / "jobs"
LINKS = ROOT / "prompts" / "links.toml"
DIST = ROOT / "dist"

# Microsoft 365 Copilot has no published prompt limit; reports range from 8,000 to 16,000
# characters (October 2026). Staying under 6,000 leaves room for the person's own request.
HARD_LIMIT = 6000
SOFT_LIMIT = 5500

# Prompts are public: they may link only to these. Never a Dropbox, SharePoint or local path.
ALLOWED_URL_PREFIXES = (
    "https://brand.unocha.org",
    "https://unocha.mediavalet.com",
    "https://un-ocha.github.io/",
    "https://raw.githubusercontent.com/UN-OCHA/",
)
FORBIDDEN = {
    "dropbox": "internal storage",
    "sharepoint": "staff-only storage",
    "/users/": "a local path",
    "~/": "a local path",
    "country icon": "internal asset",
}
REQUIRED = ("ochavisual@un.org", "ochaphoto@un.org", "I’ve learned OCHA’s visual identity.")


@dataclass
class Job:
    slug: str
    title: str
    task: str
    summary: str
    examples: list[str]
    rules: str
    path: Path


def slug_of(path: Path) -> str:
    """01_documents_and_slides.md -> documents-and-slides (the number only sets the order)."""
    return re.sub(r"^\d+_", "", path.stem).replace("_", "-")


def load_job(path: Path) -> Job:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"\+\+\+\n(.*?)\n\+\+\+\n(.*)", text, re.S)
    if not m:
        raise SystemExit(f"{path.name}: missing +++ front matter")
    meta = tomllib.loads(m.group(1))
    for key in ("title", "task", "summary", "examples"):
        if key not in meta:
            raise SystemExit(f"{path.name}: front matter has no '{key}'")
    return Job(slug_of(path), meta["title"], meta["task"], meta["summary"],
               list(meta["examples"]), m.group(2).strip(), path)


def load_jobs() -> list[Job]:
    return [load_job(p) for p in sorted(JOBS.glob("*.md"))]


def load_links() -> dict[str, str]:
    return tomllib.loads(LINKS.read_text(encoding="utf-8"))


def fill_links(text: str, links: dict[str, str], where: str) -> str:
    def sub(m: re.Match) -> str:
        name = m.group(1)
        if name not in links:
            raise SystemExit(f"{where}: unknown link '{name}' (add it to prompts/links.toml)")
        return links[name]
    return re.sub(r"\{\{link:([\w-]+)\}\}", sub, text)


def assemble(core: str, job: Job, links: dict[str, str]) -> str:
    examples = "\n".join(f"- “{e}”" for e in job.examples)
    out = (core.replace("{{task}}", job.task)
               .replace("{{job}}", job.rules)
               .replace("{{examples}}", examples))
    return fill_links(out, links, job.path.name).strip() + "\n"


def check(name: str, prompt: str) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    n = len(prompt)
    if n > HARD_LIMIT:
        errors.append(f"{n:,} characters, over the {HARD_LIMIT:,} limit")
    elif n > SOFT_LIMIT:
        warnings.append(f"{n:,} characters, over the {SOFT_LIMIT:,} target")
    if "{{" in prompt or "}}" in prompt:
        errors.append("unfilled {{slot}}")
    low = prompt.lower()
    for word, why in FORBIDDEN.items():
        if word in low:
            errors.append(f"mentions '{word}' ({why})")
    for req in REQUIRED:
        if req not in prompt:
            errors.append(f"missing required text: {req}")
    for url in re.findall(r"https?://[^\s)]+", prompt):
        if not url.startswith(ALLOWED_URL_PREFIXES):
            errors.append(f"link not on the public allowlist: {url}")
    # Prose uses curly quotes. Straight ones slip in when someone edits on GitHub.
    prose = re.sub(r"https?://\S+", "", prompt)
    for i, line in enumerate(prose.splitlines(), 1):
        if "'" in line or '"' in line:
            errors.append(f"straight quote on line {i}: {line.strip()[:60]}")
    return errors, warnings


def build(write: bool = True) -> dict[str, str]:
    core = CORE.read_text(encoding="utf-8")
    links = load_links()
    jobs = load_jobs()
    if not jobs:
        raise SystemExit("no job files in prompts/jobs/")
    prompts, failed = {}, False
    for job in jobs:
        prompt = assemble(core, job, links)
        errors, warnings = check(job.slug, prompt)
        status = "FAIL" if errors else ("warn" if warnings else "ok")
        print(f"{status:4}  {job.slug:32} {len(prompt):>6,} characters")
        for w in warnings:
            print(f"        warning: {w}")
        for e in errors:
            print(f"        error: {e}")
        failed |= bool(errors)
        prompts[job.slug] = prompt
    if failed:
        raise SystemExit(1)
    if write:
        DIST.mkdir(exist_ok=True)
        for old in DIST.glob("*.txt"):
            if old.stem not in prompts:
                old.unlink()
        for slug, prompt in prompts.items():
            (DIST / f"{slug}.txt").write_text(prompt, encoding="utf-8")
    return prompts


if __name__ == "__main__":
    build(write="--check" not in sys.argv)
