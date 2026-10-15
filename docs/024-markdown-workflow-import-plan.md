# Import a workflow from agent Markdown files

Status: implemented (I1-I4), with local validation recorded in the
[implementation ledger](003-agent-control-implementation-status.md).
See the [runtime guide](025-markdown-workflow-import.md) for usage and limits.

Updated 2026-10-12. This plan covers the requested import into a new workspace:
one selected agent Markdown file becomes one bot, its Markdown body becomes the
bot's instructions, the workspace defaults to a shared computer, and every
imported bot can message the others through the existing **Bot channel**.

## Scope and decisions

| Concern | Proposed behavior |
| --- | --- |
| Input | Multiple local `.md` files, including `.agent.md`, selected or dropped together. |
| Destination | A new workspace owned by the signed-in user; all imported bots have that owner. |
| Mapping | Exactly one bot per selected file, including files with identical contents. |
| Instructions | Preserve the decoded Markdown body after removing leading frontmatter. |
| Bot name | Suggest frontmatter `name`, otherwise the filename without `.agent.md` or `.md`; editable in preview. |
| Public purpose | Suggest frontmatter `description`; editable and shown as workspace-visible information. |
| Runtime | Choose a common framework, existing model credential, and model, with per-bot overrides. |
| Computer | Save `mode=shared`, `provider=docker` when importing. Subsequent changes use existing workspace settings. |
| Collaboration | Enable automatic collaboration and enroll every imported bot with the messaging bundle selected. |
| Execution | Import saves configuration. The user starts a task or creates the shared computer through existing controls. |

For this feature, a workflow is the collection of agent definitions and their
collaboration instructions. The importer does not infer a group, execution graph,
lead agent, routine, or initial task. References to other agents in the body stay
as written; the existing runtime directory provides bot IDs and public purposes.
Keep suggested names when possible so existing natural-language references remain
useful. Framework-specific delegation syntax may need later user edits.

The initial import supports Microsoft and Anthropic bots using the shared Docker
computer. UFO and paired Windows computers cannot participate in shared-computer
mode today. Azure configuration remains available through the workspace computer
settings after import. ZIP archives, repository URLs, importing into an existing
workspace, re-import synchronization, and copying referenced files or tool packages
are outside this initial delivery.

Ordinary workspace creation keeps its current defaults. Imported workspaces start
with all imported bots enrolled; future manual bots retain the existing explicit
enrollment behavior. Autopilot starts with the normal new-bot setting and is not
enabled by the import.

## Existing implementation and required changes

The [implementation ledger](003-agent-control-implementation-status.md) records
implemented workspace channels and shared-computer work in the current working
tree. Review those changes before implementation and preserve unrelated edits.
The [channel plan](014-agent-control-workspace-channel-plan.md),
[channel runtime](015-agent-control-workspace-channel-runtime.md),
[shared-computer guide](023-shared-workspace-computer.md), and
[ADR-0018](adr/0018-optional-shared-workspace-computer.md) supply the underlying
behavior; this feature should compose it.

| Existing boundary | Import work |
| --- | --- |
| `workspaces/http.py` creates a workspace, owner membership, and channel. | Extract reusable transaction-aware creation helpers. |
| `app/http.py` creates one bot, stream, tool selection, and optional enrollment atomically. | Reuse that behavior for a batch without calling individual HTTP endpoints. |
| `store/bots.py` accepts an existing transaction through `_db`. | Validate credentials and create all bots on the import transaction's connection. |
| `store/__init__.py::_instructions` trims text and limits it to 16,000 characters. | Separate validation from trimming and provide an explicit preservation path for imported instructions. |
| `channels/membership.py` publishes bots and enrolls them; `configure` opens its own transaction. | Expose transaction-aware enrollment/configuration helpers, including the reviewed public purpose. |
| `shared_computers/settings.py` persists computer mode using its own transaction. | Expose validated initialization for a new workspace within the import transaction. |
| `WorkspaceCenter.tsx` contains the current create-workspace form. | Add an Import workflow entry and a separate import feature UI. |

Retain current behavior for existing bot creation/editing APIs while adding the
explicit instruction-preservation path. Test both paths. Do not put import logic
or imported agent definitions into the portable kernel or built-in product tools.

