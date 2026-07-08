# Project landing page

Self-contained `index.html` (no external requests, light/dark via `prefers-color-scheme`) —
the main entry at **https://hamyrappy.github.io/drift-inspector/**, linking to all deployments.
Placeholder chips (paper, HF datasets) carry `class="soon"` and are unclickable until the
real URLs land.

## Deploy scheme (decided 2026-07-07)

| URL | Content | Source |
|---|---|---|
| `/drift-inspector/` | this landing page | `landing/index.html` |
| `/drift-inspector-emnlp/` | EMNLP 2020–2025 instance (paper study, has Compare tab) | `inspector-emnlp/` — pinned build assembled by `acc export-public` (current frontend + the EMNLP `acc_data.json` pinned at the submission build) |
| `/drift-inspector-acl/` | 6-venue main-conference instance (69,950 claims) | current `inspector/` |

## Still pending

- Paper link (OpenReview / PDF after acceptance) — the "Paper" chip is disabled until then
- Screencast link — to be added after publication (submitted directly with the EMNLP demo form)
