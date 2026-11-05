#!/usr/bin/env python3
"""Fluency report component gallery: the source of truth for every chart, table and component in a Fluency report.

Every entry below is a real call into fluency_brand; the gallery prints the exact call next to what it renders, so the
picture and the code can never drift apart. Add a component to fluency_brand.py, add an entry here, regenerate.

  python3 chart_gallery.py [OUT_DIR]        writes chart_gallery.html and chart_gallery.pdf (default: ../assets next to this script)
"""
import os, sys, html
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fluency_brand as fb  # noqa: E402

DAYS = ["10-%02d" % d for d in range(1, 15)]
WEEK = ["W40", "W41", "W42", "W43", "W44", "W45"]

# (group, name, when to use, call). `call` is a Python expression evaluated with fb in scope.
ENTRIES = [
 # ---- charts: columns
 ("Charts", "Column chart", "One measure over time or across categories. One series is blue. Values print above columns when there are 16 or fewer.",
  'fb.column_chart(DAYS[:10], [412, 380, 455, 390, 520, 610, 585, 540, 498, 470], y_label="Sign-ins per day")'),
 ("Charts", "Column chart with a gap day", "A day with no data is a hatched gap (None), never a zero column. Use it for every per-day series from an archive.",
  'fb.column_chart(DAYS, [("Admin operations", [4, 14, 3, None, None, 6, 5, 4, 79, 22, 7, 5, None, 9])], show_values=False, y_label="Admin operations per day")'),
 ("Charts", "Grouped columns", "Compare two to four categories over the same x axis. Series run black, blue, gray, amber, red.",
  'fb.column_chart(WEEK, [("Success", [120, 132, 101, 134, 190, 130]), ("Failed", [14, 22, 9, 31, 12, 18])], mode="group")'),
 ("Charts", "Stacked columns", "A total split by status; the total prints above each column. Pass colors= to give the parts meaning (blue ok, red failed).",
  'fb.column_chart(WEEK, [("Successful", [120, 132, 101, 134, 190, 130]), ("Failed", [14, 22, 9, 31, 12, 18])], mode="stack", colors=["#175d9a", "#b3242e"])'),
 ("Charts", "Stacked columns by severity", "Findings per day by band. Low blue, Medium amber, High red.",
  'fb.column_chart(DAYS[:10], [("Low", [5, 7, 3, 8, 4, 6, 9, 5, 4, 6]), ("Medium", [3, 2, 6, 4, 5, 2, 3, 7, 4, 3]), ("High", [1, 0, 2, 1, 0, 3, 1, 2, 0, 1])], mode="stack", colors=["#175d9a", "#a06c00", "#b3242e"], show_values=False)'),
 # ---- charts: horizontal bars
 ("Charts", "Bar rows", "A ranked list: the leading bar is blue, the rest gray. Use for top-N and distributions.",
  'fb.bar_rows([("Global Administrator", 8), ("Application Administrator", 2), ("SharePoint Administrator", 2), ("Exchange Administrator", 1)])'),
 ("Charts", "Bar rows with meaning", "A third element colours one bar by meaning (red critical, amber review); a fourth replaces the printed value.",
  'fb.bar_rows([("Needs action", 14, "#b3242e", "14 \\u00b7 3.7%"), ("Watch", 31, "#a06c00", "31 \\u00b7 8.2%"), ("Healthy", 335, None, "335 \\u00b7 88.2%")])'),
 ("Charts", "Grouped bars", "Two measures per row, for example sent and received by host.",
  'fb.bars_multi(["web-01", "web-02", "db-01", "vpn-gw"], [("Sent", [40, 32, 18, 55]), ("Received", [22, 25, 60, 30])], mode="group")'),
 ("Charts", "Stacked bars", "A total per row split by status.",
  'fb.bars_multi(["web-01", "web-02", "db-01", "vpn-gw"], [("Allowed", [40, 32, 18, 55]), ("Denied", [6, 9, 2, 14])], mode="stack", colors=["#175d9a", "#b3242e"])'),
 # ---- charts: other
 ("Charts", "Line chart", "A time series where the shape matters more than each value. Up to six series.",
  'fb.line_chart(DAYS, [("Sign-ins", [412, 380, 455, 390, 520, 610, 585, 540, 498, 470, 455, 430, 500, 520]), ("Failed", [31, 22, 40, 28, 52, 70, 66, 43, 38, 36, 30, 27, 41, 45])])'),
 ("Charts", "Scatter plot", "Two measures per item, optionally grouped. Example: exploitable CVEs against days since last seen.",
  'fb.scatter({"Windows": [(2, 3), (9, 5), (14, 8), (30, 11), (45, 14), (60, 22)], "Linux": [(1, 1), (4, 2), (12, 4), (33, 6), (51, 8)]}, x_label="Days since last seen", y_label="Exploitable CVEs")'),
 ("Charts", "Heatmap", "Two-dimensional counts (day by hour, user by application). tone: blue, gray, red or amber.",
  'fb.heatmap(["Mon", "Tue", "Wed", "Thu", "Fri"], ["00", "04", "08", "12", "16", "20"], [[0, 2, 30, 44, 38, 5], [1, 3, 41, 52, 47, 6], [0, 2, 36, 49, 40, 9], [2, 4, 33, 41, 35, 3], [0, 1, 20, 28, 19, 2]], tone="blue", row_header="Day / hour")'),
 ("Charts", "Risk matrix", "A labelled two-axis grid with banded fills (likelihood by impact). level() returns 0 to 3.",
  'fb.matrix_grid({(5, 4): "R3", (4, 4): "R1 R7", (3, 3): "R2", (2, 2): "R5", (1, 3): "R4"}, level=lambda L, I: 3 if L * I >= 18 else 2 if L * I >= 11 else 1 if L * I >= 6 else 0, row_title="LIKELIHOOD 1 \\u2192 5", col_title="IMPACT 1 \\u2192 5")'),
 ("Charts", "Donut", "Part to whole with up to five parts. Use palette colours only.",
  'fb.donut([("Onboarded", 380, "#111111"), ("Can be onboarded", 25, "#175d9a"), ("Unsupported", 5, "#8a8a8a")], center_big="410", center_cap="devices")'),
 ("Charts", "Segment bar", "One proportional strip with a legend, for coverage splits where a donut is too heavy.",
  'fb.segment_bar([("Onboarded", 380), ("Can be onboarded", 25), ("Insufficient information", 10), ("Unsupported", 5)])'),
 ("Charts", "Part-to-whole bar", "Two-way split, for example MFA coverage.",
  'fb.stack_bar(54.6, "331 with MFA", "275 password only")'),
 ("Charts", "Gauge", "A single score out of a maximum, with one line of interpretation.",
  'fb.gauge(72, label="score", heading="Posture score", text="Above the 60 baseline; MFA coverage is the main gap.")'),
 ("Charts", "Sparkline", "A tiny trend for a table cell or KPI.",
  'fb.sparkline([3, 5, 4, 9, 12, 10, 14])'),
 # ---- tables
 ("Tables", "Data table", "Mono caps header over a black rule, thin gray row rules, right-aligned mono numbers, a bold total row and a footnote. Cells are escaped unless their column is in raw_cols.",
  'fb.table(["Account", "Roles held", "Primary roles (top 2)"], [["admin-a", "2", "Global Administrator \\u00b7 SharePoint Administrator"], ["admin-b", "10", "AI Administrator \\u00b7 Exchange Administrator " + fb.tag("10 roles", "red")], ["Total", "12", ""]], widths=["22%", "14%", "64%"], num_cols=(1,), raw_cols=(2,), total_last=True, foot="Account labels are placeholders. Role counts are exact.")'),
 ("Tables", "Table with severity bars", "row_class() puts a coloured bar on the first cell: sev-high (red), sev-med (amber), sev-low (blue).",
  'fb.table(["Host", "Status", "Why"], [["WS-016", fb.tag("Needs action", "red"), "stale; exploitable CVE"], ["WS-021", fb.tag("Watch", "amber"), "silent 10 days"], ["WS-030", fb.tag("Healthy", "o-blue"), "none"]], num_cols=(), raw_cols=(1,), row_class=lambda r: "sev-high" if "Needs action" in r[1] else "sev-med" if "Watch" in r[1] else "sev-low")'),
 ("Tables", "Table with sparkline", "A trend in the last column.",
  'fb.table(["Application", "Events", "14-day trend"], [["Exchange", "11,746", fb.sparkline([3, 5, 4, 9, 12, 10, 14])], ["Teams", "330", fb.sparkline([9, 8, 7, 5, 4, 3, 3], color="#b3242e")]], num_cols=(1,), raw_cols=(2,))'),
 # ---- components
 ("Components", "KPI strip", "Four or five cells: big mono number, mono caps label, optional status tag. Colour a number only when it is the finding.",
  'fb.kpi_strip([fb.kpi("Active accounts", 606), fb.kpi("MFA coverage", "54.6%", color="red", tag=fb.tag("275 without MFA", "red")), fb.kpi("Global admins", 8, tag=fb.tag("Baseline \\u2264 2", "blue")), fb.kpi("OAuth-app reach", "100%", tag=fb.tag("Review consent", "amber")), fb.kpi("Audit tests clean", "3 / 5", tag=fb.tag("No action", "o-blue"))])'),
 ("Components", "Three-column band", "What is exposed, what is already right, what to fix first.",
  'fb.band([("01 \\u2014 What is exposed", "275 active accounts sign in with a password only."), ("02 \\u2014 What is already right", "No phishable MFA factors."), ("03 \\u2014 What to fix first", "Cut Global Administrators to two named accounts.")])'),
 ("Components", "Callouts", "Gray box with a coloured left border: good (blue), watch (amber), act (red).",
  'fb.callouts([fb.callout("good", "Reading note", "Read the MFA figure with two caveats", "Zero weak-factor findings does not prove that Conditional Access enforces MFA at sign-in."), fb.callout("watch", "Review", "Consent is broad", "Every user can consent to third-party apps."), fb.callout("act", "Act", "Global admins above baseline", "Eight accounts hold Global Administrator; the baseline is two.")])'),
 ("Components", "Net read", "The one black box per report, at the end of the executive summary.",
  'fb.netread("Net read", "Where MFA exists it is strong; the gap is coverage, not quality.")'),
 ("Components", "Status tags", "Filled red or blue for a problem or baseline, outlined amber for review, o-blue for clean, gray for unknown. Priority tags p1 red, p2 amber, p3 gray.",
  'fb.tag("275 without MFA", "red") + " " + fb.tag("Baseline", "blue") + " " + fb.tag("Review", "amber") + " " + fb.tag("Clean", "o-blue") + " " + fb.tag("Unknown", "gray") + " " + fb.priority("P1") + " " + fb.priority("P2") + " " + fb.priority("P3")'),
 ("Components", "Panel", "A titled block for charts that sit side by side (col is the grid span out of 12).",
  'fb.panel("Alerts by severity", fb.bar_rows([("High", 3, "#b3242e"), ("Medium", 9, "#a06c00"), ("Low", 21)]), col=12, subtitle="Last 30 days")'),
 ("Components", "Recommended actions", "P1 this week, P2 within 14 days, P3 quarterly.",
  'fb.next_steps([("This week \\u2014 admins", "Cut Global Administrators to two named accounts with break-glass.", "P1"), ("Within 14 days \\u2014 MFA", "Enforce MFA through Conditional Access.", "P2"), ("Quarterly \\u2014 hygiene", "Review guest lifecycle.", "P3")])'),
 ("Components", "Methodology", "Source, window, how figures were derived, limits.",
  'fb.methodology("<p>Read-only configuration snapshot taken 05 Nov 2026. Counts are exact; percentages are rounded to one decimal.</p>")'),
]


