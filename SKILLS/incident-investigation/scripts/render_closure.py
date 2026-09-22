#!/usr/bin/env python3
"""Render an incident closure JSON into the Fluency-branded Tier 3 closure report (self-contained HTML).

Branding is always applied: Fluency header with the logo (embedded as a data URI from
assets/fluency_logo.png by default, or from --logo / the JSON "logo" path, so the file
works when downloaded or emailed), Fluency palette
and Inter type, and a "Powered by Fluency" footer.

    python3 scripts/render_closure.py closure.json -o closure.html [--logo partner_logo.png]

Layout (fixed order; optional blocks are skipped when absent):
    eyebrow · title · lede · verdict card · metadata grid
    grounds (AI-assist claims, each tested)
    timeline          (optional — single-event incidents: raw audit times)
    score_table       (optional — multi-day incidents: activity vs riskScore bars)
    base_rate         (optional — peer census table, within this one account)
    negatives         (what did NOT happen, each against a control)
    callouts          (optional — one per red herring the ticket raised)
    recommendation · footer (date + evidence sources with row counts)

Inline markup allowed in any text field: **bold**, *italic*, `code`. Everything else
is HTML-escaped, so tenant data can be pasted in safely.
See assets/closure_schema.md for the field reference.
"""
import argparse, base64, html, json, os, re, sys

VERDICTS = {
    "benign":    ("Benign",    "var(--ok)"),
    "escalate":  ("Escalate",  "var(--warn)"),
    "confirmed": ("Confirmed", "var(--bad)"),
}

def md(s):
    """Escape, then apply the three inline marks."""
    s = html.escape(str(s if s is not None else ""))
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    return s

def paras(v):
    items = v if isinstance(v, list) else [v]
    return "".join(f"<p>{md(p)}</p>" for p in items if p)

def section(title, body, intro=None):
    intro_html = f'<p class="intro">{md(intro)}</p>' if intro else ""
    return f'<section><h2>{md(title)}</h2><div class="sec-body">{intro_html}{body}</div></section>'

def callout(c):
    return f'<aside class="callout"><h3>{md(c["title"])}</h3>{paras(c["body"])}</aside>'

def render_grounds(g):
    items = "".join(
        f'<li><span class="num">{i}</span><div><blockquote>&ldquo;{md(x["claim"])}&rdquo;</blockquote>'
        f'{paras(x["finding"])}</div></li>'
        for i, x in enumerate(g["items"], 1))
    return section(g.get("title", f"{len(g['items'])} grounds for escalation, tested"),
                   f'<ol class="grounds">{items}</ol>', g.get("intro"))

def render_timeline(t):
    rows = "".join(
        f'<tr class="{"hl" if r.get("highlight") else ""}"><td class="mono">{md(r["time"])}</td>'
        f'<td>{md(r["actor"])}</td><td>{md(r["event"])}</td></tr>' for r in t["rows"])
    table = (f'<div class="scroll"><table class="tl"><thead><tr><th>Time (UTC)</th><th>Actor</th>'
             f'<th>Event</th></tr></thead><tbody>{rows}</tbody></table></div>')
    extra = callout(t["callout"]) if t.get("callout") else ""
    return section(t["title"], table + extra, t.get("intro"))

def bar(v, vmax, hot):
    pct = 0 if not vmax else max(2, round(100 * v / vmax))
    return (f'<div class="bar"><span class="{"hot" if hot else ""}" style="width:{pct}%"></span></div>')

