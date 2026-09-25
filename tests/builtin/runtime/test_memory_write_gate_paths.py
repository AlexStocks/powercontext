# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from powercontext.builtin.artifacts.memory import (
    MemoryCandidateRequest,
    MemoryEntryInput,
    MemoryWriteAssessment,
    MemoryWriteGateRequest,
    MemoryWriteRejectionCode,
    MemoryWriteVerdict,
)
from powercontext.builtin.artifacts.memory.errors import MemoryWriteRejectedError
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    BuiltinRuntime,
    CaptureSource,
    RememberMemoryRequest,
    open_builtin_contexts,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.decision_model import (
    DecisionOutcome,
    DecisionRequest,
    DecisionResult,
    FailOpenDecisionModel,
)
from powercontext.builtin.runtime.memory_write_gate import DecisionMemoryWriteGate
from powercontext.builtin.scope import ScopeDraft
from powercontext.builtin.sources import ContentSource

_SCRIPTED_POLICY_ID = "test.memory.write-gate.v1"


class _ScriptedGate:
    """A gate that returns one prepared assessment and records its requests."""

    policy_id = _SCRIPTED_POLICY_ID

    def __init__(self, assessment: MemoryWriteAssessment) -> None:
        self._assessment = assessment
        self.requests: list[MemoryWriteGateRequest] = []

    async def assess(self, request: MemoryWriteGateRequest, /) -> MemoryWriteAssessment:
        self.requests.append(request)
        return self._assessment


class _FailingDecisionModel:
    policy_id = "test.decision.failing.v1"

    async def evaluate(self, request: DecisionRequest, /) -> DecisionResult:
        raise ValueError("backend unavailable")  # noqa: TRY003


class _ContentCandidatePipeline:
    async def extract(self, request: MemoryCandidateRequest, /) -> tuple[MemoryEntryInput, ...]:
        return tuple(
            MemoryEntryInput(kind="fact", text=source.content, sources=(source,))
            for source in request.sources
            if isinstance(source, ContentSource)
        )


def _assessment(
    verdict: MemoryWriteVerdict,
    *,
    code: MemoryWriteRejectionCode | None = None,
    reason: str | None = None,
) -> MemoryWriteAssessment:
    return MemoryWriteAssessment(verdict=verdict, policy_id=_SCRIPTED_POLICY_ID, code=code, reason=reason)


def _config(tmp_path: Path) -> BuiltinConfig:
    return BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'gate.db'}"))


async def _create_scope(runtime: BuiltinRuntime, idempotency_key: str) -> str:
    assert runtime.scopes is not None
    scope = await runtime.scopes.create(
        ScopeDraft(title="Gate Test", summary="Memory write gate path test", idempotency_key=idempotency_key)
    )
    return scope.scope_id


def test_an_accepted_write_behaves_like_the_baseline(tmp_path: Path) -> None:
    async def scenario() -> None:
        gate = _ScriptedGate(_assessment(MemoryWriteVerdict.ACCEPT))
        async with open_builtin_contexts(_config(tmp_path), memory_write_gate=gate) as contexts:
            service = (await contexts.get("project")).artifacts.memory

            plan = await service.plan_remember(
                memory=None,
                entries=(MemoryEntryInput(kind="note", text="Accepted."),),
                mode="append",
            )

            assert plan.commit is not None
            assert plan.decision is not None
            assert plan.decision.verdict is MemoryWriteVerdict.ACCEPT
            assert [change.reason for change in plan.commit.memory.content.changes] == [None]
            assert gate.requests

    asyncio.run(scenario())


def test_a_flagged_write_is_annotated_and_still_committed(tmp_path: Path) -> None:
    async def scenario() -> None:
        gate = _ScriptedGate(_assessment(MemoryWriteVerdict.FLAG, reason="evidence is thin"))
        async with open_builtin_contexts(_config(tmp_path), memory_write_gate=gate) as contexts:
            service = (await contexts.get("project")).artifacts.memory

            stored = await service.remember(
                memory=None,
                entries=(MemoryEntryInput(kind="note", text="Flagged."),),
                mode="append",
            )

            assert stored is not None
            assert [change.reason for change in stored.content.changes] == ["evidence is thin"]

    asyncio.run(scenario())


