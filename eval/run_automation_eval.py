"""Offline replay of frozen synthetic records against the public inspection service.

This measures deterministic rules, authorization and evidence references. It is
not a model quality score or an enterprise integration smoke test. Historical
receipts below belong only to isolated fixtures, never to application data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "eval" / "automation_cases_v1.json"


def load_dataset(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    document = json.loads(raw)
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != "automation-cases-v1"
        or document.get("fixture_type") != "synthetic-frozen-records"
        or not isinstance(document.get("cases"), list)
    ):
        raise ValueError("dataset_document_invalid")
    cases = document["cases"]
    if (
        len(cases) != 30
        or len({case["id"] for case in cases}) != 30
        or Counter(case["template_id"] for case in cases)
        != {"daily_progress": 10, "blockers": 10, "pending_reviews": 10}
    ):
        raise ValueError("dataset_case_distribution_invalid")
    return document, hashlib.sha256(raw).hexdigest()


def load_fixture(repository, case):
    from agentmesh.models import (
        AgentRun,
        AgentRunStatus,
        ChatThread,
        Intent,
        Project,
        Task,
        TaskManagementMetadataV1,
        TaskReviewV1,
        User,
        Workspace,
    )
    from agentmesh.task_management.contracts import TaskCommandReceiptV1

    snapshot_at = datetime.fromisoformat(case["snapshot_at"])
    repository.save_workspace(Workspace(id="workspace", name="Synthetic fixture", description="Offline only"))
    user = repository.save_user(
        User(
            id="owner",
            workspace_id="workspace" if case["workspace_matches"] else "other_workspace",
            default_project_id="project",
            name="Fixture owner",
            role=case["role"],
            status=case["actor_status"],
            personal_agent_id="owner_agent",
        )
    )
    repository.save_user(user.model_copy(update={"id": "peer", "name": "Fixture peer", "status": "active"}))
    repository.save_project(
        Project(
            id="project",
            workspace_id="workspace",
            name="Synthetic project",
            goal="Frozen rule evaluation",
            member_ids=["owner", "peer"] if case["member"] else ["peer"],
        )
    )

    def make_task(spec, *, observed_at=None):
        management = TaskManagementMetadataV1(
            delivery_stage=spec["stage"],
            version=spec["version"],
            blocked_reason=spec.get("blocked_reason"),
            due_at=spec.get("due_at"),
            archived_at=spec.get("archived_at"),
            dependency_task_ids=spec.get("dependencies", []),
            created_by="owner",
            updated_by="owner",
        )
        return Task(
            id=spec["id"],
            thread_id=f"thread_{spec['id']}",
            title="PRIVATE-ONLY" if spec.get("kind") == "conversation" else f"Public {spec['id']}",
            intent=Intent.GENERAL_CHAT,
            management=management,
            created_at=snapshot_at,
            updated_at=observed_at or datetime.fromisoformat(spec["updated_at"]),
        )

    task_specs = {spec["id"]: spec for spec in case["tasks"]}
    for spec in task_specs.values():
        repository.add_chat_thread(
            ChatThread(
                id=f"thread_{spec['id']}",
                workspace_id="workspace",
                project_id="project",
                user_id="owner",
                title="Synthetic thread",
                kind=spec["kind"],
            )
        )
        repository.save_task(make_task(spec))
    for event in case["events"]:
        spec = {**task_specs[event["task_id"]], **event, "blocked_reason": event.get("blocked_reason")}
        receipt_id = f"command_{event['task_id']}_{event['version']}"
        repository._upsert(
            "task_command_receipts",
            TaskCommandReceiptV1(
                id=receipt_id,
                command_id=receipt_id,
                user_id="owner",
                operation="create" if event["version"] == 1 else "transition",
                request_hash=hashlib.sha256(receipt_id.encode()).hexdigest(),
                task_id=event["task_id"],
                result_task=make_task(spec, observed_at=datetime.fromisoformat(event["observed_at"])),
                created_at=event["observed_at"],
            ),
        )
    for spec in case["reviews"]:
        run_id = f"run_{spec['id']}"
        repository.save_agent_run(
            AgentRun(
                id=run_id,
                thread_id=f"thread_{spec['task_id']}",
                task_id=spec["task_id"],
                user_id="owner",
                workspace_id="workspace",
                project_id="project",
                input_text="Synthetic historical record; no execution",
                status=AgentRunStatus.COMPLETED,
            )
        )
        review = TaskReviewV1(
            **spec,
            run_id=run_id,
            artifact_ids=[f"synthetic_artifact_{spec['id']}"],
            artifact_hashes=[hashlib.sha256(spec["id"].encode()).hexdigest()],
            round=1,
            requested_by="owner",
            created_at=snapshot_at,
            updated_at=snapshot_at,
            decided_at=None if spec["status"] == "pending" else snapshot_at,
        )
        with repository._connect() as connection:
            connection.execute(
                "INSERT INTO task_reviews "
                "(id,task_id,run_id,reviewer_id,status,round,version,payload,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    review.id, review.task_id, run_id, review.reviewer_id, review.status, review.round,
                    review.version, review.model_dump_json(), snapshot_at.isoformat(), snapshot_at.isoformat(),
                ),
            )
    return user


def database_digest(repository) -> str:
    digest = hashlib.sha256()
    with repository._read_connect() as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        for table in tables:
            name = table["name"].replace('"', '""')
            rows = connection.execute(f'SELECT * FROM "{name}"').fetchall()
            serialized = sorted(
                json.dumps([value.hex() if isinstance(value, bytes) else value for value in row]) for row in rows
            )
            digest.update(json.dumps([name, serialized]).encode())
    return digest.hexdigest()


def run_case(repository, case) -> dict:
    from agentmesh.automation.contracts import ProjectInspectionRequestV1
    from agentmesh.automation.service import ProjectInspectionService
    from agentmesh.task_operations.service import TaskOperationsError

    user = load_fixture(repository, case)
    before = database_digest(repository)
    private_data_excluded = True
    try:
        report = ProjectInspectionService(
            repository, clock=lambda: datetime.fromisoformat(case["snapshot_at"])
        ).inspect("project", ProjectInspectionRequestV1(template_id=case["template_id"], since=case["since"]), user)
        private_data_excluded = "PRIVATE-ONLY" not in report.model_dump_json()
        actual = {
            "outcome": report.outcome,
            "changes": sorted([[item.task_id, item.kind, item.version] for item in report.changes]),
            "blockers": {item.task_id: sorted(item.reasons) for item in report.blockers},
            "reviews": {item.review_id: item.assigned_to_me for item in report.pending_reviews},
            "evidence": sorted([[ref.source_kind, ref.source_id, ref.version] for ref in report.evidence_refs]),
            "missing_data": sorted(report.missing_data),
            "task_count": report.source_watermarks["tasks"].record_count,
        }
    except TaskOperationsError as error:
        actual = {"error_code": error.code}
    read_only = before == database_digest(repository)
    expected = dict(case["expected"])
    # Denied reads deliberately expose no report or source counts.
    if "error_code" in expected:
        expected = {"error_code": expected["error_code"]}
    else:
        for key in ("changes", "evidence", "missing_data"):
            expected[key] = sorted(expected[key])
        expected["blockers"] = {key: sorted(value) for key, value in expected["blockers"].items()}
    mismatches = sorted(key for key in expected.keys() | actual.keys() if expected.get(key) != actual.get(key))
    if not read_only:
        mismatches.append("read_only")
    if not private_data_excluded:
        mismatches.append("private_data_excluded")
    return {
        "case_id": case["id"], "template_id": case["template_id"], "passed": not mismatches,
        "mismatches": mismatches, "read_only": read_only, "private_data_excluded": private_data_excluded,
    }


def evaluate(document: dict, dataset_hash: str, directory: Path) -> dict:
    from agentmesh.store import SQLiteStore

    results = []
    for index, case in enumerate(document["cases"]):
        repository = SQLiteStore(directory / f"case_{index}.sqlite3")
        try:
            results.append(run_case(repository, case))
        finally:
            repository.close()
    return {
        "schema_version": "automation-evaluation-v1", "mode": "scripted",
        "fixture_type": document["fixture_type"], "dataset_sha256": dataset_hash,
        "case_count": len(results), "passed_count": sum(item["passed"] for item in results),
        "by_template": dict(Counter(case["template_id"] for case in results)), "model_tokens": 0,
        "actual_provider": "isolated_local_task_store", "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        document, dataset_hash = load_dataset(arguments.dataset)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="agentmesh-inspection-eval-") as directory:
        # Set isolation before importing application modules or loading dotenv.
        os.environ["AGENTMESH_SKIP_DOTENV"] = "1"
        os.environ["AGENTMESH_DB_PATH"] = str(Path(directory) / "bootstrap.sqlite3")
        os.environ["AGENTMESH_EMBEDDING_ENABLED"] = "false"
        sys.path.insert(0, str(ROOT))
        report = evaluate(document, dataset_hash, Path(directory))
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if arguments.output:
        arguments.output.write_text(serialized)
    print(serialized, end="")
    return 0 if report["passed_count"] == report["case_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