## Import experience

1. Choose **Import workflow** beside **Create workspace** in Workspace settings.
   Enter the new workspace name and select the agent Markdown files.
2. Show every selected filename with its detected name, public purpose, body
   preview, and validation results. Allow removing a selected file or replacing
   it before import. Never silently skip, merge, or truncate a file.
3. Choose a common framework, saved API key, model, and ordinary computer-tool
   selection. Permit per-bot overrides using existing compatibility rules and
   tool pickers. The Bot channel bundle is always included for this import.
   If no compatible key exists, provide the existing API-key setup link and keep
   the import draft in memory while the user configures it.
4. Review the resolved bot names, purposes, runtime settings, **Shared Docker
   computer**, and **Messaging enabled for all bots**. Explain that the bots share
   files, browser tabs, and desktop state. Require valid, distinct display names
   within the import, compared case-insensitively; highlight collisions for edits.
5. **Import workflow** submits one batch command. Disable repeat submission while
   pending. File/configuration edits invalidate the previous preview.
6. Show the created workspace and all bots with links to **Bot channel** and the
   shared computer controls. Select the workspace and invalidate the existing
   workspace, bot, directory, channel, and computer queries. A preference-update
   failure must not report the import as failed or cause another import.

The user can immediately submit a communication-only task in Bot channel with
valid model credentials. Computer work requires the shared computer to be created
and running. Show that state explicitly; joining the channel does not launch bots
or provision a computer. Later computer actions retain their normal approvals,
leases, action locks, and recovery rules.

## Markdown contract

Use a deterministic backend parser as the source of truth. The browser reads
UTF-8 strictly and preserves line endings; the backend validates the submitted
text again. Remove one optional initial UTF-8 BOM as encoding metadata.

- Recognize YAML frontmatter only when the first line is exactly `---`. Its
  closing line must be exactly `---` or `...`. Remove that opening line, metadata,
  closing line, and the closing line's terminator. Preserve every character after
  that boundary, including blank lines, indentation, code fences, trailing spaces,
  and CRLF/LF line endings. Without frontmatter, preserve the entire decoded text.
- Do not treat later horizontal rules, fenced YAML, headings, or embedded
  `---` strings as frontmatter. An opening delimiter without a closing delimiter
  is a file error. TOML/JSON frontmatter is not supported in this first version;
  identify recognizable unsupported headers in preview instead of stripping them.
- Parse the bounded YAML block as a safe mapping solely for name/description
  suggestions. Accept an empty block. Reject malformed YAML, duplicate keys,
  custom object tags, aliases, and excessive nesting. Declare the parser as a
  direct backend dependency and update the uv lock if the implementation uses it.
- Only string `name` and `description` values provide suggestions. Invalid or
  oversized suggestions are shown for correction. All other metadata is omitted
  from instructions and has no configuration effect. Show unsupported field names
  such as `tools`, `model`, hooks, or permissions without echoing their values.
- Keep body text out of automatic summaries, channel events, and public purposes.
  Leave `default_prompt` empty. Do not append a roster or messaging instructions to
  the saved body; existing tool bindings and runtime directory context supply them.

Initial limits: 1-50 files, 64 KiB UTF-8 per source file, 512 KiB total source
bytes, 16 KiB frontmatter per file, and the existing 1 MiB encoded JSON request
limit. Check both source sizes and the actual serialized request size. Keep the
existing workspace-name limit of 100 characters, bot-name limit of 80, public
purpose limit of 400 characters/1,600 UTF-8 bytes, and instruction limit of 16,000
characters. Count the preserved body, including whitespace, for that last limit.
Reject an empty/whitespace-only body and report each file's actual size and limit.
Larger instructions require an explicit limit change with adapter/context-budget
validation; the importer must never shorten them to make them fit.

The user raised the instruction limit to 16,000 characters on 2026-10-12 for both
ordinary bot creation/editing and workflow imports. Boundary tests cover persisted
Unicode bodies, including whitespace, and rejection above the limit. Mocked
Microsoft and Anthropic provider requests retain the full 16,000-character body;
history bounds do not truncate role instructions. Anthropic's 4,096-token output
budget remains separate from input context. Model context capacity still depends
on the selected provider/model and the complete request; no live-provider context
qualification is claimed.

