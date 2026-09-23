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

from types import ModuleType

import pytest


class _Socket:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def settimeout(self, value: float) -> None:
        self.timeouts.append(value)


class _Raw:
    def __init__(self, sock: _Socket) -> None:
        self._sock = sock


class _FilePointer:
    def __init__(self, sock: _Socket) -> None:
        self.raw = _Raw(sock)


class _SlowResponse:
    status = 200

    def __init__(self) -> None:
        self.sock = _Socket()
        self.fp = _FilePointer(self.sock)

    def __enter__(self) -> _SlowResponse:
        return self

    def __exit__(self, *args: object) -> object:
        return None

    def read(self, amount: int = -1) -> bytes:
        assert self.sock.timeouts
        raise TimeoutError


class _Opener:
    def __init__(self, response: _SlowResponse) -> None:
        self.response = response

    def open(self, request: object, *, timeout: float) -> _SlowResponse:
        return self.response


class _Settings:
    server_url = "http://127.0.0.1:8000"
    authorization = None
    scope_id = None
    request_timeout_seconds = 3.0


def test_scope_binding_bounds_response_body_reads(
    scope_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _SlowResponse()
    monkeypatch.setattr(scope_module, "_URL_OPENER", _Opener(response))

    with pytest.raises(scope_module.ScopeBindingError):
        scope_module._request_json(
            "/v1/scope-bindings/resolve",
            {"binding_keys": []},
            settings=_Settings(),
            deadline=scope_module.monotonic() + 6.0,
        )

    assert response.sock.timeouts
