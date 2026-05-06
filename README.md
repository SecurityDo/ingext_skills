# Ingext Skills

A collection of Claude Code skills for Fluency / Ingext users. Skills extend Claude with
specialised capabilities that activate automatically when you describe what you want.

---

## What is a Skill?

A `.skill` file is a self-contained plugin for Claude Code. Once installed, Claude
recognises trigger phrases and automatically invokes the skill's instructions and bundled
assets — no manual commands needed.

---

## Installation

1. Open Claude Code and go to **Settings → Plugins**.
2. Drag and drop a `.skill` file onto the plugins panel, or click **Add Plugin** and
   select the file.
3. The skill is now active. Just talk to Claude naturally — it will invoke the right skill
   when it recognises your request.

---

## Available Skills

### `fluency-report.skill`

Run any report from your Fluency / Ingext FPL catalog and get a branded, single-page HTML
summary — KPI cards, charts, tables, and a written interpretation of the data.

**Trigger phrases**

- "Run a Fluency report"
- "Run the Ingext `<ReportName>` report"
- "Give me a Fluency summary on `<topic>`"
- "Pull the Fluency `<ReportName>` report and summarize it"

> Fluency and Ingext are interchangeable — both trigger the skill.

**What you get**

- A browser-ready HTML file with Fluency branding
- KPI cards, bar/line/donut charts, and severity-coded tables tailored to the report's
  data shape
- A short written interpretation highlighting the highest-signal findings
- A suggested next-steps section

**Notes**

- Claude always lists your available reports first and matches your request against the
  real catalog. It will never invent or substitute a report that doesn't exist.
- If you ask for a report by name and it isn't in your catalog, Claude will tell you and
  list what's available.
- To also get a PDF, ask Claude to "convert it to PDF" after the HTML is generated — it
  will automatically chain into the `html-to-pdf` skill.

---

### `o365-user-investigation.skill`

Investigate a specific Office 365 / Azure AD (Entra) user by running three Fluency reports
in parallel and combining the results into a single-page HTML investigation report —
activity timeline, executive summary, per-report data tables, and security recommendations.

**Trigger phrases**

- "Investigate O365 user `<email>`"
- "Look into what user `<email>` did in Office 365"
- "Pull a Fluency user investigation for `<email>`"
- "Check this Azure AD account on Fluency"
- "What did `<user>` do in Office 365 last week?"

**What you get**

- A browser-ready HTML investigation report with Fluency branding
- Chronological activity timeline merging sign-ins and directory changes
- Executive summary highlighting suspicious patterns (failed logins, unusual locations,
  privilege changes, etc.)
- Three per-report data tables: sign-in history, directory changes initiated by the user,
  and directory changes targeting the user
- Suggested next steps for the analyst

**Required reports in your FPL catalog**

- `GetDirectoryChangesInitiatedByUser`
- `GetDirectoryChangesTargetingUser`
- `GetUserSigninHistory`

If any of the three are missing, Claude will stop and tell you which ones are absent
rather than producing a partial report.

**Notes**

- Claude will ask for the username and time window (Last 24 hours, 7 days, 30 days, or
  custom) if you don't supply them up front.
- To get a PDF, ask Claude to "convert it to PDF" after the HTML is generated — it will
  chain into the `html-to-pdf` skill.

---

### `html-to-pdf.skill`

Convert any HTML file to a pixel-perfect PDF using headless Chromium (via Playwright).
Produces output identical to Chrome's "Print to PDF" — CSS grid, SVG charts, conic
gradients, and embedded images all render correctly.

**Trigger phrases**

- "Convert this HTML to PDF"
- "Save this as a PDF"
- "Export to PDF"
- "Make a PDF from this HTML file"
- "I need a PDF version"
- "Print this to PDF"

Claude will also offer to convert automatically after generating an HTML report.

**What you get**

- A `.pdf` file saved next to the source `.html` file by default
- Full fidelity rendering — everything Chrome can render, the PDF will contain
- Configurable page size, orientation, margins, and scale

**Supported options** *(you can ask Claude to apply any of these)*

| Option | Default | Description |
|---|---|---|
| Page size | A4 | A4, A3, Letter, Legal |
| Orientation | Portrait | Ask for landscape |
| Scale | 1× | E.g. "scale to 85%" to fit wide content |
| Margins | 15mm top/bottom, 10mm sides | Customisable |
| Single page | Off | "Fit everything on one page" |

**Notes**

- The first conversion in a session downloads a ~107 MB Chromium binary. Subsequent
  conversions in the same session reuse the cached binary and are much faster.
- If the HTML references Google Fonts, ask Claude to "wait longer for fonts to load" if
  text appears in a fallback font.

---

## Typical Workflow

```
You:    Run the Fluency IngestionRate report
Claude: [lists reports, matches IngestionRate, runs it, generates ingestionrate_report.html]

You:    Now convert it to PDF
Claude: [invokes html-to-pdf, produces ingestionrate_report.pdf]
```

---

## Requirements

- Claude Code with plugin support enabled
- Node.js available in the environment (for `html-to-pdf`)
- The Fluency Terps MCP connector added to Claude Code (for `fluency-report`) — see setup below

---

## MCP Connector Setup

The `fluency-report` skill requires the **Fluency Terps MCP connector** to query your
Ingext FPL catalog and run reports.

### Adding the connector

1. Open Claude Code and go to **Settings → Connectors** (or **MCP Servers**).
2. Add a new HTTP connector with your organisation's Ingext URL:
   ```
   https://<your-ingext-domain>/mcp
   ```
   For example: `https://terplab.yourdomain.ingext.io/mcp`
3. When prompted, authenticate via **OAuth login** using your Ingext credentials.
4. Save the connector. Claude Code will now have access to your FPL report catalog.

> Contact your Ingext administrator if you are unsure of your organisation's MCP URL.
