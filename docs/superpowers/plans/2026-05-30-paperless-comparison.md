# Paperless-ngx comparison table in README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "## FileFolio vs Paperless-ngx" section with a color-coded comparison table to README.md, placed immediately after "## Why FileFolio?".

**Architecture:** Single README.md edit — insert a new section with an intro sentence and a 6-row markdown table using 🟢/🔴 emoji indicators. No code changes, no tests.

**Tech Stack:** Markdown, Git

---

## Files

- Modify: `README.md`

---

### Task 1: Insert the comparison section into README.md

**Files:**
- Modify: `README.md`

The current README has this block starting at line 11:

```markdown
## Why FileFolio?

- You have hundreds of PDF bills, reports, or research papers scattered in folders.
- You care about privacy and do not want to upload them to cloud AI services.
- You still want smart search, auto-tagging, and reasonable file names.

FileFolio watches a folder, uses a local LLM via Ollama to analyze each PDF, and keeps everything searchable in one interface.

## Features
```

- [ ] **Step 1: Edit README.md**

Insert the following block between the end of the "Why FileFolio?" section and the "## Features" heading:

```markdown
## FileFolio vs Paperless-ngx

If you've looked at Paperless-ngx, here's how they compare:

| | FileFolio | Paperless-ngx |
|---|---|---|
| AI tagging & naming | 🟢 Local LLM via Ollama, zero config | 🔴 Rule-based; define tags, types, and correspondents manually |
| Setup | 🟢 Single Python process + SQLite | 🔴 Docker Compose: web, worker, Redis, PostgreSQL |
| Resource footprint | 🟢 Lightweight | 🔴 Multi-service, heavier |
| Multi-user | 🔴 No | 🟢 Yes |
| Feature scope | 🔴 Focused: upload, search, tag, organize | 🟢 Broader: email ingestion, custom fields, workflow automation |
| Best for | 🟢 Personal libraries, privacy-first, low setup | 🟢 Power users, teams, complex workflows |

```

The result should be:

```markdown
## Why FileFolio?

- You have hundreds of PDF bills, reports, or research papers scattered in folders.
- You care about privacy and do not want to upload them to cloud AI services.
- You still want smart search, auto-tagging, and reasonable file names.

FileFolio watches a folder, uses a local LLM via Ollama to analyze each PDF, and keeps everything searchable in one interface.

## FileFolio vs Paperless-ngx

If you've looked at Paperless-ngx, here's how they compare:

| | FileFolio | Paperless-ngx |
|---|---|---|
| AI tagging & naming | 🟢 Local LLM via Ollama, zero config | 🔴 Rule-based; define tags, types, and correspondents manually |
| Setup | 🟢 Single Python process + SQLite | 🔴 Docker Compose: web, worker, Redis, PostgreSQL |
| Resource footprint | 🟢 Lightweight | 🔴 Multi-service, heavier |
| Multi-user | 🔴 No | 🟢 Yes |
| Feature scope | 🔴 Focused: upload, search, tag, organize | 🟢 Broader: email ingestion, custom fields, workflow automation |
| Best for | 🟢 Personal libraries, privacy-first, low setup | 🟢 Power users, teams, complex workflows |

## Features
```

- [ ] **Step 2: Verify the section is in the right place**

Run:
```bash
grep -n "## " README.md
```

Expected output (section order matters):
```
11:## Why FileFolio?
19:## FileFolio vs Paperless-ngx
28:## Features
...
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "feat(readme): add Paperless-ngx comparison table (T001)

Co-authored-by: Claude <claude@anthropic.com>"
```
