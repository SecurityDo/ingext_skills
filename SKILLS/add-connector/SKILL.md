---
name: add-connector
version: 1.0.0
description: >
  Add (install) a new application connector on Ingext / Fluency. Use this skill whenever
  the user asks to "add an application", "install a connector", "connect [app name]",
  "set up [product] integration", "add [vendor] to Fluency / Ingext", "start ingesting logs
  from X", or wants to bring a new data source into the platform. The skill discovers all
  available connector templates, matches the user's request, gathers any required credentials
  or configuration interactively, and installs the connector. Trigger proactively any time
  the user mentions onboarding a new tool, vendor, or log source into Ingext — even if they
  don't say "connector" explicitly.
---

# Add a Connector (Application) on Ingext

This skill walks through discovering, configuring, and installing a connector — the term the
platform uses for an application integration. The user may call these "applications", "integrations",
or "data sources"; treat all of these as synonymous with connectors.

## Tools available

The FPL MCP tools you will use are:

| Tool | Purpose |
|------|---------|
| `list_connector_templates` | Discover every application the platform supports, including its required parameters |
| `list_connectors` | See what connectors are already installed |
| `create_connector` | Install a new connector instance |
| `list_instance_roles` | List platform-managed IAM roles (used for AWS Role auth method) |
| `list_integrations` | List platform integrations; filter by `type == "AWS User"` for AWS User auth method |

---

## Step 1 — Discover available templates

Call `list_connector_templates` immediately. Do NOT skip this step even if you think you know
the template name — the parameter schema must come from the live API, not from memory.

Each template entry contains:

```
{
  name:          string   (internal template ID — used in create_connector)
  displayName:   string   (human-readable name)
  description:   string
  category:      string   (endpoint | cloud | office | email | onpremise | aws | business | system)
  parameters?:   Parameter[]
  output?:       OutputField[]
}
```

A `Parameter` looks like:

```
{
  name:          string
  description:   string
  dataType:      string
  optional?:     boolean  (absent means required)
  sensitive?:    boolean  (API keys, secrets — handle with care)
  defaultValue?: string
  enums?:        { value, label }[]
  isList?:       boolean
}
```

An `OutputField` is a value the platform generates after installation (e.g., a HEC URL and token
the source device needs). Capture and display these after a successful install.

---

## Step 2 — Match the user's request to a template

Match against `displayName`, `name`, and `description` using case-insensitive fuzzy matching.
Common aliases to handle:

- "Office 365" / "O365" / "Microsoft 365" → Office365
- "Google Workspace" / "GSuite" / "G Suite" → GSuite
- "FortiGate" / "Fortinet" → FortiGateFWLog or FortiGateFWLogV2
- "Azure AD" / "Entra" → AzureAudit
- "Defender" → MSDefender
- "SentinelOne" / "S1" → SentinelOneAPI
- "Trend Micro" / "Vision One" → TrendMicroVisionOne
- "Bitdefender" / "GravityZone" → BitdefenderST or BitdefenderEP
- "Proofpoint" → ProofpointTAP or ProofpointEssentials
- "AWS" / "CloudTrail" → AWSCloudTrail
- "GuardDuty" → AmazonGuardDuty

**No match:** Tell the user the application isn't available, then list all templates grouped by
category. Stop — do not attempt to install anything.

**Multiple matches** (e.g., "Bitdefender" could be BitdefenderST or BitdefenderEP): present the
options briefly and ask which variant the user wants before continuing.

---

## Step 3 — Check existing connectors

Call `list_connectors`. If a connector with the same `application` (template name) already exists,
inform the user and show the existing instance ID and state. Ask whether they want a second
instance anyway. If not, stop.

---

## Step 4 — Collect required configuration

Classify each template parameter:

- **Required** — `optional` absent/false AND no `defaultValue`: must collect before creating
- **Has default** — has `defaultValue`: use the default silently unless the user specified otherwise
- **Optional** — `optional: true` and no default: skip unless the user explicitly wants to set it

For any required params not already in the user's message, use `AskUserQuestion` to gather them
in one batch (up to 4 questions). If more than 4 are needed, handle the most critical ones first.

Guidance when prompting:
- `sensitive: true` → label it clearly as a credential/secret
- `enums` present → present the choices so the user picks the right value
- `isList: true` → ask the user for a comma-separated list

### Special handling: AWS authentication

Some AWS connectors (e.g., AWSCloudTrail, AWSCloudWatchLogGroupS3, AWSFluentbitS3,
AmazonGuardDuty) include three optional-looking auth parameters:

| Parameter | Description |
|-----------|-------------|
| `AWS_Role` | Pre-defined IAM Role (platform-managed) |
| `AWS_User` | Pre-defined IAM User (platform-managed) |
| `IAM_AccessKey` + `IAM_AccessSecret` | IAM access key and secret key pair (manual) |

Although these are individually marked `optional`, **exactly one authentication method is
required** for the connector to function. Treat them as a mutually exclusive required group.

**Workflow:**

1. If the user has not specified an auth method, ask them to choose one of the three options
   before proceeding.

