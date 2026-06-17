#!/usr/bin/env python3
"""
build_report.py — O365 User Investigation report builder.

Reads three Fluency FPL report result JSON files, extracts events, builds
an SVG activity timeline and HTML data tables, then fills report_template.html
with all the computed content.

Usage:
    python3 build_report.py \
        --username user@domain.com \
        --from-ms  1746057600000 \
        --to-ms    1746316800000 \
        --signin       /tmp/o365inv_signin.json \
        --dir-init     /tmp/o365inv_dir_init.json \
        --dir-target   /tmp/o365inv_dir_target.json \
        --template     /path/to/assets/report_template.html \
        --output       /tmp/o365inv_out/o365_investigation.html
"""

import argparse
import json
import sys
import html
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Baked-in FPL projection overrides
#
# These are the recommended minimal-column FPL scripts to pass as the `fpl`
# parameter when calling run_report.  Using them keeps result payloads small
# and consistent, avoiding the "Output too large" truncation that occurs with
# the full 30-40 column default projections.
#
# Usage in the skill (Step 3 of SKILL.md):
#
#   run_report(name="GetUserSigninHistory", fpl=FPL_SIGNIN, ...)
#   run_report(name="GetDirectoryChangesInitiatedByUser", fpl=FPL_DIR_INIT, ...)
#   run_report(name="GetDirectoryChangesTargetingUser",   fpl=FPL_DIR_TARGET, ...)
#
# ─────────────────────────────────────────────────────────────────────────────

FPL_SIGNIN = """\
function main({from="ago(1d)", to="now()", username=""}) {
   let rangeFrom = timeConvert(from)
   let rangeTo = timeConvert(to)
   let text=`let UserEmail = tolower("{{ .username }}");
let StartTime = {{ .rangeFrom }};
let EndTime = {{ .rangeTo }};
AzureSigninLogs
| where TimeGenerated between (StartTime .. EndTime)
| where tolower(UserPrincipalName) == UserEmail
| extend
    ResultStatus = iff(ResultType == "0", "Success", "Failure"),
    ErrorCode = tostring(Status.errorCode),
    FailureReason = tostring(Status.failureReason),
    Country = tostring(Location),
    City = tostring(LocationDetails.city),
    State = tostring(LocationDetails.state),
    OS = tostring(DeviceDetail.operatingSystem),
    Browser = tostring(DeviceDetail.browser)
| project TimeGenerated, UserPrincipalName, AppDisplayName, ResourceDisplayName,
    IPAddress, Country, State, City, IsInteractive, ClientAppUsed,
    OS, Browser, ConditionalAccessStatus, ResultStatus, ErrorCode, FailureReason,
    RiskLevelDuringSignIn, RiskState
| order by TimeGenerated desc`
   let renderTemplate = template(text,{rangeFrom, rangeTo, username})
   let t = kql(renderTemplate)
   return {t}
}
function timeConvert(t) {
   if contains(t, "(") { return t } else { return sprintf("unixtime_milliseconds_todatetime(%s)",t) }
}
"""

FPL_DIR_INIT = """\
function main({from="ago(1d)", to="now()", username=""}) {
   let rangeFrom = timeConvert(from)
   let rangeTo = timeConvert(to)
   let text=`
let UserEmail = tolower("{{ .username }}");
let StartTime = {{ .rangeFrom }};
let EndTime = {{ .rangeTo }};
AzureAuditLogs
| where TimeGenerated between (StartTime .. EndTime)
| where ActivityDisplayName has_any (
    "Add member to group", "Remove member from group",
    "Add owner to group", "Remove owner from group",
    "Add member to role", "Remove member from role",
    "Add eligible member to role", "Remove eligible member from role",
    "Add app role assignment", "Remove app role assignment"
)
| extend
    InitiatedByUserUPN = tolower(tostring(InitiatedBy.user.userPrincipalName)),
    InitiatedByAppName = tostring(InitiatedBy.app.displayName)
| mv-expand TargetResource = TargetResources
| extend
    TargetName = tostring(TargetResource.displayName),
    TargetUPN  = tolower(tostring(TargetResource.userPrincipalName))
| where InitiatedByUserUPN == UserEmail
| project TimeGenerated, ActivityDisplayName, Result, InitiatedByUserUPN, InitiatedByAppName, TargetName, TargetUPN, CorrelationId
| order by TimeGenerated desc`
    let renderTemplate = template(text,{rangeFrom, rangeTo, username})
    printf("%s", renderTemplate)
    let t = kql(renderTemplate)
    return {t}
}
function timeConvert(t) {
   if contains(t, "(") { return t } else { return sprintf("unixtime_milliseconds_todatetime(%s)",t) }
}
"""

