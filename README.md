# OCHA AI prompts

Copy-paste prompts that make any AI assistant (Copilot, ChatGPT, Gemini, Claude…) work to OCHA’s
brand and house style. One prompt per job: documents and slides; posters, flyers and reports;
charts, infographics and maps; social media; video; writing. Colleagues copy them from the brand
site, on the “Working with AI” page:
https://brand.unocha.org/document/281801#/overview/working-with-ai

## How it is built

Each prompt is assembled from shared parts, so a rule is changed in one place:

| File | What it holds |
|---|---|
| `prompts/core.md` | The common core in every prompt: how to respond, colours, text and layout, logo, icons, photos, numbers, names, accessibility, contacts |
| `prompts/jobs/*.md` | One file per job: its title, the short text shown on the brand site, example requests, and the rules for that job |
| `prompts/links.toml` | Every link, by name. The parts write `{{link:name}}` |
| `dist/*.txt` | The finished prompts, written by the build. Don’t edit these by hand |
| `scripts/build.py` | Assembles the prompts and checks them |

The build checks that each prompt:

- stays under 6,000 characters (a warning from 5,500), so it fits Copilot’s paste box with room to spare;
- links only to public pages (brand site, MediaValet, OCHA tools);
- never mentions internal storage (Dropbox, SharePoint) or internal assets;
- uses curly quotes in prose, and keeps the opening line and the contact emails.

## Changing a prompt

1. Edit the part: `prompts/core.md` for a rule every prompt shares, or the job’s file in `prompts/jobs/`.
   The words around the prompts on the brand site (heading, introduction, button text) are in
   `prompts/page.toml`.
2. Run `python3 scripts/build.py` (Python 3.11 or later, no extra packages). Fix anything it reports.
3. Read the changed prompt in `dist/`, then commit and push to `main` (or open a pull request).

Small changes can also be made on github.com: edit the file, commit, and the Action checks it. Only
`dist/` then needs rebuilding: the Action says so if it’s out of date.

## How it reaches the brand site

On every push to `main`, the GitHub Action `.github/workflows/publish.yml` checks the prompts and
runs `scripts/publish_frontify.py`, which writes each prompt into its copy button on the brand site
through the Frontify API. The text is stored on the brand site itself, so the buttons keep working
whatever happens to GitHub.

- `frontify.json` lists the blocks for each page: `live` (the “Working with AI” page) and
  `test` (a hidden test page). The repository variable `FRONTIFY_TARGET` picks which one the Action
  updates.
- The Action needs the repository secret `FRONTIFY_TOKEN`, a Frontify personal access token.
- Only changed blocks are written, and each write is read back to confirm it.
- **Adding or removing a job** changes the page layout, which the Action doesn’t do. Add the job file,
  then on a computer run
  `FRONTIFY_TOKEN=… python3 scripts/publish_frontify.py --target live --create-missing`,
  which builds the new blocks and saves their ids in `frontify.json`; commit that file. For a removed
  job, delete its blocks on the brand site and its entry in `frontify.json`.
- `--dry-run` shows what would change without writing anything.

## Project Owner
Javier Cueto, Head of the Brand and Design Unit, OCHA

## Maintained by
**OCHA Brand and Design Unit (BDU)**
- Team: ochavisual@un.org
- Focal point: Javier Cueto (cuetoj@un.org)
