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

## Clicks

Click events carry their own `type` (for example `ClicksPermitted`, `ClicksBlocked`). Query the
same GUID or threat id:

```kql
Proofpoint | where ['@proofpoint.type'] startswith "Click"
  and (['@proofpoint.GUID'] == "<GUID>" or tostring(['@proofpoint.threatsInfoMap']) has "<threatID>")
```

An empty result means no click events were captured for that window, which is not proof of no
click.

## Which types exist

```kql
Proofpoint | summarize n=count() by type=tostring(['@proofpoint.type'])
```
