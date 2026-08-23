- Proposal Name: `scope_organization_and_agent_integration`
- Start Date: 2026-08-21
- RFC PR: [oceanbase/powercontext#0000](https://github.com/oceanbase/powercontext/pull/0000)
- Related Discussion: [oceanbase/powercontext#1238](https://github.com/oceanbase/powercontext/pull/1238),
  [oceanbase/powercontext#1219](https://github.com/oceanbase/powercontext/issues/1219)
- Related RFCs: [RFC 0019](0019_local_source_memory_runtime.md), [RFC 0028](0028_context_pack.md),
  [RFC 0048](0048_handoff_artifact.md), [RFC 0082](0082_handoff_report.md)

# Summary

This RFC defines a common scope organization model for PowerContext. Every scope is a state and Handoff boundary
identified by `scope_id` and independently selects one Scope Role. `context` represents long-lived shared context,
`work` represents work that can be continued and handed off independently, and `execution` represents a short-lived
window for a session, agent, or subagent.

Every non-root scope also has one Parent Relation to another scope. `shared` lets the child read parent Context, while
`delegated` permits only explicitly selected input and result exchange. Scope Role answers why a boundary exists and
how it is handed off. Parent Relation answers what the boundary can read. They are independent and are not encoded in
`scope_id`.

An agent host binds a session to one current scope before a turn begins. Directory and Git information only discover
candidate scopes. Results move across scopes through explicit publication of an exact Artifact revision. A Handoff
Report projects the `work` hierarchy from a root scope and folds `execution` by default. Project, Feature, and Agent
may be UI names, but they do not form a second identity model.

This RFC covers scopes within one tenant or authorization domain. A tenant may have several unrelated `context`
scopes, or connect them with Parent Relations to share common Context. Cross-tenant sharing requires separate rules
for identity, authorization, revocation, and audit, so Parent Relation does not represent it.

# Motivation

PowerContext currently uses `scope_id` to isolate Source, Memory, Artifact, Handoff, and other mutable state. This
boundary is necessary, but an opaque ID answers only where data belongs. It does not explain the responsibility of
that boundary in collaboration.

One repository may contain several items of work, and one item of work may span several repositories. A session may
fix a bug and then develop a feature, while one item of work may continue across sessions. Peer agents need common
context, while a subagent often needs only selected task input. Binding `scope_id` to a repository, branch, session,
feature, or agent mixes state or breaks continuity in the other scenarios.

Adding only a parent relation is also insufficient. A parent determines Context reads but cannot tell whether a child
scope is temporary execution detail or work that needs independent Continue and Handoff. Conversely, knowing that a
scope is `work` does not determine whether it reads parent Context.

This proposal must provide all of these outcomes:

- one opaque `scope_id` still owns all state precisely;
- users understand scopes through titles, summaries, and roles;
- the four coding-agent scenarios use one model for one or several directories;
- agent hosts determine scopes during turn, work-switch, and subagent lifecycle;
- intermediate material, work deliverables, and long-lived knowledge have different publication targets;
- reports organize independently transferable work without Project catalog.

# Guide-level explanation

## Reading the model

The system has one kind of durable boundary: scope. Runtime routes state only by `scope_id`. Role, title, and Parent
Relation are properties that explain the ID. They do not introduce more identity objects:

```text
Scope
+-- scope_id
+-- role: context | work | execution
+-- title
+-- summary
+-- status
`-- parent relation: parent_scope_id + shared | delegated
```

Every diagram in this RFC uses the same notation. Square brackets show Role. `shared` or `delegated` on a connecting
line shows the child's Relation to its parent.

```text
scp_repo "Repository context" [context]
`-- shared --> scp_feature "Retry race" [work]
    `-- shared --> scp_agent_a "Agent A" [execution]
```

The three scopes store state separately. `scp_agent_a` can read `scp_feature` and `scp_repo` along continuous
`shared` relations, but it still writes only to `scp_agent_a`. A session or workspace refers to the current scope and
does not change data ownership.

| Choice | Question answered | Not responsible for |
| --- | --- | --- |
| `scope_id` | Which boundary owns state and Handoff? | Business meaning, hierarchy, authorization |
| Scope Role | How long does this boundary persist, and is it handed off independently? | Whether parent Context is readable |
| Parent Relation | How does the child read parent Context? | Lifecycle, report granularity, authorization |
| external binding | Which scope does current external execution use? | Data ownership and Context semantics |

## Scope Roles

Scope Role follows boundary lifetime and handoff granularity:

| Role | Lifetime | Default handoff and display |
| --- | --- | --- |
| `context` | Persists across several items of work | Stores reviewed shared material and may be a report root |
| `work` | Persists across several executions | Owns an independent Handoff and appears as a report node |
| `execution` | Serves one session, agent, or delegation window | Stores intermediate state and folds into the nearest `work` by default |

Role is not a business type. A feature, bug, migration, or review may use `work`. Repository, service, or team
knowledge may use `context`. Main agents, peer agents, and subagents usually use `execution`.

The selection rule is simple. Use `work` when the boundary needs independent continuation, acceptance, or handoff.
Use `execution` when it is an execution window for another item of work. A `context` receives only selected material
suitable for reuse across work.

## Parent Relations

Every non-root scope has at most one parent. The relation belongs to the child:

| Relation | Child Context | Parent-child exchange |
| --- | --- | --- |
| `shared` | Reads itself and continuous `shared` ancestors | Child results still require explicit publication |
| `delegated` | Reads only itself | Parent passes exact input and child returns exact result |

Read and write directions are fixed:

```text
write scope: current scope only
read scopes: current scope + continuous shared ancestors
```

Role does not imply Relation. A `work` may use `shared` with a parent `context`, or `delegated` for an isolated task.
An `execution` may read common `work`, or use `delegated` for a minimum-context subagent. A `context` may also use
another `context` as its parent. Role does not impose a fixed depth.

## Sharing Context within one tenant

One tenant does not imply one top-level `context`. Several `context` scopes may stay independent or read a common
parent:

```text
scp_common "Shared conventions" [context]
|-- shared --> scp_repo_a "Repository A" [context]
`-- shared --> scp_repo_b "Repository B" [context]
```

When `scp_repo_a` is current, the Context resolver returns `scp_repo_a` and `scp_common`. It does not return the
sibling `scp_repo_b`. Writes to `scp_repo_a` also stay out of `scp_common`. The same relation can express layered
Context reuse:

```text
scp_org "Organization knowledge" [context]
`-- shared --> scp_team "Team conventions" [context]
    `-- shared --> scp_repo "Repository context" [context]
        `-- shared --> scp_feature "Retry race" [work]
```

`scp_feature` can read Context along this continuous relation. Every scope keeps its own title, summary, status, and
Handoff. Shared reads do not merge them.

Scopes without a parent relation do not enter each other's Context read set merely because they belong to the same
tenant. They exchange selected content through exact publication:

```text
scp_repo_a [context] -- publish exact revision --> scp_repo_b [context]
```

The support boundary is explicit:

| Need | Expression | Result |
| --- | --- | --- |
| Several independent Contexts | No Parent Relation | No cross-reads |
| Several Contexts share base material | Same `context` as each scope's `shared` parent | Reads the common parent, not siblings |
| Layered Context reuse | A `context` uses another `context` as its `shared` parent | Reads along continuous relations |
| Selected exchange between independent Contexts | Exact publication | Copies one version without ongoing sync |
| Inherit several unrelated Contexts at once | Multiple parents | Not supported |
| Cross-tenant sharing | Not applicable | Outside this RFC |

`shared` provides continuous reads from parent Context. Publication delivers an exact version between two authorized
scopes. A scope has at most one parent. For reuse across several scopes, publish stable material to a common
`context`, or publish directly where needed. These relations provide no evidence of cross-tenant authorization.

## External selection

Session, workspace, and agent identity do not enter scope identity:

```text
external_session_id -> current_scope_id
workspace signals   -> candidate scope_ids
agent identity      -> execution provenance
```

The agent host freezes the current `scope_id` before a normal request begins. Prepare Context, Capture Source,
Memory, and Handoff operations for the request reuse the same ID. A switch takes effect only at a request boundary.
PowerContext does not switch automatically after natural-language or directory changes.

Git remotes, repositories, branches, directories, and worktrees only help an integration find candidate scopes. An
existing session binding, user selection, or explicit configuration resolves multiple candidates. One scope may use
several directories, and one directory may serve several scopes.

## Scenarios

### One session for one Feature

The host creates a `work` and one session `execution`:

```text
scp_repo [context]
`-- shared --> scp_feature [work]
    `-- shared --> scp_session [execution]
```

The session writes to `scp_session` and reads Context from `scp_feature` and `scp_repo`. Work conclusions are
published to `scp_feature`, whose Handoff is used for external transfer.

### One session switches between items of work

A bug and feature use sibling `work` scopes:

```text
scp_repo [context]
|-- shared --> scp_bug [work]
|   `-- shared --> scp_session_bug [execution]
`-- shared --> scp_feature [work]
    `-- shared --> scp_session_feature [execution]
```

At a request boundary, the host suspends or closes `scp_session_bug`, resolves or creates the feature scopes, and
updates session binding. The next request prepares Context from `scp_session_feature`. The external transcript may
remain, but new PowerContext writes do not enter the bug scopes.

### Peer agents collaborate

Peer agents use sibling `execution` scopes under one `work`:

```text
scp_feature [work]
|-- shared --> scp_agent_a [execution]
|-- shared --> scp_agent_b [execution]
`-- shared --> scp_agent_c [execution]
```

Each agent reads common `work` but not a sibling's intermediate state. After an agent publishes a selected result to
`scp_feature`, other agents can read it in later requests. A report displays one feature work item instead of three
agent execution windows.

### A main agent drives subagents

A temporary subagent uses a `delegated execution`:

```text
scp_feature [work]
`-- shared --> scp_main [execution]
    |-- delegated --> scp_research [execution]
    `-- delegated --> scp_test [execution]
```

The orchestrator selects input for the child scope. The child returns exact result references, then the host decides
which results to publish to `scp_feature`. A child Handoff may support recovery and diagnosis, but the default report
does not list these executions separately.

A subtask that needs independent Continue or handoff uses a nested `work`:

```text
scp_feature [work]
|-- shared --> scp_main [execution]
`-- delegated --> scp_migration [work]
    `-- shared --> scp_migration_agent [execution]
```

`scp_migration` owns its own Handoff and appears as child work under `scp_feature` in a report.

## Publication and Handoff Report

An Artifact initially belongs to the scope that produced it. A parent relation does not copy content automatically:

```text
execution-local material
    |
    +---- keep local: reasoning, debug fragments, rejected results
    |
    `---- publish exact revision ----> work deliverable
                                          |
                                          `---- reviewed publication ----> context knowledge
```

Publication creates a new immutable revision in the target scope and retains the source scope, source revision, and
digest. It grants the target no permission to read the source scope and does not merge Handoff histories.

A Handoff Report selects a `context` or `work` root, traverses bounded descendant scopes, and projects only `work`:

```text
scope relations                    report projection

scp_repo [context]                Repository context
|-- scp_bug [work]                +-- Bug fix
|   `-- scp_agent [execution]     `-- Feature
`-- scp_feature [work]                `-- Migration
    |-- scp_main [execution]
    `-- scp_migration [work]
```

Every report item freezes an exact Handoff revision or `no_handoff`. A diagnostic view or exact selection may expand
an execution explicitly. Project may be the UI name of the root scope, but the report needs no `project_id` or
Workstream membership.

## Agent integration

PowerContext divides integration behavior into three planes:

| Plane | Operations | Default caller |
| --- | --- | --- |
| control | Create scopes, update metadata, set parent relations, close and archive | host, UI, CLI |
| data | Prepare Context, Capture Source, Memory, current-scope Handoff | lifecycle hook, agent |
| exchange | Publication, Handoff Report | host, orchestrator, UI |

The control plane and cross-scope publication are absent from ordinary agent MCP by default. An agent may read the
title, Role, and breadcrumb of its current scope and use Memory and Handoff within that scope. It cannot create a
sibling, change a parent relation, or update session binding through ordinary tools.

| Integration form | Purpose |
| --- | --- |
| embedded Python API | Internal assembly, embedded hosts, and tests |
| HTTP/OpenAPI | Complete remote public contract |
| lifecycle hooks | Map turn, session, spawn, and completion events to HTTP calls |
| MCP | Allowlisted agent data plane and read-only reports |
| CLI/UI | User selection, correction, and scope inspection |

# Reference-level explanation

## Architecture boundaries

```text
Agent host / UI
    |
    +---- integration binding and lifecycle
    |
    v
Scope application layer
    |
    +---- metadata and parent repository
    +---- Context resolver
    +---- publication service
    `---- report selector
    |
    v
Scope-local Runtime
    |
    +---- Source / Memory
    `---- Artifact / Handoff
```

The scope-local Runtime continues to handle state using one explicit `scope_id`. The scope application layer owns
metadata, parent relations, and cross-scope operations. The integration maps external session, workspace, and
orchestrator lifecycle to scopes. An agent transport projects only application behavior authorized for its caller.

## Scope contract

Scope metadata contains at least:

- `scope_id`: immutable, opaque, and globally unique;
- `role`: `context`, `work`, or `execution`;
- `title`: a short and distinguishable display name;
- `summary`: the stable purpose or boundary;
- `status`: `active`, `closed`, or `archived`;
- `version`: the metadata concurrency version.

A scope may carry namespaced external references for a repository, issue, or external work item. An external reference
supports discovery and display. It does not become identity, session binding, or an authorization input.

New IDs use `scp_` followed by 26 lowercase Crockford Base32 characters. The random payload comes from a
cryptographically secure source and contains 128 bits of entropy. The server generates the ID, while the client uses
an idempotency key for creation retries. Existing IDs retain their original values, and the new format applies only
to new IDs.

The first version does not allow in-place Role changes. An `active` scope accepts normal reads and writes. A `closed`
scope retains read, Continue, and report behavior but rejects ordinary new writes. An `archived` scope remains
readable by exact identity but is absent from default discovery.

## Parent relation and Context contract

Parent relations satisfy these invariants:

1. A scope has at most one direct parent.
2. A root scope has no relation mode.
3. A non-root scope uses `shared` or `delegated`.
4. A parent chain contains no cycle.
5. Changing a parent does not move or rewrite existing state.
6. A relation mode grants no permission or cross-scope write capability.
7. This RFC does not use parent relations to represent cross-tenant sharing.

The Context resolver returns the current scope and continuous `shared` ancestors and retains source scope and exact
revision for every item. The implementation limits maximum depth and total budget. Resolution stops at `delegated`
or an unavailable ancestor. A caller that permits degradation marks the result incomplete.

## Host integration contract

The integration stores session binding. PowerContext does not introduce a general Session object. A host must:

1. Resolve the active `scope_id` before a normal request begins.
2. Freeze the ID after the request begins.
3. Reuse it for state operations in the same request.
4. Update binding only at a request boundary.
5. Use stable idempotency keys for create, spawn, and completion retries.
6. Record external session, turn, agent, and workspace identifiers as provenance instead of encoding them in the ID.

Logical operations are divided into:

```text
control:
  create_scope(role, title, summary, parent_scope_id, relation_mode, idempotency_key)
  get_scope(scope_id)
  update_scope(scope_id, expected_version, title, summary, status)
  set_parent(scope_id, parent_scope_id, relation_mode, expected_version)
  list_children(scope_id)
  find_scopes(external_refs, roles, statuses)

data:
  describe_current_scope(scope_id)
  prepare_context(scope_id, query, budget)
  capture_source(scope_id, source)
  search_memory(scope_id, query)
  prepare_handoff(scope_id, evidence)
  continue_handoff(scope_id, selection)
  commit_handoff(scope_id, prepared_handoff)

exchange:
  publish_artifact(source_scope_id, source_ref, target_scope_id, idempotency_key)
  generate_handoff_report(root_scope_id, selection_mode, rendering_options)
```

HTTP requests carry explicit `scope_id`. The first MCP version may retain that parameter, but the host must inject the
active ID at turn start and the agent only reuses it. `scope_id` is not a credential, and server authorization still
applies.

## Publication contract

A publication must:

1. Identify the source scope, exact Artifact identity, and revision.
2. Create a new immutable revision in the target scope.
3. Retain source-qualified provenance and digest.
4. Copy no other source-scope state and create no ongoing synchronization.
5. Change neither Handoff head.
6. Complete as an idempotent operation and leave no visible partial result on failure.

`ArtifactRef` continues to represent a scope-local exact revision. Cross-scope parameters add the source scope at the
operation boundary instead of changing the existing `ArtifactRef`.

Publication requires read permission on the source and write permission on the target. Role, Relation, and directory
association cannot replace either authorization check.

## Handoff Report contract

Report generation freezes these inputs:

```text
root_scope_id
parent-relation revision
selected work scope_ids
exact Handoff revision or no_handoff per work
activity boundary
rendering options
```

A dynamic descendant set is used only for discovery. The response returns the final selection, and later parent
relation or Handoff changes do not modify an existing report. The report preserves the nearest work ancestry among
selected work scopes. It does not merge Handoff histories or write to any scope.

The report authorizes every selected scope. An inaccessible scope must not leak its title, existence, or count. Strict
mode fails, while a mode that permits partial results marks omissions explicitly.

## Existing architecture and compatibility

The following existing behavior remains unchanged:

- Runtime receives an explicit `scope_id` and builds scoped services.
- Source, Memory, Artifact, and Handoff use scope-local storage.
- Handoff uses Prepared, Commit, Continue, and exact revisions.
- Handoff Report retains stable selection, canonical digests, and deterministic rendering.
- MCP continues to expose agent tools through an explicit OpenAPI operation allowlist.

The implementation adds scope metadata, a parent repository, Context resolver, publication service, and work report
selector. Codex Git and directory derivation becomes bootstrap candidate discovery, and the skill reads the current
scope selected by the host.

`ProjectDescriptor`, `WorkstreamDescriptor`, Project/Workstream membership, and the `project_id` report entry no
longer form report identity. The existing Project catalog may provide read-only reports during migration but cannot
create new organization relations.

Legacy callers may continue to provide existing `scope_id` values. Compatibility reads treat a legacy scope with no
Role as `work` to preserve single-scope Handoff behavior. The default is not written back and triggers no further
inference from an ID or directory.

# Drawbacks

- Scope Role and Parent Relation add two explicit choices. An integration must understand lifetime, handoff
  granularity, and Context-read differences.
- Full work-switch and subagent isolation support requires host turn, session, and orchestrator lifecycle.
- Explicit publication adds an operation, but prevents intermediate material and personal information from entering
  a parent scope automatically.
- Control, data, and exchange behavior must retain consistent semantics across Python, HTTP, hooks, MCP, and UI.
- Moving from Project catalog to scope projection changes report APIs and persistence.

# Rationale and alternatives

## Use only an opaque scope ID

Rejected. It isolates state but cannot determine Handoff granularity, report nodes, or long-lived sharing boundaries.
Every integration eventually reintroduces these semantics through naming conventions.

## Encode type and hierarchy in scope ID

Rejected. Renames, moves, forks, and work switches invalidate encoded values and encourage callers to infer Context
and authorization from strings.

## Let Role determine parent Context

Rejected. Independent work may share or isolate Context, and temporary execution also needs both `shared` and
`delegated`. Role and Relation must remain independent.

## Let the agent select and create scopes

Rejected. Model calls occur inside a turn and cannot guarantee that a scope switch completes before Prepare Context.
Retries can also create duplicate boundaries. The host owns session, turn, and spawn lifecycle, so it controls
topology.

## Retain Project catalog for report organization

Rejected. It creates a second identity and membership model beside scope parent relations and requires workspace, activity,
and report operations to maintain `project_id`.

## Promote all child content automatically

Rejected. Automatic promotion cannot distinguish deliverables, intermediate reasoning, personal information, and
rejected results. It also makes sharing depend on agent topology.

# Prior art

- RFC 0019 defines an integration-owned opaque business partition. This proposal retains opaque identity and adds
  Role and Relation.
- RFC 0048 defines a scope-local exact Handoff. This proposal adds cross-scope publication and default handoff
  granularity.
- RFC 0082's exact selection, canonical digest, and deterministic renderer are reusable without Project catalog.
- [OpenDAL OFS RFC 0016](https://github.com/PsiACE/opendal-ofs/blob/main/rfcs/0016_filesystem_architecture.md)
  models namespace authority and immediate application state as two independent choices. This proposal similarly
  separates scope lifetime responsibility from parent Context reads.
- Mem0 stores user, agent, and run as independent filter dimensions, but its flat filters do not express parent
  Context or handoff projection.
- CocoIndex separates session content, readable summaries, and state tracking. Its provenance design informs
  publication.
- Letta stores agent, run, step, and trace separately, showing that runtime provenance should not be encoded in a
  namespace.

# Unresolved questions

- When a host cannot provide pre-turn scope switching, should it use an explicit command, a UI choice, or delay the
  switch until the next turn?
- Length, character-set, and concurrent-update rules for `title`, `summary`, and external references belong in the
  OpenAPI design.
- The publication API design must define minimum provenance fields shared by Artifact families.
- A separate migration plan must define how old Project catalog data becomes scope metadata.

# Future possibilities

Later work may add scope search, title history, archival policy, and a host-bound MCP transport. Reports covering work
without a common parent can add a multi-root projection over exact selection without restoring Project identity.
Cross-tenant sharing needs a separate design for tenant identity, authorization, revocation, audit, and data copying.
It does not reuse Parent Relation from this RFC.
