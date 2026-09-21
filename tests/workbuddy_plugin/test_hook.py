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

import io
import json
import sys
from types import ModuleType

import pytest

_CONTEXT_BLOCK_BYTES = 20_000


def _prepared(content: str | None = "prepared context", *, status: str = "ready") -> dict[str, object]:
    return {
        "schema": "powercontext.prepared-context.v1",
        "status": status,
        "content": content,
        "content_bytes": 0 if content is None else len(content.encode("utf-8")),
    }


def _host_message(question: str, *, context_bytes: int = _CONTEXT_BLOCK_BYTES) -> str:
    """Build the shape WorkBuddy submits: an injected context block plus the user query."""

    reminder = "<system-reminder>" + "x" * context_bytes + "</system-reminder>"
    return f"{reminder}\n<user_query>{question}</user_query>"


def _payload(prompt: str) -> dict[str, object]:
    return {
        "hook_event_name": "UserPromptSubmit",
        "cwd": "/workspace/project",
        "prompt": prompt,
    }


def _run_main(
    hook_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> tuple[str, str]:
    output = io.StringIO()
    errors = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setattr(sys, "stderr", errors)
    assert hook_module.main() == 0
    return output.getvalue(), errors.getvalue()


def _stub_recall(
    hook_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    queries: list[str],
    *,
    content: str | None = "prepared context",
) -> None:
    def prepare(query: str, _scope: str, *, settings: object, deadline: float) -> dict[str, object]:
        queries.append(query)
        return _prepared(content)

    monkeypatch.setattr(hook_module, "_prepare_context", prepare)
    monkeypatch.setattr(
        hook_module,
        "resolve_scope_id",
        lambda _cwd, **_kwargs: "git:github.com/oceanbase/powercontext",
    )
    monkeypatch.setattr(hook_module, "_capture_prompt", lambda _payload, **_kwargs: {"position": 1})


def test_recall_query_prefers_the_submitted_turn_over_the_joined_transcript(
    hook_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WorkBuddy joins every user message, so retrieval must use the turn in hand.

    The joined prompt of a long session repeats the injected context block of every earlier
    message. Retrieving with the whole join asked the server for a query beyond its bound,
    which left the recall empty without reporting anything.
    """

    transcript = "\n".join(_host_message(f"earlier turn {index}") for index in range(4))
    transcript += "\n" + _host_message("Which service chain should WorkBuddy use?")
    assert len(transcript) > 8192

    queries: list[str] = []
    _stub_recall(hook_module, monkeypatch, queries, content="recalled context")

    output, _ = _run_main(hook_module, monkeypatch, _payload(transcript))

    assert queries == ["Which service chain should WorkBuddy use?"]
    assert json.loads(output)["hookSpecificOutput"]["additionalContext"] == "recalled context"


def test_recall_query_falls_back_to_the_joined_prompt_within_the_request_bound(
    hook_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A host that stops marking the submitted turn still gets a bounded query."""

    joined = "earlier turn " * 3_000
    queries: list[str] = []
    _stub_recall(hook_module, monkeypatch, queries)

    _, errors = _run_main(hook_module, monkeypatch, _payload(joined))

    (query,) = queries
    assert len(query) <= 8192
    assert len(query.encode("utf-8")) <= 8192
    assert joined.strip().endswith(query)
    events = [json.loads(line) for line in errors.splitlines()]
    reduction = [event for event in events if event["event"] == "query_reduction"]
    assert len(reduction) == 1
    assert reduction[0]["source"] == "joined_prompt"
    assert reduction[0]["truncated"] is True


def test_recall_query_keeps_a_multibyte_prompt_within_the_byte_bound(
    hook_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-ASCII text costs several bytes per character, so both bounds have to hold."""

    joined = "记忆 " * 4_000
    queries: list[str] = []
    _stub_recall(hook_module, monkeypatch, queries)

    _run_main(hook_module, monkeypatch, _payload(joined))

    (query,) = queries
    assert len(query) < len(joined)
    assert len(query.encode("utf-8")) <= 8192
    assert joined.strip().endswith(query)


def test_recall_query_passes_a_plain_prompt_through_unchanged(
    hook_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries: list[str] = []
    _stub_recall(hook_module, monkeypatch, queries)

    _, errors = _run_main(hook_module, monkeypatch, _payload("Which decisions apply?"))

    assert queries == ["Which decisions apply?"]
    assert errors == ""


def test_a_reduced_query_is_reported_on_stderr(
    hook_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The recall stays silent on failure, so a reduction is the diagnostic available."""

    transcript = "\n".join(_host_message(f"earlier turn {index}") for index in range(2))
    queries: list[str] = []
    _stub_recall(hook_module, monkeypatch, queries)

    _, errors = _run_main(hook_module, monkeypatch, _payload(transcript))

    events = [json.loads(line) for line in errors.splitlines()]
    reduction = [event for event in events if event["event"] == "query_reduction"]
    assert len(reduction) == 1
    assert reduction[0]["component"] == "powercontext.workbuddy.recall"
    assert reduction[0]["source"] == "user_query"
    assert reduction[0]["truncated"] is False
