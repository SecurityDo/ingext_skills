# References — Cisco Duo vendor-side steps

Verified 2026-07-24. Re-check at next skill revision; Duo occasionally reshuffles Admin Panel
paths and permission labels.

| Claim in SKILL.md | Source |
|---|---|
| Admin API application creation path: Admin Panel → Applications → Application Catalog → Admin API → + Add | [Duo Admin API — Cisco Duo](https://duo.com/docs/adminapi) |
| Only administrators with the **Owner** role can create or modify an Admin API application | [Duo Admin API — Cisco Duo](https://duo.com/docs/adminapi); [Duo Admin Roles — Cisco Duo](https://duo.com/docs/admin-roles) |
| The application page provides integration key (ikey), secret key (skey), and API hostname (`api-XXXXXXXX.duosecurity.com`) | [Duo Admin API — Cisco Duo](https://duo.com/docs/adminapi) |
| `Grant read log` permission covers "authentication, offline access, telephony, and administrator action log information" | [Duo Admin API — Cisco Duo](https://duo.com/docs/adminapi) |
| Other permission checkboxes to leave unchecked: Grant resource - Read / Write, Grant applications, Grant settings, Grant administrators | [Duo Admin API — Cisco Duo](https://duo.com/docs/adminapi) |
| Log endpoints behind Grant read log: authentication logs, administrator logs, telephony logs | [Duo Admin API — Cisco Duo](https://duo.com/docs/adminapi) |
| "Treat your secret key like a password" | [Duo Admin API — Cisco Duo](https://duo.com/docs/adminapi) |
| Reset Secret Key action; the previous secret key value cannot be made valid again after a reset; update the consuming application immediately | [Protecting Applications — Cisco Duo](https://duo.com/docs/protecting-applications) |
| Admin API applications are available to Duo Premier, Duo Advantage, and Duo Essentials plan customers | [Protecting Applications — Cisco Duo](https://duo.com/docs/protecting-applications) |

Notes:

- The failure-modes rows deliberately say "401-class" / "403-class" rather than quoting Duo's
  numeric API error codes — the codes were not verified at build time and the qualitative
  distinction (bad credential vs. missing permission) is what the operator needs.
- Duo API rate limits are referenced qualitatively on purpose; Duo does not publish a single
  fixed number for Admin API throttling.
- No secret-key expiry is documented — Duo Admin API secret keys do not age out; rotation is
  manual via Reset Secret Key.
