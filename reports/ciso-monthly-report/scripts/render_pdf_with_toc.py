#!/usr/bin/env python3
"""Render the CISO report to PDF with a working table of contents.

    python3 render_pdf_with_toc.py --html report.html --pdf report.pdf [--renderer <fluency-report>/scripts/render_pdf.mjs]

1. Renders the HTML with the fluency-report renderer (render_pdf.mjs).
2. Finds the PDF page each contents entry (chapter, section, appendix part) starts on and writes the page numbers
   into the contents page of the HTML (in place), then renders again until the numbers no longer move.
3. Rewrites the contents links as explicit page links. Chromium writes internal links as named destinations,
   which macOS Preview and several other viewers do not follow; explicit page links work everywhere.
4. Adds a bookmark outline (Contents, chapters, sections, appendix parts) for the viewer's sidebar.

Needs Node with Playwright (for render_pdf.mjs) and PyMuPDF (`pip install pymupdf`).
"""
import argparse, glob, html, json, os, re, subprocess, sys, tempfile, warnings

warnings.filterwarnings("ignore")
try:
    import pymupdf as fz
except ImportError:
    try:
        import fitz as fz
    except ImportError:
        sys.exit("PyMuPDF is required for the contents page numbers and links: pip install pymupdf")

ENTRY = re.compile(r'<li class="(t-ch|t-s)"><a href="#([^"]+)"><span class="t-n">(.*?)</span><span class="t-t">(.*?)</span><span class="t-p">[^<]*</span></a></li>')


def find_renderer(given):
    if given:
        return given
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(os.environ.get("FLUENCY_BRAND_DIR", ""), "render_pdf.mjs")]
    up = here
    for _ in range(5):
        up = os.path.dirname(up)
        cands.append(os.path.join(up, "fluency-report", "scripts", "render_pdf.mjs"))
        cands.append(os.path.join(up, "SKILLS", "fluency-report", "scripts", "render_pdf.mjs"))
    home = os.path.expanduser("~")
    cands += glob.glob(os.path.join(home, ".claude", "skills", "**", "fluency-report", "scripts", "render_pdf.mjs"), recursive=True)
    for c in cands:
        if c and os.path.exists(c):
            return c
    sys.exit("render_pdf.mjs not found: install the fluency-report skill, set FLUENCY_BRAND_DIR, or pass --renderer")


def render(renderer, src, out):
    r = subprocess.run(["node", renderer, "--input", src, "--output", out], capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        sys.exit("render_pdf.mjs failed: %s" % (r.stderr or r.stdout).strip()[-800:])


def norm(t):
    return re.sub(r"\s+", " ", html.unescape(t)).strip().lower()


def entries(doc):
    out = []
    for cls, aid, num, raw in ENTRY.findall(doc):
        text = html.unescape(re.sub("<[^>]+>", "", raw)).strip()
        title, n = norm(text), html.unescape(num)
        if aid.startswith("ch-"):
            key, label = "%s %s" % (norm(n), title), "%s — %s" % (n, text)
        elif aid.startswith("ap-"):
            key, label = "%s. %s" % (n.lower(), title), "%s. %s" % (n, text)
        else:
            key, label = "%s %s" % (n, title), "%s %s" % (n, text)
        out.append({"id": aid, "level": 1 if cls == "t-ch" else 2, "key": key, "title": title, "text": text, "label": label})
    return out


def contents_page(pdf):
    """The contents page: the page carrying the most internal links (named destinations or page links)."""
    counts = [(sum(1 for l in p.get_links() if l.get("kind") in (fz.LINK_NAMED, fz.LINK_GOTO)), p.number) for p in pdf]
    best = max(counts)
    return best[1] if best[0] else 1


def locate(pdf, ents):
    """First page, after the contents, where each entry's heading appears; searched in document order."""
    texts = [norm(p.get_text()) for p in pdf]
    start = contents_page(pdf) + 1
    found, cur = {}, start
    for e in ents:
        for k in range(cur, len(texts)):
            if e["key"] in texts[k]:
                found[e["id"]] = k
                cur = k
                break
        else:
            for k in range(cur, len(texts)):  # fall back to the bare title
                if e["title"] in texts[k]:
                    found[e["id"]] = k
                    cur = k
                    break
    return found


def write_pages(doc, found):
    def sub(m):
        cls, aid = m.group(1), m.group(2)
        pg = str(found[aid] + 1) if aid in found else ""
        return re.sub(r'<span class="t-p">[^<]*</span>', '<span class="t-p">%s</span>' % pg, m.group(0))
    return ENTRY.sub(sub, doc)


def target(page, e):
    hits = page.search_for(e["text"])
    return fz.Point(0, max(hits[0].y0 - 14, 0)) if hits else fz.Point(0, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True, help="report HTML from build_report.py; its contents page numbers are filled in place")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--renderer")
    a = ap.parse_args()
    renderer = find_renderer(a.renderer)
    with open(a.html) as f:
        doc = f.read()
    ents = entries(doc)
    if not ents:
        sys.exit("no contents page in %s: rebuild it with build_report.py" % a.html)
    tmp = tempfile.mkdtemp()
    found = {}
    for attempt in range(3):  # page numbers can push a heading to the next page; stop when stable
        doc = write_pages(doc, found)
        with open(a.html, "w") as f:
            f.write(doc)
        out = os.path.join(tmp, "pass%d.pdf" % attempt)
        render(renderer, a.html, out)
        pdf = fz.open(out)
        new = locate(pdf, ents)
        if new == found:
            break
        found = new
        pdf.close()
    missing = [e["id"] for e in ents if e["id"] not in found]
    by_id = {e["id"]: e for e in ents}
    fixed = 0
    for page in pdf:
        for l in page.get_links():
            dest = l.get("nameddest") or ""
            if dest in found:
                pno = found[dest]
                page.delete_link(l)
                page.insert_link({"kind": fz.LINK_GOTO, "from": l["from"], "page": pno, "to": target(pdf[pno], by_id[dest]), "zoom": 0})
                fixed += 1
    toc_pg = contents_page(pdf)
    outline = [[1, "Contents", toc_pg + 1, {"kind": fz.LINK_GOTO, "page": toc_pg, "to": fz.Point(0, 0), "zoom": 0}]]
    for e in ents:
        if e["id"] in found:
            pno = found[e["id"]]
            outline.append([e["level"], e["label"], pno + 1, {"kind": fz.LINK_GOTO, "page": pno, "to": target(pdf[pno], e), "zoom": 0}])
    pdf.set_toc(outline)
    pdf.save(a.pdf, garbage=3, deflate=True)
    print("wrote %s | %d pages, %d contents entries, %d links made explicit, %d bookmarks" % (a.pdf, len(pdf), len(ents), fixed, len(outline)))
    if missing:
        print("WARNING: no page found for %s; their contents links were left as rendered" % ", ".join(missing))


if __name__ == "__main__":
    main()