Filenames are display labels, not server filesystem paths. Accept only bounded
basenames, reject NUL and path components, and use an independent per-file ID so
duplicate filenames cannot overwrite each other. Identical bodies still create
separate bots. Render previews as text or with the application's safe Markdown
renderer; do not run embedded HTML or fetch linked resources.

## API and persistence

Add a flat `agentbot_control/workflow_imports/` domain with typed schemas, parser,
service, and HTTP modules. Keep SQL in repository helpers. Inject narrow typed
collaborators from the composition root. Follow the 450-active-line extraction
threshold and 500-line ceiling for every Python file.

Proposed authenticated endpoints:

| Endpoint | Contract |
| --- | --- |
| `POST /api/workflow-imports/preview` | Files (`file_id`, `filename`, `content`), workspace name, defaults, and per-file overrides; returns normalized configuration, exact instruction bodies, per-file errors/warnings, parser version, and preview digest. No persistence or side effects. |
| `POST /api/workflow-imports` | The same source/configuration plus `request_id` and preview digest; returns workspace ID, file-to-bot mapping, and saved computer/channel configuration. |
| `GET /api/workflow-imports/{request_id}` | Owner-scoped committed receipt for recovery after a lost response. Return 404 for absent or inaccessible receipts. |

Validate unknown fields and types strictly. Derive owner and actor from the
authenticated session. Source metadata cannot supply ownership, credential
secrets, installed tools, workspace IDs, execution grants, or approval policies.
Require available workspace, channel, tool-library, and shared-computer support;
disabled prerequisites produce an actionable error before writing any resource.
Expose an import capability and limits to the frontend so it can explain missing
support without attempting a degraded import.

Preview may report missing runtime choices while displaying valid parsed files.
Commit requires all files and resolved choices to be valid. Reparse the original
sources on commit and verify the preview digest over parser version, sources,
reviewed overrides, defaults, and resolved tool revisions. Recheck credential
ownership/provider compatibility and selected resource availability in the write
transaction. Changed choices/resources return a conflict and require a fresh
preview. A digest is a consistency check, not an authorization token.

Run bounded parsing off the event loop. Submit one database-worker operation with
one transaction to:

1. Check the owner's receipt for this request ID and reject a different payload
   using the same ID.
2. Validate current prerequisites and create the workspace and owner membership.
3. Initialize shared Docker computer settings; create no computer session.
4. Create the workspace Bot channel with automatic collaboration enabled.
5. For each file, create its bot and `bot_streams` association; save the exact body,
   validated credential/model, normal computer-tool selections plus
   `workspace.messaging/workspace_messaging`; publish the reviewed purpose and
   enroll the bot with no participation expiry.
6. Persist normal configuration/directory events and the import receipt containing
   the resulting workspace and file-to-bot mapping; commit everything together.

Any failure rolls back the entire batch, including channel events and the
receipt. Send notifications only after commit. Helpers called here must use the
same connection and never open or commit nested transactions. Use the existing
database worker's cancellation behavior: browser cancellation does not establish
rollback, and a lost response must be reconciled using the receipt.

Add the next available migration after the current
`019_shared_workspace_computer.sql` for `workflow_import_receipts`, keyed by
`(owner_id, request_id)`, with a canonical input fingerprint, parser version,
workspace ID, bounded result JSON, and timestamp. Persist filenames and source/body
hashes for provenance, not another copy of source/frontmatter. Do not log request
bodies, API keys, or private instructions. Keep receipts across bot deletion so
retry cannot recreate removed resources. A replay returns the original creation
receipt and IDs, not a promise that those resources still exist.

Compute the request fingerprint independently of the current parser implementation
and check an existing receipt before applying fresh validation, so a committed
retry still works after a restart, credential removal, or parser upgrade. Concurrent
identical commands return the same result; changed payloads with the same request
ID return 409. New imports require a new ID. Validation failures return structured
file/field errors; body-size failures return 413. Never retry a mutation with a new
ID automatically. Store only the request ID in tab session storage for reload
reconciliation; keep source drafts in memory. An absent receipt is not proof that
an in-flight worker rolled back: recover with the original ID and payload.

