# Ingext ↔ Azure Event Hubs — resources & connection string reference

Fluency / Ingext consumes events from an Azure **event hub** using a SAS **connection string** —
the value the Azure portal labels **"Connection string–primary key"**. That one value is the only
thing Ingext needs from Microsoft. This reference covers what the bundled scripts
(`setup-ingext-eventhub.sh` for az CLI, `setup-ingext-eventhub.ps1` for PowerShell 7 / Az modules)
create, how the connection string is put together, and how the fields map onto the Ingext
**Azure Event Hubs** connector.

## Azure resources created (defaults)

| Resource | Default name | Notes |
|---|---|---|
| Resource group | `ingext-eventhub-rg` | Location `eastus` by default |
| Event Hubs namespace | `ingext-ehns-<sub8>` | `<sub8>` = first 8 chars of the subscription ID, so re-runs are deterministic. **Globally unique DNS name**; SKU **Standard**, 1 throughput unit — **billable** |
| Event hub | `ingext-events` | 2 partitions, 24 h retention |
| SAS policy | `ingext-listen` | **Listen** right only, created **on the event hub** (not the namespace) |
| Consumer group | `$Default` | A dedicated one (e.g. `ingext`) only with `--consumer-group` / `-ConsumerGroup`; Basic tier supports only `$Default` |

## Anatomy of the connection string

A hub-level policy's "Connection string–primary key" looks like:

```
Endpoint=sb://<namespace>.servicebus.windows.net/;SharedAccessKeyName=ingext-listen;SharedAccessKey=<key>;EntityPath=<event-hub-name>
```

- `Endpoint` — the namespace's service-bus DNS name.
- `SharedAccessKeyName` / `SharedAccessKey` — the SAS policy and its primary key.
- `EntityPath` — the event hub name. **Present only when the policy was created on the event
  hub itself.** A namespace-level policy (e.g. the built-in `RootManageSharedAccessKey`) omits it —
  if a customer hands you such a string, append `;EntityPath=<event-hub-name>` before giving it to
  Ingext, and prefer replacing it with a hub-level Listen-only policy: `RootManageSharedAccessKey`
  carries **Manage** rights over the whole namespace, far more than Ingext needs.

Unlike an Entra client secret, the connection string is **re-retrievable** any time (portal →
Shared access policies, or `az eventhubs eventhub authorization-rule keys list`) and rotatable by
regenerating the policy's key.

## Where "Connection string–primary key" lives in the portal

**Event Hubs namespace → Entities → Event Hubs → *your hub* → Shared access policies → *your
policy*** — the flyout shows *Primary key*, *Secondary key*, **Connection string–primary key**,
and *Connection string–secondary key*. Copy the **Connection string–primary key**.

## Mapping onto the Ingext "Azure Event Hubs" connector

Connector template `AzureEventHubs` (display name **Azure Event Hubs**, category `cloud`):

| Connector parameter | Required | Value |
|---|---|---|
| `endpoint` | **yes** (sensitive) | The **Connection string–primary key** (with `EntityPath`) |
| `consumerGroup` | no | Only if a dedicated consumer group was created (default `$Default`) |
| `storageEndpoint` | no (sensitive) | Azure Storage connection string for checkpointing (see below) |
| `containerName` | no | Blob container for the checkpoints |
| `description` | no | Free text |
| `datalake` / `index` | no | Default `managed` / `AzureEventHubs` |

## Optional: blob-storage checkpointing

For high-volume, multi-partition hubs, Ingext can persist its read position (checkpoints) in an
Azure Storage container so restarts resume instead of rereading. To provision one:

```bash
az storage account create --resource-group ingext-eventhub-rg --name <globally-unique-name> \
  --location eastus --sku Standard_LRS
az storage container create --account-name <name> --name ingext-checkpoints --auth-mode login
az storage account show-connection-string --resource-group ingext-eventhub-rg --name <name> \
  --query connectionString -o tsv
```

Give the printed connection string as `storageEndpoint` and `ingext-checkpoints` as
`containerName`. Skip this entirely for a first integration — the connector works without it.

## Getting events INTO the hub

Creating the hub gives Ingext somewhere to read from; something must also write to it. Common
producers, each configured on the Microsoft side:

- **Azure Monitor diagnostic settings** — on almost any Azure resource (and the subscription's
  Activity log): *Diagnostic settings → Add → Stream to an event hub*, pick the namespace + hub.
- **Microsoft Entra ID logs** — Entra ID → *Diagnostic settings* → stream sign-in/audit logs.
- **Microsoft Defender XDR streaming API** — Defender portal → *Settings → Microsoft Defender XDR
  → Streaming API*, target the hub.
- Any AMQP/Kafka producer the customer already runs.

Streaming to an event hub generally requires the **namespace** to allow the producer to send
(Azure-managed exports handle this themselves once you pick the hub in their UI).
