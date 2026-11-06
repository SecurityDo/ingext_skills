---
name: shadow-ai-assessment-report
version: 1.0.0
description: >-
  Assess ONE Fluency / Ingext tenant's shadow generative-AI exposure for a CISO and render a report (HTML and PDF): posture
  (Low, Moderate, Elevated, High), five evidence paths, AI services found, key findings, actions by horizon, proposed detections
  and coverage gaps. Uses Entra applications and user grants, the endpoint software inventory (local LLM runners, AI desktop
  apps) and EventWatch rule coverage; paths without a data source are reported as not assessed. USE THIS SKILL for "shadow AI",
  "GenAI exposure", "AI usage assessment", "which AI tools are people using", "CISO AI report". Read-only via the tenant MCP
  connector. DO NOT use it for one user (office-user-investigation) or a general endpoint inventory.
---

# Shadow AI Assessment (CISO report)

Port of the original Shadow AI skill (five evidence paths, tiers, scoring) onto Ingext-native tools and the Fluency editorial
style. Board-safe: counts and AI service names only, never users, hosts or addresses. Read-only.

**Prerequisite: the `fluency-report` skill** (brand kit in its `scripts/`; `render_report.py` finds it or uses `FLUENCY_BRAND_DIR`).

## Steps

1. **Tenant.** Confirm which tenant; if not named, `list_accounts` and ask.
2. **Resource dumps (download and parse locally; never query resources with KQL).** `list_resource_dumps`, then
   `get_resource_dump_url` for `office365Application`, `office365InstalledApp`, `office365User` and the endpoint software
   inventory `sentinelOneApplication` (use whichever exist). `curl -o <dump_dir>/<resource>.jsonl.gz` in a shell that can reach
   the tenant host (links expire in 15 minutes).
3. **Detection coverage.** Call `eventwatch_rule_list` once per term with `nameContains` (Consent, OAuth, Copilot, LLM, ChatGPT,
   OpenAI, Ollama, GenAI, Shadow), save each reply and merge them into one JSON list file (`rules.json`).
4. **Context (optional).** If the tenant has the `Office365_Entra_Activity_Report` archive, run the ransomware skill's
   `entra_evidence.py` and pass its JSON with `--entra`: bulk file downloads appear as context under path 4.
5. **Evidence:** `python3 scripts/ai_evidence.py <dump_dir> -o evidence.json --rules rules.json [--entra entra_evidence.json]
   [--sanctioned sanctioned.json]`. Matching uses `assets/ai_catalog.json` (the original catalog plus the repo's AI name patterns).
6. **Rate and draft:** `python3 scripts/rate_evidence.py evidence.json --tenant "<Name>" --date YYYY-MM-DD --out draft_findings.json`.
   Risk and posture come only from `assets/rating_rules.json` (see `references/scoring.md`).
7. **Review** the draft: plain language, no individual names; add what the rules cannot know. Keep every `coverage_gaps` entry.
8. **Render:** `python3 scripts/render_report.py findings.json <out_dir>` writes `Shadow_AI_Assessment_<Tenant>_<DDMonYY>.html` and `.pdf`.
9. **Reply briefly:** posture, the top findings, which paths were not assessed, and the file names.

## What cannot be assessed (state in the report)

- **Network egress (path 2)** and **data exposure (path 4):** no archived report carries proxy, DNS, firewall or DLP data, and
  event data is read from archived reports only. These paths are "not assessed", never clean. Tenants that ingest Zscaler,
  FortiGate or Meraki traffic need a scheduled archive report for GenAI domains before path 2 can be measured.
- Granted permission names are mostly absent from the application dump; per-user grants are app names only.
- Without a sanctioned list, approval is "unverified".

## Rules

- Only report what the data shows. Never change tenant configuration. Do not query event tables live for report data.
