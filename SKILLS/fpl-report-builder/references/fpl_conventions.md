# FPL Report Conventions Reference

Detail to support `SKILL.md`. Read this when you need the exact time syntax, the KQL building
blocks, or fuller worked examples of multi-section reports.

## Contents
1. Relative-time syntax (the `from` / `to` values)
2. The `main` / `validateTimeRange` scaffold
3. KQL building blocks for section queries
4. The mandatory time filter, in depth
5. Worked example: a three-section report
6. Common mistakes

---

## 1. Relative-time syntax

`from` and `to` are strings parsed by `new Time(...)`. They support absolute timestamps and a
relative mini-syntax. The `@` operator snaps to the start of a unit.

| Value      | Meaning                                  |
|------------|------------------------------------------|
| `now`      | current instant                          |
| `@d`       | start of today (midnight)                |
| `-1d@d`    | start of yesterday                       |
| `-7d@d`    | start of the day 7 days ago              |
| `@h`       | start of the current hour                |
| `-1h`      | one hour ago (no snapping)               |
| `@w`       | start of the current week                |
| `@mon`     | start of the current month               |

Default report window is **yesterday**: `from="-1d@d"`, `to="@d"`. Pick a window that matches
the report's cadence — a daily report uses yesterday; a weekly report might use `from="-7d@d"`,
`to="@d"`.

`new Time` objects expose helpers used in `validateTimeRange`:
- `a.After(b)` → boolean, true if `a` is later than `b`
- `a.Add("60d")` → returns a new Time offset forward by the duration

When a Time object is interpolated into a KQL string (`${rangeFrom}`), it renders as a datetime
literal that `datetime("...")` accepts.

---

## 2. The scaffold

`main` and `validateTimeRange` are nearly identical across reports. Reproduce them as-is; the
only things that change are the default window, the section calls, and (rarely) the max-window
cap.

```javascript
function main({from="-1d@d", to="@d"}) {
    let rangeFrom = new Time(from)
    let rangeTo = new Time(to)
    validateTimeRange(rangeFrom, rangeTo)
    setEnv("from", from)
    setEnv("to", to)

    let sectionA = GetSectionA(rangeFrom, rangeTo)
    let sectionB = GetSectionB(rangeFrom, rangeTo)
    return { sectionA, sectionB }
}

function validateTimeRange(from, to) {
    if (from.After(to)) {
        throw new Error("rangeFrom must be less than rangeTo", "RangeError")
    }
    if (to.After(from.Add("60d"))) {
        throw new Error("total duration must not exceed 2 months", "RangeError")
    }
    return true
}
```

`setEnv("from", from)` / `setEnv("to", to)` store the raw strings so downstream consumers and
the rendering layer know the window the data covers. Always set both.

---

## 3. KQL building blocks for sections

A section query is ordinary KQL inside a backtick template literal. Skeleton:

```
<TableName>
| where timestamp between (datetime("${rangeFrom}") .. datetime("${rangeTo}"))
| where <condition>
| summarize <aggregations> [by <group cols>]
| order by <col> [asc|desc]
| top <N> by <col> desc
| project <cols>
```

Aggregations you'll reach for most:
- `count()` — row count
- `countif(<predicate>)` — conditional count (great for success/failure splits)
- `dcount(<col>)` — distinct count
- `sum(<col>)`, `avg(<col>)`, `min`, `max`
- `summarize ... by <col>` — group; combine with `top N by` for leaderboards
- `bin(timestamp, 1h)` — time-bucket for trend/series sections

Filtering operators: `==`, `!=`, `contains`, `has`, `startswith`, `in (...)`.

Field-name note: the time column is `timestamp` — a plain identifier, no brackets. Only
bracket-quote fields that contain special characters or start with `@` (e.g. `['@version']`).
Plain identifiers (`timestamp`, `Workload`, `UserId`) don't need brackets.

---

## 4. The mandatory time filter, in depth

Every section query's first `where` must be:

```
| where timestamp between (datetime("${rangeFrom}") .. datetime("${rangeTo}"))
```

Why it matters: the whole point of the report is that one `from`/`to` pair drives every section.
If a section omits this filter it scans the entire table regardless of the requested window —
slow, expensive, and wrong. The filter goes **immediately after the table name**, before any
content filters, so the engine prunes by time first.

When wrapping user-supplied KQL:
- If it has **no** time filter, insert this line right after the table name.
- If it has a **different** time filter (`| where TimeGenerated > ago(7d)`, a literal date
  range, etc.), replace it with this one so the report's parameters take over. Note the swap in
  your summary to the user.
- Keep using `timestamp` even if their query referenced another timestamp column — unless
  the user tells you the table's time column is named differently, in which case mirror their
  field name inside the same `between (...)` structure.

---

## 5. Worked example — three-section sign-in report

```javascript
function main({from="-1d@d", to="@d"}) {
    let rangeFrom = new Time(from)
    let rangeTo = new Time(to)
    validateTimeRange(rangeFrom, rangeTo)
    setEnv("from", from)
    setEnv("to", to)

    let overview = GetOverview(rangeFrom, rangeTo)
    let failedByUser = GetFailedByUser(rangeFrom, rangeTo)
    let signinTrend = GetSigninTrend(rangeFrom, rangeTo)
    return {
        overview,
        failedByUser,
        signinTrend
    }
}

function validateTimeRange(from, to) {
    if (from.After(to)) {
        throw new Error("rangeFrom must be less than rangeTo", "RangeError")
    }
    if (to.After(from.Add("60d"))) {
        throw new Error("total duration must not exceed 2 months", "RangeError")
    }
    return true
}

// Sign-in volume and distinct users/IPs
function GetOverview(rangeFrom, rangeTo) {
    let query = `
    Office365
    | where timestamp between (datetime("${rangeFrom}") .. datetime("${rangeTo}"))
    | where Operation == "UserLoggedIn"
    | summarize
        TotalSignins = count(),
        UniqueUsers = dcount(UserId),
        UniqueIPs = dcount(ClientIPAddress)
    `
    return kql(query)
}

// Top 10 users by failed sign-in count
function GetFailedByUser(rangeFrom, rangeTo) {
    let query = `
    Office365
    | where timestamp between (datetime("${rangeFrom}") .. datetime("${rangeTo}"))
    | where Operation == "UserLoginFailed"
    | summarize FailedCount = count() by UserId
    | top 10 by FailedCount desc
    `
    return kql(query)
}

// Hourly sign-in trend
function GetSigninTrend(rangeFrom, rangeTo) {
    let query = `
    Office365
    | where timestamp between (datetime("${rangeFrom}") .. datetime("${rangeTo}"))
    | where Operation == "UserLoggedIn"
    | summarize Signins = count() by bin(timestamp, 1h)
    | order by timestamp asc
    `
    return kql(query)
}
```

---

## 6. Common mistakes

- **Missing time filter** in a section — the #1 error. Re-read every query for it.
- **Straight quotes instead of backticks** around the query — `${rangeFrom}` only interpolates
  inside backtick template literals; with `'...'` or `"..."` it stays literal and the query is
  broken.
- **Forgetting `setEnv`** — the report still runs but downstream consumers lose the window
  metadata.
- **Section defined but never called in `main`** (or vice versa) — dead/missing code.
- **Passing raw `from`/`to` strings into section functions** instead of the `new Time(...)`
  objects — build the Time objects once in `main` and pass those.
- **Return-key / function mismatch** — the object `main` returns should have one key per section
  function, named consistently.
