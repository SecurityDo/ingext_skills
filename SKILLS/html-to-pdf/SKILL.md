---
name: html-to-pdf
description: >
  Convert any HTML file to a high-fidelity PDF using TypeScript and Playwright (headless
  Chromium). Use this skill whenever the user wants to turn an HTML file into a PDF —
  whether it's a report, dashboard, document, or any other HTML output. Trigger on
  phrasings like: "convert this HTML to PDF", "save this as a PDF", "export to PDF",
  "make a PDF from this HTML file", "I need a PDF version", "print this to PDF", or any
  request where the input is an HTML file and the output should be a PDF. Also trigger
  proactively after generating an HTML report or document if the user might want a PDF copy.
---

# HTML → PDF Conversion

Convert any HTML file to a pixel-perfect PDF using Playwright's headless Chromium. The
output matches exactly what a Chrome "Print to PDF" would produce — CSS variables, SVG
charts, conic gradients, embedded base64 images, all rendered correctly.

## One-time setup vs. per-run

**First time only:** Install `playwright` and download the Chromium browser binary (~107 MB).
This only needs to happen once in the sandbox session; subsequent runs skip straight to
Step 3.

**Every run:** Call `convert.ts` via `ts-node` with the input HTML path.

---

## Step 1 — Confirm input and output paths

Identify the HTML file to convert. It may be:
- A path the user gave explicitly
- A file just created in the current session (e.g. a Fluency report)
- A file in the workspace folder

Default output path: same directory as the input, same filename, `.pdf` extension.
Example: `report.html` → `report.pdf`

---

## Step 2 — Install dependencies (first time only)

```bash
# Create a working directory and install
mkdir -p /tmp/html-to-pdf && cd /tmp/html-to-pdf
npm init -y --quiet
npm install playwright ts-node typescript @types/node
npx playwright install chromium
```

This downloads ~107 MB of Chromium the first time. On subsequent runs the cached binary
is reused automatically — you can skip straight to Step 3.

> **Note:** `npx playwright install chromium` downloads an ARM64-compatible headless
> Chromium shell via Playwright's CDN, which works in this sandbox environment. Do NOT use
> `puppeteer` — it tries to download from Google's CDN, which is blocked here.

---

## Step 3 — Run the conversion

Call the bundled `convert.ts` script via `ts-node`:

```bash
cd /tmp/html-to-pdf
NODE_PATH=/tmp/html-to-pdf/node_modules \
  npx ts-node <skill-scripts-dir>/convert.ts \
  "<absolute-path/to/input.html>" \
  "<absolute-path/to/output.pdf>" \
  [flags]
```

Where `<skill-scripts-dir>` is the `scripts/` folder inside this skill's directory.

**Flags:**

| Flag | Default | Notes |
|---|---|---|
| `--format=<size>` | `A4` | Page size: `A4`, `A3`, `Letter`, `Legal` |
| `--landscape` | off | Landscape orientation |
| `--scale=<n>` | `1` | CSS scale 0.1–2. Use `0.85` to fit wide pages |
| `--no-background` | off | Omit background colours/images |
| `--margin=<t,r,b,l>` | `15mm,10mm,15mm,10mm` | Page margins, comma-separated |
| `--wait=<ms>` | `1000` | Extra ms to wait after page load |
| `--one-page` | off | Auto-size the PDF to fit all content on a single page. Overrides `--format` and `--landscape`. Ideal for long reports. |

**Example — convert a Fluency ingress report:**
```bash
cd /tmp/html-to-pdf
NODE_PATH=/tmp/html-to-pdf/node_modules \
  npx ts-node /path/to/html-to-pdf/scripts/convert.ts \
  "/Users/yuan/Documents/Claude/Projects/Report Template/system_event_ingress_report.html" \
  "/Users/yuan/Documents/Claude/Projects/Report Template/system_event_ingress_report.pdf"
```

---

## Step 4 — Troubleshooting

**`Cannot find module 'playwright'`**
Run the install step again from `/tmp/html-to-pdf`, or ensure `NODE_PATH` is set correctly.

**`Error: browserType.launch: Executable doesn't exist`**
The Chromium binary wasn't downloaded. Run: `cd /tmp/html-to-pdf && npx playwright install chromium`

**Page renders blank or fonts are missing**
The HTML uses Google Fonts loaded over the network. Increase the wait time: `--wait=3000`.
Alternatively, pre-embed the fonts as base64 in the HTML before converting.

**Content clipped at the right edge**
Use `--scale=0.85` to shrink content to fit within margins.

**PDF looks correct but images are missing**
The HTML references external image URLs. For best results, ensure images are embedded as
base64 data URIs in the HTML (the Fluency report template already does this).

---

## Step 5 — Share the PDF

Once the conversion prints `Done! PDF saved to: ...`, copy the PDF to the workspace folder
if it isn't already there, and share a `computer://` link with the user.

---

## How it works

The bundled `scripts/convert.ts` launches a headless Chromium browser via Playwright,
navigates to the HTML file using a `file://` URL, waits for all resources to settle, then
calls Chromium's native PDF print engine. This is identical to "Print → Save as PDF" in
Chrome Desktop, so all modern CSS features (grid, custom properties, SVG, conic-gradient)
render correctly.