def render_score_table(s):
    a_lab, b_lab = s.get("activity_label", "Admin ops"), s.get("score_label", "riskScore")
    amax = max((r["activity"] for r in s["rows"]), default=0)
    bmax = max((r["score"] for r in s["rows"]), default=0)
    rows = ""
    for r in s["rows"]:
        hot = bool(r.get("incident"))
        tag = '<span class="tag">incident</span>' if hot else ""
        rows += (f'<tr class="{"hl" if hot else ""}"><td class="mono">{md(r["day"])}</td>'
                 f'<td class="n mono">{r["activity"]:,}</td><td class="barcell">{bar(r["activity"], amax, hot)}</td>'
                 f'<td class="n mono">{r["score"]:,}</td><td class="barcell">{bar(r["score"], bmax, hot)}</td>'
                 f'<td class="tagcell">{tag}</td></tr>')
    cap = s.get("caption") or (f"Daily {a_lab.lower()} against the behavior riskScore for the same day. "
                               f"Bars are scaled within each column; column maxima are {amax:,} and {bmax:,}. "
                               f"Shaded rows were raised as incidents.")
    table = (f'<p class="cap">{md(cap)}</p><div class="scroll"><table class="bars"><thead><tr>'
             f'<th>Day</th><th colspan="2">{md(a_lab)}</th><th colspan="2">{md(b_lab)}</th><th></th>'
             f'</tr></thead><tbody>{rows}</tbody></table></div>')
    extra = callout(s["callout"]) if s.get("callout") else ""
    return section(s.get("title", "The score does not follow the activity"), table + extra, s.get("intro"))

def render_base_rate(b):
    cols = b["columns"]
    head = "".join(f'<th class="{"n" if i else ""}">{md(c)}</th>' for i, c in enumerate(cols))
    body = "".join("<tr>" + "".join(
        f'<td class="{"mono" if i == 0 else "n"}">{md(v)}</td>' for i, v in enumerate(r)) + "</tr>"
        for r in b["rows"])
    cap = f'<p class="cap">{md(b["caption"])}</p>' if b.get("caption") else ""
    return section(b["title"], f'{cap}<div class="scroll"><table class="grid"><thead><tr>{head}</tr></thead>'
                               f'<tbody>{body}</tbody></table></div>', b.get("intro"))

def render_negatives(n):
    items = "".join(f'<li><strong>{md(x["title"])}</strong> {md(x.get("body", ""))}</li>' for x in n["items"])
    extra = "".join(callout(c) for c in n.get("callouts", []))
    intro = n.get("intro", "Each negative below was run against a control proving the query finds these "
                           "operations elsewhere on the tenant — a zero from a broken query looks identical "
                           "to a real one.")
    return section(n.get("title", "What did not happen"), f'<ul class="checks">{items}</ul>{extra}', intro)

