# References — Bitdefender GravityZone vendor-side steps

Verified 2026-07-24. Re-check at next skill revision; Bitdefender reorganizes the GravityZone
policy documentation periodically (the Security Telemetry section is referenced under two
slightly different paths across their own pages — both recorded below).

**Fetch caveat:** Bitdefender's support-center pages load article content via JavaScript, so
automated fetch returns only the navigation tree. The claims below were verified from the
indexed content excerpts of Bitdefender's **own** support articles (primary sources) via web
search at build time.

| Claim in SKILL.md | Source |
|---|---|
| Security Telemetry is configured in the policy: General → Security Telemetry; enable the Security Telemetry option | [Send security telemetry from GravityZone to Splunk Enterprise — Bitdefender support](https://www.bitdefender.com/business/support/en/77209-158569-send-security-telemetry-from-gravityzone-to-splunk-enterprise.html); [Security Telemetry — Bitdefender support](https://www.bitdefender.com/business/support/en/77209-342928-security-telemetry.html) |
| Same section also referenced as "General → Agent → Security Telemetry" in Bitdefender's docs | [Raw Events — Bitdefender support](https://www.bitdefender.com/business/support/en/77209-244521-raw-events.html) |
| SIEM Connection Settings: enter the SIEM server URL and the (Splunk / HTTP Event Collector) token | [Send security telemetry from GravityZone to Splunk Enterprise — Bitdefender support](https://www.bitdefender.com/business/support/en/77209-158569-send-security-telemetry-from-gravityzone-to-splunk-enterprise.html) |
| HTTPS with TLS 1.2 or higher required, otherwise event submission fails; optional "Bypass collector CA validation" and "Ignore SSL errors" toggles exist for certificate problems | [Security Telemetry — Bitdefender support](https://www.bitdefender.com/business/support/en/77209-342928-security-telemetry.html); [Send security telemetry from GravityZone to Splunk Enterprise — Bitdefender support](https://www.bitdefender.com/business/support/en/77209-158569-send-security-telemetry-from-gravityzone-to-splunk-enterprise.html) |
| The security agent sends the events as JSON directly (from endpoints) to the SIEM target | [Send security telemetry from GravityZone to Splunk Enterprise — Bitdefender support](https://www.bitdefender.com/business/support/en/77209-158569-send-security-telemetry-from-gravityzone-to-splunk-enterprise.html) |
| Security Telemetry requires a license that provides access to the EDR feature; endpoints need the BEST agent with the EDR sensor module enabled and an EDR-enabled policy | [Security Telemetry — Bitdefender support](https://www.bitdefender.com/business/support/en/77209-342928-security-telemetry.html); [Raw Events — Bitdefender support](https://www.bitdefender.com/business/support/en/77209-244521-raw-events.html) |
| DNS query and network connection events require the Network Attack Defense module installed and enabled | [Raw Events — Bitdefender support](https://www.bitdefender.com/business/support/en/77209-244521-raw-events.html) |
| Sibling variant: Event Push Service API (`setPushEventSettings`) is a separate mechanism (the `BitdefenderEP` template's territory, not this skill's) | [setPushEventSettings — Bitdefender support](https://www.bitdefender.com/business/support/en/77209-135319-setpusheventsettings.html) |
| The `BitdefenderST` template has no input parameters and outputs `url` (HEC Server URL) + `token` (HEC Token, sensitive) | Live `list_connector_templates` schema for `BitdefenderST`, fetched 2026-07-24 (platform-side fact, not a vendor claim) |

Notes:

- **Product tiers are deliberately not named.** The verifiable formulation is "a license that
  provides access to the EDR feature" — Bitdefender's indexed pages did not yield a named
  tier-by-tier availability list at build time, and inventing one would violate the
  do-not-guess rule. The skill's failure-modes table uses the absence of the Security Telemetry
  policy section as the practical license diagnostic.
- **Per-OS telemetry support is deliberately not claimed.** The GravityZone platform covers
  Windows/macOS/Linux broadly, but a telemetry-specific OS matrix was not verifiable; see
  Bitdefender's "Features by endpoint type" page
  (https://www.bitdefender.com/business/support/en/77209-376324-features-by-asset-type.html)
  when this matters to a customer.
- The exact list of selectable telemetry event categories is left to the console — the skill
  instructs choosing from what the section offers rather than asserting a list.
