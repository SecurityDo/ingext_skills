---
name: automatic-create-ingext-ms-eventhub
version: 1.0.0
description: >-
  Automatic variant for integrating Fluency / Ingext with Microsoft Azure Event Hubs. On the
  Microsoft side it provisions, per Microsoft's documentation, an Event Hubs namespace, an event
  hub, and a Listen-only SAS policy, and captures the one value Ingext needs — the "Connection
  string–primary key". On the Fluency side it creates (or guides creating) an "Azure Event Hubs"
  connector whose endpoint parameter is that connection string. MODE A — the operator has rights
  in the target Azure subscription (Contributor+), so cowork runs a bundled script directly (Azure
  CLI / az preferred, PowerShell 7 / pwsh + Az modules as automatic fallback when az is absent)
  and the operator only completes the interactive sign-in when prompted; MODE B — a brief
  fallback that guides a third-party admin who runs it in their own subscription (cowork has no
  credentials there), via script or an Azure-portal walkthrough. Prefer this skill when the
  operator wants cowork to perform the Event Hubs setup for them. Triggers: "connect Ingext to
  Azure Event Hubs", "set up an event hub for Fluency", "stream Azure logs to Ingext via Event
  Hub", "create the ingext event hub for me". Do NOT use for the Entra audit-log importer app —
  that's automatic-create-ingext-azureaudit-app; nor the Defender incidents exporter app — that's
  automatic-create-ingext-defender-app; nor generic connector creation with existing credentials —
  that's add-connector.
---

# Integrate Ingext with Microsoft Azure Event Hubs — automatically (az CLI, pwsh fallback)

Set up the pipeline that lets Fluency / Ingext consume events from **Azure Event Hubs**:

- **Microsoft side** — an Event Hubs **namespace**, an **event hub**, and a **Listen-only shared
  access policy**, following Microsoft's standard Event Hubs quickstart flow.
- **Fluency / Ingext side** — an **Azure Event Hubs** connector (template `AzureEventHubs`). The
  **only item it requires from Microsoft is the "Connection string–primary key"** of that policy,
  which becomes the connector's `endpoint` parameter.

