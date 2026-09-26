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

"""Family-level ports used by the Memory service and SQL adapters."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from powercontext.artifacts import Artifact, ArtifactRef
from powercontext.builtin.artifacts.memory.models import (
    EmbeddingProfile,
    Memory,
    MemoryCapabilities,
    MemoryChannelHit,
    MemoryEntryInput,
    MemoryEntryVersion,
    MemoryHit,
    MemoryRevisionChanges,
    MemoryUsedSearchMode,
)
from powercontext.builtin.inference import EmbeddingModel, EmbeddingVector
from powercontext.builtin.tags import TagFilter
from powercontext.sources import Source


class MemoryCandidateRequest(BaseModel):
    """Canonical evidence and bounded current entries offered to a pipeline."""

    sources: tuple[Source, ...]
    artifacts: tuple[Artifact[object], ...]
    current_entries: tuple[MemoryEntryVersion, ...]


class MemoryProjection(BaseModel):
    """A rebuildable active-head projection prepared outside a transaction."""

    entry_version: MemoryEntryVersion
    searchable_text: str
    embedding: EmbeddingVector | None = None
    embedding_content_hash: str | None = None


class MemoryCommit(BaseModel):
    """A complete Memory Revision and every row changed atomically with it."""

    base: Memory | None
    memory: Memory
    content_hash: str
    entry_versions: tuple[MemoryEntryVersion, ...]
    projections: tuple[MemoryProjection, ...]


class MemoryWriteRejectionCode(StrEnum):
    """Structured, caller-visible vocabulary for a held Memory write.

    Names mirror the evidence-selection vocabulary so a host can branch on one stable set of
    codes instead of parsing prose.
    """

    NEEDS_EVIDENCE = "needs_evidence"
    EVIDENCE_LIMIT_EXCEEDED = "evidence_limit_exceeded"
    INSUFFICIENT_COVERAGE = "insufficient_coverage"


class MemoryWriteVerdict(StrEnum):
    """The complete verdict vocabulary a Memory write gate may produce."""

    ACCEPT = "accept"
    FLAG = "flag"
    HOLD = "hold"


class MemoryWriteAssessment(BaseModel):
    """One gate verdict with the structured refusal a caller can observe.

    ``HOLD`` always carries both a ``code`` and a ``reason``: a refused write is visible to
    its caller, never silently dropped. ``ACCEPT``/``FLAG`` leave ``code`` unset.
    """

    model_config = ConfigDict(frozen=True)

    verdict: MemoryWriteVerdict
    policy_id: str
    code: MemoryWriteRejectionCode | None = None
    reason: str | None = None
    used_fallback: bool = False


@dataclass(frozen=True, slots=True)
class MemoryWriteGateRequest:
    """A bounded projection of one pending Memory write for sufficiency judgement."""

    candidates: tuple[str, ...]
    evidence: tuple[str, ...]
    expected_revision: int | None = None


class MemoryWriteGate(Protocol):
    """Judge whether a pending Memory write is supported by its cited evidence.

    A gate only classifies: it never writes, approves, rejects, or deletes anything. A missing
    or failing gate must be treated by callers as a pass-through, never as a hold.
    """

    policy_id: str

    async def assess(self, request: MemoryWriteGateRequest, /) -> MemoryWriteAssessment:
        """Return one verdict for a candidate set and its bounded evidence projection."""

        ...


class MemoryWritePlan(BaseModel):
    """A side-effect-free result that can be committed in an outer transaction."""

    result: Memory | None
    commit: MemoryCommit | None
    decision: MemoryWriteAssessment | None = None


class MemoryConflictVerdict(StrEnum):
    """The complete observation vocabulary for a suspected Memory conflict.

    ``POSSIBLE_CONFLICT`` is a write-path observation only. It is not a lifecycle state and it
    never implies a delete, a supersession, or a merge; nothing downstream acts on it.
    """

    NONE = "none"
    POSSIBLE_CONFLICT = "possible_conflict"


class MemoryConflictAssessment(BaseModel):
    """One conflict observation with the bounded reason its caller may read.

    The assessment is a mark: it never carries a mutation and never changes a commit. It is not
    carried on any plan; the gate that produces it logs it and keeps it out of every result.
    """

    model_config = ConfigDict(frozen=True)

    verdict: MemoryConflictVerdict
    policy_id: str
    reason: str | None = None
    used_fallback: bool = False


@dataclass(frozen=True, slots=True)
class MemoryConflictGateRequest:
    """A bounded projection of one pending write and the active entries it might contradict."""

    candidates: tuple[str, ...]
    existing_entries: tuple[str, ...]
    expected_revision: int | None = None


class MemoryConflictGate(Protocol):
    """Observe whether a pending Memory write conflicts with existing content.

    A gate only observes: it never writes, deletes, deactivates, merges, or supersedes anything,
    and a missing or failing gate must be treated by callers as "no conflict observed". The
    returned assessment is the port's own self-description: it is logged, never carried onward.
    """

    policy_id: str

    async def assess(self, request: MemoryConflictGateRequest, /) -> MemoryConflictAssessment:
        """Return one conflict mark for a candidate set and its bounded existing-entry projection."""

        ...


class MemorySearchRequest(BaseModel):
    """A fully validated backend search request for explicit current heads."""

    query: str
    analyzed_query: str
    memories: tuple[ArtifactRef, ...]
    candidate_limit: int
    mode: MemoryUsedSearchMode
    query_vector: EmbeddingVector | None = None
    embedding_profile: EmbeddingProfile | None = None
    tag_filter: TagFilter | None = None


class MemorySearchChannels(BaseModel):
    """Backend-internal channel rankings before shared fusion."""

    fts: tuple[MemoryChannelHit, ...] = ()
    vector: tuple[MemoryChannelHit, ...] = ()


class CandidatePipeline(Protocol):
    """Produce untrusted Memory candidates from canonical bounded evidence."""

    async def extract(self, request: MemoryCandidateRequest, /) -> tuple[MemoryEntryInput, ...]:
        """Return candidates that still require all service validations."""

        ...


class MemoryUnitOfWork(Protocol):
    """Commit authoritative and projection rows in one backend transaction."""

    async def commit(self, value: MemoryCommit, /) -> Memory:
        """Validate and atomically commit one complete Revision."""

        ...


class MemoryBackend(Protocol):
    async def tagged_entry_ids(self, memory: ArtifactRef, tag_filter: TagFilter) -> frozenset[str]:
        """Return exact tag matches without imposing a candidate limit."""

        ...

    """Storage and retrieval capabilities required by the Memory Family."""

    async def capabilities(self) -> MemoryCapabilities:
        """Return probed deployment capabilities."""

        ...

    async def get(self, memory: ArtifactRef, /) -> Memory:
        """Load one exact Memory Revision."""

        ...

    async def latest(self, artifact_id: str, /) -> Memory:
        """Load the current head of one Memory identity."""

        ...

    async def entries(self, memory: ArtifactRef, /) -> tuple[MemoryEntryVersion, ...]:
        """Load the entry versions referenced by an exact manifest."""

        ...

    async def projections(self, memory: ArtifactRef, /) -> tuple[MemoryProjection, ...]:
        """Load rebuildable active-head projections for an exact Memory Revision."""

        ...

    async def rebuild_projections(self, embedding_model: EmbeddingModel | None = None, /) -> None:
        """Rebuild active-head and search projections from authoritative revisions."""

        ...

    def begin(self) -> AbstractAsyncContextManager[MemoryUnitOfWork]:
        """Open the adapter-specific atomic write boundary."""

        ...

    async def changes(
        self,
        memory: ArtifactRef,
        since_revision: int | None,
        /,
    ) -> tuple[MemoryRevisionChanges, ...]:
        """Read compact Revision changes without entry bodies."""

        ...

    async def vector_complete(
        self,
        memories: tuple[ArtifactRef, ...],
        profile: EmbeddingProfile,
        /,
    ) -> bool:
        """Derive fixed-profile vector completeness for selected heads."""

        ...

    async def search(self, request: MemorySearchRequest, /) -> MemorySearchChannels:
        """Return backend-ordered FTS/vector channels after manifest checks."""

        ...

    async def expand(self, hits: tuple[MemoryHit, ...], /) -> tuple[MemoryEntryVersion, ...]:
        """Load and validate exact versions anchored by hits."""

        ...