CSS = r"""
:root{--bg:#ffffff;--panel:#f8f7f4;--ink:#1c1d21;--ink2:#3d4048;--mute:#6b6f78;--rule:#e3e1dc;
--ok:#1d6b56;--warn:#a8641a;--bad:#a9403a;--hot:#a94a3c;--cool:#c5ccd6;--track:#ecebe8;--hl:#f6e9da;--tag:#a86a2a;
--serif:"Source Serif 4",Georgia,"Times New Roman",serif;--sans:"Source Sans 3","Segoe UI",system-ui,-apple-system,sans-serif;
--mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#15161a;--panel:#1d1f24;--ink:#ecebe7;--ink2:#c9c8c3;
--mute:#9a9ca3;--rule:#2f3138;--ok:#4fb393;--warn:#e0a052;--bad:#e27a70;--hot:#d0705f;--cool:#4a5160;--track:#2a2c33;--hl:#3a2d22;--tag:#e0a560}}
:root[data-theme="dark"]{--bg:#15161a;--panel:#1d1f24;--ink:#ecebe7;--ink2:#c9c8c3;--mute:#9a9ca3;--rule:#2f3138;--ok:#4fb393;
--warn:#e0a052;--bad:#e27a70;--hot:#d0705f;--cool:#4a5160;--track:#2a2c33;--hl:#3a2d22;--tag:#e0a560}
*,*::before,*::after{box-sizing:inherit}html{scroll-padding-top:env(safe-area-inset-top,0px)}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 var(--sans)}
main{max-width:960px;margin:0 auto;padding:2.5rem 1.25rem 3rem}
.eyebrow{font:500 .72rem/1 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--mute);margin:0 0 .75rem}
h1{font:700 clamp(2rem,5vw,2.9rem)/1.12 var(--serif);margin:0 0 1rem;max-width:21ch;background:var(--panel);padding:.25rem .5rem;margin-left:-.5rem}
.lede{font:400 1.15rem/1.6 var(--serif);color:var(--ink2);max-width:40rem;margin:0 0 2rem}
.verdict{display:flex;gap:2rem;align-items:flex-start;border:1px solid var(--rule);border-left:5px solid var(--vc);border-radius:4px;padding:1.4rem 1.5rem;margin:0 0 2rem;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.verdict b{font:700 1.7rem/1 var(--serif);color:var(--vc);min-width:7.5rem}.verdict p{margin:0;color:var(--ink2);max-width:28rem;font-size:.95rem}
.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1.1rem 1.5rem;border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);background:var(--panel);padding:1.1rem 0;margin:0 0 2.5rem}
.meta div{padding:0}.meta dt{font:500 .66rem/1 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--mute);margin:0 0 .45rem}
.meta dd{margin:0;font-size:.88rem;overflow-wrap:anywhere}
section{background:var(--panel);margin:0 0 2.25rem;padding:0 0 1.25rem}
h2{font:700 1.35rem/1.3 var(--serif);margin:0;padding:.6rem 0;border-bottom:1px solid var(--rule)}
.sec-body{padding:1rem 0 0}.sec-body>p,.intro{max-width:38rem;color:var(--ink2);font-size:.95rem}
.cap{font-size:.82rem;color:var(--mute);max-width:32rem;margin:.25rem 0 .75rem}
code{font:.85em var(--mono);background:transparent}
ol.grounds{list-style:none;margin:0;padding:0}
ol.grounds li{display:flex;gap:1rem;padding:1.1rem 0;border-top:1px solid var(--rule)}ol.grounds li:first-child{border-top:0}
.num{flex:0 0 1.4rem;height:1.4rem;border-radius:50%;background:var(--hl);color:var(--tag);font:600 .7rem/1.4rem var(--mono);text-align:center;margin-top:.35rem}
blockquote{margin:0 0 .6rem;font:italic 1.1rem/1.4 var(--serif);color:var(--ink2)}
ol.grounds p{margin:.4rem 0;max-width:36rem;font-size:.93rem}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.85rem}
th{font:500 .66rem/1 var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--mute);text-align:left;padding:.6rem .5rem;border-bottom:1px solid var(--rule)}
td{padding:.55rem .5rem;border-bottom:1px solid var(--rule);vertical-align:middle}
.mono{font-family:var(--mono);font-size:.82rem}.n{text-align:right;white-space:nowrap}
tr.hl td{background:var(--hl)}
table.bars td.barcell{width:32%;min-width:120px}.bar{height:9px;background:var(--track);border-radius:1px}
.bar span{display:block;height:100%;background:var(--cool)}.bar span.hot{background:var(--hot)}
.tagcell{width:5.5rem}.tag{font:.68rem var(--mono);color:var(--tag)}
table.grid td:first-child{white-space:nowrap}table.grid th.n{text-align:right}
table.tl td:first-child{white-space:nowrap;width:9rem}
.callout{border:1px solid var(--rule);background:var(--bg);border-radius:4px;padding:1rem 1.2rem;margin:1.25rem 0 0;max-width:36rem;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.callout h3{font:600 .92rem/1.3 var(--sans);margin:0 0 .4rem}.callout p{margin:.3rem 0;font-size:.88rem;color:var(--ink2)}
ul.checks{list-style:none;margin:0;padding:0;max-width:36rem}
ul.checks li{position:relative;padding:.35rem 0 .35rem 1.5rem;font-size:.93rem}
ul.checks li::before{content:"\2713";position:absolute;left:0;color:var(--ok);font-weight:700}
footer{border-top:1px solid var(--rule);padding:.9rem 0;font-size:.78rem;color:var(--mute);background:var(--panel)}
footer span+span{margin-left:1.5rem}
@media print{section,.verdict,.callout,tr{break-inside:avoid}body{font-size:13px}}
@media (max-width:560px){.verdict{flex-direction:column;gap:.6rem}}
"""

# ---- Fluency branding (applied to every closure report) ---------------------------
LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "fluency_logo.png")