def render_entry(group, name, when, call):
    ns = {"fb": fb, "DAYS": DAYS, "WEEK": WEEK}
    out = eval(call, ns)
    code = html.escape(call.replace("\\u00b7", "·").replace("\\u2192", "→").replace("\\u2014", "—").replace("\\u2264", "≤"))
    return ('<div style="break-inside:avoid;margin:0 0 26px"><h3>%s</h3><p class="fn" style="margin:0 0 6px">%s</p>%s'
            '<pre style="margin:8px 0 0;padding:8px 10px;border-left:2px solid #d8d8d8;background:#f6f6f6;font:400 9.5px/1.45 var(--mono);color:#444;white-space:pre-wrap;word-break:break-word">%s</pre></div>'
            % (html.escape(name), html.escape(when), out, code))


def build(out_dir):
    body, n, last = [], 1, None
    for group, name, when, call in ENTRIES:
        if group != last:
            n += 1
            last = group
            body.append(fb.section(n, {"Charts": "Charts", "Tables": "Tables", "Components": "Components"}[group]))
        body.append(render_entry(group, name, when, call))
    rules = ('<ul style="margin:8px 0 0 18px;padding:0"><li>Use only these helpers. Do not hand-write SVG, Chart.js or inline bar markup in a report script.</li>'
             '<li>Palette: ink #111, text #242424, gray #777, rules #d8d8d8, red #b3242e, blue #175d9a, amber #a06c00. Colour carries meaning, never decoration.</li>'
             '<li>Every chart gets a one-line gray footnote saying what it shows. A day or bucket with no data is a hatched gap, never zero.</li>'
             '<li>To add a component: write it in fluency_brand.py, add an entry to ENTRIES in chart_gallery.py, regenerate this file.</li></ul>')
    doc = fb.page("Fluency report component gallery", "Chart and component gallery", body=fb.section(1, "Rules", rules) + "".join(body),
                  subtitle="Every chart, table and component a Fluency report may use, each shown with the exact helper call that draws it. This page is generated from fluency_brand.py and is the source of truth.",
                  meta="fluency-report skill · scripts/fluency_brand.py · %d components" % len(ENTRIES),
                  )
    os.makedirs(out_dir, exist_ok=True)
    hp, pp = os.path.join(out_dir, "chart_gallery.html"), os.path.join(out_dir, "chart_gallery.pdf")
    open(hp, "w", encoding="utf-8").write(doc)
    try:
        fb.to_pdf(hp, pp)
    except Exception as e:  # PDF needs Playwright/Chromium; the HTML is still written
        print("PDF step skipped (%s)" % e)
    return hp, pp


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(HERE), "assets")
    for p in build(out):
        print(p)
