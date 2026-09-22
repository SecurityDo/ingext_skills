# Closure JSON — field reference

`scripts/render_closure.py closure.json -o closure.html` renders this into the Tier 3
closure report. Worked examples in `assets/examples/`:

- `sendas_admin_closure.json`: a multi-day admin incident. It uses `score_table` and
  `base_rate`.
- `credential_policy_closure.json`: a single-event incident. It uses `timeline`.

Inline markup in any text field: `**bold**`, `*italic*`, `` `code` ``. Everything else
is escaped.

| Field | Req | Shape | Rule |
|---|---|---|---|
| `eyebrow` | – | string | Defaults to `Incident closure · Tier 3 review`. |
| `logo` | – | string | Path to a replacement logo (PNG, JPEG, SVG, WebP or GIF), relative to the JSON file. Defaults to `assets/fluency_logo.png`; `--logo` on the command line overrides it. |
| `title` | ✓ | string | **What actually happened**, in plain words. It is not the rule name and not "Incident 1234". Examples: "SendAs grants by a tenant identity administrator", "A passkey campaign switched on by Microsoft". |
| `lede` | ✓ | string | One paragraph with three parts: what escalated it, how many grounds were cited, and how many survived testing. |
| `verdict.outcome` | ✓ | `benign` \| `escalate` \| `confirmed` | Sets the card colour. |
| `verdict.text` | ✓ | string | Two sentences at most. Give the verdict, then the action. |
| `meta[]` | ✓ | `{label, value}` | Always include subject, tenant, window and peak riskScore. `Tenant` is the account's **display name** from `list_accounts` (e.g. `Contoso Ltd`), never the connector and never `connector : account`. Add incident days or incident time, the AI-assist verdict when one exists, and rules if useful. Keep it to 6–7 entries. |
| `grounds.items[]` | ✓ | `{claim, finding}` | `claim` is quoted **verbatim** from the AI-assist workflow. When there is no AI-assist verdict, write the grounds the summary raises. `finding` names the index each number came from and puts counts in bold. |
| `grounds.title` / `.intro` | – | string | The title defaults to "N grounds for escalation, tested". |
| `timeline` | – | `{title, intro, rows[{time, actor, event, highlight}], callout}` | Use for single-event or single-transaction incidents. Times come from the **raw audit log**, never from summary `from`/`to`. Set `highlight` on the rows the rule fired on. |
| `score_table` | – | `{title, intro, activity_label, rows[{day, activity, score, incident}], callout}` | Use for multi-day incidents. Put the entity's real daily activity next to the daily riskScore. Bars are scaled per column. Put the risk term that actually drives the score in `callout`. |
| `base_rate` | – | `{title, intro, caption, columns[], rows[[…]]}` | The Step 2 census **within this one account**: one row per rule, with the number of distinct entities and the highest scorer. Never another tenant's numbers. |
| `negatives.items[]` | ✓ | `{title, body}` | One item per Step 5 negative. Each `body` gives the zero **and its control**, meaning the count of the same operation elsewhere on the tenant. |
| `negatives.callouts[]` | – | `{title, body}` | Use one callout for each red herring the ticket raised, such as an "ISP discrepancy" or "impossible travel". |
| `callouts[]` | – | `{title, body}` | Standalone callouts rendered before the Recommendation section. |
| `recommendation` | ✓ | string or string[] | The first paragraph gives the disposition and the tuning lever, stating which lever it is (see Step 7). Later paragraphs cover gaps found along the way, such as collection or ingestion problems, kept separate from the verdict. |
| `footer.date` | ✓ | string | The review date. |
| `footer.evidence` | ✓ | string | Every index or API consulted, each with its row or hit count, ending with the data-boundary line "All findings: <tenant display name> only." |

## Section titles are findings, not labels

This rule applies to `score_table.title`, `base_rate.title`, `timeline.title` and
`grounds.title`.

- **Good:** "The score does not follow the activity", "She is not an outlier among her
  peers", "The trigger was Microsoft, not an admin".
- **Bad:** "Risk score analysis", "Peer comparison", "Timeline".

If a section's evidence does not support a one-line claim, leave the section out.
Do not fill it with a neutral label.
