# References — Peplink syslog vendor-side steps & platform transport

Verified 2026-07-28.

## Peplink / Pepwave device side

| Claim in SKILL.md | Source |
|---|---|
| Remote syslog lives at **System → Event Log**; settings are enable + server address (IP or hostname) + port, default **514**; available across Balance / MediaFast / MAX | [Pepwave MAX firmware manual (official PDF, download.peplink.com)](https://download.peplink.com/manual/pepwave_max_firmware_manual-fw7.pdf); [Peplink Balance One user manual — Event Log page (ManualsLib copy of the official manual)](https://www.manualslib.com/manual/1123169/Peplink-Balance-One.html?page=213) |
| Delivery is **UDP**; the device offers no TCP or TLS option (TCP was a community feature request, not a shipped option) | [Peplink community — "Send Events to Remote Syslog Server"](https://forum.peplink.com/t/send-events-to-remote-syslog-server/6661); [Peplink community — "Syslog port"](https://forum.peplink.com/t/syslog-port/4388) — **secondary sources** (Peplink's own forum, staff-answered); the official manuals specify host + port only, with no protocol selector |
| The event log carries device events (WAN state, system/admin events); volume is modest | Same manuals — Event Log chapter |

Notes:

- The manuals are the primary source for the menu path and fields; the UDP-only claim rests on
  Peplink's community forum (staff answers) because the manuals are silent on protocol — labeled
  secondary per the research protocol. If a future firmware adds a protocol selector, prefer the
  device's own UI over this file.
- No claim is made about InControl (Peplink's cloud manager) pushing syslog settings — not
  verified, so the skill sticks to the device web admin UI.

## Fluency platform side (not vendor documentation)

The syslog transport mechanism is platform guidance from the Fluency team (2026-07-28), recorded
in `plans/connector-skills-rollout.md` (R1 resolution):

- `syslog_get_config` — read the site's syslog configuration.
- `syslog_register_config` — create it; **once per site, ever** — never when one exists.
- `syslog_update_config` — enable an additional listener (e.g. `syslog_udp`) on an existing
  configuration, leaving other listeners untouched.
- TLS-capable sources (not Peplink) use the `syslog_tls` listener with the platform CA
  certificate: https://fluency-public.s3.us-east-1.amazonaws.com/certs/ca.crt
- Exact parameter shapes come from the live MCP tool schemas at runtime.
