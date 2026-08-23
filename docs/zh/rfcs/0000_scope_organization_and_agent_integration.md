- Proposal Name: `scope_organization_and_agent_integration`
- Start Date: 2026-08-21
- RFC PR: [oceanbase/powercontext#0000](https://github.com/oceanbase/powercontext/pull/0000)
- Related Discussion: [oceanbase/powercontext#1238](https://github.com/oceanbase/powercontext/pull/1238)、
  [oceanbase/powercontext#1219](https://github.com/oceanbase/powercontext/issues/1219)
- Related RFCs: [RFC 0019](0019_local_source_memory_runtime.md)、[RFC 0028](0028_context_pack.md)、
  [RFC 0048](0048_handoff_artifact.md)、[RFC 0082](0082_handoff_report.md)

# Summary

本文为 PowerContext 定义统一的 scope 组织模型。每个 scope 都是一个由 `scope_id` 标识的状态与 Handoff 边界，并独立选择
一个 Scope Role。`context` 表示长期共享上下文，`work` 表示可独立继续和交接的工作，`execution` 表示 session、agent 或
sub-agent 的短期执行窗口。

每个非根 scope 还通过一条 Parent Relation 连接另一个 scope。`shared` 允许子 scope 读取父 Context，`delegated` 只允许
父子交换显式选择的输入和结果。Scope Role 回答边界为什么存在以及如何交接，Parent Relation 回答边界可以读取什么。
两者互相独立，也不编码进 `scope_id`。

agent host 在 turn 开始前把 session 绑定到一个当前 scope。目录和 Git 信息只用于发现候选 scope。跨 scope 结果通过 exact
Artifact revision 显式发布，Handoff Report 从根 scope 投影 `work` 层级并默认折叠 `execution`。Project、Feature 和 Agent
可以作为界面名称，不形成第二套身份模型。

本 RFC 讨论同一租户或授权域内的 scope。一个租户可以有多个互不相关的 `context` scope，也可以通过 Parent Relation 共享
共同 Context。跨租户共享涉及身份、授权、撤销和审计，不使用本 RFC 的 Parent Relation 表达，需要单独设计。

# Motivation

PowerContext 当前使用 `scope_id` 隔离 Source、Memory、Artifact、Handoff 和其他可变状态。这个边界是必要的，但不透明 ID
只能回答数据属于哪里，不能回答该边界在协作中承担什么职责。

一个 repo 可能同时包含多个工作，一个工作可能跨多个 repo。一个 session 可以先修 bug，再开发 feature；同一个工作也可能
跨 session 延续。peer agent 需要读取共同上下文，sub-agent 往往只应获得经过选择的任务输入。把 `scope_id` 固定为 repo、
branch、session、feature 或 agent，都会在其他场景中混合状态或切断连续性。

仅增加父子关系也不够。父关系可以确定 Context 读取范围，却不能判断一个子 scope 是临时执行细节，还是需要独立 Continue
和 Handoff 的工作。反过来，知道一个 scope 是 `work` 也不能决定它是否读取父 Context。

本提案需要同时得到以下结果：

- 所有状态仍由一个不透明 `scope_id` 精确归属；
- 用户能通过标题、摘要和角色理解 scope；
- 四类 coding agent 场景使用同一模型，不绑定单目录或多目录；
- agent host 能在 turn、work switch 和 sub-agent 生命周期中确定 scope；
- 中间材料、工作交付物和长期知识具有不同的发布目标；
- 报告按可独立交接的工作组织，不依赖 Project catalog。

# Guide-level explanation

## 如何阅读这个模型

系统中只有一种持久边界：scope。Runtime 只用 `scope_id` 路由状态。Role、标题和 Parent Relation 是 scope 的属性，用于解释
这个 ID，而不是新的身份对象：

```text
Scope
+-- scope_id
+-- role: context | work | execution
+-- title
+-- summary
+-- status
`-- parent relation: parent_scope_id + shared | delegated
```

本文中的图使用同一种写法：方括号表示 Role，连接线上的 `shared` 或 `delegated` 表示 child 对 parent 的 Relation。

```text
scp_repo "Repository context" [context]
`-- shared --> scp_feature "Retry race" [work]
    `-- shared --> scp_agent_a "Agent A" [execution]
```

三个 scope 各自保存状态。`scp_agent_a` 可以沿连续的 `shared` 关系读取 `scp_feature` 和 `scp_repo`，但仍只写入
`scp_agent_a`。session 和 workspace 只引用当前 scope，不改变数据归属。

| 选择 | 回答的问题 | 不负责 |
| --- | --- | --- |
| `scope_id` | 状态和 Handoff 属于哪个边界 | 业务含义、层级、授权 |
| Scope Role | 这个边界保留多久，是否独立交接 | 父 Context 是否可读 |
| Parent Relation | 子 scope 怎样读取父 Context | 生命周期、报告粒度、授权 |
| external binding | 当前外部执行使用哪个 scope | 数据归属和 Context 语义 |

## Scope Roles

Scope Role 根据边界的生命周期和交接粒度选择：

| Role | 生命周期 | 默认交接和展示 |
| --- | --- | --- |
| `context` | 跨多个工作保留 | 保存经审阅的共享材料，可作为报告根 |
| `work` | 跨多个 execution 保留 | 拥有独立 Handoff，作为报告节点 |
| `execution` | 服务一个 session、agent 或委派窗口 | 保存中间状态，默认折叠到最近的 `work` |

Role 不表示业务类型。feature、bug、migration 和 review 都可以使用 `work`。repository、service 或 team knowledge 可以使用
`context`。main agent、peer agent 和 sub-agent 通常使用 `execution`。

选择规则只有一个：如果该边界需要被独立继续、验收或交接，则使用 `work`；如果它只是完成另一个工作的执行窗口，则使用
`execution`。`context` 只接收经过选择、适合跨工作复用的材料。

## Parent Relations

每个非根 scope 最多有一个父 scope。关系属于子节点：

| Relation | 子 scope 的 Context | 父子交换 |
| --- | --- | --- |
| `shared` | 读取自身和连续的 `shared` 祖先 | 子结果仍需显式发布 |
| `delegated` | 只读取自身 | 父传入 exact input，子返回 exact result |

读写方向固定：

```text
write scope: current scope only
read scopes: current scope + continuous shared ancestors
```

Relation 不由 Role 推断。一个 `work` 可以与父 `context` 使用 `shared`，也可以作为隔离任务使用 `delegated`。一个
`execution` 可以读取共同 `work`，也可以作为最小上下文 sub-agent 使用 `delegated`。`context` 也可以把另一个 `context`
作为 parent，Role 不限制合理的层级深度。

## 单租户内的 Context 共享

单租户不等于只有一个顶层 `context`。多个 `context` scope 可以保持独立，也可以读取一个共同的 parent：

```text
scp_common "Shared conventions" [context]
|-- shared --> scp_repo_a "Repository A" [context]
`-- shared --> scp_repo_b "Repository B" [context]
```

以 `scp_repo_a` 为当前 scope 时，Context resolver 返回 `scp_repo_a` 和 `scp_common`。它不会返回 sibling
`scp_repo_b`。`scp_repo_a` 的写入也不会进入 `scp_common`。如果两个 context 需要分层复用，可以继续使用相同表达：

```text
scp_org "Organization knowledge" [context]
`-- shared --> scp_team "Team conventions" [context]
    `-- shared --> scp_repo "Repository context" [context]
        `-- shared --> scp_feature "Retry race" [work]
```

`scp_feature` 可以读取这条连续关系上的 Context。每个 scope 仍有自己的标题、摘要、状态和 Handoff，不会因为共享读取而合并。

没有 parent 关系的 scope 不会因为属于同一租户而进入彼此的 Context 读取范围。它们之间如需传递确定内容，使用 exact
publication：

```text
scp_repo_a [context] -- publish exact revision --> scp_repo_b [context]
```

支撑边界如下：

| 需求 | 表达 | 结果 |
| --- | --- | --- |
| 多个独立 Context | 不设置 Parent Relation | 不互相读取 |
| 多个 Context 共享基础材料 | 分别以同一 `context` 为 `shared` parent | 读取共同 parent，不读取 sibling |
| Context 分层复用 | `context` 以另一个 `context` 为 `shared` parent | 沿连续关系读取 |
| 独立 Context 交付选定材料 | exact publication | 复制确定版本，不持续同步 |
| 同时继承多个无关 Context | 多 parent | 不支持 |
| 跨租户共享 | 不适用 | 不在本 RFC 范围内 |

`shared` 用于持续读取 parent Context，publication 用于在两个已授权 scope 之间交付一个确定版本。一个 scope 最多有一个
parent。需要多方复用时，应把稳定材料发布到共同 `context`，或按需直接 publication。以上关系不能作为跨租户授权依据。

## 外部选择

session、workspace 和 agent identity 不进入 scope identity：

```text
external_session_id -> current_scope_id
workspace signals   -> candidate scope_ids
agent identity      -> execution provenance
```

agent host 在普通请求开始前固定当前 `scope_id`。该请求的 Prepare Context、Capture Source、Memory 和 Handoff 操作复用同一
ID。切换只在请求边界生效，PowerContext 不根据自然语言或目录变化自动切换。

Git remote、repo、branch、目录和 worktree 只帮助 integration 找到候选 scope。多候选时由已有 session binding、用户选择或
明确配置消歧。一个 scope 可以使用多个目录，同一目录也可以服务多个 scope。

## 场景

### Session 和 Feature 一对一

host 创建一个 `work` 和一个 session `execution`：

```text
scp_repo [context]
`-- shared --> scp_feature [work]
    `-- shared --> scp_session [execution]
```

session 写入 `scp_session`，并读取 `scp_feature` 和 `scp_repo` 的 Context。工作结论发布到 `scp_feature`，对外 Handoff 由
`scp_feature` 提供。

### 一个 Session 顺序切换多个工作

bug 和 feature 使用两个 sibling `work`：

```text
scp_repo [context]
|-- shared --> scp_bug [work]
|   `-- shared --> scp_session_bug [execution]
`-- shared --> scp_feature [work]
    `-- shared --> scp_session_feature [execution]
```

host 在请求边界暂停或关闭 `scp_session_bug`，解析或创建 feature scopes，然后更新 session binding。下一个请求从
`scp_session_feature` Prepare Context。外部 transcript 可以保留，但新的 PowerContext 写入不会进入 bug scopes。

### 多个平级 Agent 协同

peer agent 使用同一 `work` 下的 sibling `execution`：

```text
scp_feature [work]
|-- shared --> scp_agent_a [execution]
|-- shared --> scp_agent_b [execution]
`-- shared --> scp_agent_c [execution]
```

每个 agent 读取共同 `work`，不读取 sibling 的中间状态。agent 把选定结果发布到 `scp_feature` 后，其他 agent 才能在后续
请求中读取。报告显示一个 feature 工作，而不是三个 agent 执行窗口。

### 主 Agent 驱动 Sub-agent

临时 sub-agent 使用 `delegated execution`：

```text
scp_feature [work]
`-- shared --> scp_main [execution]
    |-- delegated --> scp_research [execution]
    `-- delegated --> scp_test [execution]
```

orchestrator 为 child scope 选择输入。child 返回 exact result references，host 决定哪些结果发布到 `scp_feature`。child
Handoff 可以用于恢复和诊断，默认报告不单列这些 execution。

需要独立 Continue 或交接的子任务使用嵌套 `work`：

```text
scp_feature [work]
|-- shared --> scp_main [execution]
`-- delegated --> scp_migration [work]
    `-- shared --> scp_migration_agent [execution]
```

`scp_migration` 拥有自己的 Handoff，并作为 `scp_feature` 的子工作出现在报告中。

## Publication 和 Handoff Report

Artifact 首先属于产生它的 scope。父关系不自动复制内容：

```text
execution-local material
    |
    +---- keep local: reasoning, debug fragments, rejected results
    |
    `---- publish exact revision ----> work deliverable
                                          |
                                          `---- reviewed publication ----> context knowledge
```

publication 在 target scope 创建新的 immutable revision，并保留 source scope、source revision 和 digest。它不授予 target
读取 source scope 的权限，也不合并双方的 Handoff history。

Handoff Report 选择一个 `context` 或 `work` root，遍历有界的后代 scope，只投影 `work`：

```text
scope relations                    report projection

scp_repo [context]                Repository context
|-- scp_bug [work]                +-- Bug fix
|   `-- scp_agent [execution]     `-- Feature
`-- scp_feature [work]                `-- Migration
    |-- scp_main [execution]
    `-- scp_migration [work]
```

每个 report item 冻结 exact Handoff revision 或 `no_handoff`。diagnostic view 或 exact selection 可以显式展开 execution。
Project 可以是 root scope 的界面名称，报告本身不需要 `project_id` 或 Workstream membership。

## Agent integration

PowerContext 将集成行为分成三个平面：

| Plane | Operations | Default caller |
| --- | --- | --- |
| control | 创建 scope、更新元数据、设置父关系、关闭和归档 | host、UI、CLI |
| data | Prepare Context、Capture Source、Memory、当前 scope Handoff | lifecycle hook、agent |
| exchange | publication、Handoff Report | host、orchestrator、UI |

control plane 和跨 scope publication 默认不进入 agent MCP。agent 可以读取当前 scope 的标题、Role 和 breadcrumb，并在该
scope 内使用 Memory 和 Handoff。它不能通过普通工具创建 sibling、调整父关系或改变 session binding。

| Integration form | Purpose |
| --- | --- |
| embedded Python API | 内部装配、嵌入式 host 和测试 |
| HTTP/OpenAPI | 完整远程公共契约 |
| lifecycle hooks | 将 turn、session、spawn 和 completion 事件映射为 HTTP 调用 |
| MCP | allowlist 后的 agent data plane 和只读报告 |
| CLI/UI | 用户选择、纠正和观察 scope |

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

Scope-local Runtime 继续以一个显式 `scope_id` 处理状态。Scope application layer 负责 metadata、parent relations 和跨
scope 操作。
integration 负责把外部 session、workspace 和 orchestrator lifecycle 映射到 scope。agent transport 只能投影调用方被授权的
application 行为。

## Scope contract

scope metadata 至少包含：

- `scope_id`：不可变、不透明、全局唯一；
- `role`：`context`、`work` 或 `execution`；
- `title`：简短且可区分的展示名称；
- `summary`：稳定目标或边界说明；
- `status`：`active`、`closed` 或 `archived`；
- `version`：metadata 并发更新版本。

scope 可以带 namespaced external references，用于关联 repository、issue 或外部工作项。external reference 只参与发现和
展示，不成为 identity、session binding 或授权依据。

新建 ID 使用 `scp_` 加 26 位小写 Crockford Base32 字符，随机载荷来自密码学安全随机源并包含 128 bit 熵。服务端生成 ID，
客户端通过幂等键处理创建重试。已有 ID 保留原值，新格式只用于新建 ID。

Role 首期不可原地变更。`active` 接受正常读写；`closed` 保留读取、Continue 和报告能力，但拒绝普通新增写入；`archived`
仍可按 exact identity 读取，但不进入默认发现结果。

## Parent relation and Context contract

父关系满足以下不变量：

1. 一个 scope 最多有一个直接父 scope；
2. 根 scope 没有 relation mode；
3. 非根 scope 使用 `shared` 或 `delegated`；
4. 父链不能成环；
5. 调整父关系不移动或重写已有状态；
6. relation mode 不授予权限和跨 scope 写入能力；
7. 本 RFC 不使用父关系表达跨租户共享。

Context resolver 返回当前 scope 和连续 `shared` 祖先，并保留每条内容的来源 scope 和 exact revision。实现必须限制最大
深度和总预算。遇到 `delegated` 或不可用祖先时停止；允许降级的调用必须标记结果不完整。

## Host integration contract

session binding 由 integration 保存，PowerContext 不建立通用 Session 对象。host 必须：

1. 在普通请求开始前解析活动 `scope_id`；
2. 请求开始后固定该 ID；
3. 同一请求的状态操作复用该 ID；
4. 只在请求边界更新 binding；
5. 对 create、spawn 和 completion 重试使用稳定幂等键；
6. 把 external session、turn、agent 和 workspace identifiers 记录为 provenance，不编码进 ID。

逻辑操作分为：

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

HTTP 请求显式携带 `scope_id`。MCP 首期可以保留该参数，但 host 必须在 turn 开始时注入活动 ID，agent 只复用该值。
`scope_id` 不是凭证，服务端仍执行授权。

## Publication contract

一次 publication 必须：

1. 指定 source scope、exact Artifact identity 和 revision；
2. 在 target scope 创建新的 immutable revision；
3. 保留 source-qualified provenance 和 digest；
4. 不复制 source scope 的其他状态，不建立持续同步；
5. 不改变双方的 Handoff head；
6. 作为幂等操作完成，失败时不留下可见的部分结果。

`ArtifactRef` 继续表示 scope-local exact revision。跨 scope 参数在操作边界增加 source scope，不修改现有 `ArtifactRef`。

publication 需要读取 source 和写入 target。Role、Relation 和目录关联都不能替代这两个授权检查。

## Handoff Report contract

报告生成固定以下输入：

```text
root_scope_id
parent-relation revision
selected work scope_ids
exact Handoff revision or no_handoff per work
activity boundary
rendering options
```

动态的后代集合只用于发现。响应返回最终 selection，后续 parent relation 或 Handoff 变化不修改已经生成的报告。报告保留
selected work 之间最近的 work ancestry，不合并 Handoff histories，也不写入任何 scope。

报告对每个 selected scope 执行读取授权。不可访问 scope 的标题、存在性和数量也不能泄露。严格模式失败；允许部分结果的
模式明确标记缺失。

## Existing architecture and compatibility

以下现有行为保持不变：

- Runtime 显式接收 `scope_id` 并构造 scoped services；
- Source、Memory、Artifact 和 Handoff 使用 scope-local 存储；
- Handoff 使用 Prepared、Commit、Continue 和 exact revision；
- Handoff Report 保留 stable selection、canonical digest 和 deterministic renderer；
- MCP 继续通过显式 OpenAPI operation allowlist 暴露 agent tools。

新增 scope metadata、parent repository、Context resolver、publication service 和 work report selector。Codex 的 Git/目录派生逻辑
收缩为 bootstrap candidate discovery，skill 改为读取 host 已选择的当前 scope。

`ProjectDescriptor`、`WorkstreamDescriptor`、Project/Workstream membership 和 `project_id` 不再构成报告身份。现有 Project
catalog 可以在迁移期提供只读报告，但不能创建新的组织关系。

旧调用方可以继续提供已有 `scope_id`。缺少 Role 的旧 scope 在兼容读取中视为 `work`，以保留单 scope Handoff 行为。该
默认值不写回，也不根据 ID 或目录继续推断。

# Drawbacks

- Scope Role 和 Parent Relation 增加了两个显式选择。integration 必须理解生命周期、交接粒度和 Context 读取的差异。
- 完整支持 work switch 和 sub-agent 隔离需要 host 提供 turn、session 和 orchestrator lifecycle。
- 显式 publication 增加一次操作，但阻止中间材料和个人信息自动进入上级 scope。
- control、data 和 exchange 行为需要在 Python、HTTP、hooks、MCP 和 UI 之间保持一致语义。
- 从 Project catalog 切换到 scope projection 会改变报告 API 和持久化结构。

# Rationale and alternatives

## 只使用不透明 scope ID

不采用。它能隔离状态，却不能确定 Handoff 粒度、报告节点和长期共享边界。每个 integration 最终会通过命名规则重新引入这些
语义。

## 在 scope ID 中编码类型和层级

不采用。重命名、移动、fork 和 work switch 会让编码失效，也会诱导调用方从字符串推断 Context 和授权。

## 用 Role 同时决定父 Context

不采用。独立工作的 Context 可以共享，也可以隔离；临时 execution 也有 shared 和 delegated 两种需求。Role 和 Relation
必须独立。

## Agent 自行选择和创建 scope

不采用。模型调用发生在 turn 内部，无法保证 scope switch 在 Prepare Context 之前完成。重试还可能创建重复边界。host
掌握 session、turn 和 spawn lifecycle，应由 host 控制拓扑。

## 保留 Project catalog 组织报告

不采用。它在 scope parent relations 之外建立第二套 identity 和 membership，并要求 workspace、activity 和 report 同时维护
`project_id`。

## 自动提升所有 child 内容

不采用。自动提升无法区分交付物、中间推理、个人信息和未采用结果，也让共享范围随 agent 拓扑变化。

# Prior art

- RFC 0019 定义 integration-owned 的不透明业务分区。本提案保留不透明 identity，并补充 Role 和 Relation。
- RFC 0048 定义 scope-local exact Handoff。本提案补充跨 scope publication 和默认交接粒度。
- RFC 0082 的 exact selection、canonical digest 和 deterministic renderer 可以独立于 Project catalog 复用。
- [OpenDAL OFS RFC 0016](https://github.com/PsiACE/opendal-ofs/blob/main/rfcs/0016_filesystem_architecture.md)
  将 namespace authority 和应用的立即读写状态建模为两个独立选择。本提案同样把 scope 的生命周期职责与父 Context
  读取分开。
- Mem0 将 user、agent 和 run 作为独立过滤维度，但其平面过滤不能表达父 Context 和交接投影。
- CocoIndex 分开保存 session 内容、可读摘要和状态跟踪，其 provenance 设计适合 publication。
- Letta 分开记录 agent、run、step 和 trace，说明运行 provenance 不应编码进 namespace。

# Unresolved questions

- host 无法提供 pre-turn scope switching 时，应采用显式命令、UI 选择，还是把切换延迟到下一次 turn？
- `title`、`summary` 和 external references 的长度、字符集及并发更新规则需要在 OpenAPI 设计中确定。
- 不同 Artifact family 共享的最小 provenance 字段需要在 publication API 设计中确定。
- 旧 Project catalog 数据转换为 scope metadata 的规则需要单独迁移方案。

# Future possibilities

后续可以增加 scope 搜索、历史标题、归档策略和 host-bound MCP transport。需要报告多个无共同 parent 的工作时，可以在
exact selection 上增加多 root projection，不恢复 Project identity。跨租户共享需要单独定义租户身份、授权、撤销、审计和
数据复制语义，不复用本 RFC 的 Parent Relation。