Two interchangeable scripts are bundled for the Microsoft side: Azure CLI (`az` + Bash, preferred)
and PowerShell 7 (`pwsh` + Az modules, the automatic fallback when `az` isn't installed). Both are
idempotent and print the same JSON. **cowork runs them for the operator** instead of handing them
instructions — the operator only signs in.

> **Scope note:** this skill ends when the connector has its connection string. Pointing producers
> (diagnostic settings, Defender streaming API, …) at the hub is the customer's follow-up — see
> "Getting events into the hub" below for orientation.

## What this creates

| Side | Item | Detail |
|---|---|---|
| Azure | Resource group | Default `ingext-eventhub-rg` (location `eastus`) |
| Azure | Event Hubs namespace | Default `ingext-ehns-<sub8>` (first 8 chars of subscription ID — deterministic, globally unique). SKU **Standard**, 1 throughput unit — **billable** |
| Azure | Event hub | Default `ingext-events`, 2 partitions, 24 h retention |
| Azure | SAS policy | Default `ingext-listen`, **Listen** right only, **on the event hub** so the connection string embeds `EntityPath` |
| Azure | Consumer group | `$Default` (a dedicated one only on request; Basic tier allows only `$Default`) |
| Ingext | Connector | Template `AzureEventHubs` ("Azure Event Hubs"), `endpoint` = the connection string |

> **Cost, unlike the app-registration skills:** an Event Hubs namespace is a **billable** Azure
> resource (per throughput unit per hour, plus ingress — roughly tens of US dollars/month for
> Standard at 1 TU; see Azure pricing). Say so before creating it. `--sku Basic` is cheaper but
> caps retention at 24 h and allows only the `$Default` consumer group.

A standalone reference (resource table, connection-string anatomy, connector parameter mapping,
optional checkpoint storage) lives in `assets/resources.md`.

---

## Prerequisites

- **One of two toolchains** on this machine — check in this order, and take the first hit:
  1. **Azure CLI** (`az version` succeeds) → use `assets/setup-ingext-eventhub.sh` (preferred).
  2. **PowerShell 7+** (`pwsh --version` succeeds) → use `assets/setup-ingext-eventhub.ps1`. It
     auto-installs the three Az submodules it needs on first run (`Az.Accounts`, `Az.Resources`,
     `Az.EventHub`) — no other setup.
  If **neither** is present, install Azure CLI
  (https://learn.microsoft.com/cli/azure/install-azure-cli) if feasible on this machine;
  otherwise fall back to Mode B.
- An identity with rights to create resource groups and Event Hubs resources in the **target
  subscription** — **Contributor** (or Owner) on the subscription, or Contributor on an existing
  resource group passed via `--resource-group`. Note this is Azure **RBAC on a subscription**, not
  the Entra directory-admin roles the app-registration skills need.
- To have cowork also create the Ingext connector: the **Fluency Ingext MCP** connected for the
  target Ingext instance. Without it, the operator pastes the connection string into the Fluency
  UI instead.

---

## Pick a mode

**Ask who is at the keyboard** (use `AskUserQuestion` if it isn't already clear):

- **Mode A — "I have Contributor on the target subscription and want cowork to run it."** cowork
  executes a bundled script on this machine (`az` if installed, `pwsh` otherwise), against the
  subscription the operator signs in to. This is the primary path — the setup is performed on the
  operator's behalf.
- **Mode B — "I'm onboarding a different customer's subscription / another admin will run it."**
  cowork does **not** run anything against that subscription (it has no credentials there). Hand
  the admin the script or the portal walkthrough and collect the connection string they report
  back.

> **Why the distinction matters:** creating Azure resources requires an interactive sign-in to the
> *target* subscription. In Mode A that subscription is the operator's own and the sign-in happens
> on this machine, so cowork can drive it. In Mode B the subscription belongs to someone else —
> cowork cannot authenticate there, so its role is to guide.

---

## Mode A — cowork runs the setup script (primary)

Precondition: the operator has Contributor (or equivalent) on the target subscription, and this
machine can complete an Azure sign-in.

**Run the script for the operator — don't hand them instructions.** The only thing they must do
themselves is complete the interactive sign-in when it appears. Tell them that up front ("a
sign-in prompt is about to appear — please authenticate with an account that has Contributor on
the target subscription"), then start. **Assume they will authenticate**; don't stop to ask
permission to run the script. cowork's normal per-command approval already governs what runs, and
both scripts are idempotent — safe to re-run.

### A1 — Pick the tooling

1. `az version` succeeds → **az path** (A2).
2. `az` missing but `pwsh --version` shows 7+ → **pwsh path** (A3).
3. Neither → install Azure CLI if feasible on this machine, else fall back to Mode B or another
   machine.

### A2 — az path

1. **Confirm the target subscription.** Run `az account show`. If it errors (not logged in), run
   the sign-in — the operator completes the browser/device step:

   ```bash
   az login                    # opens a browser
   # or, headless / no browser on this machine:
   az login --use-device-code  # prints a code; relay it and the operator finishes sign-in in a browser
   ```

   Then re-run `az account show` and **read back the subscription name + id and tenantId** so the
   operator confirms it is the intended subscription before anything is created — Event Hubs are
   subscription-scoped and billable, so this matters more here than in the app-registration
   skills. Switch if needed: `az account set --subscription <id-or-name>`.

2. **Run the bundled script:**

   ```bash
   bash ${SKILL_DIR}/assets/setup-ingext-eventhub.sh
   # optional overrides:
   bash ${SKILL_DIR}/assets/setup-ingext-eventhub.sh --resource-group my-rg --location westus2 --sku Basic
   bash ${SKILL_DIR}/assets/setup-ingext-eventhub.sh --namespace my-unique-ns --consumer-group ingext
   ```

   The script **stops for a confirmation prompt** (listing the resource group, namespace + SKU,
   event hub, and policy it is about to create in the shown subscription) unless run with
   `--yes`. Surface that prompt to the operator; only pass `--yes` if the operator has explicitly
   approved the target subscription.

What the sh script does, in order: preflight (`az` present + logged in) → read tenant +
subscription and confirm → register the `Microsoft.EventHub` resource provider if needed →
create/reuse the resource group → create/reuse the namespace (globally-unique-name hint on
failure) → create/reuse the event hub (handles old/new az retention flags) → create/reuse the
Listen-only hub-level SAS policy → optionally create a dedicated consumer group → fetch the
policy's **primary connection string** → print the JSON.

### A3 — pwsh path (az not installed)

The PowerShell script signs in via `Connect-AzAccount`, which drives its own authentication —
there is no prior `az login` equivalent. Just start the script and let the prompt appear. Pick the
auth flow from the machine's session:

- **Graphical session on this box** (`DISPLAY` / `WAYLAND_DISPLAY` set and a browser installed):

  ```bash
  pwsh ${SKILL_DIR}/assets/setup-ingext-eventhub.ps1
  ```

  A browser window opens on the operator's desktop for sign-in.

- **Headless** (no display):

  ```bash
  pwsh ${SKILL_DIR}/assets/setup-ingext-eventhub.ps1 -UseDeviceCode
  ```

  Relay the printed URL + code; the operator finishes sign-in in any browser.

Run it as a **background task and watch the output** — the first run installs three Az submodules
(`Az.Accounts`, `Az.Resources`, `Az.EventHub`, a few minutes) and the operator's sign-in takes as
long as it takes. Unlike the app-registration skills' ps1, **this one does prompt**: after
printing `Connected to tenant …` and `Subscription: '<name>' (<id>) as <account>`, it stops at a
`Proceed? [y/N]` confirmation (skippable with `-Yes`) because it creates billable resources —
surface that prompt and the subscription line to the operator. If the wrong subscription is shown,
abort and re-run with `-SubscriptionId <guid>`.

What the ps1 script does, in order: ensure/import Az modules → `Connect-AzAccount` (reusing an
existing context if present) → read tenant + subscription from `Get-AzContext` and confirm →
register the `Microsoft.EventHub` provider if needed → create/reuse the resource group, namespace,
event hub (parameter detection across Az.EventHub versions), and Listen-only hub-level SAS policy
→ optionally create a dedicated consumer group → `Get-AzEventHubKey` → print the JSON.

### A4 — Capture the output

Both scripts end by printing the JSON object (the sh script writes **only** JSON to stdout with
progress on stderr; the ps1 script prints it after a banner):

```json
{
  "connectionString": "Endpoint=sb://…;SharedAccessKeyName=ingext-listen;SharedAccessKey=…;EntityPath=ingext-events",
  "namespace": "…", "eventHub": "…", "resourceGroup": "…", "location": "…", "consumerGroup": "$Default"
}
```

`connectionString` **is** the "Connection string–primary key". Treat it as a credential — don't
echo it into logs or long-lived chat beyond handing it to the connector step. (Unlike an app
secret it is re-retrievable from **Shared access policies** and rotatable by regenerating the
key, so a lost value is an inconvenience, not an incident.)

---

## Mode B — guide a third-party admin (fallback)

cowork cannot reach the customer's subscription. Offer the admin either path; the deliverable is
the same connection string (plus the event hub / consumer group names for reference).

### Path B1 — az CLI script (recommended for Linux/macOS admins)

Give the admin the script at `${SKILL_DIR}/assets/setup-ingext-eventhub.sh` (or paste its contents
to save and run). Tell them to:

1. Install Azure CLI if needed, then `az login` (or `az login --use-device-code`) as an identity
   with **Contributor** on the intended subscription; `az account set --subscription <id>` if they
   have several.
2. Run `bash setup-ingext-eventhub.sh` and answer the confirmation prompt (it names the
   subscription and the billable namespace before creating anything).
3. Copy the printed JSON — above all the `connectionString` — back to you.

For an admin who prefers PowerShell (e.g. on Windows), hand them
`${SKILL_DIR}/assets/setup-ingext-eventhub.ps1` instead — PowerShell 7+, same JSON output, and it
installs its own Az modules on first run.

### Path B2 — manual Azure portal walkthrough

Direct the admin through **[https://portal.azure.com](https://portal.azure.com)**, following
Microsoft's Event Hubs quickstart:

1. **Create the namespace.** Search **Event Hubs** → **+ Create**. Pick the subscription and a
   resource group (create `ingext-eventhub-rg` if none), a **globally unique namespace name**, a
   region, pricing tier **Standard** (Basic is cheaper but 24 h retention max and `$Default`-only
   consumer groups), throughput units **1**. **Review + create → Create**.
2. **Create the event hub.** Open the namespace → **+ Event Hub**. Name it **`ingext-events`**,
   partition count **2**, retention **24 h** (Delete cleanup policy). **Create**.
3. **Create a Listen-only policy on the hub.** Namespace → **Entities → Event Hubs →
   `ingext-events` → Shared access policies → + Add.** Name **`ingext-listen`**, check **Listen**
   only. **Create.** (Creating it on the *event hub*, not the namespace, keeps rights minimal and
   embeds `EntityPath` in the connection string.)
4. **Copy the connection string.** Click the new policy — copy **Connection string–primary key**.
   That single value is everything Ingext needs; send it back. (If they instead hand you the
   namespace-level `RootManageSharedAccessKey` string, it lacks `EntityPath` and over-grants —
   ask for a hub-level Listen policy, or at minimum append `;EntityPath=ingext-events`.)

---

## Ingext side — create the "Azure Event Hubs" connector

With the connection string in hand, finish the integration on the Fluency / Ingext side. **If the
Fluency Ingext MCP is connected, do this for the operator too:**

1. Call `list_connector_templates` and locate the **`AzureEventHubs`** template (display name
   "Azure Event Hubs") to confirm its current parameter schema.
2. Call `create_connector` with:
   - `application`: `AzureEventHubs`
   - `instance`: a unique lowercase id, e.g. `eventhub1`
   - `displayName`: something the operator will recognize, e.g. `Azure Event Hubs — ingext-events`
   - `inputParameters`: `endpoint` = the **connection string** (required); add `consumerGroup`
     only if a dedicated group was created; leave `datalake`/`index` at their defaults
     (`managed` / `AzureEventHubs`) unless the operator wants otherwise. `storageEndpoint` +
     `containerName` only if checkpoint storage was provisioned (see `assets/resources.md`).
3. Verify with `list_connectors` / `get_connector` that the instance exists and reports healthy.

**Without the MCP**, walk the operator through the Fluency UI: **Connectors / Integrations → Add →
Azure Event Hubs**, paste the **Connection string–primary key** into the **Event Hub endpoint**
field, leave the optional fields blank, save.

---

## Getting events into the hub (orientation, not this skill's job)

An empty hub imports nothing — something on the Microsoft side must stream **into** it. Point the
customer at the usual producers, each configured in its own UI by picking the namespace + hub:

- **Azure Monitor diagnostic settings** on any resource / the Activity log → *Stream to an event
  hub*.
- **Microsoft Entra ID → Diagnostic settings** for sign-in and audit logs.
- **Microsoft Defender XDR → Streaming API** for raw Defender events.

Details and links live in `assets/resources.md`.

---

## Output — the deliverable

Present the result both human-readably and as a JSON block so a calling onboarding task can parse
it deterministically. The `connectionString` (the portal's **"Connection string–primary key"**)
is the field the Ingext connector consumes as `endpoint`:

```json
{
  "connectionString": "Endpoint=sb://<ns>.servicebus.windows.net/;SharedAccessKeyName=ingext-listen;SharedAccessKey=<key>;EntityPath=<hub>",
  "namespace": "<namespace>",
  "eventHub": "<event hub name>",
  "resourceGroup": "<resource group>",
  "location": "<region>",
  "consumerGroup": "$Default"
}
```

If the connector was created via MCP, also report its `instance` id and health.

---

## Verification

- **Connection string shape:** starts with `Endpoint=sb://`, contains
  `SharedAccessKeyName=ingext-listen` (or the chosen policy) and an `EntityPath=` — no
  `Manage`/`Send`-bearing `RootManageSharedAccessKey`.
- **Azure resources:**
  `az eventhubs eventhub show --resource-group <rg> --namespace-name <ns> --name <hub>` succeeds,
  and `az eventhubs eventhub authorization-rule show … --name ingext-listen` lists rights
  `["Listen"]`.
- **Connector:** `get_connector` (MCP) or the Fluency UI shows the instance; once a producer
  streams into the hub, events land in the `AzureEventHubs` index (spot-check with `kql_search`).
- In Mode B you cannot verify inside the customer's subscription — rely on the admin's
  confirmation or the script's printed output.

---

## Failure modes

| Situation | Response |
|---|---|
| `az account show` fails / "Please run 'az login'" | Not signed in. Run `az login` (or `az login --use-device-code`), confirm the subscription, then re-run the script. |
| `az` is not installed | Fall back to the bundled PowerShell script (Mode A3) if `pwsh` 7+ is present. Otherwise install Azure CLI (https://learn.microsoft.com/cli/azure/install-azure-cli) or fall back to Mode B. |
| `pwsh` present but PowerShell < 7 | The ps1 script throws on startup. Install PowerShell 7 (`pwsh`), or use the az path / Mode B. |
| ps1 module install fails (locked-down PSGallery) | Stage `Az.Accounts` + `Az.Resources` + `Az.EventHub` manually, then re-run with `-SkipModuleInstall`. |
| Account has multiple subscriptions / wrong one shown | Both scripts print the subscription and stop at a confirmation prompt before creating anything. Switch with `az account set --subscription <id>` (sh) or `-SubscriptionId <guid>` (ps1), then re-run. |
| Namespace name "not available" / taken | Namespace names are global DNS names. Re-run with `--namespace` / `-NamespaceName <another-globally-unique-name>`. |
| `Microsoft.EventHub` provider not registered | Both scripts register it (best-effort, first use in a subscription). If creation still fails, run `az provider register --namespace Microsoft.EventHub --wait` as a subscription Contributor/Owner and re-run. |
| Authorization / `AuthorizationFailed` on create | The signed-in identity lacks RBAC on the subscription or resource group. Grant Contributor (or have an admin run the script — Mode B). |
| Event hub create rejects retention flags | az/Az versions renamed the retention parameters; both scripts fall back automatically (legacy `--message-retention` / `MessageRetentionInDays`, then provider defaults). Retention can be adjusted later in the portal. |
| Consumer-group create fails on Basic tier | Expected — Basic allows only `$Default`. Use `$Default` (scripts fall back with a warning) or recreate the namespace as Standard. |
| Customer supplies a namespace-level connection string | It lacks `EntityPath` and usually over-grants (`RootManageSharedAccessKey`). Ask for a hub-level Listen-only policy's string, or append `;EntityPath=<hub>` as a stopgap. |
| Resources already exist | Expected on re-runs — the scripts reuse every existing resource and just re-fetch the connection string. |
| Connector shows no events | The connector only reads; check that a producer (diagnostic settings, Defender streaming, …) is streaming into this specific hub, and that `consumerGroup` matches an existing group. |
| Connection string value lost | Not an incident — re-fetch it any time from **Shared access policies** or by re-running the script. |

---

## Security & cost notes

- The SAS policy carries the **Listen** right only, scoped to a single event hub — least privilege
  for a consumer. Never hand Ingext the namespace `RootManageSharedAccessKey`.
- The connection string is a credential: don't paste it into logs, tickets, or persistent chat
  beyond handing it to the connector. It does not expire; rotate it by **regenerating the
  policy's primary key** (portal → policy → Regenerate primary key, or
  `az eventhubs eventhub authorization-rule keys renew --key PrimaryKey …`) and updating the
  connector.
- **Billable resource:** the namespace accrues charges as long as it exists (per throughput unit
  per hour, plus ingress). Tell the operator, and when an integration is retired delete the
  namespace (or the whole `ingext-eventhub-rg` resource group) to stop the meter.
- **Mode A** creates resources in whatever subscription the sign-in selects — both scripts read
  the subscription back and stop at a confirmation prompt before creating anything; prefer that
  prompt over `--yes` / `-Yes`.

---

## Layout

```
automatic-create-ingext-ms-eventhub/
├── SKILL.md
├── assets/
│   ├── setup-ingext-eventhub.sh    ← az CLI script: namespace + hub + Listen policy, prints the connection string JSON
│   ├── setup-ingext-eventhub.ps1   ← PowerShell 7 fallback (Az modules): same job, same output
│   └── resources.md                ← reference: resources, connection-string anatomy, connector mapping, producers
└── evals/
    └── evals.json                  ← trigger phrases for skill selection
```
