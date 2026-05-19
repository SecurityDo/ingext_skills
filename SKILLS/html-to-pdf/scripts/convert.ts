#!/usr/bin/env ts-node
/**
 * html-to-pdf/scripts/convert.ts
 *
 * Converts a local HTML file to PDF using Playwright's headless Chromium.
 * Produces the same output as Chrome "Print → Save as PDF".
 *
 * Usage:
 *   ts-node --project <tsconfig> convert.ts <input.html> [output.pdf] [flags]
 *
 * Flags:
 *   --format=A4|A3|Letter|Legal   Page size (default: A4)
 *   --landscape                   Landscape orientation
 *   --scale=<number>              CSS scale factor 0.1–2 (default: 1)
 *   --no-background               Skip background colours/images
 *   --margin=<t,r,b,l>            Page margins e.g. "15mm,10mm,15mm,10mm"
 *   --wait=<ms>                   Extra ms to wait after load (default: 1000)
 *   --one-page                    Auto-size page to fit all content on one page
 *
 * Prerequisites (one-time):
 *   npm install playwright ts-node typescript @types/node
 *   npx playwright install chromium
 */

import { chromium } from "playwright";
import * as path from "path";
import * as fs from "fs";

// ── Arg parsing ───────────────────────────────────────────────────────────────

const args = process.argv.slice(2);

if (args.length === 0 || args.includes("--help") || args.includes("-h")) {
  console.log(`
Usage: ts-node --project <tsconfig.json> convert.ts <input.html> [output.pdf] [flags]

Flags:
  --format=A4|A3|Letter|Legal    Page size              (default: A4)
  --landscape                    Landscape orientation
  --scale=<n>                    CSS scale 0.1–2         (default: 1)
  --no-background                Omit backgrounds
  --margin=<t,r,b,l>             Margins                 (default: 15mm,10mm,15mm,10mm)
  --wait=<ms>                    Extra wait ms           (default: 1000)
  --one-page                     Auto-size to fit everything on one page

Examples:
  ts-node --project tsconfig.json convert.ts report.html
  ts-node --project tsconfig.json convert.ts report.html report.pdf --format=Letter --scale=0.9
  ts-node --project tsconfig.json convert.ts report.html out.pdf --one-page
`);
  process.exit(0);
}

type PaperFormat = "A4" | "A3" | "Letter" | "Legal";

let inputPath = "";
let outputPath = "";
let format: PaperFormat = "A4";
let landscape = false;
let scale = 1;
let printBackground = true;
let waitMs = 1000;
let onePage = false;
let margin = { top: "15mm", right: "10mm", bottom: "15mm", left: "10mm" };

for (const arg of args) {
  if (arg.startsWith("--format=")) {
    format = arg.split("=")[1] as PaperFormat;
  } else if (arg === "--landscape") {
    landscape = true;
  } else if (arg.startsWith("--scale=")) {
    scale = parseFloat(arg.split("=")[1]);
    if (isNaN(scale) || scale < 0.1 || scale > 2) {
      console.error("Error: --scale must be a number between 0.1 and 2");
      process.exit(1);
    }
  } else if (arg === "--no-background") {
    printBackground = false;
  } else if (arg.startsWith("--margin=")) {
    const parts = arg.split("=")[1].split(",");
    margin = {
      top:    parts[0]?.trim() ?? "15mm",
      right:  parts[1]?.trim() ?? "10mm",
      bottom: parts[2]?.trim() ?? "15mm",
      left:   parts[3]?.trim() ?? "10mm",
    };
  } else if (arg.startsWith("--wait=")) {
    waitMs = parseInt(arg.split("=")[1], 10);
  } else if (arg === "--one-page") {
    onePage = true;
  } else if (!arg.startsWith("--")) {
    if (!inputPath) {
      inputPath = arg;
    } else {
      outputPath = arg;
    }
  }
}

// ── Validate paths ────────────────────────────────────────────────────────────

if (!inputPath) {
  console.error("Error: No input HTML file specified.");
  process.exit(1);
}

const absInput = path.resolve(inputPath);

if (!fs.existsSync(absInput)) {
  console.error(`Error: Input file not found: ${absInput}`);
  process.exit(1);
}

const absOutput = outputPath
  ? path.resolve(outputPath)
  : absInput.replace(/\.html?$/i, ".pdf");

fs.mkdirSync(path.dirname(absOutput), { recursive: true });

// ── Convert ───────────────────────────────────────────────────────────────────

(async () => {
  const modeLabel = onePage ? "one-page (auto-sized)" : `${format}${landscape ? " landscape" : ""}`;
  console.log(`Input:   ${absInput}`);
  console.log(`Output:  ${absOutput}`);
  console.log(`Mode:    ${modeLabel}, scale=${scale}, printBackground=${printBackground}, wait=${waitMs}ms`);
  console.log("Launching headless Chromium...");

  const browser = await chromium.launch({ headless: true });

  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 900 },
    });

    console.log("Loading HTML...");
    await page.goto(`file://${absInput}`, {
      waitUntil: "networkidle",
      timeout: 30_000,
    });

    if (waitMs > 0) {
      console.log(`Waiting ${waitMs}ms for late-rendering content...`);
      await new Promise((resolve) => setTimeout(resolve, waitMs));
    }

    if (onePage) {
      // Disable CSS page breaks so nothing is forced onto a second page
      await page.addStyleTag({
        content: `
          * {
            page-break-before: auto !important;
            page-break-after:  auto !important;
            page-break-inside: auto !important;
            break-before:      auto !important;
            break-after:       auto !important;
            break-inside:      auto !important;
          }
        `,
      });

      // Measure the full rendered content dimensions
      const dims = await page.evaluate(() => ({
        w: document.documentElement.scrollWidth,
        h: document.documentElement.scrollHeight,
      }));

      // Chromium renders PDF at ~86 DPI (not 96). Use 86 DPI to convert px → mm.
      // Add a generous buffer so content never clips.
      const PDF_DPI = 86;
      const mmPerPx = 25.4 / PDF_DPI;
      const marginH = parseInt(margin.left) + parseInt(margin.right);
      const marginV = parseInt(margin.top) + parseInt(margin.bottom);
      const wMm = Math.ceil(dims.w * mmPerPx) + marginH + 15;
      const hMm = Math.ceil(dims.h * mmPerPx) + marginV + 30;

      console.log(`Content: ${dims.w}×${dims.h}px → page: ${wMm}×${hMm}mm`);

      await page.pdf({
        path: absOutput,
        width:  `${wMm}mm`,
        height: `${hMm}mm`,
        scale,
        printBackground,
        margin,
      });
    } else {
      await page.pdf({
        path: absOutput,
        format,
        landscape,
        scale,
        printBackground,
        margin,
      });
    }

    const stats = fs.statSync(absOutput);
    const sizeKb = (stats.size / 1024).toFixed(1);
    console.log(`\nDone! PDF saved to: ${absOutput} (${sizeKb} KB)`);
  } finally {
    await browser.close();
  }
})().catch((err: Error) => {
  console.error(`\nConversion failed: ${err.message}`);
  if (err.message.includes("Executable doesn't exist")) {
    console.error("\nFix: run `npx playwright install chromium` to download the browser.");
  }
  process.exit(1);
});
