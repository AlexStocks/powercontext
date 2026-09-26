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

"""Guards for the mark-only, log-only Memory conflict gate.

The gate may only *observe*: a ``possible_conflict`` mark must never change what is committed, must
never be carried on a plan or any public projection, and must never introduce a lifecycle term or a
destructive ``MemoryChangeOp``. These tests pin the default-off write path, the byte-stability of a
marked commit, the anti-revival gate on ``MemoryWritePlan``, and the fail-open degradation.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest import mock
from uuid import UUID

import pytest
from pydantic import BaseModel

import powercontext.builtin.runtime.relational as relational_module
import powercontext.http._generated.models as http_models
from powercontext.builtin.artifacts.memory import (
    Memory,
    MemoryConflictGateRequest,
    MemoryConflictVerdict,
    MemoryContent,
    MemoryEntryInput,
    MemoryEntryVersion,
    MemoryManifest,
    MemoryManifestEntry,
    MemoryWritePlan,
)
from powercontext.builtin.artifacts.memory.service import (
    _MAX_CONFLICT_ENTRIES,
    _MAX_CONFLICT_ENTRY_LENGTH,
    _active_entry_texts,
)
from powercontext.builtin.inference import InferenceUsage
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    BuiltinRuntime,
    MemoryMutationResult,
    RememberMemoryRequest,
    RuntimeConfig,
    open_builtin_contexts,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.decision_model import (
    DecisionModel,
    DecisionOutcome,
    DecisionRequest,
    DecisionResult,
    FailOpenDecisionModel,
)
from powercontext.builtin.runtime.memory_conflict_gate import (
    _MAX_EVIDENCE_ITEMS,
    _MAX_REASON_LENGTH,
    _MAX_SUBJECT_LENGTH,
    DecisionMemoryConflictGate,
    build_memory_conflict_gate,
)
from powercontext.builtin.scope import ScopeDraft

_STATIC_POLICY_ID = "powercontext.decision.static.v1"


class _StaticDecisionModel:
    """A backend that always returns one prepared verdict."""

    policy_id = _STATIC_POLICY_ID

    def __init__(self, result: DecisionResult) -> None:
        self._result = result

    async def evaluate(self, request: DecisionRequest, /) -> DecisionResult:
        return self._result


class _RecordingDecisionModel:
    """A backend that records every request it receives."""

    policy_id = "powercontext.decision.recording.v1"

    def __init__(self, result: DecisionResult) -> None:
        self._result = result
        self.requests: list[DecisionRequest] = []

    async def evaluate(self, request: DecisionRequest, /) -> DecisionResult:
        self.requests.append(request)
        return self._result


class _CountingDecisionModel:
    """A backend that counts how often it is asked to evaluate."""

    policy_id = "powercontext.decision.counting.v1"

    def __init__(self) -> None:
        self.calls = 0

    async def evaluate(self, request: DecisionRequest, /) -> DecisionResult:
        self.calls += 1
        return DecisionResult(DecisionOutcome.YES, self.policy_id, InferenceUsage(requests=1))


class _FailingDecisionModel:
    """A backend whose every evaluation raises."""

    policy_id = "powercontext.decision.failing.v1"

    async def evaluate(self, request: DecisionRequest, /) -> DecisionResult:
        raise ValueError("backend unavailable")  # noqa: TRY003


class _DeterministicIdentity:
    """Yield reproducible UUIDs so two independent runs become byte-comparable.

    Memory identities are random by construction, so a raw comparison across two runs would compare
    randomness. Pinning the generator lets the guard tests prove the *content* is identical field
    for field.
    """

    def __init__(self) -> None:
        self._counter = 0

    def __call__(self) -> UUID:
        self._counter += 1
        return UUID(int=self._counter)


def _verdict(
    outcome: DecisionOutcome,
    *,
    rationale: str | None = None,
    confidence: float | None = None,
    used_fallback: bool = False,
) -> DecisionResult:
    return DecisionResult(
        outcome,
        _STATIC_POLICY_ID,
        InferenceUsage(requests=1),
        rationale=rationale,
        confidence=confidence,
        used_fallback=used_fallback,
    )


def _request(
    *,
    candidates: tuple[str, ...] = ("The deployment target is production.",),
    existing_entries: tuple[str, ...] = (),
) -> MemoryConflictGateRequest:
    return MemoryConflictGateRequest(candidates=candidates, existing_entries=existing_entries, expected_revision=1)


def _config(
    tmp_path: Path,
    runtime: RuntimeConfig | None = None,
    database: str = "conflict.db",
) -> BuiltinConfig:
    return BuiltinConfig(
        database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / database}"),
        runtime=RuntimeConfig() if runtime is None else runtime,
    )


async def _create_scope(runtime: BuiltinRuntime, idempotency_key: str) -> str:
    assert runtime.scopes is not None
    scope = await runtime.scopes.create(
        ScopeDraft(title="Conflict Test", summary="Memory conflict gate path test", idempotency_key=idempotency_key)
    )
    return scope.scope_id


async def _plan_under_deterministic_ids(
    tmp_path: Path,
    database: str,
    *,
    decision_model: DecisionModel | None = None,
) -> MemoryWritePlan:
    with mock.patch.object(relational_module, "uuid4", _DeterministicIdentity()):
        async with open_builtin_contexts(
            _config(tmp_path, database=database), decision_model=decision_model
        ) as contexts:
            service = (await contexts.get("project")).artifacts.memory
            return await service.plan_remember(
                memory=None,
                entries=(MemoryEntryInput(kind="fact", text="The deployment target is production."),),
                mode="append",
            )


async def _remember_under_deterministic_ids(
    tmp_path: Path, database: str, gate: DecisionMemoryConflictGate | None
) -> Memory:
    with mock.patch.object(relational_module, "uuid4", _DeterministicIdentity()):
        async with open_builtin_contexts(_config(tmp_path, database=database), memory_conflict_gate=gate) as contexts:
            service = (await contexts.get("project")).artifacts.memory
            first = await service.remember(
                memory=None,
                entries=(MemoryEntryInput(kind="fact", text="The build runs on Linux."),),
                mode="append",
            )
            assert first is not None
            stored = await service.remember(
                memory=first,
                entries=(
                    MemoryEntryInput(kind="fact", text="The build runs on Windows."),
                    MemoryEntryInput(kind="fact", text="The build runs on macOS."),
                ),
                mode="append",
            )
            assert stored is not None
            return stored


def _memory_with_entries(count: int) -> tuple[Memory, tuple[MemoryEntryVersion, ...]]:
    entries = tuple(
        MemoryManifestEntry(
            entry_id=f"entry-{index}",
            entry_version_id=f"version-{index}",
            entry_content_hash="h" * 64,
            state="active",
        )
        for index in range(count)
    )
    versions = tuple(
        MemoryEntryVersion(
            memory_artifact_id="memory",
            entry_id=f"entry-{index}",
            entry_version_id=f"version-{index}",
            version=1,
            previous_version_id=None,
            kind="fact",
            text="t" * (_MAX_CONFLICT_ENTRY_LENGTH + 100),
            entry_content_hash="h" * 64,
            created_in_revision=1,
        )
        for index in range(count)
    )
    memory = Memory(artifact_id="memory", revision=1, content=MemoryContent(manifest=MemoryManifest(entries=entries)))
    return memory, versions


def _http_models_with_conflict_field() -> list[str]:
    return sorted(
        name
        for name, value in vars(http_models).items()
        if isinstance(value, type) and issubclass(value, BaseModel) and "conflict" in getattr(value, "model_fields", {})
    )


def test_conflict_gate_marks_possible_conflict() -> None:
    async def scenario() -> None:
        gate = DecisionMemoryConflictGate(
            _StaticDecisionModel(_verdict(DecisionOutcome.YES, rationale="contradicts an existing entry")),
            conflict_on=DecisionOutcome.YES,
        )

        assessment = await gate.assess(_request(existing_entries=("The deployment target is staging.",)))

        assert assessment.verdict is MemoryConflictVerdict.POSSIBLE_CONFLICT
        assert assessment.verdict.value == "possible_conflict"
        assert assessment.policy_id == _STATIC_POLICY_ID
        assert assessment.used_fallback is False
        assert assessment.reason == "contradicts an existing entry"

    asyncio.run(scenario())


def test_conflict_gate_abstain_and_fallback_yield_none() -> None:
    async def scenario() -> None:
        abstaining = DecisionMemoryConflictGate(
            _StaticDecisionModel(_verdict(DecisionOutcome.ABSTAIN)), conflict_on=DecisionOutcome.YES
        )
        abstained = await abstaining.assess(_request(existing_entries=("The deployment target is staging.",)))

        failing = DecisionMemoryConflictGate(
            FailOpenDecisionModel(_FailingDecisionModel()), conflict_on=DecisionOutcome.YES
        )
        fell_back = await failing.assess(_request(existing_entries=("The deployment target is staging.",)))

        assert abstained.verdict is MemoryConflictVerdict.NONE
        assert abstained.used_fallback is False
        assert fell_back.verdict is MemoryConflictVerdict.NONE
        assert fell_back.used_fallback is True

    asyncio.run(scenario())


def test_conflict_mark_never_mutates_memory(tmp_path: Path) -> None:
    async def scenario() -> None:
        baseline = await _remember_under_deterministic_ids(tmp_path, "conflict-baseline.db", None)
        gate = DecisionMemoryConflictGate(
            _StaticDecisionModel(_verdict(DecisionOutcome.YES, rationale="contradicts an entry")),
            conflict_on=DecisionOutcome.YES,
        )
        marked = await _remember_under_deterministic_ids(tmp_path, "conflict-marked.db", gate)

        # Mark-only: the observed conflict never changes the committed Memory Revision.
        assert marked.model_dump_json() == baseline.model_dump_json()
        assert {change.op for change in marked.content.changes} == {change.op for change in baseline.content.changes}
        assert {change.op for change in marked.content.changes} == {"add"}
        assert {entry.state for entry in marked.content.manifest.entries} == {"active"}
        assert len(marked.content.manifest.entries) == 3
        assert not any(word in marked.model_dump_json() for word in ("inactive", "superseded", "unresolved_conflict"))

    asyncio.run(scenario())


def test_conflict_disabled_no_model_call(tmp_path: Path) -> None:
    async def scenario() -> None:
        spy = _CountingDecisionModel()
        baseline = await _plan_under_deterministic_ids(tmp_path, "conflict-disabled-baseline.db")
        disabled = await _plan_under_deterministic_ids(tmp_path, "conflict-disabled.db", decision_model=spy)

        # The switch is off: the conflict path is never reached and the backend is never called.
        assert spy.calls == 0
        assert baseline.commit is not None
        assert disabled.commit is not None
        assert disabled.commit.memory.model_dump_json() == baseline.commit.memory.model_dump_json()

    asyncio.run(scenario())


def test_conflict_no_plan_field() -> None:
    # Anti-revival gate: the plan must never carry a conflict field, and its shape stays the baseline.
    assert "conflict" not in MemoryWritePlan.model_fields
    assert set(MemoryWritePlan.model_fields) == {"result", "commit", "decision"}


def test_conflict_no_backend_passes_through(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # A disabled gate and a missing backend both resolve to no gate at all.
    assert build_memory_conflict_gate(None, enabled=True) is None

    async def scenario() -> None:
        config = _config(tmp_path, RuntimeConfig(memory_conflict_enabled=True), database="conflict-no-backend.db")
        async with open_builtin_runtime(config) as runtime:
            scope_id = await _create_scope(runtime, "conflict-no-backend")
            written = await runtime.memory.for_scope(scope_id).remember(
                RememberMemoryRequest(entries=(MemoryEntryInput(kind="note", text="Passed through."),))
            )

            assert written.memory_ref is not None

    with caplog.at_level(logging.WARNING, logger="powercontext.builtin.runtime.composition"):
        asyncio.run(scenario())

    assert "memory.conflict-gate.unavailable" in {getattr(record, "event", None) for record in caplog.records}


def test_conflict_mark_internal_only(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # Neither the in-process mutation result nor any generated HTTP model carries conflict information.
    assert "conflict" not in MemoryMutationResult.model_fields
    assert _http_models_with_conflict_field() == []

    async def scenario() -> None:
        gate = DecisionMemoryConflictGate(
            _StaticDecisionModel(_verdict(DecisionOutcome.YES, rationale="contradicts an entry")),
            conflict_on=DecisionOutcome.YES,
        )
        config = _config(tmp_path, database="conflict-internal.db")
        async with open_builtin_runtime(config, memory_conflict_gate=gate) as runtime:
            scope_id = await _create_scope(runtime, "conflict-internal")
            written = await runtime.memory.for_scope(scope_id).remember(
                RememberMemoryRequest(entries=(MemoryEntryInput(kind="note", text="Observed internally."),))
            )

            assert written.memory_ref is not None
            assert not hasattr(written, "conflict")

    with caplog.at_level(logging.INFO, logger="powercontext.builtin.runtime.memory_conflict_gate"):
        asyncio.run(scenario())

    # The sole observable outlet is the gate's own structured log event.
    assert "memory.conflict.assess" in {getattr(record, "event", None) for record in caplog.records}


def test_conflict_structured_log_event(caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        gate = DecisionMemoryConflictGate(
            _StaticDecisionModel(_verdict(DecisionOutcome.YES, rationale="contradicts an entry")),
            conflict_on=DecisionOutcome.YES,
        )
        await gate.assess(_request(existing_entries=("The deployment target is staging.",)))

    with caplog.at_level(logging.INFO, logger="powercontext.builtin.runtime.memory_conflict_gate"):
        asyncio.run(scenario())

    # A single, stable event name; a reader filters on ``verdict`` rather than on a second name.
    assert {getattr(record, "event", None) for record in caplog.records} == {"memory.conflict.assess"}
    assert {getattr(record, "decision_kind", None) for record in caplog.records} == {"memory.conflict"}
    assert {getattr(record, "policy_id", None) for record in caplog.records} == {_STATIC_POLICY_ID}
    assert {getattr(record, "verdict", None) for record in caplog.records} == {"possible_conflict"}
    assert {getattr(record, "used_fallback", None) for record in caplog.records} == {False}


def test_conflict_request_bounded() -> None:
    async def scenario() -> None:
        backend = _RecordingDecisionModel(_verdict(DecisionOutcome.YES, rationale="x" * 5000))
        gate = DecisionMemoryConflictGate(backend, conflict_on=DecisionOutcome.YES)
        request = MemoryConflictGateRequest(
            candidates=("y" * 5000,),
            existing_entries=tuple(f"entry-{index}" for index in range(100)),
            expected_revision=1,
        )

        assessment = await gate.assess(request)

        sent = backend.requests[0]
        assert len(sent.subject) <= _MAX_SUBJECT_LENGTH
        assert len(sent.evidence) <= _MAX_EVIDENCE_ITEMS
        assert assessment.reason is not None
        assert len(assessment.reason) <= _MAX_REASON_LENGTH

        # The projection that feeds the gate is bounded on both axes before any model call.
        memory, entries = _memory_with_entries(_MAX_CONFLICT_ENTRIES + 5)
        projected = _active_entry_texts(memory, entries)
        assert len(projected) == _MAX_CONFLICT_ENTRIES
        assert all(len(text) <= _MAX_CONFLICT_ENTRY_LENGTH for text in projected)

    asyncio.run(scenario())