FPL_DIR_TARGET = """\
function main({from="ago(1d)", to="now()", username=""}) {
   let rangeFrom = timeConvert(from)
   let rangeTo = timeConvert(to)
   let text=`
let UserEmail = tolower("{{ .username }}");
let StartTime = {{ .rangeFrom }};
let EndTime = {{ .rangeTo }};
AzureAuditLogs
| where TimeGenerated between (StartTime .. EndTime)
| where ActivityDisplayName has_any (
    "Add member to group", "Remove member from group",
    "Add owner to group", "Remove owner from group",
    "Add member to role", "Remove member from role",
    "Add eligible member to role", "Remove eligible member from role",
    "Add app role assignment", "Remove app role assignment",
    "Add app role assignment grant to user", "Remove app role assignment grant from user"
)
| extend
    InitiatedByUserUPN = tolower(tostring(InitiatedBy.user.userPrincipalName)),
    InitiatedByUserId = tostring(InitiatedBy.user.id),
    InitiatedByAppName = tostring(InitiatedBy.app.displayName),
    InitiatedByServicePrincipalId = tostring(InitiatedBy.app.servicePrincipalId)
| mv-expand TargetResource = TargetResources
| extend
    TargetType = tostring(TargetResource.type),
    TargetId = tostring(TargetResource.id),
    TargetName = tostring(TargetResource.displayName),
    TargetUPN = tolower(tostring(TargetResource.userPrincipalName)),
    TargetText = tolower(tostring(TargetResource)),
    ModifiedProperties = TargetResource.modifiedProperties
| where TargetUPN == UserEmail or TargetText has UserEmail
| project TimeGenerated, ActivityDisplayName, Result, ResultReason,
    TargetType, TargetName, TargetUPN,
    InitiatedByUserUPN, InitiatedByAppName, InitiatedByServicePrincipalId,
    ModifiedProperties, CorrelationId
| order by TimeGenerated desc`
    let renderTemplate = template(text,{rangeFrom, rangeTo, username})
    printf("%s", renderTemplate)
    let t = kql(renderTemplate)
    return {t}
}
function timeConvert(t) {
   if contains(t, "(") { return t } else { return sprintf("unixtime_milliseconds_todatetime(%s)",t) }
}
"""

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

TIMESTAMP_COLUMN_HINTS = [
    "eventtime", "timestamp", "time", "datetime", "date", "signintime",
    "createddatetime", "activitydatetime", "occurredat", "eventdatetime",
    "created", "modified", "whencreated", "lastmodified", "ts"
]

def find_timestamp_column(columns: list[str]) -> str | None:
    """Return the column most likely to hold a timestamp, or None."""
    lower = [c.lower() for c in columns]
    for hint in TIMESTAMP_COLUMN_HINTS:
        for i, col in enumerate(lower):
            if hint in col:
                return columns[i]
    return None