No new event transport is needed. Preserve protocol v2 replay and existing channel
envelopes. Define import HTTP schemas in the backend and derive their frontend
contracts from that source; keep schema generation free of runtime side effects.
If existing snapshot/event fields change, regenerate their established contracts.

## Delivery and acceptance

| Milestone | Work | Completion evidence |
| --- | --- | --- |
| I1: Parser and contract | Bounded source parsing, exact body handling, preview models, direct dependencies, fixtures. | Parser cases and API preview validation pass; no resource creation on preview. |
| I2: Atomic import | Transaction-aware creation helpers, receipt migration/recovery, complete channel enrollment and shared settings. | All-or-nothing, concurrent retry, restart, ownership, and dependency-revocation tests pass. |
| I3: Import UI | File selection, per-bot review, runtime defaults/overrides, errors, workspace selection and receipt recovery. | Frontend unit and browser tests cover the complete flow, keyboard use, and narrow layouts. |
| I4: Integrated qualification | Real shared-computer exercise, messaging round trip, regression gates, runtime documentation and ledger. | All acceptance scenarios below pass with evidence classified by environment/provider. |

Required scenarios:

1. Import Planner, Researcher, and Writer files. Exactly three bots appear in one
   new workspace; saved instructions match each expected body character for
   character, and frontmatter is absent. Test no frontmatter, UTF-8 BOM, Unicode,
   LF/CRLF, embedded rules, fenced YAML, whitespace, and unsupported metadata.
2. Malformed/unclosed frontmatter, unsafe YAML, invalid encoding, empty/oversized
   files, name collisions, and boundary-sized requests produce useful file errors.
   No subset of the workspace survives failure. Identical content in two selected
   files creates two bots once distinct names have been reviewed.
3. Fail after creating a bot, after enrolling it, and before receipt insertion;
   all writes roll back. Exercise double submission, concurrent identical IDs,
   mismatched payloads, response loss after commit, cancellation, process restart,
   and preview/parser changes. Assert one workspace and one bot per source.
4. Test foreign credentials, incompatible frameworks/models/tools, deleted
   credentials between preview and commit, disabled channel capability, and
   unauthorized receipt access. Source frontmatter must not bypass any check.
5. Every imported bot has the messaging binding and published enabled enrollment;
   automatic collaboration is on. With mocked models, Planner discovers Researcher,
   asks for help, receives a reply, and continues in Bot channel. Test Microsoft,
   Anthropic, and a mixed workflow. No model calls occur during import.
6. A communication-only request succeeds before any computer exists. After an
   explicit shared-computer create, use real Docker with deterministic adapters to
   prove two imported bots reference one session and can exchange a file through
   the same workspace. Human control pauses both; individual computer actions
   retain serialization and approvals. No per-bot computer is provisioned.
7. Browser tests cover edited names/purposes, common and per-bot settings, invalid
   file removal, missing-key setup, stale preview, lost-response recovery, reload,
   preference-save failure, responsive preview, and truthful computer readiness.
8. Ordinary workspace/bot creation, explicit empty tool selections, instruction
   trimming on legacy paths, channel revocation, existing shared-computer lifecycle,
   and protocol v2 reconnect behavior retain their regression coverage.

Keep tests under backend `tests/`, frontend `tests/` and `e2e/`; use synthetic
agent definitions without secrets. Run changed Python files through `ruff check
--fix`, `ruff format`, active-line counting, and retests. Use the locked workspace
environment and the Makefile/CI supported platforms for the project pytest suite,
`make check`, `make check-docker`, and applicable `make windows-test`/demo checks.
Record native Windows or demo checks as applicable to any shared code touched;
do not claim they ran from collection or mocked results. On Linux/macOS use
`make BIN=.venv/bin <target>`. Run `make docs-check` for the completed guides.

The user approved implementation on 2026-10-12. The parser, atomic import service,
receipt recovery, generated HTTP contracts, and review UI are implemented. The
runtime guides describe import usage, limits, and recovery. The implementation
also fixes idle shared-mode bot removal and isolates frontend test API settings
from local development configuration. I4 passed the local Python, frontend,
browser, real-Docker, and native Windows gates. Model exchanges use deterministic
provider fixtures; no live-provider, hosted CI, or deployment evidence is claimed.
