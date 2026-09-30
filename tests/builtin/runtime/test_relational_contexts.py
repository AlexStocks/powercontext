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

from powercontext.builtin.persistence.sqlite import SQLiteConfig, SQLiteProfile
from powercontext.builtin.persistence.tables import BUILTIN_TABLES
from powercontext.builtin.runtime.relational import RelationalContexts


def test_evict_removes_scope_skill_publication_locks() -> None:
    async def scenario() -> None:
        async with SQLiteProfile.open(SQLiteConfig(), tables=BUILTIN_TABLES) as profile:
            contexts = RelationalContexts(database=profile.database)
            contexts.skill_publications("scope-a", "target-1", "skill-1")
            contexts.skill_publications("scope-b", "target-1", "skill-1")

            contexts.evict("scope-a")

            assert ("scope-a", "target-1", "skill-1") not in contexts._skill_publication_locks
            assert ("scope-b", "target-1", "skill-1") in contexts._skill_publication_locks

    asyncio.run(scenario())
