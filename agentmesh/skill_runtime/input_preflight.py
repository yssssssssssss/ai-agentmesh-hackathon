from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import TYPE_CHECKING, Literal

from agentmesh.canonical_json import canonical_json_bytes, canonical_json_sha256
from agentmesh.input_adapters import MAX_NODE_INPUT_BYTES, adapter_identity_for_media_type
from agentmesh.models import (
    AgentRun,
    RunInputArtifactStatus,
    SkillDefinition,
    SkillInputBindingV1,
    SkillInputContractSnapshotV1,
    SkillInputFieldStatus,
    SkillInputFieldV1,
    SkillInputRequestStatus,
    SkillInputRequestV1,
    SkillInputSubmitRequest,
    SkillPlan,
    SkillUserInputMode,
    now_utc,
)
from agentmesh.risk import RiskDecision, assess_external_content
from agentmesh.skill_runtime.input_contracts import (
    LoadedUserInputContract,
    field_kind,
    field_media_types,
    load_user_input_contract,
)
from agentmesh.skill_runtime.profiles import ProfileError, load_capability_profile_record, profile_path
from agentmesh.tool_runtime.guardrails import contains_credential

if TYPE_CHECKING:
    from agentmesh.store import SQLiteStore


class SkillInputPreflightError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class SkillInputPreflightService:
    def __init__(self, repository: SQLiteStore):
        self.repository = repository

    @staticmethod
    def _field_key(node_id: str, field_id: str) -> str:
        return f"{node_id}.{field_id}"

    @staticmethod
    def _request_text(run: AgentRun, skill: SkillDefinition | None = None) -> str:
        text = run.input_text.strip()
        if skill is not None and text.startswith("$"):
            command, separator, argument = text.partition(" ")
            if command.removeprefix("$") in {skill.name, *skill.aliases}:
                return argument.strip() if separator else ""
        return text

    def _profile_for_skill(self, skill: SkillDefinition):  # noqa: ANN202
        path = profile_path(skill)
        if path.is_file():
            try:
                return load_capability_profile_record(skill).profile
            except ProfileError as error:
                raise SkillInputPreflightError(str(error)) from error
        return self.repository.get_skill_capability_profile(skill.id)

    def requires_preflight(self, skill: SkillDefinition) -> bool:
        profile = self._profile_for_skill(skill)
        return bool(profile and profile.user_input_mode is SkillUserInputMode.PREFLIGHT)

    def _loaded_contract(self, skill: SkillDefinition) -> LoadedUserInputContract | None:
        profile = self._profile_for_skill(skill)
        if profile is None or profile.user_input_mode is not SkillUserInputMode.PREFLIGHT:
            return None
        if not profile.user_input_schema_ref or not profile.user_input_contract_hash:
            raise SkillInputPreflightError("user_input_contract_missing")
        loaded = load_user_input_contract(skill, profile.user_input_schema_ref)
        if loaded.content_hash != profile.user_input_contract_hash:
            raise SkillInputPreflightError("user_input_contract_invalid")
        return loaded

    def _compile_fields(
        self,
        *,
        node_id: str,
        skill: SkillDefinition,
        loaded: LoadedUserInputContract,
        prefill_text: str,
    ) -> list[SkillInputFieldV1]:
        fields: list[SkillInputFieldV1] = []
        prefilled = False
        for field_id, specification in loaded.contract.properties.items():
            kind = field_kind(specification)
            required = field_id in loaded.contract.required
            text_value = None
            if (
                not prefilled
                and required
                and kind == "text"
                and specification.type == "string"
                and specification.format is None
                and prefill_text
                and (specification.enum is None or prefill_text in specification.enum)
            ):
                text_value = prefill_text
                prefilled = True
            artifact_spec = specification.artifact_spec
            fields.append(
                SkillInputFieldV1(
                    id=self._field_key(node_id, field_id),
                    node_id=node_id,
                    skill_id=skill.id,
                    skill_name=skill.name,
                    field_id=field_id,
                    title=specification.title,
                    description=specification.description,
                    required=required,
                    value_kind=kind,
                    multiple=specification.type == "array",
                    accepted_media_types=field_media_types(specification),
                    min_length=specification.min_length,
                    max_length=specification.max_length,
                    min_items=specification.min_items,
                    max_items=specification.max_items,
                    required_columns=(artifact_spec.required_columns if artifact_spec is not None else []),
                    options=specification.enum or [],
                    text_value=text_value,
                )
            )
        return fields

    def compile_for_skill(
        self,
        *,
        run: AgentRun,
        skill: SkillDefinition,
        next_run_status: Literal["waiting_plan_approval", "running"] = "running",
    ) -> SkillInputRequestV1 | None:
        loaded = self._loaded_contract(skill)
        if loaded is None:
            return None
        node_id = "direct"
        request = SkillInputRequestV1(
            run_id=run.id,
            plan_id=None,
            contract_snapshots=[
                SkillInputContractSnapshotV1(
                    node_id=node_id,
                    skill_id=skill.id,
                    skill_name=skill.name,
                    skill_version=skill.version,
                    skill_content_hash=skill.content_hash,
                    contract_hash=loaded.content_hash,
                    contract=loaded.canonical_payload,
                )
            ],
            fields=self._compile_fields(
                node_id=node_id,
                skill=skill,
                loaded=loaded,
                prefill_text=self._request_text(run, skill),
            ),
            next_run_status=next_run_status,
            expires_at=now_utc() + timedelta(hours=24),
        )
        return self._evaluate(request)

    def compile_for_plan(
        self,
        *,
        run: AgentRun,
        plan: SkillPlan,
        next_run_status: Literal["waiting_plan_approval", "running"],
        previous: SkillInputRequestV1 | None = None,
    ) -> SkillInputRequestV1 | None:
        snapshots: list[SkillInputContractSnapshotV1] = []
        fields: list[SkillInputFieldV1] = []
        for node in plan.nodes:
            skill = self.repository.get_skill_definition(node.skill_id)
            if skill is None:
                raise SkillInputPreflightError("skill_unavailable")
            loaded = self._loaded_contract(skill)
            if loaded is None:
                continue
            snapshots.append(
                SkillInputContractSnapshotV1(
                    node_id=node.id,
                    skill_id=skill.id,
                    skill_name=skill.name,
                    skill_version=skill.version,
                    skill_content_hash=skill.content_hash,
                    contract_hash=loaded.content_hash,
                    contract=loaded.canonical_payload,
                )
            )
            fields.extend(
                self._compile_fields(
                    node_id=node.id,
                    skill=skill,
                    loaded=loaded,
                    prefill_text=self._request_text(run),
                )
            )
        if not snapshots:
            return None
        if previous is not None:
            prior_contracts = {
                (snapshot.node_id, snapshot.contract_hash)
                for snapshot in previous.contract_snapshots
            }
            prior_fields = {(field.node_id, field.field_id): field for field in previous.fields}
            snapshot_hashes = {snapshot.node_id: snapshot.contract_hash for snapshot in snapshots}
            fields = [
                field.model_copy(
                    update={
                        "text_value": prior.text_value,
                        "artifact_ids": list(prior.artifact_ids),
                    }
                )
                if (
                    (prior := prior_fields.get((field.node_id, field.field_id))) is not None
                    and (field.node_id, snapshot_hashes[field.node_id]) in prior_contracts
                    and prior.value_kind == field.value_kind
                )
                else field
                for field in fields
            ]
        request_payload: dict[str, object] = {
            "run_id": run.id,
            "plan_id": plan.id,
            "version": previous.version + 1 if previous is not None else 1,
            "contract_snapshots": snapshots,
            "fields": fields,
            "next_run_status": next_run_status,
            "created_at": previous.created_at if previous is not None else now_utc(),
            "expires_at": now_utc() + timedelta(hours=24),
        }
        if previous is not None:
            request_payload["id"] = previous.id
        request = SkillInputRequestV1.model_validate(request_payload)
        return self._evaluate(request)

    def _evaluate(self, request: SkillInputRequestV1) -> SkillInputRequestV1:
        fields: list[SkillInputFieldV1] = []
        missing: list[str] = []
        for original in request.fields:
            field = original.model_copy(deep=True)
            errors: list[str] = []
            if field.value_kind == "text":
                value = field.text_value or ""
                if value:
                    if contains_credential(value):
                        errors.append("input_credential_detected")
                    elif assess_external_content(value).decision is not RiskDecision.ALLOW:
                        errors.append("input_content_quarantined")
                    if field.min_length is not None and len(value) < field.min_length:
                        errors.append("input_text_too_short")
                    if field.max_length is not None and len(value) > field.max_length:
                        errors.append("input_text_too_long")
                    if field.options and value not in field.options:
                        errors.append("input_value_not_allowed")
                if errors:
                    field.status = SkillInputFieldStatus.INVALID
                elif value:
                    field.status = SkillInputFieldStatus.SATISFIED
                else:
                    field.status = SkillInputFieldStatus.MISSING
            else:
                artifacts = [self.repository.get_run_input_artifact(item) for item in field.artifact_ids]
                if any(artifact is None or artifact.run_id != request.run_id for artifact in artifacts):
                    errors.append("input_artifact_not_found")
                elif any(artifact.status is RunInputArtifactStatus.PROCESSING for artifact in artifacts if artifact):
                    field.status = SkillInputFieldStatus.PROCESSING
                elif any(artifact.status is not RunInputArtifactStatus.READY for artifact in artifacts if artifact):
                    errors.append("input_artifact_not_ready")
                elif any(
                    artifact.field_id != field.id or artifact.media_type not in field.accepted_media_types
                    for artifact in artifacts
                    if artifact
                ):
                    errors.append("input_artifact_binding_invalid")
                count = len(field.artifact_ids)
                if count and field.min_items is not None and count < field.min_items:
                    errors.append("input_artifact_count_invalid")
                if count > (field.max_items or (20 if field.multiple else 1)):
                    errors.append("input_artifact_count_invalid")
                if errors:
                    field.status = SkillInputFieldStatus.INVALID
                elif count:
                    field.status = SkillInputFieldStatus.SATISFIED
                elif field.status is not SkillInputFieldStatus.PROCESSING:
                    field.status = SkillInputFieldStatus.MISSING
            field.error_codes = list(dict.fromkeys(errors))
            if field.required and field.status is not SkillInputFieldStatus.SATISFIED:
                missing.append(field.id)
            fields.append(field)
        complete = not missing and not any(
            field.status in {SkillInputFieldStatus.INVALID, SkillInputFieldStatus.PROCESSING}
            for field in fields
        )
        updated = request.model_copy(
            deep=True,
            update={
                "fields": fields,
                "missing_required_field_ids": missing,
                "status": SkillInputRequestStatus.COMPLETE if complete else SkillInputRequestStatus.OPEN,
                "frozen_bindings": self._freeze_bindings(request, fields) if complete else [],
            },
        )
        return SkillInputRequestV1.model_validate(updated.model_dump(mode="python"))

    def _freeze_bindings(
        self,
        request: SkillInputRequestV1,
        fields: list[SkillInputFieldV1],
    ) -> list[SkillInputBindingV1]:
        hashes = {snapshot.node_id: snapshot.contract_hash for snapshot in request.contract_snapshots}
        bindings: list[SkillInputBindingV1] = []
        for field in fields:
            if field.status is not SkillInputFieldStatus.SATISFIED:
                continue
            if field.value_kind == "text" and field.text_value:
                bindings.append(
                    SkillInputBindingV1(
                        plan_id=request.plan_id,
                        node_id=field.node_id,
                        field_id=field.field_id,
                        value_kind="text",
                        value_ref=field.text_value,
                        content_hash=hashlib.sha256(field.text_value.encode("utf-8")).hexdigest(),
                        contract_hash=hashes[field.node_id],
                    )
                )
            elif field.value_kind == "artifact":
                for artifact_id in field.artifact_ids:
                    artifact = self.repository.get_run_input_artifact(artifact_id)
                    if artifact is None or artifact.status is not RunInputArtifactStatus.READY:
                        raise SkillInputPreflightError("input_artifact_not_ready")
                    bindings.append(
                        SkillInputBindingV1(
                            plan_id=request.plan_id,
                            node_id=field.node_id,
                            field_id=field.field_id,
                            value_kind="artifact",
                            value_ref=artifact.id,
                            content_hash=artifact.content_hash,
                            contract_hash=hashes[field.node_id],
                        )
                    )
        node_payload_sizes: dict[str, int] = {}
        for binding in bindings:
            if binding.value_kind == "text":
                size = len(binding.value_ref.encode("utf-8"))
            else:
                artifact = self.repository.get_run_input_artifact(binding.value_ref)
                if artifact is None:
                    raise SkillInputPreflightError("input_artifact_not_found")
                payload = (
                    artifact.structured_payload
                    if artifact.media_type == "text/csv"
                    else artifact.normalized_text or ""
                )
                size = (
                    len(canonical_json_bytes(payload))
                    if isinstance(payload, (dict, list))
                    else len(str(payload).encode("utf-8"))
                )
            node_payload_sizes[binding.node_id] = node_payload_sizes.get(binding.node_id, 0) + size
            if node_payload_sizes[binding.node_id] > MAX_NODE_INPUT_BYTES:
                raise SkillInputPreflightError("input_content_too_large")
        return bindings

    def apply_submission(
        self,
        current: SkillInputRequestV1,
        submission: SkillInputSubmitRequest,
    ) -> tuple[SkillInputRequestV1, str]:
        payload_hash = canonical_json_sha256(submission.model_dump(mode="json"))
        if current.last_command_id == submission.client_turn_id:
            if current.last_payload_hash != payload_hash:
                raise SkillInputPreflightError("input_submission_idempotency_conflict")
            return current, payload_hash
        if current.version != submission.expected_request_version:
            raise SkillInputPreflightError("input_request_version_conflict")
        if current.status is not SkillInputRequestStatus.OPEN:
            raise SkillInputPreflightError("input_request_frozen")
        if now_utc() >= current.expires_at:
            raise SkillInputPreflightError("input_request_expired")
        known_fields = {field.id: field for field in current.fields}
        supplied_ids = set(submission.text_values) | set(submission.artifact_ids)
        if supplied_ids - set(known_fields):
            raise SkillInputPreflightError("input_field_unknown")
        fields: list[SkillInputFieldV1] = []
        for original in current.fields:
            field = original.model_copy(deep=True)
            if field.id in submission.text_values:
                if field.value_kind != "text":
                    raise SkillInputPreflightError("input_field_type_mismatch")
                field.text_value = submission.text_values[field.id]
            if field.id in submission.artifact_ids:
                if field.value_kind != "artifact":
                    raise SkillInputPreflightError("input_field_type_mismatch")
                field.artifact_ids = list(dict.fromkeys(submission.artifact_ids[field.id]))
            fields.append(field)
        candidate = current.model_copy(
            deep=True,
            update={
                "version": current.version + 1,
                "fields": fields,
                "last_command_id": submission.client_turn_id,
                "last_payload_hash": payload_hash,
                "updated_at": now_utc(),
            },
        )
        evaluated = self._evaluate(candidate)
        if submission.advance and evaluated.status is not SkillInputRequestStatus.COMPLETE:
            raise SkillInputPreflightError(
                "input_required_fields_missing"
                if evaluated.missing_required_field_ids
                else "input_fields_invalid"
            )
        if not submission.advance and evaluated.status is SkillInputRequestStatus.COMPLETE:
            evaluated = evaluated.model_copy(
                deep=True,
                update={"status": SkillInputRequestStatus.OPEN, "frozen_bindings": []},
            )
        return evaluated, payload_hash

    def node_inputs(
        self,
        request: SkillInputRequestV1,
        node_id: str,
        *,
        skill_id: str | None = None,
    ) -> dict[str, object]:
        if request.status is not SkillInputRequestStatus.COMPLETE:
            raise SkillInputPreflightError("input_request_incomplete")
        snapshot = next(
            (item for item in request.contract_snapshots if item.node_id == node_id),
            None,
        )
        if snapshot is None:
            skill = self.repository.get_skill_definition(skill_id) if skill_id else None
            profile = self._profile_for_skill(skill) if skill is not None else None
            if profile is not None and profile.user_input_mode is SkillUserInputMode.PREFLIGHT:
                raise SkillInputPreflightError("input_contract_snapshot_missing")
            return {}
        skill = self.repository.get_skill_definition(snapshot.skill_id)
        profile = self.repository.get_skill_capability_profile(snapshot.skill_id)
        if (
            skill is None
            or profile is None
            or skill.version != snapshot.skill_version
            or skill.content_hash != snapshot.skill_content_hash
            or profile.user_input_contract_hash != snapshot.contract_hash
        ):
            raise SkillInputPreflightError("input_contract_revalidation_failed")
        result: dict[str, object] = {}
        for binding in request.frozen_bindings:
            if binding.node_id != node_id:
                continue
            if binding.value_kind == "text":
                result[binding.field_id] = {
                    "kind": "text",
                    "content_hash": binding.content_hash,
                    "value": binding.value_ref,
                }
                continue
            artifact = self.repository.get_run_input_artifact(binding.value_ref)
            expected_adapter = adapter_identity_for_media_type(artifact.media_type) if artifact is not None else None
            if (
                artifact is None
                or artifact.status is not RunInputArtifactStatus.READY
                or artifact.content_hash != binding.content_hash
                or expected_adapter is None
                or (artifact.adapter_id, artifact.adapter_version) != expected_adapter
            ):
                raise SkillInputPreflightError("input_artifact_binding_invalid")
            value = {
                "kind": "artifact",
                "artifact_id": artifact.id,
                "media_type": artifact.media_type,
                "content_hash": artifact.content_hash,
                "normalized_text": (
                    None if artifact.media_type == "text/csv" else artifact.normalized_text
                ),
                "structured_payload": artifact.structured_payload,
            }
            existing = result.get(binding.field_id)
            if existing is None:
                result[binding.field_id] = [value] if self._field_is_multiple(request, node_id, binding.field_id) else value
            elif isinstance(existing, list):
                existing.append(value)
        return result

    @staticmethod
    def _field_is_multiple(request: SkillInputRequestV1, node_id: str, field_id: str) -> bool:
        return next(
            (
                field.multiple
                for field in request.fields
                if field.node_id == node_id and field.field_id == field_id
            ),
            False,
        )
