#!/usr/bin/env node
// Render a Fluency report HTML to a US Letter PDF that matches the on-screen report.
// Uses the page's own CSS (brand.css @page / @media print rules), emulates print media,
// keeps backgrounds. Branded (editorial) reports carry their own brandline and closing footer line,
// so no paged footer is added; unbranded legacy HTML still gets "Page X of Y".
//
// Usage: node render_pdf.mjs --input report.html --output report.pdf [--title "Report Title"]
//                            [--chrome /path/to/chrome] [--landscape] [--a4]
// Needs Playwright (npm i playwright, or a global install). Chromium is found automatically
// (CHROME_PATH, common install paths, else Playwright's own download).
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { execSync } from "node:child_process";

const args = process.argv.slice(2);
const take = (flag, hasValue = true) => {
  const i = args.indexOf(flag);
  if (i === -1) return null;
  if (!hasValue) { args.splice(i, 1); return true; }
  const v = args[i + 1];
  args.splice(i, 2);
  return v;
};

const input = take("--input") || args[0];
const output = take("--output") || args[1];
const explicitTitle = take("--title");
const chromeArg = take("--chrome");
const landscape = !!take("--landscape", false);
const a4 = !!take("--a4", false);
take("--letter", false);   // accepted for old scripts; Letter is the default

if (!input || !output) {
  console.error('Usage: render_pdf.mjs --input report.html --output report.pdf [--title "Title"] [--chrome PATH] [--landscape] [--a4]');
  process.exit(2);
}

const inputPath = path.resolve(input);
const outputPath = path.resolve(output);
const html = fs.readFileSync(inputPath, "utf8");
const branded = /name=["']fluency-brand["']/.test(html);
const fullBleed = /name=["']fluency-pdf["']\s+content=["']full-bleed["']/.test(html);   // cover/sheet template: own page chrome, no page margin or paged footer
const rawTitle = explicitTitle || html.match(/<title>([^<]+)<\/title>/i)?.[1]?.trim() || "Report";
const title = rawTitle.replace(/\s*·\s*Fluency Report$/i, "");

const esc = (s) => s.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");

function findChrome() {
  return [
    chromeArg, process.env.CHROME_PATH,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  ].find((p) => p && fs.existsSync(p)) || null;
}

function loadPlaywright() {
  const require = createRequire(import.meta.url);
  const roots = [process.cwd(), path.dirname(inputPath), path.dirname(new URL(import.meta.url).pathname)];
  try { roots.push(execSync("npm root -g", { stdio: ["ignore", "pipe", "ignore"] }).toString().trim()); } catch { /* npm absent */ }
  for (const name of ["playwright", "playwright-core"]) {
    for (const root of roots) {
      for (const base of [path.join(root, "node_modules"), root]) {
        try { return require(path.join(base, name)); } catch { /* next */ }
      }
    }
    try { return require(name); } catch { /* next */ }
  }
  throw new Error("Could not load Playwright. Run `npm install playwright` in the working directory (or install it globally).");
}

const { chromium } = loadPlaywright();
const executablePath = findChrome();
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });

try {
  const page = await browser.newPage({ viewport: { width: 816, height: 1056 }, deviceScaleFactor: 1 });
  await page.goto(`file://${inputPath}`, { waitUntil: "networkidle" });
  await page.emulateMedia({ media: "print" });
  await page.evaluate(() => (document.fonts && document.fonts.ready) || null);

  const footer = `
    <div style="width:100%;padding:0 ${branded ? "30px" : "12mm"};font-family:Arial,Helvetica,sans-serif;font-size:8.5px;color:#8a92a3;display:flex;justify-content:space-between;align-items:center;-webkit-print-color-adjust:exact;">
      <span><b style="color:#c0161c;font-weight:700">Fluency</b>&nbsp;·&nbsp;${esc(title)}</span>
      <span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span>
    </div>`;

  await page.pdf({
    path: outputPath,
    format: a4 ? "A4" : "Letter",
    landscape,
    printBackground: true,
    preferCSSPageSize: (branded || fullBleed) && !a4 && !landscape,   // branded docs: honour @page { size:Letter; margin… } from brand.css
    displayHeaderFooter: !(fullBleed || branded),
    headerTemplate: "<div></div>",
    footerTemplate: footer,
    margin: fullBleed ? { top: "0", right: "0", bottom: "0", left: "0" } : branded ? { top: "15mm", right: "0", bottom: "15mm", left: "0" } : { top: "14mm", right: "12mm", bottom: "16mm", left: "12mm" },
  });
} finally {
  await browser.close();
}

console.log(outputPath);