2. Based on the chosen method, do the following **before** calling `create_connector`:

   **IAM Role:**
   - Call `list_instance_roles` and present the available roles to the user (show `displayName`
     and `roleARN` for each).
   - Ask the user which role to use. Use that role's **`displayName`** as the value of `AWS_Role`
     in `inputParameters` (NOT the `id` field).
   - Do NOT include `AWS_User`, `IAM_AccessKey`, or `IAM_AccessSecret`.

   **IAM User:**
   - Call `list_integrations` and filter results to entries where `integration == "AWSUser"`.
   - Present the filtered list to the user (show `name` for each).
   - Ask the user which user to use. Use that entry's **`name`** as the value of `AWS_User` in
     `inputParameters` (NOT the `id` field).
   - Do NOT include `AWS_Role`, `IAM_AccessKey`, or `IAM_AccessSecret`.

   **Access Key / Secret:**
   - Prompt the user for `IAM_AccessKey` and `IAM_AccessSecret` directly (no platform lookup).
   - Do NOT include `AWS_Role` or `AWS_User`.

---

## Step 5 — Derive the instance ID

Build a clean instance ID from the template's `name`:
1. Lowercase the template name
2. Strip or replace special characters with hyphens
3. Keep it ≤ 20 characters

**Never use `"default"` as an instance ID.** The platform commonly has pre-existing connectors
registered under `"default"`, and reusing that ID will silently conflict with or overwrite them.
Always derive the ID from the template name (e.g. `SentinelOneAPI` → `sentineloneapi`,
`Office365` → `office365`, `FortiGateFWLog` → `fortigatefwlog`).

If `list_connectors` already has that derived ID, append `-2`, `-3`, etc. until you find one
that's free.

---

## Step 6 — Create the connector

Call `create_connector` with:
- `application`: the template's `name` (exact, case-sensitive)
- `instance`: the derived ID
- `displayName`: derived from the instance ID to match it human-readably. Take the
  template's `displayName` as the base, then append any suffix from the instance ID.
  Convert hyphens to spaces and capitalise words naturally.

  Examples:
  - instance `office365` → display name `Office365`
  - instance `office365-2` → display name `Office365 2`
  - instance `sentineloneapi` → display name `SentinelOne API`
  - instance `sentinelone-usea1` → display name `SentinelOne API usea1`
  - instance `fortigatefwlog-2` → display name `FortiGate NGFW Syslog 2`

  The display name should always make it obvious which instance it refers to.
- `inputParameters`: include **every parameter defined in the template schema** — not just
  the required ones. The platform requires the full parameter list to be present. For each
  parameter, determine the value as follows:
  - User provided a value → use it
  - No user value but `defaultValue` exists → use the `defaultValue`
  - Optional param with no value and no default → include it with an empty string `""`
  
  Do NOT omit any parameter from the template, even optional or defaulted ones.

---

## Step 7 — Report the result

**On success:**
1. Confirm the install with the instance ID.
2. If `output` fields exist on the template: display each field name and description. These are
   configuration values the user needs to enter in their source device or application.
3. **Syslog connectors** (no `parameters`, description contains "Syslog"): note that the user
   must configure their device to forward syslog to the Fluency Syslog Endpoint (find the
   IP/port in the platform under Connectors).
4. **OAuth/consent connectors** (only param is `adminConsentEmail`, e.g., Office365, AzureAudit,
   GSuite): note that a consent email will be sent to the provided address and the admin must
   complete the OAuth authorization flow before data starts flowing.

**On failure:** surface the error clearly and suggest corrective action (wrong credentials,
duplicate instance ID, permission issue, etc.).

---

## Example interactions

**API connector with all params supplied:**
> "Add SentinelOne to Ingext. URL is https://usea1.sentinelone.net, token is S1-xxxx."
> → Match SentinelOneAPI. Both required params present. Create. Confirm.

**Syslog connector (no config needed):**
> "I want to add a FortiGate firewall."
> → Match FortiGateFWLog (ask V1 vs V2 if unsure). No params needed.
> → Create. Tell user to point syslog at the Fluency endpoint.

**OAuth connector:**
> "Connect our Office 365 tenant."
> → Match Office365. Ask for adminConsentEmail. Create. Note consent flow.

**AWS connector — IAM Role auth:**
> "Add AWS CloudTrail."
> → Match AWSCloudTrail. Ask for SQS URL and which auth method (Role / User / Access Key+Secret).
> → User picks IAM Role. Call `list_instance_roles`, display roles by `displayName`, user picks one.
> → Pass only `AWS_Role` = the chosen role's `displayName` (e.g. "DevelopAccount") in inputParameters.
> → Do NOT include AWS_User, IAM_AccessKey, or IAM_AccessSecret.

**AWS connector — IAM User auth:**
> "Add AWS CloudTrail, use the AWS User."
> → Match AWSCloudTrail. Ask for SQS URL. User picks IAM User method.
> → Call `list_integrations`, filter to `integration == "AWSUser"`, display the list by `name`, user picks one.
> → Pass only `AWS_User` = the chosen entry's `name` (e.g. "testUser") in inputParameters.
> → Do NOT include AWS_Role, IAM_AccessKey, or IAM_AccessSecret.

**Ambiguous match:**
> "Add Bitdefender."
> → BitdefenderST vs BitdefenderEP: present both, ask which. Then proceed.

**No match:**
> "Add CrowdStrike."
> → Not available. List all templates by category. Stop.
