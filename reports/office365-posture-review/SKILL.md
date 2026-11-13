---
name: office365-posture-review
version: 2.0.0
description: >-
  Produce the Microsoft 365 identity hygiene report for ONE Fluency / Ingext tenant from its resource
  dumps (office365User, office365Application, office365Device): a customer-ready HTML and PDF with a
  rating, scorecard, top finding, admins against a headcount baseline with compound flags, weak MFA,
  OAuth consent, stale tokens, password policy None, real headcount and unlicensed accounts, Windows
  end-of-life, app registrations and device registration hygiene, callouts and a remediation
  sequence, plus a CSV and facts JSON. USE THIS SKILL for "Office 365 posture review",
  "Office 365 hygiene report", "identity hygiene", "Entra hygiene", "who are our admins", "real user
  count", "end-of-life Windows in Entra", "app registration review", "device registration review".
  Read-only; uses no FPL report and no event query. DO NOT use it for activity questions (failed logins, mailbox activity, impossible travel):
  use office-user-investigation or azure-user-signin-investigation.
---

# Office 365 Posture Review (Microsoft 365 identity hygiene report)

Turns the tenant's Office 365 inventory snapshots into the Microsoft 365 identity hygiene report: the
same sections and evidence as the `office365-hygiene-report` skill, in the Fluency editorial style,
computed from the dumps alone with no live FPL run, plus application-registration and
device-registration hygiene. It is resource posture, not activity: it never says a risk was exploited.
Read-only; nothing is changed in the tenant.

## Inputs

| Input | Rule |
|---|---|
| Connector | The MCP connector the user names. Use its tools directly. |
| Tenant | One account. Call `list_accounts` and match the user's name; stop if ambiguous. |
| Customer name | The customer's display name for the title (`--tenant`). The tenant id goes in `--account` and appears once, in the method note. |

## Step 1 — Collect

Make a work folder **outside the repository** (the dumps name real users and devices).

1. `list_resource_dumps(account)`; save the result as `WORKDIR/resources.json`.
2. For each of `office365User`, `office365Application`, `office365Device` that is listed, and for each
   customer (feed) it lists, call `get_resource_dump_url(account, resource, customer)` and download with
   `curl -sf -o` (the link expires in 15 minutes; never read it into the conversation). Name the files
   `users__<customer>.jsonl.gz`, `apps__<customer>.jsonl.gz`, `devices__<customer>.jsonl.gz`.
3. A resource that is not listed is absent: skip it, the report shows it as "No dump".
4. Check each file's record count against the `count` that `list_resource_dumps` reported; a mismatch
   is a truncated download. The script warns.

An account can have more than one Office 365 feed (customer name). Each feed is assessed on its own and
never summed with another, because two feeds may describe the same tenant.

## Step 2 — Build

```bash
python3 scripts/build_report.py --evidence-dir WORKDIR --out WORKDIR/<Customer>_M365_Identity_Hygiene_<YYYY-MM-DD>.html \
  --csv WORKDIR/findings.csv --tenant "Example Corp" --account acme --site Develop [--narrative WORKDIR/narrative.json]
```

It writes the HTML, `<out>.facts.json` (every figure, the top rows of each list and the narrative used) and
the CSV (every finding row). `NOTE:` lines name licence IDs the tier list does not know; `WARNING:` lines
name truncated downloads. With several feeds it writes one report per feed.

The report, in order: title and thesis; the five-tile scorecard (privileged roles against the baseline, weak
MFA, OAuth, old token baselines, password policy None); the highest-impact finding; §1 executive summary
with the rating; the headline KPIs (active licensed accounts, guests, unlicensed, end-of-life Windows); §2
privileged role footprint (top 10 admins, role tags, Global Administrators marked, compound flags); §3 MFA,
token and password hygiene; §4 third-party OAuth consent; §5 account composition; §6 device OS currency;
§7 application registrations; §8 device registration hygiene; §9 analyst callouts; §10 remediation
sequence; method.

**Narrative.** The thesis, top finding, summary, callouts and remediation are generated from the numbers,
so a plain run is a complete report. To tailor the wording, copy `narrative` out of the facts file into
`narrative.json`, edit it and run again with `--narrative` (keys and rules: `references/narrative.md`).
Do not hand-edit the HTML and do not add, drop or reorder sections.

## Step 3 — PDF and check

```bash
node <fluency-report>/scripts/render_pdf.mjs --input report.html --output report.pdf
```

Look at every page: the scorecard and the top finding sit on page 1, no table runs past its column, no
heading is stranded at the foot of a page. Check the scorecard and KPIs against `facts.json`, and that the
compound flags list every admin who appears in another finding.

## Reading the result

