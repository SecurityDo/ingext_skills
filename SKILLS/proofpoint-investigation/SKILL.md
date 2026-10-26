---
name: proofpoint-investigation
version: 1.0.0
description: >-
  Investigate one Proofpoint email message or case from the tenant's own Proofpoint event table
  and say what really happened: who sent it, who received it, inbound or outbound, whether it
  was delivered or blocked, what Proofpoint flagged (threat, URL, attachment), whether there is
  click evidence, and how far the same threat spread. USE THIS SKILL for "who sent this
  Proofpoint email", "was it delivered", "did the user click", "what did Proofpoint flag",
  "investigate this Proofpoint alert/case/GUID/message", "is this phish really outbound",
  or any question about a Proofpoint message. Reads the Proofpoint table with kql_search and the
  behavior summary with behavior_summary_search, computes the verdict locally from the event
  fields, and answers in analyst language with confirmed facts, inferences and unknowns kept
  apart. DO NOT use it for a general behavior incident (use incident-investigation) or for
  mailbox activity in Office 365 (use office-user-investigation).
---

# Proofpoint email investigation

Answers one question about one message: what really happened. The verdict is computed by
`scripts/proofpoint_verdict.py` from the Proofpoint event fields, never from the case label,
the risk score or the cluster name.

## Rules that decide the verdict

- **Event rows are the authority** for sender, recipients, direction, delivery, clicks, URLs and
  attachments. A behavior summary is context (rule, risk, timeline); its `key` or username usually
  names the recipient or case subject, not the sender.
- **Direction comes from the participants.** An internal sender with external recipients is
  outbound even when the cluster says `...inbound`. Report the contradiction; never flip the
  verdict to follow the label.
- **Anchor on the internal user.** If the case key is an external address but an internal address
  sent the message, investigate the internal sender as the local user. Only
  `sender`, `fromAddress` or `headerFrom` prove someone sent it.
- **Delivery.** `MessagesDelivered`, a delivered/allowed/relayed disposition or an `allow_relay`
  route is delivery evidence. `MessagesBlocked`, a quarantine folder or rule, or a
  block/drop/quarantine disposition contradicts it. One message can be delivered to some
  recipients and blocked for others: the script then reports `mixed`; check which recipients each
  event carries before saying the message "was blocked".
- **Clicks.** "No click evidence in the captured records" is not "the user did not click". Only
  say nobody clicked if click events for the relevant window exist and show none.
- **Old threats.** A `threatTime` far before the message (the script flags more than 30 days)
  usually means a known indicator was matched again, often a link shortener or a legitimate
  tracking domain, not a new attack. Say so.
- **Per recipient.** `toAddresses` and `ccAddresses` are header lists; the gateway processes one
  `recipient` per event. Judge delivery from `delivery_by_recipient`, and say if a header
  recipient has no event.
- **Duplicates.** Proofpoint rows are re-emitted. The script removes exact duplicate rows and
  reports the count; do not count rows as messages.
- Report CC and BCC exactly. If a field is empty, say it is empty.
- Do not paste raw event rows into the chat or the report. Quote field names and summarize values.

## Inputs

| Input | Rule |
|---|---|
| Connector and tenant | The MCP connector the user names. Call `list_accounts`, match the tenant, stop if ambiguous. Query only that account. |
| Message scope | One of: a Proofpoint `GUID`, `QID` or `messageID`; a recipient or sender address plus a day; a threat URL or id; or a behavior summary (case) id. |
| Internal domains | The tenant's own mail domains. Ask if unknown. Without them the script derives them from the sender domain and lowers the confidence to medium. |

## Step 1 — Confirm the table

`list_data_tables` for the tenant. Run the queries below only if `Proofpoint` is listed among the
stream tables. If it is not, stop and say the tenant has no Proofpoint events.

## Step 2 — Collect

All queries are `kql_search` with `rangeFrom` and `rangeTo` set to the window (a day either side
of the message). Save each result to a file in the work folder **outside the repository**: the rows
hold customer email addresses and subjects.

1. **The message:** every row for the identifier. Query in `references/queries.md` (by GUID, QID,
   messageID, or by recipient/sender and day). Save as `events.json`.
2. **Blast radius (optional):** other messages that share the threat id or URL, the sender or the
   subject. Save as `related.json`. Treat it as support, not as facts about this message.
3. **Baseline and related mail (recommended):** the threat baseline and the sender / sender-IP
   queries. They say whether the threat is common noise or part of a campaign. Save as
   `baseline.json` and read the counts; they are not passed to the script.
4. **After delivery (when the message was delivered to an internal user):** the Office365 census
   and `bec_sweep.kql` for that user, from the delivery time. Proofpoint cannot show forwards,
   inbox rules or deletions.
5. **Behavior summary (optional):** `behavior_summary_search` with `searchStr` on the entity,
   same window, for the rule, risk and timeline context. Use it only to explain why it was raised.
6. **Clicks (optional):** the click query in `references/queries.md`. Save as `clicks.json` and
   pass it with `--events` as well.

A large `kql_search` result is saved by the harness to a file; use that file. If a query returns
no rows, do not widen it blindly: say what the window and identifier were.

## Step 3 — Compute

```bash
python3 scripts/proofpoint_verdict.py --events WORKDIR/events.json [--events WORKDIR/clicks.json] \
  [--related WORKDIR/related.json] --internal-domain example.com [--case-key user@example.com] \
  --out WORKDIR/verdict.json
```

If it prints `insufficient_event_evidence`, stop short of any email conclusion and say the event
rows were not available.

## Step 4 — Answer

Use this shape, short for simple questions:

- **Answer:** what happened, in one or two sentences, with the result (escalate, contain, monitor,
  close as benign, or evidence insufficient). Lead with who is affected and why it matters.
- **Evidence:** the confirmed facts, citing the fields (sender, recipients with internal or
  external, direction and its confidence, delivery evidence, threat and URL, attachments, scores).
- **Analysis:** your reasoning, including contradictions. Label each point `confirmed` (a direct
  field), `inferred` (reasoned from several fields) or `unknown` (the data is absent).
- **Unknowns:** missing fields, no click events, failed or empty queries.
- **Next step:** one or two bounded actions that would change the verdict, such as purging the
  message, checking the sign-in logs of the local user for the same window, or looking for click
  events.

For a forwarded or relayed message, call the chain an inference unless the headers or paired
message records prove the order.

## Accuracy discipline

- Every figure comes from the script output; do not type a number from memory.
- Quote counters and field names; do not paraphrase them.
- Secondary checks (other cases for the same entity, sign-in activity of the local user) stay
  scoped to the tenant, the window and identifiers already in the results.
- A Proofpoint score of 0 means Proofpoint scored it as clean, not that nothing was found.
