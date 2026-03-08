"""Tests for mux_orchestrate JSONL persistence."""

import json
from pathlib import Path

import pytest

from modelmux.orchestrate import TaskState, create_task
from modelmux.orchestrate_store import OrchestrateStore, _store_file


class TestOrchestrateStore:
    def test_next_task_id_increments_from_existing_records(self, tmp_path):
        path = tmp_path / "orchestrate.jsonl"
        store = OrchestrateStore(path=path)
        store.upsert(create_task("first task", "T001"))
        store.upsert(create_task("second task", "T002"))

        reloaded = OrchestrateStore(path=path)
        assert reloaded.next_task_id() == "T003"

    def test_get_returns_copy(self, tmp_path):
        path = tmp_path / "orchestrate.jsonl"
        store = OrchestrateStore(path=path)
        store.upsert(create_task("first task", "T001"))

        task = store.get("T001")
        assert task is not None
        task.title = "changed"

        fresh = store.get("T001")
        assert fresh is not None
        assert fresh.title == "first task"
        assert store.get("missing") is None

    def test_list_sorts_descending_and_filters_state(self, tmp_path):
        path = tmp_path / "orchestrate.jsonl"
        store = OrchestrateStore(path=path)
        first = create_task("first task", "T001")
        second = create_task("second task", "T002")
        second.state = TaskState.REVIEWING
        second.updated_at = first.updated_at + 5
        store.upsert(first)
        store.upsert(second)

        listed = store.list()
        assert [task.task_id for task in listed] == ["T002", "T001"]

        reviewing = store.list(state="reviewing")
        assert [task.task_id for task in reviewing] == ["T002"]

    def test_find_by_branch_returns_most_recent_match(self, tmp_path):
        path = tmp_path / "orchestrate.jsonl"
        store = OrchestrateStore(path=path)
        older = create_task("older task", "T001")
        older.branch = "feat/x"
        newer = create_task("newer task", "T002")
        newer.branch = "feat/x"
        newer.updated_at = older.updated_at + 10
        store.upsert(older)
        store.upsert(newer)

        found = store.find_by_branch("feat/x")
        assert found is not None
        assert found.task_id == "T002"
        assert store.find_by_branch("missing") is None

    def test_state_counts_and_invalid_lines_are_ignored(self, tmp_path):
        path = tmp_path / "orchestrate.jsonl"
        valid = create_task("first task", "T001").to_dict()
        invalid_semantic = {"task_id": "T002", "title": "bad", "created_at": "oops"}
        path.write_text(
            "\n".join(
                [
                    "",
                    "not json",
                    json.dumps(["not", "a", "task"]),
                    json.dumps(valid),
                    json.dumps(invalid_semantic),
                    json.dumps({"task_id": "", "title": "bad"}),
                ]
            ),
            encoding="utf-8",
        )

        store = OrchestrateStore(path=path)
        counts = store.state_counts()
        assert counts == {"planned": 1}
        assert store.get("T001") is not None
        assert store.get("T002") is None

    def test_rotation_keeps_latest_snapshot_for_each_task(self, tmp_path):
        path = tmp_path / "orchestrate.jsonl"
        store = OrchestrateStore(path=path, max_bytes=1)
        store.upsert(create_task("first task", "T001"))
        store.upsert(create_task("second task", "T002"))
        updated = create_task("second task updated", "T002")
        updated.state = TaskState.REVIEWING
        store.upsert(updated)

        reloaded = OrchestrateStore(path=path, max_bytes=1)
        ids = [task.task_id for task in reloaded.list(limit=10)]
        assert "T001" in ids
        assert "T002" in ids
        latest = reloaded.get("T002")
        assert latest is not None
        assert latest.title == "second task updated"
        assert latest.state is TaskState.REVIEWING

    def test_upsert_rolls_back_memory_when_persistence_fails(
        self, tmp_path, monkeypatch
    ):
        path = tmp_path / "orchestrate.jsonl"
        store = OrchestrateStore(path=path)
        original = store.upsert(create_task("first task", "T001"))
        replacement = create_task("replacement task", "T001")

        def fail_snapshot(_task):
            raise OSError("disk full")

        monkeypatch.setattr(store, "_append_snapshot", fail_snapshot)

        with pytest.raises(OSError, match="disk full"):
            store.upsert(replacement)

        persisted = store.get("T001")
        assert persisted is not None
        assert persisted.title == original.title

    def test_store_file_uses_config_home(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert (
            _store_file()
            == tmp_path / ".config" / "modelmux" / "orchestrate_tasks.jsonl"
        )

    def test_next_task_id_ignores_non_matching_ids(self, tmp_path):
        path = tmp_path / "orchestrate.jsonl"
        store = OrchestrateStore(path=path)
        store.upsert(create_task("non standard", "task-custom"))
        assert store.next_task_id() == "T001"