def parse_timestamp(val) -> datetime | None:
    """Best-effort parse of a timestamp value (ms int, ISO string, epoch s)."""
    if val is None:
        return None
    try:
        # Integer milliseconds
        v = int(val)
        if v > 1e12:
            return datetime.fromtimestamp(v / 1000, tz=timezone.utc)
        else:
            return datetime.fromtimestamp(v, tz=timezone.utc)
    except (ValueError, TypeError):
        pass
    if isinstance(val, str):
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f%z",
        ):
            try:
                dt = datetime.strptime(val, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
    return None


def ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def fmt_dt(dt: datetime) -> str:
    return dt.strftime("%d %b %Y %H:%M") if dt else "—"


def fmt_date(dt: datetime) -> str:
    return dt.strftime("%d %b %Y") if dt else "—"


def esc(s) -> str:
    return html.escape(str(s)) if s is not None else "—"


# ─────────────────────────────────────────────
# Data extraction
# ─────────────────────────────────────────────

def load_report(path: str) -> dict:
    """
    Load a Fluency FPL report result JSON from disk.

    Accepts multiple envelope shapes produced by Fluency / the normalisation
    step in SKILL.md:

    Shape A (normalised by skill):
        {"objects": [{"name": "t", "table": {"columns": [...], "rows": [...]}}]}

    Shape B (raw get_report_result output):
        {"objects": [{"table": {"columns": [...], "rows": [...]}}]}

    Shape C (nested under result/data/response):
        {"result": {"objects": [...]}}

    Returns a dict with an "objects" key, or {"objects": []} on failure.
    """
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception as e:
        print(f"[warn] Could not load {path}: {e}", file=sys.stderr)
        return {"objects": []}

    if isinstance(data, dict):
        if "objects" in data:
            return data
        for key in ("result", "data", "response"):
            if key in data and isinstance(data[key], dict) and "objects" in data[key]:
                return data[key]
    return {"objects": []}


def extract_rows(report_data: dict) -> tuple[list[str], list[list]]:
    """
    Pull columns + rows from the first table-bearing object in the report.

    Handles two column formats returned by Fluency FPL:
      - String list:  ["col1", "col2", ...]
      - Dict list:    [{"name": "col1", ...}, {"name": "col2", ...}, ...]

    Handles two row formats returned by Fluency FPL:
      - Array rows:   [[val1, val2, ...], ...]
      - Dict rows:    [{"col1": val1, "col2": val2, ...}, ...]  ← most common

    Always returns (column_name_list, rows_as_2d_array).
    Returns ([], []) if nothing found.
    """
    objects = report_data.get("objects", [])
    for obj in objects:
        tbl = obj.get("table", {})
        raw_cols = tbl.get("columns", [])
        rows     = tbl.get("rows", [])
        if not raw_cols or not rows:
            continue

        # ── Normalise column definitions to plain name strings ──
        if isinstance(raw_cols[0], dict):
            cols = [c.get("name", str(c)) for c in raw_cols]
        else:
            cols = list(raw_cols)

        # ── Normalise dict rows → 2-D array ──
        if isinstance(rows[0], dict):
            rows = [[str(row.get(c, "")) for c in cols] for row in rows]

        return cols, rows
    return [], []


def extract_events(report_data: dict, label: str, color: str) -> list[dict]:
    """
    Extract timestamped events from a report for the timeline.
    Returns list of {"dt": datetime, "label": str, "color": str}.
    """
    cols, rows = extract_rows(report_data)
    if not cols:
        return []
    ts_col = find_timestamp_column(cols)
    if ts_col is None:
        return []
    ts_idx = cols.index(ts_col)
    events = []
    for row in rows:
        if ts_idx >= len(row):
            continue
        dt = parse_timestamp(row[ts_idx])
        if dt:
            events.append({"dt": dt, "label": label, "color": color})
    return events


# ─────────────────────────────────────────────
# Timeline SVG
# ─────────────────────────────────────────────

def build_timeline_svg(events: list[dict], from_ms: int, to_ms: int) -> str:
    """
    Build a static SVG showing all events as coloured dots on a horizontal
    time axis.  Three lanes (one per source) sit at y=40, 80, 120.
    """
    W, H = 700, 170
    PAD_L, PAD_R = 10, 10
    PLOT_W = W - PAD_L - PAD_R
    LANE_Y = {"Sign-in": 50, "Dir change initiated": 90, "Dir change targeting user": 130}
    LABEL_X = PAD_L

    from_dt = ms_to_dt(from_ms)
    to_dt   = ms_to_dt(to_ms)
    span_s  = (to_dt - from_dt).total_seconds()
    if span_s <= 0:
        span_s = 1

    def time_x(dt: datetime) -> float:
        elapsed = (dt - from_dt).total_seconds()
        return PAD_L + (elapsed / span_s) * PLOT_W

    # Axis line
    lines = []
    lines.append(f'<line x1="{PAD_L}" y1="155" x2="{W-PAD_R}" y2="155" stroke="#e3e6ec" stroke-width="1"/>')

    # X-axis labels (start, mid, end)
    mid_dt = ms_to_dt((from_ms + to_ms) // 2)
    for dt, anchor in [(from_dt, "start"), (mid_dt, "middle"), (to_dt, "end")]:
        x = time_x(dt)
        label = dt.strftime("%d %b %H:%M")
        lines.append(f'<text class="chart-axis" x="{x:.1f}" y="166" text-anchor="{anchor}">{esc(label)}</text>')

    # Lane labels + horizontal guide lines
    for lane, y in LANE_Y.items():
        color = {"Sign-in": "#2d65a1", "Dir change initiated": "#e8a01e",
                 "Dir change targeting user": "#c0161c"}.get(lane, "#8a92a3")
        lines.append(f'<line x1="{PAD_L}" y1="{y}" x2="{W-PAD_R}" y2="{y}" stroke="#eef0f4" stroke-width="1" stroke-dasharray="3 3"/>')

    # Dots — jitter dots that land too close together slightly
    for ev in events:
        dt = ev["dt"]
        if dt < from_dt or dt > to_dt:
            continue
        x = time_x(dt)
        y = LANE_Y.get(ev["label"], 90)
        c = ev["color"]
        ts_label = esc(dt.strftime("%d %b %H:%M"))
        lines.append(
            f'<circle cx="{x:.1f}" cy="{y}" r="5" fill="{c}" opacity="0.85">'
            f'<title>{ts_label} — {esc(ev["label"])}</title>'
            f'</circle>'
        )

    if not events:
        lines.append(f'<text class="chart-axis" x="{W//2}" y="95" text-anchor="middle" font-style="italic">No events in this window</text>')

    svg = (
        f'<svg class="svg-chart" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">\n'
        + "\n".join(lines)
        + "\n</svg>"
    )
    return svg


# ─────────────────────────────────────────────
# KPI strip
# ─────────────────────────────────────────────

def build_kpi_strip(signin_rows, dir_init_rows, dir_target_rows, signin_cols) -> str:
    total_signins = len(signin_rows)
    total_init    = len(dir_init_rows)
    total_target  = len(dir_target_rows)

    # Unique IPs from sign-in data
    ip_col = None
    for hint in ["ipaddress", "ip", "clientip", "sourceip", "ipaddr", "remoteip"]:
        for c in signin_cols:
            if hint in c.lower():
                ip_col = c
                break
        if ip_col:
            break

    unique_ips = 0
    if ip_col and signin_rows:
        ip_idx = signin_cols.index(ip_col)
        unique_ips = len({r[ip_idx] for r in signin_rows if ip_idx < len(r) and r[ip_idx]})

    signin_color = "blue" if total_signins < 20 else "amber" if total_signins < 100 else "red"
    target_color = "green" if total_target == 0 else "amber" if total_target < 5 else "red"

    return f"""
<div class="kpi">
  <div class="kpi-label">Total Sign-ins</div>
  <div class="kpi-value {signin_color}">{total_signins}</div>
  <div class="kpi-note">in investigation window</div>
</div>
<div class="kpi">
  <div class="kpi-label">Unique Source IPs</div>
  <div class="kpi-value navy">{unique_ips if unique_ips else "—"}</div>
  <div class="kpi-note">distinct IP addresses</div>
</div>
<div class="kpi">
  <div class="kpi-label">Dir Changes Initiated</div>
  <div class="kpi-value amber">{total_init}</div>
  <div class="kpi-note">changes made by user</div>
</div>
<div class="kpi">
  <div class="kpi-label">Dir Changes Targeting</div>
  <div class="kpi-value {target_color}">{total_target}</div>
  <div class="kpi-note">changes made to user</div>
</div>
""".strip()


# ─────────────────────────────────────────────
# Data tables
# ─────────────────────────────────────────────

# Columns to prefer for each report (ordered; first match wins)
SIGNIN_PREFERRED = ["eventtime", "timestamp", "time", "datetime", "ipaddress", "ip",
                    "clientip", "appdisplayname", "appname", "application",
                    "app", "country", "city", "resultstatus", "status", "result", "errorcode"]
DIR_PREFERRED    = ["eventtime", "timestamp", "time", "datetime", "activitydisplayname",
                    "operationname", "operation", "activitytype",
                    "result", "status",
                    "initiated",          # matches merged "Initiated By" column
                    "targetname",
                    "targetresource", "target"]
# ModifiedProperties is intentionally excluded from DIR_PREFERRED — it is rendered
# as a spanning sub-row beneath each data row instead (see build_table).


def merge_initiator_col(cols: list[str], rows: list[list]) -> tuple[list[str], list[list]]:
    """
    Collapse InitiatedByUserUPN, InitiatedByAppName, and InitiatedByServicePrincipalId
    into a single 'Initiated By' column.  User UPN takes priority; falls back to app
    name, then service-principal ID.  The merged column replaces the first source column
    found; the other source columns are dropped.
    """
    lower = [c.lower() for c in cols]

    user_idx = next((i for i, c in enumerate(lower) if c == "initiatedbyuserupn"), None)
    app_idx  = next((i for i, c in enumerate(lower) if c == "initiatedbyappname"), None)
    sp_idx   = next((i for i, c in enumerate(lower)
                     if c in ("initiatedbyserviceprincipalid", "initiatedbyappid")), None)

    merge_indices = {i for i in (user_idx, app_idx, sp_idx) if i is not None}
    if not merge_indices:
        return cols, rows   # nothing to merge

    insert_at = min(merge_indices)

    # Build new column list
    new_cols = []
    for i, c in enumerate(cols):
        if i == insert_at:
            new_cols.append("Initiated By")
        elif i in merge_indices:
            continue
        else:
            new_cols.append(c)

    # Build new rows
    new_rows = []
    for row in rows:
        def _get(idx):
            return str(row[idx]).strip() if idx is not None and idx < len(row) else ""
        combined = _get(user_idx) or _get(app_idx) or _get(sp_idx) or ""
        new_row = []
        for i, val in enumerate(row):
            if i == insert_at:
                new_row.append(combined)
            elif i in merge_indices:
                continue
            else:
                new_row.append(val)
        new_rows.append(new_row)

    return new_cols, new_rows


def pick_columns(available: list[str], preferred_hints: list[str], max_cols: int = 6) -> list[int]:
    """
    Pick indices of the most informative columns from available, guided by
    preferred_hints (checked as substrings), up to max_cols.
    """
    lower = [c.lower() for c in available]
    chosen_indices = []
    seen = set()
    for hint in preferred_hints:
        for i, col in enumerate(lower):
            if hint in col and i not in seen:
                chosen_indices.append(i)
                seen.add(i)
                break
        if len(chosen_indices) >= max_cols:
            break
    # Fill remaining slots with whatever columns are left
    if len(chosen_indices) < max_cols:
        for i in range(len(available)):
            if i not in seen:
                chosen_indices.append(i)
                seen.add(i)
            if len(chosen_indices) >= max_cols:
                break
    return chosen_indices


def classify_row(cols: list[str], row: list) -> str:
    """Return 'sev-high', 'sev-med', 'sev-low', or '' based on result/status column."""
    for hint in ["result", "status", "resultstatus", "errorcode"]:
        for i, c in enumerate(cols):
            if hint in c.lower() and i < len(row):
                v = str(row[i]).lower()
                if v in ("failure", "failed", "error", "0", "false"):
                    return "sev-high"
                if v in ("success", "succeeded", "true", "1"):
                    return "sev-low"
    return ""


def make_pill(value: str) -> str:
    v = str(value).lower()
    if v in ("failure", "failed", "error"):
        return f'<span class="pill fail">{esc(value)}</span>'
    if v in ("success", "succeeded"):
        return f'<span class="pill success">{esc(value)}</span>'
    return esc(value)


def format_modified_props(raw: str) -> str:
    """Convert ModifiedProperties JSON array to readable text lines.

    Input example:
      [{"displayName":"Group.DisplayName","oldValue":"\"Foo\"","newValue":null}]
    Output example:
      Group.DisplayName: "Foo" → (removed)
    """
    s = raw.strip()
    if not s or s in ("null", "[]", ""):
        return "(none)"
    try:
        items = json.loads(s)
    except (ValueError, TypeError):
        return esc(raw)  # not JSON — return as-is

    if not isinstance(items, list):
        items = [items]

    lines = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("displayName") or item.get("name") or "?"
        # oldValue / newValue are sometimes double-JSON-encoded strings
        def _decode(v):
            if v is None:
                return "(none)"
            v = str(v)
            # strip outer quotes added by double-encoding
            if v.startswith('"') and v.endswith('"'):
                try:
                    v = json.loads(v)
                except Exception:
                    pass
            v = str(v).strip()
            return v if v else "(none)"

        old = _decode(item.get("oldValue"))
        new = _decode(item.get("newValue"))
        lines.append(f"{esc(name)}: {esc(old)} → {esc(new)}")

    return "<br>".join(lines) if lines else esc(raw)


def build_table(cols: list[str], rows: list[list], preferred_hints: list[str],
                max_rows: int = 50, max_cols: int = 6) -> str:
    """Build an HTML <table class='data'> from columns and rows.

    ModifiedProperties (if present) is excluded from the main column selection and
    rendered as a full-width sub-row beneath each data row that has non-empty values.
    """
    if not cols or not rows:
        return '<p class="empty-notice">No events found in this investigation window.</p>'

    # Identify ModifiedProperties column in the raw cols (before pick_columns filters)
    mod_prop_raw_idx = None
    for i, c in enumerate(cols):
        cl = c.lower()
        if "modifiedprop" in cl:
            mod_prop_raw_idx = i
            break

    # Pick display columns, explicitly excluding ModifiedProperties
    col_indices = pick_columns(cols, preferred_hints, max_cols=max_cols)
    if mod_prop_raw_idx is not None and mod_prop_raw_idx in col_indices:
        col_indices = [i for i in col_indices if i != mod_prop_raw_idx]
    display_cols = [cols[i] for i in col_indices]
    n_cols = len(display_cols)

    # Identify result column for pill rendering
    result_col_idx_in_display = None
    for j, c in enumerate(display_cols):
        if any(h in c.lower() for h in ["result", "status", "resultstatus", "errorcode"]):
            result_col_idx_in_display = j
            break

    header_cells = "".join(f"<th>{esc(c)}</th>" for c in display_cols)
    header = f"<thead><tr>{header_cells}</tr></thead>"

    body_rows = []
    for row in rows[:max_rows]:
        # Main data row
        cells = []
        for j, orig_idx in enumerate(col_indices):
            val = row[orig_idx] if orig_idx < len(row) else ""
            if j == result_col_idx_in_display:
                cell = f"<td>{make_pill(val)}</td>"
            else:
                cell = f'<td class="wrap">{esc(val)}</td>'
            cells.append(cell)
        row_class = classify_row(cols, row)
        body_rows.append(f'<tr class="{row_class}">{"".join(cells)}</tr>')

        # ModifiedProperties sub-row (only when the column exists and has real data)
        if mod_prop_raw_idx is not None:
            raw_mod = str(row[mod_prop_raw_idx]).strip() if mod_prop_raw_idx < len(row) else ""
            if raw_mod and raw_mod not in ("null", "[]", "", "None"):
                formatted = format_modified_props(raw_mod)
                sub_style = (
                    "padding:4px 10px 6px 14px;font-size:11px;"
                    "color:var(--t2);background:var(--surface-raised, #f7f8fb);"
                    "border-top:none;"
                )
                label_style = "font-weight:600;color:var(--t3);margin-right:6px;"
                body_rows.append(
                    f'<tr class="{row_class}">'
                    f'<td colspan="{n_cols}" style="{sub_style}">'
                    f'<span style="{label_style}">Changes:</span>{formatted}'
                    f'</td></tr>'
                )

    if len(rows) > max_rows:
        body_rows.append(
            f'<tr><td colspan="{n_cols}" style="color:var(--t3);font-style:italic;'
            f'font-size:10px;padding:4px 6px;">'
            f'… {len(rows) - max_rows} more rows not shown</td></tr>'
        )

    body = f"<tbody>{''.join(body_rows)}</tbody>"
    return f'<table class="data">{header}{body}</table>'


# ─────────────────────────────────────────────
# User profile card
# ─────────────────────────────────────────────

def build_user_profile_card(user_record: dict | None) -> str:
    """Render a compact profile card from get_azure_user_record output.

    The tool returns fields: userPrincipalName, displayName, userType, email,
    createdDateTime, and roles (either a dict {displayName: description} or a
    list of {displayName, description} dicts).  All fields are optional — the
    card degrades gracefully if any are missing.

    Returns an empty string when user_record is None or empty.
    """
    if not user_record:
        return ""

    def field(label: str, value: str) -> str:
        if not value or value.lower() in ("null", "none", ""):
            return ""
        return (
            f'<div class="up-section">'
            f'<div class="up-label">{esc(label)}</div>'
            f'<div class="up-value">{esc(value)}</div>'
            f'</div>'
            f'<div class="up-divider"></div>'
        )

    # Basic fields
    display_name   = str(user_record.get("displayName") or "").strip()
    upn            = str(user_record.get("userPrincipalName") or "").strip()
    user_type      = str(user_record.get("userType") or "").strip()
    email          = str(user_record.get("email") or "").strip()
    created_raw    = str(user_record.get("createdDateTime") or "").strip()

    # Format created date
    created_fmt = ""
    if created_raw and created_raw not in ("null", "None"):
        try:
            dt = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            created_fmt = dt.strftime("%d %b %Y")
        except Exception:
            created_fmt = created_raw

    # Roles — accept dict {name: desc} or list [{displayName, description}]
    raw_roles = user_record.get("roles") or user_record.get("directoryRoles") or {}
    role_names: list[str] = []
    if isinstance(raw_roles, dict):
        role_names = list(raw_roles.keys())
    elif isinstance(raw_roles, list):
        for r in raw_roles:
            if isinstance(r, dict):
                role_names.append(r.get("displayName") or r.get("name") or str(r))
            else:
                role_names.append(str(r))

    # Role pills — highlight privileged roles in red
    ADMIN_KEYWORDS = {"admin", "global", "privileged", "security", "compliance",
                      "billing", "authentication", "helpdesk", "password", "directory"}
    role_pills = ""
    for rn in role_names:
        is_admin = any(kw in rn.lower() for kw in ADMIN_KEYWORDS)
        css = "role-pill admin" if is_admin else "role-pill"
        role_pills += f'<span class="{css}" title="{esc(rn)}">{esc(rn)}</span>'
    if not role_pills:
        role_pills = '<span class="up-none">No directory roles assigned</span>'

    sections = ""
    if display_name:
        sections += field("Display Name", display_name)
    if user_type:
        sections += field("User Type", user_type)
    if email and email != upn:
        sections += field("Email", email)
    if created_fmt:
        sections += field("Account Created", created_fmt)
    # Strip trailing divider from last field section
    sections = sections.rstrip().removesuffix('<div class="up-divider"></div>') if sections else ""

    roles_section = (
        f'<div class="up-section" style="flex:1;min-width:180px;">'
        f'<div class="up-label">Directory Roles</div>'
        f'<div class="up-roles">{role_pills}</div>'
        f'</div>'
    )

    return (
        f'<div class="user-profile">'
        f'{sections}'
        f'{roles_section}'
        f'</div>'
    )


# ─────────────────────────────────────────────
# Summary generator
# ─────────────────────────────────────────────

def _col_idx(cols: list[str], *hints: str) -> int | None:
    """Return index of first column whose name (lowercased) contains any hint."""
    lower = [c.lower() for c in cols]
    for hint in hints:
        for i, col in enumerate(lower):
            if hint in col:
                return i
    return None


def _unique_vals(rows, idx, max_show: int = 5) -> list[str]:
    """Return up to max_show distinct non-empty string values at column index idx."""
    seen: list[str] = []
    for r in rows:
        v = str(r[idx]).strip() if idx < len(r) else ""
        if v and v not in seen:
            seen.append(v)
        if len(seen) >= max_show:
            break
    return seen


def _join_english(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def build_summary(username: str, signin_rows, dir_init_rows, dir_target_rows,
                  signin_cols, from_ms: int, to_ms: int) -> str:
    from_dt = ms_to_dt(from_ms)
    to_dt   = ms_to_dt(to_ms)
    window  = f"{fmt_date(from_dt)} to {fmt_date(to_dt)}"

    total_s = len(signin_rows)
    total_i = len(dir_init_rows)
    total_t = len(dir_target_rows)
    parts   = []

    # ── Sign-in paragraph ────────────────────────────────────────────────────
    if total_s > 0:
        # Failures
        fail_idx = _col_idx(signin_cols, "resultstatus", "result", "status", "errorcode")
        failures = 0
        if fail_idx is not None:
            failures = sum(1 for r in signin_rows
                           if str(r[fail_idx]).lower() in ("failure", "failed", "error"))

        # Unique source IPs
        ip_idx = _col_idx(signin_cols, "ipaddress", "clientip", "sourceip", "ipaddr")
        unique_ips = sorted({str(r[ip_idx]) for r in signin_rows
                             if ip_idx is not None and ip_idx < len(r) and r[ip_idx]})

        # Locations: prefer city+state, fall back to country
        city_idx  = _col_idx(signin_cols, "city")
        state_idx = _col_idx(signin_cols, "state")
        loc_set: list[str] = []
        if city_idx is not None:
            for r in signin_rows:
                city  = str(r[city_idx]).strip()  if city_idx < len(r)  else ""
                state = str(r[state_idx]).strip()  if state_idx is not None and state_idx < len(r) else ""
                loc   = f"{city}, {state}" if city and state else city or state
                if loc and loc not in loc_set:
                    loc_set.append(loc)

        # Apps accessed
        app_idx  = _col_idx(signin_cols, "appdisplayname", "appname", "application", "app")
        apps = _unique_vals(signin_rows, app_idx, max_show=6) if app_idx is not None else []

        # Build sentence
        sentence = (
            f"During the investigation window ({window}), <strong>{esc(username)}</strong> "
            f"made <strong>{total_s} sign-in{'s' if total_s != 1 else ''}</strong>"
        )
        if failures:
            sentence += f" (<strong>{failures} failed</strong>)"
        if unique_ips:
            ip_str = _join_english([f"<code>{esc(ip)}</code>" for ip in unique_ips[:3]])
            if len(unique_ips) > 3:
                ip_str += f" and {len(unique_ips) - 3} more"
            sentence += f" from IP address{'es' if len(unique_ips) > 1 else ''} {ip_str}"
        if loc_set:
            sentence += f" ({_join_english([esc(l) for l in loc_set[:3]])})"
        sentence += "."
        if apps:
            sentence += (
                f" Applications accessed include "
                f"{_join_english([f'<strong>{esc(a)}</strong>' for a in apps])}"
            )
            if app_idx is not None:
                all_apps = {str(r[app_idx]).strip() for r in signin_rows if app_idx < len(r)}
                if len(all_apps) > len(apps):
                    sentence += f" and {len(all_apps) - len(apps)} other app{'s' if len(all_apps) - len(apps) != 1 else ''}"
            sentence += "."
        parts.append(sentence)

        if failures and failures > total_s * 0.3:
            parts.append(
                f"A high proportion of sign-in failures ({failures}/{total_s}) was observed "
                f"and may indicate a credential attack, MFA fatigue attempt, or misconfigured application."
            )

    # ── Directory changes initiated paragraph ────────────────────────────────
    if total_i > 0:
        act_idx    = _col_idx(["ActivityDisplayName"], "activitydisplayname", "operationname", "operation", "activity")
        # dir_init_cols not passed here — re-derive from first row keys if dict, else use positional
        # We work with the rows as lists; use find_timestamp_column-style approach on a synthetic list
        # Instead, detect operation types from known column name patterns in dir_init_rows
        ops: dict[str, int] = {}
        # Try to find operation column by scanning column 0 values (ActivityDisplayName is usually col 1 for dir_init)
        # Use index 1 as the most common position, but also try 0
        for trial_idx in [1, 0, 2]:
            sample = [str(r[trial_idx]).strip() for r in dir_init_rows[:5]
                      if trial_idx < len(r) and r[trial_idx]]
            if any("member" in s.lower() or "role" in s.lower() or "group" in s.lower() for s in sample):
                for r in dir_init_rows:
                    if trial_idx < len(r):
                        op = str(r[trial_idx]).strip()
                        if op:
                            ops[op] = ops.get(op, 0) + 1
                break

        # Result column (usually index 2 for dir_init simplified FPL)
        res_idx_candidates = [2, 3]
        init_failures = 0
        for ri in res_idx_candidates:
            sample = [str(r[ri]).strip().lower() for r in dir_init_rows[:5] if ri < len(r) and r[ri]]
            if any(s in ("success", "failure") for s in sample):
                init_failures = sum(1 for r in dir_init_rows
                                    if ri < len(r) and str(r[ri]).strip().lower() in ("failure", "failed", "error"))
                break

        if ops:
            op_strs = [f"<strong>{esc(op)}</strong> ({cnt}×)" for op, cnt in ops.items()]
            sentence = (
                f"The user initiated <strong>{total_i} directory change{'s' if total_i != 1 else ''}</strong>: "
                f"{_join_english(op_strs)}"
            )
            if init_failures:
                sentence += f" ({init_failures} failed)"
            sentence += "."
        else:
            sentence = (
                f"The user initiated <strong>{total_i} directory change{'s' if total_i != 1 else ''}</strong> "
                f"during the investigation window."
            )
        parts.append(sentence)

    # ── Directory changes targeting user paragraph ────────────────────────────
    if total_t > 0:
        # Operation type breakdown
        t_ops: dict[str, int] = {}
        for trial_idx in [1, 0, 2]:
            sample = [str(r[trial_idx]).strip() for r in dir_target_rows[:5]
                      if trial_idx < len(r) and r[trial_idx]]
            if any("member" in s.lower() or "role" in s.lower() or "group" in s.lower() for s in sample):
                for r in dir_target_rows:
                    if trial_idx < len(r):
                        op = str(r[trial_idx]).strip()
                        if op:
                            t_ops[op] = t_ops.get(op, 0) + 1
                break

        # Initiators (app or user)
        initiators: list[str] = []
        for hint_idx in range(min(len(dir_target_rows[0]) if dir_target_rows else 0, 15)):
            sample_vals = [str(r[hint_idx]).strip() for r in dir_target_rows if hint_idx < len(r) and r[hint_idx]]
            # Look for initiator-like values: app names or UPNs that are NOT the subject user
            if sample_vals and any(
                ("pim" in v.lower() or "app" in v.lower() or "@" in v)
                and username.lower() not in v.lower()
                for v in sample_vals
            ):
                for v in sample_vals:
                    if v and v not in initiators and username.lower() not in v.lower():
                        initiators.append(v)
                if initiators:
                    break

        if t_ops:
            op_strs = [f"<strong>{esc(op)}</strong> ({cnt}×)" for op, cnt in t_ops.items()]
            sentence = (
                f"<strong>{total_t} change{'s' if total_t != 1 else ''}</strong> "
                f"{'were' if total_t != 1 else 'was'} applied to the account: "
                f"{_join_english(op_strs)}"
            )
        else:
            sentence = (
                f"<strong>{total_t} change{'s' if total_t != 1 else ''}</strong> "
                f"{'were' if total_t != 1 else 'was'} applied to the account during this window"
            )
        if initiators:
            init_str = _join_english([f"<strong>{esc(i)}</strong>" for i in initiators[:3]])
            sentence += f", initiated by {init_str}"
        sentence += ". These changes should be verified as authorised and expected."
        parts.append(sentence)

    if total_s == 0 and total_i == 0 and total_t == 0:
        parts.append(
            "No activity was found for this user in the specified time window. "
            "Verify the username and time range are correct."
        )

    return "\n".join(f"<p>{p}</p>" for p in parts)


# ─────────────────────────────────────────────
# Recommendations
# ─────────────────────────────────────────────

def build_recommendations(signin_rows, dir_init_rows, dir_target_rows,
                           signin_cols, username: str) -> str:
    items = []

    # Count failures
    failures = 0
    fail_col = None
    for hint in ["result", "status", "resultstatus", "errorcode"]:
        for c in signin_cols:
            if hint in c.lower():
                fail_col = c
                break
        if fail_col:
            break
    if fail_col and signin_rows:
        fi = signin_cols.index(fail_col)
        failures = sum(1 for r in signin_rows
                       if fi < len(r) and str(r[fi]).lower() in ("failure", "failed", "error"))

    urgencies = []
    if len(dir_target_rows) > 0:
        urgencies.append(("red", "Immediate", f"Review all {len(dir_target_rows)} directory change(s) applied to {esc(username)}'s account — confirm each was authorised and expected."))
    if failures > 3:
        urgencies.append(("red", "Immediate", f"Investigate {failures} sign-in failures — determine whether these represent a credential attack, MFA fatigue, or application misconfiguration."))
    if len(dir_init_rows) > 0:
        urgencies.append(("red", "Within 24 h", f"Audit the {len(dir_init_rows)} directory change(s) initiated by this user — verify no unauthorised group membership or permission grants were made."))
    urgencies.append(("blue", "Within 7 days", "Cross-reference sign-in IPs against known VPNs, corporate egress points, and threat intelligence feeds to identify anomalous source addresses."))
    urgencies.append(("blue", "Within 7 days", "Confirm that Multi-Factor Authentication is enforced for this account across all applications."))
    urgencies.append(("navy", "Within 30 days", "Enable Azure AD Identity Protection risk policies to automate detection of future anomalous sign-in behaviour for this and similar accounts."))

    html_items = []
    for i, (color_key, timing, action) in enumerate(urgencies[:6], start=1):
        color_map = {"red": "var(--red)", "blue": "var(--blue)", "navy": "var(--navy)"}
        color = color_map.get(color_key, "var(--blue)")
        html_items.append(
            f'<div class="ns-item">'
            f'  <div class="ns-num" style="background:{color}">{i}</div>'
            f'  <div>'
            f'    <div class="ns-when">{timing}</div>'
            f'    <div class="ns-act">{action}</div>'
            f'  </div>'
            f'</div>'
        )
    return "\n".join(html_items)


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────



def main():
    parser = argparse.ArgumentParser(description="Build O365 User Investigation HTML report")
    parser.add_argument("--username",    required=True)
    parser.add_argument("--from-ms",     required=True, type=int, dest="from_ms")
    parser.add_argument("--to-ms",       required=True, type=int, dest="to_ms")
    parser.add_argument("--signin",      required=True)
    parser.add_argument("--dir-init",    required=True, dest="dir_init")
    parser.add_argument("--dir-target",  required=True, dest="dir_target")
    parser.add_argument("--template",    required=True)
    parser.add_argument("--output",      required=True)
    parser.add_argument("--user-record", required=False, default=None, dest="user_record",
                        help="Path to JSON file from get_azure_user_record (optional)")
    args = parser.parse_args()

    # Load user record (optional — gracefully absent when tool is unavailable)
    user_record: dict | None = None
    if args.user_record:
        try:
            raw = json.loads(Path(args.user_record).read_text(encoding="utf-8"))
            # The tool result may be wrapped — unwrap common envelopes
            if isinstance(raw, dict):
                user_record = raw.get("result") or raw.get("data") or raw
        except Exception as e:
            print(f"[warn] Could not load user record from {args.user_record}: {e}", file=sys.stderr)

    # Load data
    signin_data      = load_report(args.signin)
    dir_init_data    = load_report(args.dir_init)
    dir_target_data  = load_report(args.dir_target)

    signin_cols,     signin_rows     = extract_rows(signin_data)
    dir_init_cols,   dir_init_rows   = extract_rows(dir_init_data)
    dir_target_cols, dir_target_rows = extract_rows(dir_target_data)

    # Timeline events
    events = []
    events += extract_events(signin_data,     "Sign-in",                    "#2d65a1")
    events += extract_events(dir_init_data,   "Dir change initiated",       "#e8a01e")
    events += extract_events(dir_target_data, "Dir change targeting user",  "#c0161c")
    events.sort(key=lambda e: e["dt"])

    # Time labels
    from_dt = ms_to_dt(args.from_ms)
    to_dt   = ms_to_dt(args.to_ms)
    time_range_label = f"Investigation window: {fmt_dt(from_dt)} → {fmt_dt(to_dt)} UTC"
    time_range_short = f"{fmt_date(from_dt)} – {fmt_date(to_dt)}"

    # Build components
    user_profile_card = build_user_profile_card(user_record)
    kpi_strip       = build_kpi_strip(signin_rows, dir_init_rows, dir_target_rows, signin_cols)
    timeline_svg    = build_timeline_svg(events, args.from_ms, args.to_ms)
    summary_html    = build_summary(args.username, signin_rows, dir_init_rows, dir_target_rows,
                                    signin_cols, args.from_ms, args.to_ms)
    # Merge initiator columns for directory tables
    dir_init_cols,   dir_init_rows   = merge_initiator_col(dir_init_cols,   dir_init_rows)
    dir_target_cols, dir_target_rows = merge_initiator_col(dir_target_cols, dir_target_rows)

    signin_table    = build_table(signin_cols,     signin_rows,     SIGNIN_PREFERRED)
    dir_init_table  = build_table(dir_init_cols,   dir_init_rows,   DIR_PREFERRED, max_rows=50, max_cols=7)
    dir_target_table= build_table(dir_target_cols, dir_target_rows, DIR_PREFERRED, max_rows=50, max_cols=7)
    next_steps      = build_recommendations(signin_rows, dir_init_rows, dir_target_rows,
                                            signin_cols, args.username)

    # Load template
    template_path = Path(args.template)
    if not template_path.exists():
        print(f"ERROR: Template not found: {template_path}", file=sys.stderr)
        sys.exit(1)
    template = template_path.read_text(encoding="utf-8")

    # Embed logo as base64 data URL so the HTML is fully self-contained
    import base64
    logo_path = template_path.parent / "logo2.png"
    if logo_path.exists():
        logo_b64 = base64.b64encode(logo_path.read_bytes()).decode("ascii")
        template = template.replace(
            'src="assets/logo2.png"',
            f'src="data:image/png;base64,{logo_b64}"'
        )
    else:
        print(f"[warn] Logo not found at {logo_path} — report will render without it", file=sys.stderr)

    # Fill placeholders
    replacements = {
        "{{username}}":          esc(args.username),
        "{{report_date}}":       datetime.now(tz=timezone.utc).strftime("%d %b %Y"),
        "{{time_range_label}}":  esc(time_range_label),
        "{{time_range_short}}":  esc(time_range_short),
        "{{user_profile_card}}":  user_profile_card,
        "{{total_events}}":      str(len(events)),
        "{{kpi_strip}}":         kpi_strip,
        "{{timeline_svg}}":      timeline_svg,
        "{{summary_html}}":      summary_html,
        "{{signin_count}}":      str(len(signin_rows)),
        "{{dir_init_count}}":    str(len(dir_init_rows)),
        "{{dir_target_count}}":  str(len(dir_target_rows)),
        "{{signin_table}}":      signin_table,
        "{{dir_init_table}}":    dir_init_table,
        "{{dir_target_table}}":  dir_target_table,
        "{{next_steps_items}}":  next_steps,
    }
    output_html = template
    for placeholder, value in replacements.items():
        output_html = output_html.replace(placeholder, value)

    # Write output
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output_html, encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()