LOGO_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".svg": "image/svg+xml", ".webp": "image/webp", ".gif": "image/gif"}

def logo_uri(path=None):
    """Embed the header/footer logo as a data URI. `path` overrides the bundled
    Fluency logo (PNG, JPEG, SVG, WebP or GIF). A missing file is an error, not a
    silent fallback, so a report never ships with the wrong brand."""
    p = path or LOGO_PATH
    mime = LOGO_TYPES.get(os.path.splitext(p)[1].lower())
    if not mime:
        sys.exit(f"logo must be one of {', '.join(sorted(LOGO_TYPES))}: {p}")
    try:
        with open(p, "rb") as fh:
            return f"data:{mime};base64," + base64.b64encode(fh.read()).decode()
    except OSError as e:
        if path:
            sys.exit(f"cannot read logo {p}: {e.strerror}")
        return None

BRAND_CSS = """
:root{--f-red:#c0161c;--f-blue:#2d65a1;--f-navy:#1d2a52;--bg:#eef1f6;--panel:#ffffff;--ink:#141925;--ink2:#4a5163;--mute:#8a92a3;--rule:#e3e6ec;
--ok:#1f9d55;--warn:#e8a01e;--bad:#c0161c;--hot:#c0161c;--cool:#457fc1;--track:#e3e6ec;--hl:#eaf1fa;--tag:#2d65a1;
--serif:"Inter",-apple-system,"Segoe UI",sans-serif;--sans:"Inter",-apple-system,"Segoe UI",sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0e1530;--panel:#16203f;--ink:#eef2fb;--ink2:#cdd7ec;--mute:#93a3c8;--rule:#2a3660;--hl:#1f2d57;--tag:#9fb4e0;--cool:#457fc1}}
:root[data-theme="dark"]{--bg:#0e1530;--panel:#16203f;--ink:#eef2fb;--ink2:#cdd7ec;--mute:#93a3c8;--rule:#2a3660;--hl:#1f2d57;--tag:#9fb4e0;--cool:#457fc1}
.f-hero{background:linear-gradient(135deg,#0e1530 0%,#1d2a52 56%,#2a2552 100%);color:#eef2fb;border-bottom:4px solid var(--f-red)}
.f-hero-in,.f-foot-in{max-width:960px;margin:0 auto;padding:1.1rem 1.25rem;display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap}
.f-logo{background:#fff;border-radius:9px;padding:8px 12px;display:inline-flex;color:#c0161c;font:700 1rem/1 "Inter",sans-serif;text-decoration:none}.f-logo img{height:24px;max-width:160px;display:block}
.f-tag{font:600 .7rem/1 "Inter",sans-serif;letter-spacing:.14em;text-transform:uppercase;color:#cdd7ec;border:1px solid rgba(205,215,236,.4);border-radius:999px;padding:6px 13px}
section{border:1px solid var(--rule);border-radius:10px;padding:0 1.25rem 1.25rem}
h2{border-bottom:2px solid var(--f-blue);color:var(--ink)}
h1{background:none;color:var(--ink);margin-left:0;padding:.1rem 0 .1rem .75rem;border-left:5px solid var(--f-red)}
.eyebrow{color:var(--f-blue);font-weight:700}.meta{border-radius:10px;border:1px solid var(--rule);padding:1.1rem 1.25rem}
.verdict{background:var(--panel);border-radius:10px}.callout{border-radius:10px;border-left:4px solid var(--f-blue)}
footer{border-radius:10px;padding:.9rem 1.25rem}
.f-foot{background:var(--f-navy);color:#93a3c8;font:.78rem/1.4 "Inter",sans-serif}
.f-foot a{color:#cdd7ec;text-decoration:none}.f-foot img{height:18px;background:#fff;border-radius:6px;padding:4px 8px;vertical-align:middle}
@media print{.f-hero,.f-foot{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""

def meta_value(c, label):
    for m in c.get("meta", []):
        if m.get("label", "").lower() == label:
            return html.escape(re.sub(r"[*`]", "", str(m.get("value", ""))))
    return ""

def brand_header(c, logo):
    tenant = meta_value(c, "tenant")
    tag = " · ".join(x for x in ["Confidential", tenant, "Incident Closure"] if x)
    mark = f'<img src="{logo}" alt="Fluency">' if logo else "Fluency"
    return (f'<header class="f-hero"><div class="f-hero-in"><a class="f-logo" href="https://fluencysecurity.com" '
            f'target="_blank" rel="noopener">{mark}</a><span class="f-tag">{tag}</span></div></header>')

def brand_footer(c, logo):
    who = " · ".join(x for x in ["Fluency Incident Closure", meta_value(c, "subject"), meta_value(c, "tenant")] if x)
    mark = f' <img src="{logo}" alt="Fluency">' if logo else ""
    return (f'<div class="f-foot"><div class="f-foot-in"><span>{who}</span><a href="https://fluencysecurity.com" '
            f'target="_blank" rel="noopener">Powered by Fluency{mark}</a></div></div>')

def render(c, logo_path=None):
    label, color = VERDICTS[c["verdict"]["outcome"].lower()]
    meta = "".join(f'<div><dt>{md(m["label"])}</dt><dd>{md(m["value"])}</dd></div>' for m in c["meta"])
    parts = [
        f'<p class="eyebrow">{md(c.get("eyebrow", "Fluency Security · Incident closure · Tier 3 review"))}</p>',
        f'<h1>{md(c["title"])}</h1>',
        f'<p class="lede">{md(c["lede"])}</p>',
        f'<div class="verdict" style="--vc:{color}"><b>{label}</b><p>{md(c["verdict"]["text"])}</p></div>',
        f'<dl class="meta">{meta}</dl>',
        render_grounds(c["grounds"]),
    ]
    if c.get("timeline"):    parts.append(render_timeline(c["timeline"]))
    if c.get("score_table"): parts.append(render_score_table(c["score_table"]))
    if c.get("base_rate"):   parts.append(render_base_rate(c["base_rate"]))
    parts.append(render_negatives(c["negatives"]))
    if c.get("callouts"):
        parts.append("".join(callout(x) for x in c["callouts"]))
    parts.append(section("Recommendation", paras(c["recommendation"])))
    f = c["footer"]
    parts.append(f'<footer><span>{md(f.get("label", "Tier 3 review"))} · {md(f["date"])}</span>'
                 f'<span>Evidence: {md(f["evidence"])}</span></footer>')
    title = html.escape(c["title"])
    logo = logo_uri(logo_path)
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            f'<title>{title}</title>'
            f'<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            f'<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Source+Sans+3:ital,wght@0,400;0,600;1,400&family=Source+Serif+4:ital,wght@0,400;0,700;1,400&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">'
            f'<style>{CSS}{BRAND_CSS}</style></head><body>{brand_header(c, logo)}<main>{"".join(parts)}</main>{brand_footer(c, logo)}</body></html>')

REQUIRED = ["title", "lede", "verdict", "meta", "grounds", "negatives", "recommendation", "footer"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("closure_json")
    ap.add_argument("-o", "--out", default="-")
    ap.add_argument("--logo", help="image to use instead of assets/fluency_logo.png "
                    "(overrides a \"logo\" path in the closure JSON)")
    a = ap.parse_args()
    c = json.load(open(a.closure_json))
    logo_path = a.logo
    if not logo_path and c.get("logo"):
        # a relative "logo" in the JSON resolves against the JSON file's own folder
        logo_path = os.path.join(os.path.dirname(os.path.abspath(a.closure_json)), c["logo"])
    missing = [k for k in REQUIRED if not c.get(k)]
    if missing:
        sys.exit(f"closure JSON missing required field(s): {', '.join(missing)}")
    if c["verdict"]["outcome"].lower() not in VERDICTS:
        sys.exit("verdict.outcome must be benign, escalate or confirmed")
    out = render(c, logo_path)
    (sys.stdout.write(out) if a.out == "-" else open(a.out, "w").write(out))

if __name__ == "__main__":
    main()
