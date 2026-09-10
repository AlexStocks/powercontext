- Proposal Name: `recurring_failure_repair`
- Start Date: 2026-09-10
- Status: Proposed
- Tracking Issue: [oceanbase/powercontext#1554](https://github.com/oceanbase/powercontext/issues/1554)
- Related RFCs: [产品定义](0001_product_definition_and_vision.md)、[记忆层设计](0014_memory_layer_design.md)、
  [Context Pack](0028_context_pack.md)、[Handoff 制品](0048_handoff_artifact.md)、
  [Artifact Candidate 与 Review Inbox](0050_artifact_candidate_review_inbox.md)、
  [Experience 与 Skill 制品家族](0051_experience_skill_artifact_families.md)、
  [Scope 统计与用量](0072_scoped_statistics_and_usage.md)、
  [记忆检索重排](0080_memory_search_reranking.md)、
  [端到端评测架构](0081_end_to_end_evaluation_architecture.md)、
  [Source 定义与观测模型](1400_source_definition_and_observation_model.md)、
  [Prepared Context 文本装配](1489_prepared_context_text_assembly.md)

# Summary

Experience 回答的是"在什么情境下、什么动作产生了什么结果、我们学到了什么"。PowerContext 里没有任何东西回答它的
后续问题：「那个情境又出现了 —— 我们学到的东西到底起作用了吗？」

本 RFC 给反复出现的失败一个可机器匹配的身份、一个指明"修复必须触碰哪一层"的归因，以及一个记录某条已发布记录是否
被选中过、是否再次复发过、是否安静收场的结果账本。设计可归纳为四条：

1. **复发需要身份，而自由文本不是身份。** Experience 增加一个可选的 `failure` 结构化块，其中 signature 就是匹配键。
   没有它，同一个失败换一种措辞描述就是一条新的 Experience，于是复发无法计数，`lesson` 也无法被证伪。
2. **归因用于路由修复，而不是因果断言。** 必填的 `repair_surface` 指明修复该触碰哪一层，从而让"记录是对的，但召回
   从不触发它"成为一个可表达的诊断，而不是一个不可见的缺陷。
3. **准入以证据为闸门，降级以 Review 为闸门。** 没有引用了失败观测的失败记录，也没有任何自动退休、衰减或重要度评分 ——
   [RFC 0051](0051_experience_skill_artifact_families.md) 已记录的边界保持不变。
4. **账本从写入路径上已有的证据派生，绝不来自 `prepare_context`。** 选中由 Handoff 引用重建；复发在归整 Task Outcome
   Source 时判定。读路径保持只读。

# Motivation

## 当前无法计数复发

`LLMExperienceCandidatePipeline.incubate` 把 `task-outcome` Source 归整为 Experience 候选，并按内容精确相等加 Source
身份去重 —— `key = (candidate.proposal.model_dump_json(), tuple((source.source_type, source.source_id) for source in
selected))`，见 `src/powercontext/builtin/artifacts/experience/incubation.py`。这个 `seen` 集合只活在单次 `incubate()`
调用内部，而该调用受 `EXPERIENCE_INCUBATION_WINDOW_LIMIT = 32` 约束。它既不与更早窗口产出的候选比较，也不与已发布的
revision 比较。因此同一个失败在两个窗口被观测到就是两条 Experience —— 而用不同措辞描述的失败即便在同一个窗口内也是两条
Experience。由此产生两个后果：

- **一条 lesson 无法被证明是错的。** `ReviewService` 在发布*之前*校验证据、内容与 revision 一致性，但没有任何东西在发布
  *之后*观察这条记录到底起没起作用。
- **反复出现的失败看起来像进展。** 归整流水线忠实读取失败 —— 它的指令已经禁止把 failed、timed-out、cancelled 的 check
  写成成功（`artifacts/experience/prompts.py`）—— 然后从每一次失败里产出一条正向 Experience。同一个缺陷的第四次出现会
  产出第四条格式良好的 lesson，读起来像是知识在累积。

## 缺失的概念已经被命名过

[RFC 0014](0014_memory_layer_design.md) 把 "validated pitfalls" 列入 Memory 应优先保存的内容，要求一条持久条目
"会改变未来 agent 的判断或行动"，并把 `decision` 与 `constraint` 定义为一等 kind。但它没有定义 *validated* 是什么
意思。RFC 0014 同时固定了本 RFC 必须遵守的纪律："只有显式的 revision 证据才能修订条目；停用仍需要显式的 `forget()`"。

与此同时，[RFC 0051](0051_experience_skill_artifact_families.md) 把 "retirement, ranking, and usage attribution for
Experience and Skill" 列为未来工作，并声明当前 Artifact 契约 "has no retirement semantics, so this RFC adds no
automatic retirement or time decay"。用量归因正是本提案缺失的那一半。

## 具体场景

一个编码 agent 在两周内三次修复同一个不稳定的集成测试。每一次都会提出一条格式良好的 Experience，每一次都有人批准。
到周末，这个 scope 里躺着三条近乎相同的 Experience，而没有任何东西能区分"这条 lesson 起作用了"、"这条 lesson 从来没
进过上下文"和"这条 lesson 进过三次上下文，失败照样发生"。

我们想要的三个答案分别是：这条记录是否被选中过；失败是否还是复发了；以及复发时，坏掉的到底是哪一层。今天这三个答案都
无法表达。

## 本 RFC 不是什么

它不等同于 [#1508](https://github.com/oceanbase/powercontext/issues/1508)：后者把反复出现的 Task Outcome 关联到已有
Experience，并在配对比较下为 Skill 修订设闸。 #1508 做的事是归整；它没有匹配键，所以无法计数复发，也没有修复分类，
所以"召回策略坏了"只能被写成散文。它也不等同于 [#1510](https://github.com/oceanbase/powercontext/pull/1510) 的 Dream
工作流：Dream 决定*该提出哪个制品*，并假定输入概念已经存在。本 RFC 提供的正是这两个机制可以归整与路由的负面知识类型。

# Guide-level explanation

## 三个新概念

**Failure signature。** `ExperienceContent` 可以携带一个可选的 `failure` 块，其 `signature` 由两部分组成：
`recall_cue`（这条记录应该在什么情境下被召回）和可选的 `symptom`（失败的可观测形态）。cue 是匹配键：正是它让
"这事以前发生过"成为一个可核查的陈述。Experience 的其余部分保持原状 —— `situation` / `action` / `outcome` /
`lesson` 依然承载人类可读的判断。

**Repair surface。** 一个必填枚举，指明要让失败停止，必须改变哪一层：

| 取值 | 修复必须改变 |
| --- | --- |
| `experience_content` | Memory 条目文本、`ExperienceContent` 或纳管的 Skill 包 |
| `working_state` | Handoff 的 `objective` / `state[]` / `next_action`，或被记录的 Task Outcome 字段 |
| `recall_policy` | Scope 召回配置、`prepare` 查询的构造方式，或 `assembly.sections` 的选择 |
| `acceptance_check` | Handoff 的 `disposition` / 验收标准，或挂在 Experience 或 Handoff 上的校验指令 |

这个枚举存在的意义是路由修复。一条修复属于 `recall_policy` 的记录不应该再产出另一条 lesson —— 它应该产出一个关于检索的
信号。`repair_surface` 由生成环节提议、在 Review 确认；它不会被自动推断之后当作事实使用。

**Outcome ledger。** 每条已发布的 Experience revision 配三个计数器，全部从证据派生，而不是从插桩读路径得到：

- `selected` —— 该 revision 被某个 Handoff 引用过，而后来的 Task Outcome 是在该 Handoff 下完成的；
- `recurred` —— 更晚的 Task Outcome 报告了与该 signature 匹配的失败；
- `avoided` —— 该 revision 被选中用于某个已完成的 Task Outcome，且没有为该次任务报告本 signature 的复发。

`avoided` 是一个代理指标，本 RFC 明确这么说：任务成功并不能证明这条记录阻止了任何事情。

## 贡献者该如何理解它

把失败记录理解为一条**可被证伪、可被路由**的 Experience，而不是第二类知识存储。如果一条记录的证据不足，就不要写它 ——
缺失的记录好过错误的记录。如果一条记录反复被选中而失败仍在发生，答案不是再写一条记录，而是检查 `repair_surface`，因为
失败可能根本不在内容层。

被否决的方案记录与 API 陷阱依然是普通的 Experience 或 Memory 内容。它们是决策知识，没有复发可计数。只有*反复出现*的失败
才需要匹配键和账本。把两者混为一谈 —— 如下文引用的参考实现所做的那样 —— 会迫使每一条被否决的方案都背上永远用不到的计数器。

## 完整示例

agent 在沙箱里让 `pytest` 因为端口已被占用而失败。Outcome status 为 `failed`，check status 为 `failed`。

1. 归整流程把这次失败与 scope 中已有的 signature 做匹配，返回一条既有 Experience 的 cue（其 `repair_surface` 为
   `experience_content`），并以失败的 check 作为证据。
2. 账本为该 revision 记一次 `recurred`，provenance 指向该 Task Outcome。
3. 这是该记录第三次复发且期间没有 `avoided`，因此它被标记为待 Review。
4. 因为 surface 是 `experience_content`，Review 收到一个 revision 候选，其 `reason` 写明复发次数，证据就是同一次失败观测。
   由人决定是打磨这条记录，还是修改它的 `repair_surface`。

假如 surface 是 `recall_policy`，第 4 步根本不会发生。流水线会记录这次复发、在统计里暴露它，并且不提出任何制品变更，因为
坏掉的是检索而不是文本。

# Reference-level explanation

## 数据模型

可选块加在既有内容模型上，而不是新增一个 Artifact 家族：

```python
class FailureSignature(_ExperienceValue):
    recall_cue: Annotated[str, Field(min_length=1, max_length=MAX_FAILURE_CUE_LENGTH)]
    symptom: ExperienceText | None = None

class FailureRecord(_ExperienceValue):
    signature: FailureSignature
    repair_surface: RepairSurface
    @model_validator(mode="after")
    def reject_blank_cue(self) -> FailureRecord: ...

class ExperienceContent(_ExperienceValue):
    situation: ExperienceText
    action: ExperienceText
    outcome: ExperienceText
    lesson: ExperienceText
    failure: FailureRecord | None = None
```

`RepairSurface = Literal["experience_content", "working_state", "recall_policy", "acceptance_check"]`。
`MAX_FAILURE_CUE_LENGTH` 是提议新增的常量（512），因为匹配键不该有 8000 字符；具体数值是实现决策，不是设计决策。

**向后兼容。** Artifact 内容以 JSON 持久化，加载时经注册内容类型重新校验，因此可选字段对既有所有 revision 都是加载兼容的。
不引入 `schema_version`：Artifact 家族今天都不带它，为单个可选字段引入会产生第二套版本机制。

**两个必须实现的改动。** `experience_search_text` 目前只返回用户书写的字段（"so renderer labels cannot cause
matches"）—— signature 必须显式加入该投影，否则 cue 不会参与检索。`render_experience` 服务于有界上下文投递，因此 cue 与
symptom 需要一个渲染形态；否则这条记录可能被选中却永远无法被读到它的 agent 认出来。

## 准入规则

只有当下列条件全部成立时，失败记录才被准入。规则 1 与 2 构成置信下限：无法核实的记录被丢弃而不是被存储。

1. **必须引用一个失败观测。** 候选必须至少引用一个内容记录了失败的 Source —— status 为 `failed` 或 `blocked` 的 Task
   Outcome，或 status 为 `failed`、`timed_out`、`unavailable` 的 `TaskCheck`。既有的 Review 不变量（至少一条精确引用）是
   必要条件但不充分，因为这条引用必须专门为失败提供证据。
2. **单一、自足的 cue。** cue 必须命名一个可识别的情境，而不是对 outcome 字段的复述。
3. **必须有 `repair_surface`。** 记录必须说明修复该触碰哪一层。
4. **不允许静默的近似孪生。** 若归一化后的 cue 与既有记录的 cue 近似重复，候选会带一条指明既有记录的警告返回，以便作者改为
   修订那条记录。候选不会被自动拒绝。
5. **provenance。** 复用既有 Review 证据模型，不新增第二套证据机制。

每一次拒绝、每一条近似重复警告都以不可变 Source 的形式落入既有 Source/Observation 模型
（[RFC 1400](1400_source_definition_and_observation_model.md)），因此拒绝行为可审计，且无需发明日志文件。

## 匹配策略

匹配是承重机制，因此规定得保守。

- **归一化。** Unicode NFKC、大小写折叠、空白折叠、去掉首尾标点，得到比较键。归一化是比较的辅助手段，不是被存储的身份。
- **从候选集里选，而不是自由生成。** 归整时把 scope 中已有的 signature 交给流水线，问它这次观测到的失败与哪一个（如果有）
  匹配，并要求引用失败观测。流水线要么原样返回一个已有的归一化键，要么报告不匹配。这避免了改写漂移：模型是在封闭集合里做选择，
  而不是发明一个将来要用字符串相等去比较的键。
- **精确匹配才建立关联；模糊匹配只做提示。** 归一化精确匹配会写一条账本事件。token bigram 重叠度达到 0.8 时只产生*提示*，
  该阈值沿用参考实现，且绝不写计数器。模糊匹配绝不能静默增加复发计数，因为一次错误关联会静默污染这个特性存在的意义本身。
- **歧义一律不处理。** 若匹配到两条记录，则不写账本事件，并暴露该冲突。
- **signature 不是全局身份。** 记录的身份仍然是 `(artifact_id, revision)`。参考实现用内容派生的可变 id 作为卡片键，使得重新
  存储等于原地编辑；这与不可变 revision 不兼容，修改一条记录必须保持为显式修订。

## 账本写入路径

账本只由已经在消费 `task-outcome` Source 的归整流水线写入，绝不由 `prepare_context` 或检索写入。

这不是偏好，而是既有契约的要求。[RFC 0028](0028_context_pack.md) 规定 Context Pack "writes no database or file, enters
no Source journal or Memory evidence, starts no scheduler work, and is not persisted as telemetry"，且正常日志
"must not record scope, query, snippets, entry IDs, entry version IDs, or response bodies"。
[RFC 1489](1489_prepared_context_text_assembly.md) 同样把模型调用挡在装配之外。在读路径上插桩"选中"会同时违反这三条。

因此"选中"改由已经存在的 provenance 重建：

```
TaskOutcome.handoff_receipt_ref  ->  Handoff Revision
                                 ->  HandoffArtifactCitation[]  ->  进入上下文的 Experience revision
                                 ->  HandoffMemoryCitation[]
```

`HandoffResolution` 已经携带 `selection`、`selected_revision`、`current_revision` 与 `evidence_checks`，Handoff 激活
证据也已经受 `MAX_HANDOFF_CITATIONS` 约束。因此该重建是对既有数据的读取，而不是新的采集路径。它的信任级别是
`untrusted_history`，账本会记录这一点：一条引用只能证明 agent 的上下文里出现过这条记录，不能证明 agent 读过或遵守了它。

每次观测写一条账本事件：

```python
class RecurrenceObservation(_ArtifactValue):
    scope_id: str
    artifact_ref: ArtifactRef                      # 精确的 Experience revision
    signature_key: str                             # 匹配成功的归一化 cue
    event: Literal["selected", "recurred", "avoided"]
    match_basis: Literal["exact", "human_confirmed"]
    task_outcome_ref: SourceRef                    # recurred/avoided 的证据
    handoff_ref: ArtifactRef | None = None         # 选中是如何推导出来的
    observed_at: datetime
```

事件只追加，键为 `(scope_id, artifact_ref, signature_key)`。任何内容都不原地更新，因此即使记录后来被修订，它的产出历史仍然可查。

## 降级与 Review 的交互

当同一个 revision 上累积出复发连击 —— 提议默认值为连续 3 次 `recurred` 且其间没有 `avoided` —— 该 revision 被标记为
**needing review**。后果取决于 `repair_surface`：

- `experience_content` —— 流水线通过既有 `CandidateRepository` 提出一个 revision 候选，把复发次数写进 `reason`，把失败观测
  作为证据。批准会产出一个新的不可变 revision。这复用 #1510 的 Dream 模式：候选自动生成，人工决策强制。
- `working_state`、`recall_policy`、`acceptance_check` —— 不提出任何制品候选。复发被记录并在统计中暴露，因为这次修复不是
  内容变更。
- **没有自动退休、衰减、重要度评分或停用。** [RFC 0051](0051_experience_skill_artifact_families.md) 禁止它
  （"this RFC adds no automatic retirement or time decay"），Artifact 根本没有 `state` 字段，Experience 家族也不存在
  `active`/`inactive` 概念 —— 这与 Memory 条目不同，后者有。低产出的记录被变得*可见*，而不是被*停用*。真正的退休语义需要
  它自己的 RFC。
- `avoided` 事件会清除连击但不改变任何制品状态；它把记录送回正常召回，这是本 RFC 引入的唯一自动转换。

## 读取面

`ScopeStatistics`（[RFC 0072](0072_scoped_statistics_and_usage.md)）增加一个 `recurrence` 块：按 scope 统计
`selected` / `recurred` / `avoided` 数量，以及处于 needing review 的 revision 数量。因为既有统计层没有按制品的用量视图，
本 RFC 提议一个有界读取：由既有 statistics 操作返回某 scope 内按复发连击排序的前 N 个 revision。不新增 MCP 工具。

## 兼容性与影响面

| 影响面 | 影响 |
| --- | --- |
| `openapi/powercontext.yaml` | `ExperienceProposal` 增加一个可选对象；需要 `make api-generate` 再 `make contract-test` |
| 持久化 | 不引入 Artifact schema 版本；账本是持久化层新增的只追加记录 |
| Review | 契约不变。#1508 式归整继续可用；复发候选沿用既有 `propose_experience` 形态 |
| 检索（`prepare`） | 保持只读、不变。cue 之所以能被索引，是因为它成为内容投影的一部分 |
| 标签、授权 profile、artifact 资源发现 | 不受影响，因为没有新增 Artifact 家族 |
| 评测 | 新增一个可用于度量本特性的 outcome 类别；[#1422](https://github.com/oceanbase/powercontext/issues/1422) 尚未落地，因此该指标在此以不依赖它的方式定义 |

# Drawbacks

- **cue 是模型书写的自由文本，一个糟糕的 cue 会让整套机制失效。** 含糊的 cue 什么都匹配不到，于是复发被静默少计。这个失效模式
  是刻意选择的：少计只会产出一条安静的记录，而多计会产出一个自信的错误信号。两者都不免费。
- **账本给一个刻意保持读路径不写库的系统增加了持久化行。** 存储增长与归整事件成正比、与请求量无关，但它是真实存在的。
- **`avoided` 是代理指标。** 任务成功不可归因于某条记录在场，本 RFC 也不如此宣称。一条总被选中却从未被需要的记录会显得很成功。
- **Review 负担上升。** 嘈杂的归整流水线现在可以用复发候选淹没 Review Inbox。复发连击阈值是这里唯一的刹车。
- **把负面知识混入 `ExperienceContent` 拓宽了该家族的形态。** RFC 0051 把 Experience 定义为可复用判断；失败记录仍然是判断，
  但一个只期望四个散文字段的读者，现在需要知道何时该多读两个。

# Rationale and alternatives

**为什么扩展 `ExperienceContent` 而不是新增家族。** 新增家族需要触碰仓库元组、candidate 仓库、`BaseArtifactFamily`、标签、
授权 profile、artifact 资源发现、Review service 的家族分支、OpenAPI、JS 集成、文档与测试 —— 而这条记录的形态本身就是
Experience 形态（situation、action、outcome、lesson）加一个匹配键。反复失败的归整已经通过 `incubation.py` 落在 Experience
上，因此身份应该待在归整发生的地方。如果维护者判断独立家族更干净，那么三件东西 —— signature、`repair_surface`、账本 —— 一起
迁移，无需设计变更；唯一的开放部分就是落点。

**备选：保留一个 Memory `kind`。** 拒绝。Memory 条目已经有 `active`/`inactive` 状态与 `MemoryChangeOp`，且 RFC 0014 给它们
的准入契约是围绕"改变未来判断的陈述"构建的，与本提案不同。失败记录的评审单元应当是 Experience revision，账本也以 revision 为键。

**备选：原样照搬参考实现的卡片。** 拒绝，理由是两点在不可变 revision 模型下不可谈判：连续 5 次未避免后自动停用（违反 RFC 0051
且违反"Artifact 无状态"），以及内容派生的可变卡片 id（违反不可变 revision）。它的置信下限 —— 丢弃而不存储 —— 以及近似重复
只做*提示*的语义被采纳。

**备选：等 #1422 落地后再说。** 这是合理的排序论证，也是先提 issue 的原因。但本特性需要的指标必须向 #1422 提出请求，否则等循环
建好时它不会存在。

**不做这件事的影响。** 复发继续无法计数，召回策略类失败继续无法表达，也没有任何记录能被证明失败过。Experience 只会单调地、
不可证伪地累积。

# Prior art

**Recuris** —— Zhaochen Yu、Yingcheng Wu、Zhenfei Yin、Kaiyuan Chen、Zhe Zhao、Mengdi Wang、Shuicheng Yan、Ling Yang，
*Recursive Experiential-Working Memory Evolution for Long-Horizon Agent Harnesses*，arXiv:2608.24876v1，2026 年 8 月
25 日（[论文](https://arxiv.org/abs/2608.24876)、[代码](https://github.com/Gen-Verse/Recuris)，Apache-2.0）。它把 harness
的记忆控制层建模为 `M_k = (E_k, W_k, rho_k, C_k)`，并把这个元组定义为**补丁空间**：失败被定位到某个组件，而不仅仅是被总结。
有三点被沿用：以定位取代总结；把归因表述为 *"a repair decision rather than a claim of causal identification"*，这与
PowerContext 的证据纪律一致；以及验证门控的准入。

它的局限界定了可借鉴的边界。**它没有逐失败的复发计数器** —— 复用与避免只通过聚合代理指标衡量（`Reach`、留出集成功率增益、
dev 集回退率）。它的准入还假定存在一个留出开发集，而生产环境的召回环路没有这个预算。作者报告的增益（某模型在 tau-bench 上
+17.8 分、长程失败最高减少 80%）是单篇论文的自报数字，此处未做复现。因此本 RFC 是在已发表基线之上往前走 —— 账本是新工作，
而不是复现。

**claw-mem v7.6.0**（`Error Pattern Card`）是一个小型 Apache-2.0 社区插件，把 `E` 附近的诊断落地了。它的卡片格式是有用的起点：
`{trigger, symptom}` signature；`skill-defect | state-defect | invocation-timing | transition-judgment` 根因枚举
（其源码注释称这些语义映射到"the layer the fix must touch"）；最短 resolution 长度；0.8 重叠度的近似重复 trigger 检测且仅
提示编辑；以及逐卡片的 `hitCount` / `avoidedCount` / `lastHitAt`。其中两个组件被采纳；停用规则与可变卡片 id 不被采纳。它公开的
基准数字不作为基线引用：其 README 同时声称在 LoCoMo、ConvoMem、LongMemEval 上达到 100%，并声称存在源码里并不存在的 "subagent
memory merge"。只有其代码中可核验的常量在此被引用。

**PowerContext 自身的既有工作。** [RFC 0028](0028_context_pack.md) 允许把聚合的选择计数作为 telemetry，但禁止按条目记录日志；
[RFC 0072](0072_scoped_statistics_and_usage.md) 已经持久化召回测量（`preparations`、`baseline_tokens`、`recalled_tokens`、
`token_reduction`）与按 kind 的记忆计数，是复发块的天然归宿。
[RFC 0081](0081_end_to_end_evaluation_architecture.md) 定义了这个指标应当汇入的评测架构。

# Unresolved questions

1. **落点。** 扩展 `ExperienceContent`（本 RFC 推荐）、新增家族，还是保留一个 Memory kind。这是实现前必须敲定的唯一问题；RFC
   其余内容与落点无关。
2. **`repair_surface` 放在哪里** —— 放进制品，还是作为不触碰制品内容的 Review 注记？放进制品则持久、可查询；放进 Review 则
   保持内容不可变、判断可审计。
3. **阈值。** 触发 Review 的复发连击次数、`MAX_FAILURE_CUE_LENGTH`、以及 0.8 的近似重复重叠度都是提议值而非实测值。复发连击
   阈值尤其与每个 scope 的归整频率相互影响。
4. **`recall_policy` 类复发是否应该汇入检索评测环路**，而不是一个统计视图？如果是，`repair_surface` 就成为两个下游环路之间的
   路由键。
5. **账本归属。** 新增只追加的持久化记录，还是扩展统计层？RFC 0072 的仓库已经是可写且按 scope 分组的，这支持扩展；而按制品的
   粒度支持独立记录。
6. **命名。** RFC 0001 与 RFC 0002 把 `Trigger` 保留为产品级概念且其公开契约尚未定义。本 RFC 刻意避开这个词
   （`recall_cue`、`FailureSignature`）；请在生成公开 schema 之前确认该选择。
7. **`avoided` 是否属于 #1422**，作为通用的按制品 outcome 信号，而不是特性专用计数器？

# Future possibilities

- **跨 Scope 的失败模式。** 在多个 scope 中复发的 signature 是从个人资产晋升为团队资产的候选，这正是 RFC 0001 已经描述的流程。
- **signature 驱动的检索。** 今天 `SearchMemoryRequest` 只按 tag 过滤，没有家族或 kind 过滤。如果召回能直接针对 signature 求值，
  `recall_policy` 诊断会更有可操作性。
- **喂给 Skill 校验。** surface 为 `acceptance_check` 的记录，是 `SkillContent` 已携带的 `validation` 条目的天然来源。
- **Handoff 集成。** 最相关的 signature 可以被带进 `HandoffContent.state` 或 `omissions`，让后继 agent 继承"要避免的失败"，
  而不仅是"要继续的工作"。
- **可验证的退休。** 一旦账本存在，未来的 RFC 就能在实测产出的基础上定义退休语义，而不是靠猜 —— 这正是 RFC 0051 暗示的顺序。
