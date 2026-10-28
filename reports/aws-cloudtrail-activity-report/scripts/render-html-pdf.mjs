#!/usr/bin/env node
// Render a self-contained HTML report to a Letter PDF with a per-page footer:
// report title on the left, "X of Y" on the right.
//
// Usage: node render-html-pdf.mjs --input report.html --output report.pdf [--title "Report Title"] [--chrome /path/to/chrome]
// Needs Playwright (npm i playwright, or a global install) and a Chrome/Chromium binary.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { execSync } from "node:child_process";

const args = process.argv.slice(2);

function take(flag) {
  const index = args.indexOf(flag);
  if (index === -1) return null;
  const value = args[index + 1];
  args.splice(index, 2);
  return value;
}

const input = take("--input") || args[0];
const output = take("--output") || args[1];
const explicitTitle = take("--title");
const chromeArg = take("--chrome");

if (!input || !output) {
  console.error('Usage: render-html-pdf.mjs --input report.html --output report.pdf [--title "Report Title"] [--chrome PATH]');
  process.exit(2);
}

const inputPath = path.resolve(input);
const outputPath = path.resolve(output);
const html = fs.readFileSync(inputPath, "utf8");
const title = explicitTitle || html.match(/<title>([^<]+)<\/title>/i)?.[1]?.trim() || "Report";

function findChrome() {
  const candidates = [
    chromeArg,
    process.env.CHROME_PATH,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  ];
  return candidates.find((p) => p && fs.existsSync(p)) || null;
}

function loadPlaywright() {
  const require = createRequire(import.meta.url);
  const roots = [process.cwd(), path.dirname(inputPath)];
  try {
    roots.push(execSync("npm root -g", { stdio: ["ignore", "pipe", "ignore"] }).toString().trim());
  } catch {
    // npm not on PATH; the local lookups below still apply.
  }
  for (const name of ["playwright", "playwright-core"]) {
    for (const root of roots) {
      for (const base of [path.join(root, "node_modules"), root]) {
        try {
          return require(path.join(base, name));
        } catch {
          // Try the next location.
        }
      }
    }
    try {
      return require(name);
    } catch {
      // Try the next package name.
    }
  }
  throw new Error("Could not load Playwright. Run `npm install playwright` in the working directory (or install it globally).");
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

const { chromium } = loadPlaywright();
const footerTitle = escapeHtml(title);
const executablePath = findChrome();

const browser = await chromium.launch({
  headless: true,
  ...(executablePath ? { executablePath } : {}),
});

try {
  const page = await browser.newPage({
    viewport: { width: 1280, height: 1600 },
    deviceScaleFactor: 1,
  });
  await page.goto(`file://${inputPath}`, { waitUntil: "networkidle" });
  await page.emulateMedia({ media: "print" });
  await page.pdf({
    path: outputPath,
    format: "Letter",
    printBackground: true,
    displayHeaderFooter: true,
    headerTemplate: "<div></div>",
    footerTemplate: `
      <div style="width:100%; padding:0 0.7in; font-family:Inter,Arial,sans-serif; font-size:9px; color:#5b6776; display:flex; justify-content:space-between;">
        <span>${footerTitle}</span>
        <span><span class="pageNumber"></span> of <span class="totalPages"></span></span>
      </div>
    `,
    margin: {
      top: "0.65in",
      right: "0.7in",
      bottom: "0.62in",
      left: "0.7in",
    },
  });
} finally {
  await browser.close();
}

console.log(outputPath);
