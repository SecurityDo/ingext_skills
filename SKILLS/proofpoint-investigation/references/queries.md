# Proofpoint queries

Run each with `kql_search`, `rangeFrom` and `rangeTo` set to the window. Columns are named
`@proofpoint.<field>`; the script reads them by that prefix, so do not rename them with `project`.
Quote the field with `['...']` in KQL. Replace the values in angle brackets.

## The message (pick the identifier you have)

```kql
Proofpoint | where ['@proofpoint.GUID'] == "<GUID>"
Proofpoint | where ['@proofpoint.QID'] == "<QID>"
Proofpoint | where ['@proofpoint.messageID'] == "<messageID>"
```

By person and day (the recipient fields are arrays, so search the text):

```kql
Proofpoint
| where tostring(['@proofpoint.recipient']) has "<user@example.com>"
    or tostring(['@proofpoint.toAddresses']) has "<user@example.com>"
    or tostring(['@proofpoint.sender']) has "<user@example.com>"
```

Large result: add `| take 200`, or `| project` only the columns the script reads: `timestamp`,
`GUID`, `QID`, `messageID`, `type`, `sender`, `fromAddress`, `headerFrom`, `recipient`,
`toAddresses`, `ccAddresses`, `bccAddresses`, `replyToAddress`, `headerReplyTo`, `cluster`,
`policyRoutes`, `modulesRun`, `senderIP`, `quarantineFolder`, `quarantineRule`, `disposition`,
`finalAction`, `deliveryStatus`, `messageTime`, `phishScore`, `spamScore`, `malwareScore`,
`impostorScore`, `subject`, `messageParts`, `threatsInfoMap`.

## Blast radius

```kql
Proofpoint | where tostring(['@proofpoint.threatsInfoMap']) has "<threatID or threat URL>"
Proofpoint | where ['@proofpoint.subject'] == "<subject without RE:/FW: prefix>"
```

## Related mail from the same sender or sender IP

Finds a campaign that rotates URLs and subjects. Counts only, no rows:

```kql
Proofpoint
| where ['@proofpoint.senderIP'] == "<sender IP>" or tostring(['@proofpoint.sender']) =~ "<sender address>"
| summarize records=count(), msgs=dcount(tostring(['@proofpoint.GUID'])),
    recipients=dcount(tostring(['@proofpoint.recipient'])), first=min(timestamp), last=max(timestamp)
  by type=tostring(['@proofpoint.type'])
```

## Baseline for the threat

How common is this threat id on the tenant? Use 14 to 30 days. A threat that is on hundreds of
messages from dozens of senders is a flagged shared or shortened link, not a targeted attack:

```kql
Proofpoint
| where tostring(['@proofpoint.threatsInfoMap']) has "<threatID>"
| summarize msgs=dcount(tostring(['@proofpoint.GUID'])), senders=dcount(tostring(['@proofpoint.sender'])),
    first=min(timestamp), last=max(timestamp) by type=tostring(['@proofpoint.type'])
```

The same shape on the sender domain gives the sender baseline.

## After delivery (Office365)

Proofpoint stops at the gateway. For each internal user who received the message, look at the
mailbox from the delivery time on. `kql_search` on `Office365`, window from the delivery time;
the `Office365` fields have no prefix (`UserId`, `Operation`). Wide `has_any` lists over a
several-day window time out, so start narrow:

```kql
Office365 | where tolower(tostring(UserId)) == "<user@example.com>"
| summarize n=count() by op=tostring(Operation) | order by n desc | take 12
```

For follow-on actions (inbox rules, forwarding, delegated access, OAuth consent) run
`incident-investigation/assets/queries/bec_sweep.kql` with `{USER}` and `{TARGET}` set to the
user. A zero is only meaningful with a control: the census above must show the user was active.

## Clicks

Click events carry their own `type` (for example `ClicksPermitted`, `ClicksBlocked`). Query the
same GUID or threat id:

```kql
Proofpoint | where ['@proofpoint.type'] startswith "Click"
  and (['@proofpoint.GUID'] == "<GUID>" or tostring(['@proofpoint.threatsInfoMap']) has "<threatID>")
```

An empty result means no click events were captured for that window, which is not proof of no
click.

## Per-recipient delivery

No query: one Proofpoint event carries one `recipient`, so `proofpoint_verdict.py` reports
`delivery_by_recipient` from query 1. `toAddresses` and `ccAddresses` are header fields and can
list people who have no event of their own; only the `recipient` field shows who the gateway
processed.

## Which types exist

```kql
Proofpoint | summarize n=count() by type=tostring(['@proofpoint.type'])
```
