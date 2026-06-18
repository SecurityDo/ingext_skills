---
name: fortigate-bandwidth
version: 1.0.0
description: >
  Correctly calculate FortiGate traffic bandwidth (bytes sent/received, top talkers, data
  volume) from NetworkFortigateTraffic / fortigatetraffic data in the Ingext datalake. ALWAYS
  apply these rules whenever a KQL query, FPL report, dashboard, or summary sums or ranks
  FortiGate sentbyte/rcvdbyte/sentpkt/rcvdpkt — e.g. "top talkers", "bandwidth by srcip",
  "data usage per host", "busiest IPs", "traffic volume". FortiGate byte fields are CUMULATIVE
  session counters, so a naive sum() massively over-counts; the per-interval deltas in _fields
  must be used instead. This knowledge should fire before writing or running any FortiGate
  traffic aggregation, including when reached indirectly through ingext-kql, fluency-report, or
  fpl-report-builder.
---

# FortiGate Bandwidth Calculation

Rules for correctly aggregating FortiGate traffic byte/packet counters
(`NetworkFortigateTraffic` schema, or any `fortigatetraffic`-style index) in the
Ingext datalake. Apply to any FortiGate byte/packet aggregation — KQL queries,
FPL reports, dashboards, or written summaries.

> The ready-to-run query lives in the ingext-kql schema KB:
> `references/schemas/NetworkFortigateTraffic/queries/fortigate-bandwidth.yaml`,
> and the field-level guidance is in that table's `info.yaml`. This page is the
> *why* and the validation checklist; use the KB example as the canonical query
> and don't duplicate it.

## The core problem: cumulative counters

`sentbyte`, `rcvdbyte`, `sentpkt`, and `rcvdpkt` are **cumulative running totals
for the session**, not the bytes for that single log record. FortiGate emits
periodic log lines for long-lived sessions, and each line repeats the cumulative
total to date. So `summarize sum(sentbyte)` **double-counts** — a single
multi-day session can inflate an hourly total to petabytes.

## The fix: per-interval deltas from `_fields`

There are no top-level delta columns. The correct per-record values are the
deltas inside the `_fields` dynamic JSON bag — `sentdelta`, `rcvddelta`
(plus `sentpktdelta`, `rcvdpktdelta`, `durationdelta`). They are stored as
**strings**, so wrap in `tolong()`, and **not every record has them** (a
session-close record may carry only the cumulative byte, which is then the true
session total). The canonical rule is therefore delta-first with a cumulative
fallback:

```kql
extend sent = coalesce(tolong(_fields.sentdelta), sentbyte),
       rcvd = coalesce(tolong(_fields.rcvddelta), rcvdbyte)
```

`logid 0000000020` is the periodic "traffic forward" session update — the
high-volume records that repeat cumulative counters. Decide deliberately:
exclude `logid 0000000020` to drop the noisiest periodic updates, **or** keep it
and rely on its `sentdelta`/`rcvddelta` (which it reliably carries) if you want
long-lived-session bandwidth included. Pick one approach consistently.

## Sanity checks before reporting

1. Never `sum()` raw `sentbyte`/`rcvdbyte` across session logs — use the
   `coalesce(tolong(_fields.sentdelta), sentbyte)` rule (and the rcvd analog).
2. Decide deliberately whether to include or exclude `logid 0000000020`.
3. Check the top result's **bytes-per-packet** ratio (`sentbyte/sentpkt`).
   Multi-MB/packet is physically impossible (real packets max ~65 KB) and means
   the byte field is cumulative or corrupt.
4. Be suspicious of any single IP whose total dwarfs everything else by orders of
   magnitude — usually one long-lived session with a cumulative counter.
5. Always state the time window; FortiGate volume is meaningless without it.

For reference, on a live tenant a naive `sum(sentbyte)` ranked one IP at ~15.6 PB
over an hour — actually a single 102-day VoIP session logged 28 times with a
corrupt cumulative counter. Applying the delta rule dropped it out of the top 100.
