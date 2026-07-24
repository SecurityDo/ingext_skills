# References — HEC passthrough source-side guidance

Verified 2026-07-24. The Fluency-side facts (template `output` block, parameter schema) come
from the live `list_connector_templates` at install time, not from documentation.

| Claim in SKILL.md | Source |
|---|---|
| HEC authentication is an `Authorization: Splunk <token>` HTTP header | [Set up and use HTTP Event Collector in Splunk Web — Splunk Docs](https://docs.splunk.com/Documentation/Splunk/latest/Data/UsetheHTTPEventCollector) |
| JSON events carry the payload under the `"event"` key, with optional `time` / `host` / `source` / `sourcetype` metadata keys at the same level | [Format events for HTTP Event Collector — Splunk Docs](https://docs.splunk.com/Documentation/Splunk/latest/Data/FormateventsforHTTPEventCollector) |
| Smoke-test curl shape (`curl -H "Authorization: Splunk <token>" … -d '{"event": …}'`) | [Set up and use HTTP Event Collector in Splunk Web — Splunk Docs](https://docs.splunk.com/Documentation/Splunk/latest/Data/UsetheHTTPEventCollector) (documented example) |

Notes:

- Splunk's own servers expose `/services/collector/event`; the skill deliberately does **not**
  claim the Fluency endpoint uses the same path — the installed connector's returned `url` is
  used verbatim, and the SKILL says so.
- The exact response body of the Fluency endpoint is not documented here; the smoke test judges
  by HTTP status plus the subsequent row count.
- Whether the platform supports in-place HEC token rotation is marked UNVERIFIED in the SKILL
  (Security notes / Failure modes); the documented fallback is replace-instance-and-repoint.
