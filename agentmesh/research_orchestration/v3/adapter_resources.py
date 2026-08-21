from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_bytes, canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.catalog import (
    CompetitiveTextCatalog,
    load_catalog_document,
    load_competitive_text_catalog,
)
from agentmesh.research_orchestration.v3.common import (
    FrozenJson,
    Identifier,
    Sha256Hex,
    StrictFrozenModel,
)
from agentmesh.research_orchestration.v3.snapshots import FrozenActorV3, FrozenDocumentV3, ResearchControlSnapshotV3

_MAX_RESOURCE_FILES = 8
_MAX_RESOURCE_BYTES = 262_144
_MAX_RESOURCE_BATCH_BYTES = 524_288


class CompetitiveTextResourceError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class VerifiedCompetitiveTextResourceV3(StrictFrozenModel):
    """One catalog resource whose packaged and frozen canonical bodies agree."""

    document_id: Identifier
    kind: Literal["knowledge"]
    content_hash: Sha256Hex
    content: FrozenJson


def _document(snapshot: ResearchControlSnapshotV3, document_id: str) -> FrozenDocumentV3:
    matches = tuple(item for item in snapshot.documents if item.document_id == document_id)
    if len(matches) != 1:
        raise CompetitiveTextResourceError("frozen_resource_missing")
    return matches[0]


class CompetitiveTextResourceLoaderV3:
    """Load only Skill resources declared by the verified Competitive Text snapshot.

    The loader never follows a path supplied by a Skill or model. It compares the sealed
    snapshot with the packaged catalog and returns the already-frozen document bodies.
    """

    def __init__(self, catalog: CompetitiveTextCatalog | None = None) -> None:
        self._catalog = catalog or load_competitive_text_catalog()

    def load(
        self,
        *,
        snapshot: ResearchControlSnapshotV3,
        frozen_skill: FrozenActorV3,
    ) -> tuple[VerifiedCompetitiveTextResourceV3, ...]:
        if (
            snapshot.catalog_id != "competitive-text-v1"
            or snapshot.catalog_hash != self._catalog.catalog_hash
            or frozen_skill.actor_type != "skill"
        ):
            raise CompetitiveTextResourceError("competitive_text_snapshot_mismatch")
        matching_actor = tuple(
            actor
            for actor in snapshot.actors
            if (actor.actor_type, actor.actor_id) == (frozen_skill.actor_type, frozen_skill.actor_id)
        )
        if matching_actor != (frozen_skill,):
            raise CompetitiveTextResourceError("frozen_skill_identity_mismatch")

        catalog_skill = next(
            (item for item in self._catalog.actors.skills if item.id == frozen_skill.actor_id),
            None,
        )
        if catalog_skill is None:
            raise CompetitiveTextResourceError("skill_outside_competitive_text_snapshot")
        resource_ids = catalog_skill.required_resources
        if len(resource_ids) > _MAX_RESOURCE_FILES:
            raise CompetitiveTextResourceError("frozen_resource_file_limit")

        resources: list[VerifiedCompetitiveTextResourceV3] = []
        total_bytes = 0
        for document_id in resource_ids:
            catalog_document = next(
                (item for item in self._catalog.documents if item.id == document_id),
                None,
            )
            if catalog_document is None or catalog_document.kind != "knowledge":
                raise CompetitiveTextResourceError("catalog_resource_mapping_invalid")
            expected_content = load_catalog_document(self._catalog, document_id)
            frozen_document = _document(snapshot, document_id)
            expected_hash = canonical_json_v3_sha256(expected_content)
            if (
                frozen_document.kind != "knowledge"
                or frozen_document.content_hash != expected_hash
                or canonical_json_v3_sha256(frozen_document.content) != expected_hash
            ):
                raise CompetitiveTextResourceError("frozen_resource_drifted")
            size = len(canonical_json_v3_bytes(frozen_document.content))
            total_bytes += size
            if size > _MAX_RESOURCE_BYTES or total_bytes > _MAX_RESOURCE_BATCH_BYTES:
                raise CompetitiveTextResourceError("frozen_resource_size_limit")
            resources.append(
                VerifiedCompetitiveTextResourceV3(
                    document_id=document_id,
                    kind="knowledge",
                    content_hash=frozen_document.content_hash,
                    content=frozen_document.content,
                )
            )
        return tuple(resources)


def verify_frozen_catalog_document(
    *,
    snapshot: ResearchControlSnapshotV3,
    document_id: str,
    expected_kind: str,
    catalog: CompetitiveTextCatalog | None = None,
) -> FrozenDocumentV3:
    """Verify a frozen instruction/policy document against the locked package copy."""

    locked_catalog = catalog or load_competitive_text_catalog()
    if snapshot.catalog_hash != locked_catalog.catalog_hash:
        raise CompetitiveTextResourceError("competitive_text_snapshot_mismatch")
    catalog_document = next((item for item in locked_catalog.documents if item.id == document_id), None)
    if catalog_document is None or catalog_document.kind != expected_kind:
        raise CompetitiveTextResourceError("catalog_document_mapping_invalid")
    frozen_document = _document(snapshot, document_id)
    expected_content = load_catalog_document(locked_catalog, document_id)
    expected_hash = canonical_json_v3_sha256(expected_content)
    if (
        frozen_document.kind != expected_kind
        or frozen_document.content_hash != expected_hash
        or canonical_json_v3_sha256(frozen_document.content) != expected_hash
    ):
        raise CompetitiveTextResourceError("frozen_catalog_document_drifted")
    if isinstance(frozen_document.content, Mapping) and not frozen_document.content:
        raise CompetitiveTextResourceError("frozen_catalog_document_empty")
    return frozen_document
