---
name: executive-report
version: 1.0.0
description: >-
  Turn already-gathered analysis or tool results into a polished executive report: a
  self-contained HTML file with analysis, callouts, charts and tables, plus a mail-ready PDF
  with a title footer and "X of Y" page count, checked for print layout. Presentation only:
  it does not query data or change anything. USE THIS SKILL when the user asks for an
  executive report, board-ready report, customer-ready report, "an executive HTML report for
  this", or an HTML-to-PDF report built from results already in the conversation or in files.
  DO NOT use it to fetch or compute the underlying data (run the relevant investigation or
  report skill first), or to convert an arbitrary existing HTML file to PDF (use html-to-pdf).
---

# Executive Report

Create a self-contained executive HTML report, render it to PDF, and QA the printed result.
This skill is presentation-only: it summarizes evidence that is already approved and present,
and must not invent facts or change anything in the platform.

## Trigger

A request such as "Provide me an executive HTML report for this. Add analysis, callouts,
charts and tables." Produce both:

- a standalone `.html` report with embedded CSS and no external runtime (no CDN scripts,
  fonts or images that need the network); and
- a `.pdf` generated from that HTML.

## Workflow

1. Identify the source evidence already in the conversation or in files. If the report
   depends on live tenant data and that data is missing or stale, run the proper read-only
   workflow first (the matching investigation, KQL or report skill) rather than guessing.
2. Write the title, executive summary, analysis, callouts, charts and tables. Keep every
   claim tied to the source evidence, and say what is unknown.
3. Build the HTML with print CSS from the start. Use CSS Grid/Flex for side-by-side KPI
   cards, callouts and charts. Do not rely on mobile breakpoints for print. For Fluency
   branding, reuse `fluency-report`'s `assets/base_template.html` and logo.
4. Add print rules that keep headings with the content that follows:
   - `h2 { break-after: avoid; page-break-after: avoid; }`
   - `.section > h2 + * { break-before: avoid; page-break-before: avoid; }`
   - an explicit `print-page-start` class only for a section that should start a clean page.
5. Render the PDF with this skill's script:
   ```bash
   node scripts/render-html-pdf.mjs --input reports/name.html --output reports/name.pdf --title "Report Title"
   ```
   It needs Playwright (`npm install playwright`, local or global) and a Chrome or Chromium
   install. It looks in the usual macOS, Linux and Windows locations, or take `--chrome PATH`
   or the `CHROME_PATH` environment variable.

## Executive lead

Open with the lead, not the investigation journey. The first visible block answers, in order:

1. **What happened**: the situation in plain operational language.
2. **Why it matters**: business and security impact, and exposure.
3. **Result / decision**: the verdict, escalation, containment status or closure.
4. **Evidence strength**: what is confirmed, inferred and unknown, at a glance.

Do not begin with methodology, analyst corrections, case-history narration, or wording like
"the subject was originally X but analysis says Y". That belongs in a later "Analysis Notes",
"Evidence Basis" or "Methodology" section. If a corrected interpretation matters, state the
operational conclusion first, then explain the correction as support.

## PDF requirements

- Footer on every page: report title at bottom left, `X of Y` page count at bottom right
  (the script does this).
- Margins about `0.65in` top, `0.7in` left/right, `0.62in` bottom.
- Charts and side-by-side content stay side by side in print unless the page is genuinely
  too narrow.
- Tables fit the page width with no clipped columns.
- No section heading stranded alone at the bottom of a page.

## QA gate

Before delivering:

1. Parse the HTML: `python3 -m html.parser reports/name.html`.
2. Render the PDF.
3. If `pdftoppm` exists, convert pages to PNG and look at them:
   ```bash
   mkdir -p reports/pdf-preview
   pdftoppm -png -r 120 reports/name.pdf reports/pdf-preview/name
   ```
4. Inspect every page and confirm:
   - the footer title and `X of Y` appear on every page;
   - no heading is stranded without at least a line of content or a graphic;
   - charts, cards and callouts print side by side where intended;
   - text is not clipped, overlapped or too small to read;
   - tables fit the page with readable row spacing;
   - the report meets the stated objective and contains analysis, callouts, charts and tables.
5. Check table fit in print media with Playwright: emulate print at the PDF content width and
   assert each table has `scrollWidth <= clientWidth` and a `getBoundingClientRect().right`
   inside the document width. If any table overflows, tighten column widths, font size or
   wrapping, or switch that section to a single column, then regenerate.
6. Delete the temporary preview images unless the user asked to keep them.

If QA fails, fix the HTML/CSS and regenerate the PDF before replying. Deliver the HTML and
PDF paths, and say anything you could not verify (for example, no `pdftoppm` for the visual check).
