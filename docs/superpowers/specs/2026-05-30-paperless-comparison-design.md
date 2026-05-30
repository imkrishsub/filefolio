---
title: Paperless-ngx comparison table in README
date: 2026-05-30
task: T001
status: approved
---

## Goal

Add a "FileFolio vs Paperless-ngx" comparison section to README.md so that a cold GitHub visitor who already knows Paperless-ngx can quickly understand how FileFolio differs and whether it suits their needs.

## Placement

A new `## FileFolio vs Paperless-ngx` section inserted immediately after the existing `## Why FileFolio?` section. The Why section's bullet points serve as the opening hook (pain points); the table answers the natural follow-up question.

## Format

A markdown table with emoji color coding (🟢 = advantage, 🔴 = disadvantage) prefixed in each cell. GitHub strips inline CSS, so emoji indicators are the only practical way to add color.

## Table content

| | FileFolio | Paperless-ngx |
|---|---|---|
| AI tagging & naming | 🟢 Local LLM via Ollama, zero config | 🔴 Rule-based; define tags, types, and correspondents manually |
| Setup | 🟢 Single Python process + SQLite | 🔴 Docker Compose: web, worker, Redis, PostgreSQL |
| Resource footprint | 🟢 Lightweight | 🔴 Multi-service, heavier |
| Multi-user | 🔴 No | 🟢 Yes |
| Feature scope | 🔴 Focused: upload, search, tag, organize | 🟢 Broader: email ingestion, custom fields, workflow automation |
| Best for | 🟢 Personal libraries, privacy-first, low setup | 🟢 Power users, teams, complex workflows |

The "Best for" row uses 🟢 on both sides — no winner, just different audiences. This prevents the table reading as one-sided marketing.

## Intro line

> "If you've looked at Paperless-ngx, here's how they compare:"

One sentence is enough context. No need for a paragraph.

## Out of scope

- Comparing against any other tool (Papermerge, Mayan EDMS, etc.)
- Changes to the Features list (covered by T008)
- Any backend or frontend code changes