def test_a_held_write_is_not_committed_and_stays_visible(tmp_path: Path) -> None:
    async def scenario() -> None:
        gate = _ScriptedGate(
            _assessment(
                MemoryWriteVerdict.HOLD,
                code=MemoryWriteRejectionCode.NEEDS_EVIDENCE,
                reason="the candidate cites no evidence",
            )
        )
        async with open_builtin_contexts(_config(tmp_path), memory_write_gate=gate) as contexts:
            service = (await contexts.get("project")).artifacts.memory

            plan = await service.plan_remember(
                memory=None,
                entries=(MemoryEntryInput(kind="note", text="Held."),),
                mode="append",
            )

            assert plan.commit is None
            assert plan.decision is not None
            assert plan.decision.verdict is MemoryWriteVerdict.HOLD
            assert plan.decision.code is MemoryWriteRejectionCode.NEEDS_EVIDENCE
            assert plan.decision.reason == "the candidate cites no evidence"
            # No head is written, and the refusal is not silently dropped.
            assert await service.remember(memory=None, entries=(MemoryEntryInput(kind="note", text="Held."),)) is None

    asyncio.run(scenario())


def test_a_failing_backend_leaves_the_write_unchanged(tmp_path: Path) -> None:
    async def scenario() -> None:
        gate = DecisionMemoryWriteGate(FailOpenDecisionModel(_FailingDecisionModel()), hold_on=DecisionOutcome.YES)
        async with open_builtin_contexts(_config(tmp_path), memory_write_gate=gate) as contexts:
            service = (await contexts.get("project")).artifacts.memory

            stored = await service.remember(
                memory=None,
                entries=(MemoryEntryInput(kind="note", text="Passed through."),),
                mode="append",
            )

            assert stored is not None

    asyncio.run(scenario())


def test_without_a_gate_the_plan_carries_no_decision(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with open_builtin_contexts(_config(tmp_path)) as contexts:
            service = (await contexts.get("project")).artifacts.memory

            plan = await service.plan_remember(
                memory=None,
                entries=(MemoryEntryInput(kind="note", text="Plain."),),
                mode="append",
            )

            assert plan.decision is None
            assert plan.commit is not None

    asyncio.run(scenario())


def test_the_explicit_write_surfaces_a_hold_as_a_structured_error(tmp_path: Path) -> None:
    async def scenario() -> None:
        gate = _ScriptedGate(
            _assessment(
                MemoryWriteVerdict.HOLD,
                code=MemoryWriteRejectionCode.INSUFFICIENT_COVERAGE,
                reason="the citation is thin",
            )
        )
        async with open_builtin_runtime(_config(tmp_path), memory_write_gate=gate) as runtime:
            scope_id = await _create_scope(runtime, "gate-explicit-hold")
            with pytest.raises(MemoryWriteRejectedError) as error:
                await runtime.memory.for_scope(scope_id).remember(
                    RememberMemoryRequest(entries=(MemoryEntryInput(kind="note", text="Rejected."),))
                )

            assert error.value.code == "insufficient_coverage"
            assert error.value.reason == "the citation is thin"

    asyncio.run(scenario())


def test_the_ingestion_window_reports_a_hold_and_still_advances(tmp_path: Path) -> None:
    async def scenario() -> None:
        gate = _ScriptedGate(
            _assessment(
                MemoryWriteVerdict.HOLD,
                code=MemoryWriteRejectionCode.INSUFFICIENT_COVERAGE,
                reason="the window evidence is thin",
            )
        )
        async with open_builtin_runtime(
            _config(tmp_path),
            candidate_pipeline=_ContentCandidatePipeline(),
            memory_write_gate=gate,
        ) as runtime:
            scope_id = await _create_scope(runtime, "gate-ingestion-hold")
            await runtime.sources.for_scope(scope_id).capture(
                CaptureSource(source_id="task-1", content="A durable note.", metadata={})
            )

            result = await runtime.memory.for_scope(scope_id).flush()

            assert result.held_count == 1
            assert result.hold_codes == ("insufficient_coverage",)
            assert result.processed is True
            assert result.memory_ref is None

    asyncio.run(scenario())
