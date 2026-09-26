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

"""Observe a suspected conflict on a pending Memory write and log it (mark-only, log-only).

The gate answers one narrow question: does the new content contradict any existing active entry?
It never decides content and never mutates anything — a ``POSSIBLE_CONFLICT`` is an observation on
the write path, not a lifecycle state. The observation is *log-only*: ``assess`` returns the
assessment so it can be unit-tested directly, but it is deliberately not carried on any plan, and
the sole observable outlet is this module's structured log event ``memory.conflict.assess``.

``possible_conflict`` is *not* RFC 1652's retrieval-time lifecycle projection
``unresolved_conflict``: that projection is unimplemented and RFC 1652 is still a Proposal. The two
vocabularies must never be conflated.

Do-not-do (hard, this module has no exit that changes data):
- never delete, ``deactivate``, merge, or ``supersede`` an entry;
- never write any lifecycle state on any entry;
- never rewrite content or memo prose;
- never route Memory to the Review Inbox (RFC 0050 §280: Memory is direct-write);
- never perform a pre-write refusal (that is the write gate's job, not this observation);
- never introduce a destructive ``MemoryChangeOp``;
- never change the public HTTP/MCP contract.

Any backend failure degrades to ``NONE`` so an unavailable judge can never mark — or block — a
write.
"""

from __future__ import annotations

import logging
from typing import Literal

from powercontext._logging import log_safely
from powercontext.builtin.artifacts.memory.protocols import (
    MemoryConflictAssessment,
    MemoryConflictGate,
    MemoryConflictGateRequest,
    MemoryConflictVerdict,
)
from powercontext.builtin.runtime.decision_model import (
    DecisionKind,
    DecisionModel,
    DecisionOutcome,
    DecisionRequest,
    DecisionResult,
)

logger = logging.getLogger(__name__)

_CONFLICT_QUESTION = (
    "Does the proposed memory content contradict any existing active entry, so that keeping both "
    "would record inconsistent facts?"
)
# The existing-entry projection is bounded by the same ceiling as the write gate's citation
# selector, so an oversized comparison set is truncated instead of being sent whole.
_MAX_EVIDENCE_ITEMS = 32
_MAX_SUBJECT_LENGTH = 4000
_MAX_REASON_LENGTH = 512
_DEFAULT_REASON = "the proposed content may contradict an existing entry"


def build_memory_conflict_gate(
    decision_model: DecisionModel | None,
    *,
    enabled: bool,
    conflict_on: Literal["yes", "no"] = "yes",
    threshold: float | None = None,
) -> MemoryConflictGate | None:
    """Build the opt-in gate, or return ``None`` while it stays disabled.

    The direction is supplied by configuration and must be calibrated before the gate is enabled;
    a disabled gate and a missing backend both resolve to ``None``.
    """

    if not enabled or decision_model is None:
        return None
    return DecisionMemoryConflictGate(
        decision_model,
        conflict_on=DecisionOutcome(conflict_on),
        threshold=threshold,
    )


class DecisionMemoryConflictGate:
    """Map one decision-model verdict onto a Memory conflict observation.

    ``conflict_on`` is the calibrated outcome that means "the new content contradicts an existing
    entry"; a clear verdict in that direction becomes ``POSSIBLE_CONFLICT``, every other verdict
    becomes ``NONE``. An abstention or fallback is never a mark. When a threshold is configured, a
    conflict-direction verdict whose confidence falls below it stays unmarked, so a weak signal
    cannot create a false positive.

    Mark-only: this gate has no exit that changes data.
    """

    def __init__(
        self,
        decision_model: DecisionModel,
        /,
        *,
        conflict_on: DecisionOutcome = DecisionOutcome.YES,
        threshold: float | None = None,
    ) -> None:
        if conflict_on is DecisionOutcome.ABSTAIN:
            raise ValueError("the conflict direction cannot be abstain")  # noqa: TRY003
        self._decision_model = decision_model
        self._conflict_on = conflict_on
        self._threshold = threshold
        self.policy_id = decision_model.policy_id

    async def assess(self, request: MemoryConflictGateRequest, /) -> MemoryConflictAssessment:
        """Observe one pending write and return a caller-visible conflict mark."""

        decision = await self._decision_model.evaluate(
            DecisionRequest(
                decision_kind=DecisionKind.MEMORY_CONFLICT.value,
                question=_CONFLICT_QUESTION,
                subject=_bounded_subject(request.candidates),
                evidence=request.existing_entries[:_MAX_EVIDENCE_ITEMS],
            )
        )
        assessment = self._map(decision)
        self._log(assessment)
        return assessment

    def _map(self, decision: DecisionResult) -> MemoryConflictAssessment:
        if decision.used_fallback or decision.outcome is DecisionOutcome.ABSTAIN:
            return MemoryConflictAssessment(
                verdict=MemoryConflictVerdict.NONE,
                policy_id=decision.policy_id,
                used_fallback=decision.used_fallback,
            )
        if decision.outcome is not self._conflict_on:
            return MemoryConflictAssessment(verdict=MemoryConflictVerdict.NONE, policy_id=decision.policy_id)
        if self._threshold is not None and decision.confidence is not None and decision.confidence < self._threshold:
            return MemoryConflictAssessment(verdict=MemoryConflictVerdict.NONE, policy_id=decision.policy_id)
        return MemoryConflictAssessment(
            verdict=MemoryConflictVerdict.POSSIBLE_CONFLICT,
            policy_id=decision.policy_id,
            reason=_bounded_reason(decision.rationale),
        )

    def _log(self, assessment: MemoryConflictAssessment) -> None:
        # One event name for every verdict: a reader filters on the ``verdict`` field, not on a
        # second event name, so the vocabulary stays single-sourced.
        log_safely(
            logger,
            logging.INFO,
            "Memory conflict gate observed a pending write",
            extra={
                "event": "memory.conflict.assess",
                "decision_kind": DecisionKind.MEMORY_CONFLICT.value,
                "policy_id": assessment.policy_id,
                "verdict": assessment.verdict.value,
                "used_fallback": assessment.used_fallback,
            },
        )


def _bounded_subject(candidates: tuple[str, ...]) -> str:
    return "\n".join(candidates)[:_MAX_SUBJECT_LENGTH]


def _bounded_reason(value: str | None) -> str:
    if value is None:
        return _DEFAULT_REASON
    normalized = value.strip()
    return normalized[:_MAX_REASON_LENGTH] if normalized else _DEFAULT_REASON


__all__ = [
    "DecisionMemoryConflictGate",
    "MemoryConflictAssessment",
    "MemoryConflictGate",
    "MemoryConflictGateRequest",
    "MemoryConflictVerdict",
    "build_memory_conflict_gate",
]