| Severity | Finding patterns |
|---|---|
| Critical | privileged account with weak MFA, a stale token baseline or password policy None (compound); rooted or jailbroken device; app older than 730 days that still has implicit grant or an HTTP redirect |
| High | admins above the baseline; more than 2 Global Administrators; end-of-life or out-of-support Windows; implicit grant; HTTP redirect URI; unmanaged or non-compliant device |
| Medium | guests above 15% of directory records; enabled members with no licence; weak MFA factors; OAuth consent queue; HTTP homepage; no verified publisher; Workplace trust; stale hybrid sync; stale token baseline; macOS below 14 |
| Low | admins within the baseline; Windows build to confirm; password policy None; apps with no credentials; stale sign-ins; no username |

**Overall rating:** Elevated when any Critical finding is raised, Moderate when any High, otherwise Good.
In the hand-off, lead with the rating and the top finding in two or three sentences, then give the files.

**Accounts and headcount.** Every directory record falls in one bucket, in priority order: disabled,
guest, paid (holds a licence that `assets/sku_tiers.json` marks `core`), free (only free or
auto-assigned), add-on only, unlicensed. **Headcount = paid members**; quote it as the employee count
and say that you did. Never use the raw record count as headcount. Unlicensed members are a list to
classify (service accounts, shared mailboxes, resource accounts, people), not "service accounts".
Licence IDs the tier list does not know are named in the report (and as `NOTE:` lines from the
script): members holding only those fall outside the headcount, so say the headcount may be
understated, and add the IDs to `assets/sku_tiers.json` once you have checked them against Microsoft's
published licence ID list. Never guess a tier.

**Admin baseline.** 2, plus 1 per 500 of headcount. The page shows the admin count against the
baseline and the ratio. Admin roles: Global, Company, Security, Privileged Role, User, Exchange and
SharePoint Service Administrator. Without a headcount the baseline is "not computed".

**Windows and macOS.** `assets/os_catalog.json` labels Windows builds: `eol` (Windows 7/8/8.1 and
Windows 10 builds before 2004: replace or upgrade), `out_of_support` (Windows 11 21H2/22H2, Windows 10
2004 to 21H1: update to a current release), `verify` (builds shared with a supported Server or LTSC
edition: confirm the SKU, never call them end-of-life), `aging`, `current`. A build the catalogue does
not list shows as "not in catalogue" in the builds table and raises nothing: add it to the catalogue
rather than guessing. macOS below major version 14 is flagged. Mobile OS versions are shown, not judged.

- A check whose field is absent from every record shows **n/a** with "Not measured", never zero or
  Clean. On some tenants the token baseline fields are not in the snapshot at all.
- Weak MFA means email or SMS registered. Dumps carry `mobilePhone` and `email`, and the check ignores
  case and underscores. MFA registration is not MFA enforcement.
- No verified publisher means `verifiedPublisher` has neither an id nor a display name; the dump holds an
  empty object for unverified apps, so a plain "is it set" test would never fire.
- Some findings are expected: service or federated accounts (password policy None), public-client apps
  (no credentials), long-idle devices. Ask the operator to confirm purpose; do not call them failures.

## Honesty rules

- Counts are as of the dump time, not a time window; say so. Preserve counts exactly.
- The body names at most 10 accounts per table; the CSV holds every row. Offer it rather than pasting lists.
- The licence tiers and the OS catalogue are dated snapshots (their `as_of` is printed in the Limits).
  Refresh them when they are stale; never edit them to make a report read better.
- A tenant with no Office 365 dump is a coverage gap, not a clean result.
- Never write "compromised", "compliant" or "secure" from these counts. Escalate to the activity tools
  when the operator asks whether a risk was used.
- The output names users, devices and apps. Keep it out of the repository and out of release notes.

## Fluency report branding and PDF

**Prerequisite: the `fluency-report` skill.** All Fluency report styling lives in that skill's `scripts/` folder
(`fluency_brand.py`, `brand.css`, the IBM Plex fonts, the lock mark and `render_pdf.mjs`). This skill does not carry its own
copy: the build scripts here that style a report find the `fluency-report` skill next to this one (or at `FLUENCY_BRAND_DIR`) and
import `fluency_brand` from it, and stop with a clear message if it is not installed. Install `fluency-report` alongside this skill. In the steps below, `<fluency-report>` means
that skill's folder.

- The HTML report is one self-contained file (mark, fonts and CSS inlined). The PDF is rendered from that same HTML with the same
  CSS, so the two match: `node <fluency-report>/scripts/render_pdf.mjs --input report.html --output report.pdf`.
  US Letter, same editorial styling as the HTML (brandline, closing footer line; no paged footer). It needs Playwright
  (`npm install playwright`) and a Chromium or Chrome binary; it finds a Chrome install automatically.
- Do not convert these reports with WeasyPrint, wkhtmltopdf or a generic HTML-to-PDF step: they ignore
  the brand CSS (grid, fonts, page rules), so the PDF would not match the HTML.
- Do not hand-write report styling. The look is the Fluency editorial style (white paper, IBM Plex, black rules, one blue / red / amber, no cards or gradients). A new page is `fluency_brand.page(...)`; markup from an older script goes
  through `fluency_brand.apply_brand(html)`. Design and component reference: the `fluency-report` skill (`references/widget_recipes.md`).
