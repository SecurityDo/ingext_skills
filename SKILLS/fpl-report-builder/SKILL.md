---
name: fpl-report-builder
description: >
  Author a Fluency / Ingext FPL report source file that compiles one or more KQL queries
  into a single time-bounded report. Use this skill whenever the user wants to BUILD, WRITE,
  CREATE, or ASSEMBLE a report definition out of KQL — e.g. "create an FQL/FPL report",
  "turn these KQL queries into a report", "build a report with an overview and a success-rate
  section", "write me a Fluency report that runs these queries", "compile these queries into
  one report", "scaffold an Office365 Exchange report". Trigger on any phrasing about
  authoring or generating report *source code* from KQL sections, even if the user says "FQL"
  instead of "FPL". This is for WRITING the report definition, NOT for running an existing
  report (use fluency-report for that) and NOT for writing a single standalone KQL query
  (use ingext-kql for that).
---

# FPL Report Builder

You author the **source code** for a Fluency / Ingext FPL report: a single file that wraps one
or more KQL queries into named sections and exposes a `main({from, to})` entry point. The file
is the deliverable — the user pastes or deploys it into Fluency themselves.

This is purely a code-authoring task. Do **not** call MCP tools, run reports, or query a live
tenant. Generate well-formed FPL/KQL from the conventions below.

## What an FPL report is

An FPL report is JavaScript-flavored source with one required entry point, `main`, plus one
helper function per report section. `main` takes a time range (`from`/`to`), validates it,
records it in the environment, calls each section function, and returns an object whose keys
are the section results. Each section function builds a KQL string and runs it through the
built-in `kql()` helper.

The canonical shape — study it, then reproduce it for the user's sections:

```javascript
function main({from="-1d@d", to="@d"}) {
    let rangeFrom = new Time(from)
    let rangeTo = new Time(to)
    validateTimeRange(rangeFrom, rangeTo)
    setEnv("from", from)
    setEnv("to", to)

    let overview = GetOverview(rangeFrom, rangeTo)
    let successRate = GetSuccess(rangeFrom, rangeTo)
    return {
        overview,
        successRate
    }
}

function validateTimeRange(from, to) {
    // start of the range must come before the end
    if (from.After(to)) {
        throw new Error("rangeFrom must be less than rangeTo", "RangeError")
    }
    // cap the window so a report can't scan an unbounded amount of data
    if (to.After(from.Add("60d"))) {
        throw new Error("total duration must not exceed 2 months", "RangeError")
    }
    return true
}

// Exchange activity overview
function GetOverview(rangeFrom, rangeTo) {
    let query = `
    Office365
    | where timestamp between (datetime("${rangeFrom}") .. datetime("${rangeTo}"))
    | where Workload == "Exchange"
    | summarize
        TotalEvents = count(),
        UniqueUsers = dcount(UserId),
        UniqueMailboxes = dcount(MailboxOwnerUPN),
        UniqueIPs = dcount(ClientIPAddress)
    `
    return kql(query)
}

// Exchange successful vs failed operations
function GetSuccess(rangeFrom, rangeTo) {
    let query = `
    Office365
    | where timestamp between (datetime("${rangeFrom}") .. datetime("${rangeTo}"))
    | where Workload == "Exchange"
    | summarize
        FailedOperations = countif(ResultStatus != "Succeeded"),
        SuccessfulOperations = countif(ResultStatus == "Succeeded")
    `
    return kql(query)
}
```

## Non-negotiable conventions

These are the parts that make a report actually run inside Fluency. Get them exactly right.

1. **`main` is the entry point** and always destructures `{from, to}` with relative-time
   defaults. Use `from="-1d@d"`, `to="@d"` unless the user asks for a different default
   window. (`-1d@d` = start of yesterday, `@d` = start of today — see the time syntax
   reference.)

2. **Build `rangeFrom` / `rangeTo` once** at the top of `main` with `new Time(...)`, then pass
   those Time objects into every section function. Section functions receive the Time objects,
   never the raw strings.

3. **Always call `validateTimeRange(rangeFrom, rangeTo)`** and **`setEnv("from", from)` /
   `setEnv("to", to)`** in `main`, before calling any section. Reproduce `validateTimeRange`
   verbatim unless the user wants a different maximum window (then change the `60d` and its
   message together).

4. **Every KQL query MUST be time-bounded** with this exact filter as the first `where` after
   the table name:

   ```
   | where timestamp between (datetime("${rangeFrom}") .. datetime("${rangeTo}"))
   ```

   This is the single most common thing to get wrong. A section without it scans all of time.
   When the user hands you raw KQL that lacks this line, insert it immediately after the table
   identifier — do not skip it, and do not assume their query already handles time.

5. **Each section is its own named function** returning `kql(query)`, where `query` is a
   template literal (backticks). The interpolations `${rangeFrom}` and `${rangeTo}` only work
   inside backtick strings — never single/double quotes.

6. **`main` returns an object** whose keys map a short camelCase name to each section's result.
   Use object shorthand (`{ overview, successRate }`) when the variable name already is the key
   you want.

7. **Add a one-line `//` comment above each section function** describing what it measures.
   These become the human-readable labels a downstream renderer can use.

## Workflow

### 1. Determine the inputs

The user provides report content in one of two ways — handle both:

- **Natural-language sections.** They describe what each section should measure ("an overview
  with total events and unique users", "success vs failure counts", "top 10 senders"). Generate
  the KQL for each from the description plus what you know about the relevant table/columns.
- **Ready-made KQL.** They paste queries. Wrap each as a section as-is, but still enforce the
  time-bound filter (convention #4) and the structural conventions. If a pasted query hardcodes
  its own time filter (e.g. `ago(7d)` or a literal date range), replace it with the standard
  `timestamp` filter so the report's `from`/`to` actually drives it — and mention you did.

Either way, confirm the **table name** and the **default time window** if they're not obvious.
Don't invent column names silently; if you're unsure of a field, use a sensible name and flag it
in your summary so the user can correct it.

### 2. Name the sections

Give each section function a `GetXxx`-style PascalCase name and a short camelCase key for the
return object (e.g. function `GetTopSenders` → key `topSenders`). Keep them descriptive and
distinct.

### 3. Assemble the file

Write the file in this order: `main` first, then `validateTimeRange`, then each section function
in the same order they're called in `main`. This top-down reading order matches the example and
is what reviewers expect.

For the detailed KQL filtering/aggregation patterns and the relative-time syntax (`-1d@d`,
`@d`, `now`, etc.), read `references/fpl_conventions.md`.

### 4. Write and share

Save to `<output-dir>/<report_name>.fpl` (snake_case the name, e.g. `office365_exchange.fpl`).
`.fpl` is the convention; use `.js` only if the user asks. Then present the file to the user.

In your closing note (1–2 sentences) call out anything they should verify: guessed column names,
queries where you swapped in the standard time filter, or the assumed table name.

## Quality bar

Before you finish, re-read the generated file against this checklist:

- `main` destructures `{from, to}` with defaults, builds both Time objects, calls
  `validateTimeRange`, calls `setEnv` twice, calls every section, returns the keyed object.
- `validateTimeRange` is present and correct.
- **Every** section query contains the `timestamp` between-filter, right after the table
  name, using `${rangeFrom}`/`${rangeTo}` inside backticks.
- Section count in `main` matches the number of section functions, and every returned key has a
  matching function call.
- No section function is dead code (defined but never called) and no `main` call references a
  missing function.

A subtle but common failure is a query that looks complete but silently omits the time filter,
or uses straight quotes instead of backticks so the interpolation never happens. Those make the
report run against all data or throw at parse time — worth the extra read to catch.
