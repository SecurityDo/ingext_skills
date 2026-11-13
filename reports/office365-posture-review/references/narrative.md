# narrative.json (optional)

`build_report.py` writes every text block from the numbers, so a plain run already gives a complete report.
Pass `--narrative narrative.json` only to replace some of that wording for the customer. Any key you leave out
keeps the generated text; the generated version of every key is saved in `<out>.facts.json` under `narrative`,
so start from that file.

| Key | Shape | Where it shows |
|---|---|---|
| `thesis` | one sentence | the line under the title |
| `top_finding` | `{"headline", "text", "action"}` | the black "Highest-impact finding" box; `action` is a short verb phrase ("Reduce and harden") |
| `summary` | list of 2 paragraphs (HTML allowed, e.g. `<strong>`) | section 1, executive summary |
| `callouts` | 4 to 6 `{"kind", "tag", "heading", "text"}`; `kind` is `act` (red), `watch` (amber) or `good` (blue) | section 9 |
| `remediation` | up to 8 `{"severity", "action", "owner", "verify"}`, worst first; severity Critical, High, Medium or Low | section 10 |

Rules:

- Every number must come from `facts.json` (or a count of CSV rows). Never round up or invent a figure.
- Use the customer's display name, never the tenant id, in the thesis and callouts.
- Name at most the top 10 accounts; the full lists are in the CSV.
- Never write "compromised", "compliant" or "secure". This is a configuration snapshot, not activity.
- A check shown as "not measured" (for example token baselines when the fields are absent) is never described as clean.
