# Build → development → production workflow

How a bot actually gets built and shipped, and where this repo sits on that path.

---

## 0. Correcting the mental model

Your version:

> create the repo locally → push to GitHub → then what?

That's the right *first two steps* but it treats GitHub as a backup drive. The
professional version treats the repo as the **single source of truth that
everything else hangs off**: CI runs from it, deploys are triggered by it, and
production runs a *tagged, immutable artifact* built from it.

The corrected loop:

```
design → scaffold → local dev loop → branch → PR → CI → merge → tag → build image → deploy → observe → repeat
```

Two rules that separate hobby from professional:

1. **Nothing reaches production that didn't pass CI on a pull request.**
2. **You deploy an artifact (a tagged image), not a branch.** "It works on my
   machine" dies the moment the thing you ship is a container digest.

---

## 1. Before any code

- **Write the design doc first.** One page: goals, non-goals, architecture,
  data flow, failure table. This repo has `docs/design.md` — that's why the code
  came out coherent instead of accreting.
- **Decide the boring things once**: language version, package manager, layout,
  formatter, linter, test runner. Put them in `pyproject.toml` so nobody argues later.
- **Know your deployment target before you write code.** A bot that must run on a
  free PaaS is architected differently (no local disk, no long-lived state) from
  one on a VPS.

**Polling vs webhook** — the one Telegram-specific architecture decision:

| | Long polling | Webhook |
|---|---|---|
| Inbound port | none | HTTPS + valid TLS cert |
| Works behind NAT/home PC | yes | no (needs tunnel) |
| Latency | ~ok | lower |
| Scaling | one process | load-balanced |
| Best for | dev, personal bots, PaaS free tiers | production, high volume |

Start with polling. Move to webhooks only when volume or latency demands it —
aiogram supports both behind the same dispatcher, so it's a config change, not
a rewrite. (This repo is polling; `docs/design.md` says so deliberately.)

---

## 2. Repo bootstrap (your step 1–2, expanded)

```bash
mkdir movie-bot && cd movie-bot
git init -b main
# create pyproject.toml, .gitignore, README.md, LICENSE, src/, tests/
git add -A && git commit -m "chore: project scaffold"
gh repo create movie-bot --private --source=. --push
```

Before the first push, make sure these exist:

- **`.gitignore`** — `.env`, `*.session`, `__pycache__/`, `.venv/`, secrets.
  Get this right *before* the first commit; a leaked token in git history is
  forever (and Telegram will revoke it).
- **`.env.example`** — every variable with a dummy value. Documents config
  without leaking it.
- **`README.md`** — what it is, how to run it, config table.
- **`LICENSE`** — even for private repos. Absent = nobody may legally use it.
- **Branch protection on `main`** — require PR + passing checks, no direct pushes.
  Settings → Branches → Add rule. This is the single highest-value 30 seconds.

---

## 3. The local development loop

```bash
python -m venv .venv && source .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -e ".[dev]"
cp .env.example .env        # fill in real values
python -m pytest -q
python -m src.main
```

Practices that matter:

- **A second bot token for development.** Never test against the production bot.
  Create `@yourbot_dev_bot` in BotFather. Two tokens, two `.env` files.
- **Test with fixtures, not the network.** This repo saves real HTML into
  `tests/fixtures/` and parses those. Tests stay fast, deterministic, and
  runnable offline — and when the site redesigns, you re-capture one fixture and
  see exactly what broke. This is why there are 155 tests and no flakiness.
- **Pure functions at the edges.** `services/parsers.py` and
  `services/formatting.py` take strings and return models with no I/O. Almost all
  your tests should hit these; handler tests are the expensive minority.
- **Pin the runtime, floor the libraries.** `requires-python = ">=3.12"`,
  `aiogram>=3.31`. For reproducible deploys, add a lock file.

---

## 4. Branch → PR → CI → merge

```bash
git switch -c feat/rich-movie-card
# ... work, committing in small logical steps ...
git push -u origin feat/rich-movie-card
gh pr create --fill
```

- **Branch naming**: `feat/`, `fix/`, `chore/`, `docs/`, `refactor/`.
- **Commit messages**: Conventional Commits (`feat:`, `fix:`, `docs:`…). Not
  ceremony — it's what lets you auto-generate a changelog and infer semver.
- **PR size**: if it can't be reviewed in ten minutes, split it.
- **Self-review the diff before requesting review.** You'll catch half your own
  mistakes. Solo projects included — open the PR, read your own diff, then merge.
- **Squash-merge** into `main` so history stays one-commit-per-change.

**CI** (`.github/workflows/ci.yml`) should, on every PR: install, lint, type-check,
test. If it's not in CI it will rot. A minimal Python CI is ~25 lines and is the
difference between "I think it works" and "it works."

Add `ruff` (lint + format) and `mypy` (types) early. This repo has full type hints
already but no linter config — that's the obvious next chore.

---

## 5. Release & deploy

**Tag a release:**

```bash
git tag -a v0.2.0 -m "Rich message movie cards"
git push origin v0.2.0
```

**Build an immutable image.** This repo already has a good Dockerfile: slim base,
non-root `appuser`, no secrets baked in. Secrets arrive at *runtime* via
`--env-file` or the platform's secret store — never `COPY .env`, never `ENV TOKEN=`.

**Deploy targets, in ascending seriousness:**

| Target | Notes |
|---|---|
| Your PC | Fine for personal bots. Dies when you close the laptop. |
| Free PaaS (Railway, Fly, Render) | Easy; ephemeral disk — persist sessions to a volume or external store |
| VPS ($5 Hetzner/DO) | `docker compose up -d` + `restart: unless-stopped`. Sweet spot for a bot like this. |
| Managed container platform | Only once you need scale you don't currently have |

**A bot has state you must not lose**: this one persists `session.json` (the
scraper login cookie). On any ephemeral filesystem that means a mounted volume,
or it re-prompts `/login` on every redeploy. Design for restart-at-any-moment.

**CD**: a second workflow on `push: tags: v*` that builds the image, pushes it to
`ghcr.io`, and tells the host to pull. Deploy becomes `git push origin v0.2.0`.

---

## 6. Production hygiene

- **Structured logging to stdout** at INFO; let the platform collect it. Never
  log tokens, cookies, or user data. (This repo's rules already forbid it.)
- **Error alerting** — this bot DMs the owner on session expiry. That's the
  right instinct: the operator learns from a notification, not from a user
  complaining.
- **Health**: for polling bots, "is the process alive and is it consuming
  updates?" `restart: unless-stopped` covers most of it.
- **Backups**: whatever holds state (`session.json`, later SQLite) needs a
  backup, or it isn't durable.
- **Secret rotation**: if a token ever touches a commit, revoke it in BotFather
  *immediately*. Rewriting history is not enough — assume it's compromised.
- **Staging**: dev bot token + a `staging` deploy of `main`, production on tags.

---

## 7. Where this repo stands

Already professional:

- Layered architecture matching a written design doc
- 155 tests, fixture-driven, offline, fast
- Pydantic models and type hints across every layer
- Secrets in `.env`, gitignored, never logged
- Non-root Dockerfile with no baked secrets
- Conventional commits

Missing, in priority order:

1. **CI workflow** — no `.github/workflows/`. Tests that only run when you
   remember are tests that stop running.
2. **`ruff` + `mypy`** config and a CI gate for them.
3. **Branch protection** on the default branch.
4. **`LICENSE`**.
5. **Lock file** for reproducible deploys.
6. **CD on tags** → build + push image to `ghcr.io`.
7. Default branch is `feature/zarfilm-bot`; rename to `main` once the feature
   line settles.
