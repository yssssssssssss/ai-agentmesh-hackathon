from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from jsonschema import validators
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from agentmesh.research_orchestration.v3.canonical import canonical_json_v3_sha256
from agentmesh.research_orchestration.v3.catalog import (
    CompetitiveTextCatalog,
    load_catalog_document,
    load_competitive_text_catalog,
)
from agentmesh.research_orchestration.v3.common import thaw_json_value
from agentmesh.research_orchestration.v3.execution_plan import (
    ExecutionPlanV3,
    ExecutionPlanVersionV3,
    PlanCandidateV3,
    PlanInputBindingV3,
    PlanStepProposalV3,
    PlanStepV3,
)
from agentmesh.research_orchestration.v3.planning.models import PlanningArtifactPort
from agentmesh.research_orchestration.v3.planning.validation import validate_competitive_problem_graph
from agentmesh.research_orchestration.v3.ports import (
    CandidateCompilationRequestV3,
    ClockPort,
    IdGeneratorPort,
)
from agentmesh.research_orchestration.v3.problem_graph import ProblemGraphV1
from agentmesh.research_orchestration.v3.snapshots import (
    FrozenActorV3,
    FrozenDocumentV3,
    ResearchControlSnapshotV3,
)


class CandidateCompilationError(ValueError):
    def __init__(self, *codes: str) -> None:
        self.codes = tuple(dict.fromkeys(codes))
        super().__init__(", ".join(self.codes))


def _pointer_tokens(pointer: str) -> tuple[str, ...]:
    if not pointer.startswith("/"):
        raise CandidateCompilationError("json_pointer_invalid")
    tokens: list[str] = []
    for raw in pointer[1:].split("/"):
        index = 0
        while index < len(raw):
            if raw[index] == "~":
                if index + 1 >= len(raw) or raw[index + 1] not in {"0", "1"}:
                    raise CandidateCompilationError("json_pointer_invalid")
                index += 2
            else:
                index += 1
        tokens.append(raw.replace("~1", "/").replace("~0", "~"))
    return tuple(tokens)


_MISSING = object()


def _array_index(token: str) -> int | None:
    if token == "0":
        return 0
    if not token or token[0] == "0" or not token.isascii() or not token.isdigit():
        return None
    return int(token)


def _resolve_pointer(document: object, pointer: str) -> object:
    current = document
    for token in _pointer_tokens(pointer):
        if isinstance(current, Mapping):
            current = current.get(token, _MISSING)
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            index = _array_index(token)
            if index is None:
                raise CandidateCompilationError("json_pointer_invalid")
            current = current[index] if index < len(current) else _MISSING
        else:
            return _MISSING
        if current is _MISSING:
            return _MISSING
    return current


def _schema(document: FrozenDocumentV3) -> Mapping[str, object]:
    if document.kind != "json_schema":
        raise CandidateCompilationError("actor_schema_document_kind_invalid")
    schema = thaw_json_value(document.content)
    if not isinstance(schema, Mapping):
        raise CandidateCompilationError("actor_schema_invalid")
    try:
        validator_type = validators.validator_for(schema)
        validator_type.check_schema(schema)
    except (SchemaError, TypeError, ValueError):
        raise CandidateCompilationError("actor_schema_invalid") from None
    return schema


def _dereference_schema(
    root: Mapping[str, object],
    schema: object,
    visited_refs: frozenset[str] = frozenset(),
) -> object | None:
    if isinstance(schema, bool):
        return schema
    if not isinstance(schema, Mapping):
        return None
    reference = schema.get("$ref")
    if reference is None:
        return schema
    if not isinstance(reference, str) or reference in visited_refs:
        return None
    if reference == "#":
        resolved: object = root
    elif reference.startswith("#/"):
        resolved = _resolve_pointer(root, reference[1:])
    else:
        return None
    if resolved is _MISSING:
        return None
    return _dereference_schema(root, resolved, visited_refs | {reference})


def _schema_variants(
    root: Mapping[str, object],
    schema: object,
    visited_refs: frozenset[str] = frozenset(),
) -> tuple[object, ...]:
    resolved = _dereference_schema(root, schema, visited_refs)
    if isinstance(resolved, bool):
        return (resolved,)
    if not isinstance(resolved, Mapping):
        return ()
    for keyword in ("oneOf", "anyOf"):
        branches = resolved.get(keyword)
        if branches is None:
            continue
        if _has_assertion_siblings(resolved, keyword):
            return ()
        if keyword == "oneOf" and not _one_of_is_unambiguous(root, branches):
            return ()
        return tuple(
            variant
            for branch in branches
            for variant in _schema_variants(root, branch, visited_refs)
        )
    if "allOf" in resolved:
        # Traversing an intersection requires proving the combined child schema. Fail closed
        # instead of treating allOf as a union and accepting a pointer from only one branch.
        return ()
    return (resolved,)


def _schema_child(root: Mapping[str, object], schema: object, token: str) -> tuple[object, ...]:
    children: list[object] = []
    for variant in _schema_variants(root, schema):
        if variant is True:
            children.append(True)
            continue
        if variant is False or not isinstance(variant, Mapping):
            continue
        schema_type = variant.get("type")
        types = {schema_type} if isinstance(schema_type, str) else set(schema_type or ())
        properties = variant.get("properties")
        if isinstance(properties, Mapping) and token in properties:
            children.append(properties[token])
        else:
            object_shape = "object" in types or any(
                key in variant for key in ("properties", "patternProperties", "additionalProperties")
            )
            additional = variant.get("additionalProperties", True)
            if object_shape and additional is not False:
                children.append(additional)
        array_shape = "array" in types or any(key in variant for key in ("items", "prefixItems"))
        if not array_shape:
            continue
        index = _array_index(token)
        if index is None:
            if token.isdigit():
                raise CandidateCompilationError("json_pointer_invalid")
            continue
        prefix_items = variant.get("prefixItems")
        if (
            isinstance(prefix_items, Sequence)
            and not isinstance(prefix_items, (str, bytes, bytearray))
            and index < len(prefix_items)
        ):
            children.append(prefix_items[index])
            continue
        items = variant.get("items", True)
        if isinstance(items, Sequence) and not isinstance(items, (str, bytes, bytearray, Mapping)):
            if index < len(items):
                children.append(items[index])
        elif items is not False:
            children.append(items)
    return tuple(children)


def _schemas_at_pointer(schema: Mapping[str, object], pointer: str) -> tuple[object, ...]:
    current: tuple[object, ...] = (schema,)
    for token in _pointer_tokens(pointer):
        current = tuple(child for node in current for child in _schema_child(schema, node, token))
        if not current:
            return ()
    return current


def _schema_allows_pointer(schema: Mapping[str, object], pointer: str) -> bool:
    return bool(_schemas_at_pointer(schema, pointer))


_SCHEMA_ANNOTATIONS = {
    "$comment",
    "$defs",
    "$id",
    "$schema",
    "definitions",
    "deprecated",
    "description",
    "examples",
    "readOnly",
    "title",
    "writeOnly",
}
_JSON_TYPES = {"array", "boolean", "integer", "null", "number", "object", "string"}


def _has_assertion_siblings(schema: Mapping[str, object], keyword: str) -> bool:
    return any(key != keyword and key not in _SCHEMA_ANNOTATIONS for key in schema)


def _schema_accepts_instance(root: Mapping[str, object], schema: object, instance: object) -> bool:
    if not isinstance(schema, (Mapping, bool)):
        return False
    try:
        validator_type = validators.validator_for(root)
        validator = validator_type(root, format_checker=validator_type.FORMAT_CHECKER)
        return not any(validator.evolve(schema=schema).iter_errors(instance))
    except (RecursionError, TypeError, ValueError):
        return False
    except Exception:
        # Resolution backends raise version-specific exceptions for unavailable external refs.
        return False


def _schema_finite_values(root: Mapping[str, object], schema: object) -> tuple[object, ...] | None:
    resolved = _dereference_schema(root, schema)
    if not isinstance(resolved, Mapping):
        return None
    candidates: tuple[object, ...] | None = None
    if "const" in resolved:
        candidates = (resolved["const"],)
    else:
        enum = resolved.get("enum")
        if isinstance(enum, Sequence) and not isinstance(enum, (str, bytes, bytearray)):
            candidates = tuple(enum)
    if candidates is None:
        for keyword in ("oneOf", "anyOf"):
            branches = resolved.get(keyword)
            if branches is None or not isinstance(branches, Sequence) or isinstance(branches, (str, bytes, bytearray)):
                continue
            branch_values = tuple(_schema_finite_values(root, branch) for branch in branches)
            if any(values is None for values in branch_values):
                return None
            candidates = tuple(value for values in branch_values for value in values or ())
            break
    if candidates is None:
        branches = resolved.get("allOf")
        if isinstance(branches, Sequence) and not isinstance(branches, (str, bytes, bytearray)):
            candidates = next(
                (values for branch in branches if (values := _schema_finite_values(root, branch)) is not None),
                None,
            )
    if candidates is None:
        return None
    return tuple(value for value in candidates if _schema_accepts_instance(root, resolved, value))


def _json_type(value: object) -> str | None:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, (float, Decimal)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "array"
    return None


def _schema_types(root: Mapping[str, object], schema: object) -> frozenset[str] | None:
    resolved = _dereference_schema(root, schema)
    if not isinstance(resolved, Mapping):
        return None
    raw_type = resolved.get("type")
    if isinstance(raw_type, str):
        return frozenset({raw_type}) if raw_type in _JSON_TYPES else None
    if isinstance(raw_type, Sequence) and not isinstance(raw_type, (str, bytes, bytearray)):
        types = frozenset(raw_type)
        return types if types and types <= _JSON_TYPES else None
    finite = _schema_finite_values(root, resolved)
    if finite:
        types = frozenset(filter(None, (_json_type(value) for value in finite)))
        return types or None
    for keyword in ("oneOf", "anyOf"):
        branches = resolved.get(keyword)
        if branches is None or not isinstance(branches, Sequence) or isinstance(branches, (str, bytes, bytearray)):
            continue
        branch_types = tuple(_schema_types(root, branch) for branch in branches)
        if any(types is None for types in branch_types):
            return None
        return frozenset(item for types in branch_types for item in types or ())
    branches = resolved.get("allOf")
    if isinstance(branches, Sequence) and not isinstance(branches, (str, bytes, bytearray)):
        known = tuple(types for branch in branches if (types := _schema_types(root, branch)) is not None)
        if not known:
            return None
        common = set(known[0])
        for types in known[1:]:
            common &= set(types)
        return frozenset(common) or None
    return None


def _types_overlap(left: frozenset[str], right: frozenset[str]) -> bool:
    for left_type in left:
        for right_type in right:
            if left_type == right_type or {left_type, right_type} == {"integer", "number"}:
                return True
    return False


def _one_of_is_unambiguous(root: Mapping[str, object], branches: object) -> bool:
    if not isinstance(branches, Sequence) or isinstance(branches, (str, bytes, bytearray)) or not branches:
        return False
    for index, left in enumerate(branches):
        left_types = _schema_types(root, left)
        if left_types is None:
            return False
        for right in branches[index + 1 :]:
            right_types = _schema_types(root, right)
            if right_types is None:
                return False
            if not _types_overlap(left_types, right_types):
                continue
            left_values = _schema_finite_values(root, left)
            right_values = _schema_finite_values(root, right)
            if left_values is not None and not any(
                _schema_accepts_instance(root, right, value) for value in left_values
            ):
                continue
            if right_values is not None and not any(
                _schema_accepts_instance(root, left, value) for value in right_values
            ):
                continue
            return False
    return True


def _decimal(value: object) -> Decimal | None:
    try:
        if isinstance(value, bool):
            return None
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _lower_bound(schema: Mapping[str, object]) -> tuple[Decimal, bool] | None:
    exclusive = schema.get("exclusiveMinimum")
    if isinstance(exclusive, bool):
        if "minimum" not in schema:
            return None
        value = _decimal(schema["minimum"])
        return (value, exclusive) if value is not None else None
    if exclusive is not None:
        value = _decimal(exclusive)
        return (value, True) if value is not None else None
    if "minimum" in schema:
        value = _decimal(schema["minimum"])
        return (value, False) if value is not None else None
    return None


def _upper_bound(schema: Mapping[str, object]) -> tuple[Decimal, bool] | None:
    exclusive = schema.get("exclusiveMaximum")
    if isinstance(exclusive, bool):
        if "maximum" not in schema:
            return None
        value = _decimal(schema["maximum"])
        return (value, exclusive) if value is not None else None
    if exclusive is not None:
        value = _decimal(exclusive)
        return (value, True) if value is not None else None
    if "maximum" in schema:
        value = _decimal(schema["maximum"])
        return (value, False) if value is not None else None
    return None


def _lower_implies(source: tuple[Decimal, bool] | None, target: tuple[Decimal, bool] | None) -> bool:
    if target is None:
        return True
    if source is None:
        return False
    if source[0] != target[0]:
        return source[0] > target[0]
    return source[1] or not target[1]


def _upper_implies(source: tuple[Decimal, bool] | None, target: tuple[Decimal, bool] | None) -> bool:
    if target is None:
        return True
    if source is None:
        return False
    if source[0] != target[0]:
        return source[0] < target[0]
    return source[1] or not target[1]


def _string_constraints_assignable(source: Mapping[str, object], target: Mapping[str, object]) -> bool:
    source_min = source.get("minLength", 0)
    target_min = target.get("minLength", 0)
    source_max = source.get("maxLength")
    target_max = target.get("maxLength")
    if not isinstance(source_min, int) or not isinstance(target_min, int) or source_min < target_min:
        return False
    if target_max is not None and (not isinstance(source_max, int) or source_max > target_max):
        return False
    for keyword in ("pattern", "format", "contentEncoding", "contentMediaType"):
        if keyword in target and source.get(keyword) != target[keyword]:
            return False
    return True


def _numeric_constraints_assignable(source: Mapping[str, object], target: Mapping[str, object]) -> bool:
    if not _lower_implies(_lower_bound(source), _lower_bound(target)):
        return False
    if not _upper_implies(_upper_bound(source), _upper_bound(target)):
        return False
    if "multipleOf" in target:
        source_multiple = _decimal(source.get("multipleOf"))
        target_multiple = _decimal(target["multipleOf"])
        if source_multiple is None or target_multiple is None or target_multiple == 0:
            return False
        if source_multiple % target_multiple != 0:
            return False
    return True


def _array_constraints_assignable(
    source_root: Mapping[str, object],
    source: Mapping[str, object],
    target_root: Mapping[str, object],
    target: Mapping[str, object],
    visited: frozenset[tuple[int, int]],
) -> bool:
    if any(keyword in target for keyword in ("contains", "minContains", "maxContains", "prefixItems", "unevaluatedItems")):
        return False
    if any(keyword in source for keyword in ("prefixItems", "unevaluatedItems")):
        return False
    source_min = source.get("minItems", 0)
    target_min = target.get("minItems", 0)
    source_max = source.get("maxItems")
    target_max = target.get("maxItems")
    if not isinstance(source_min, int) or not isinstance(target_min, int) or source_min < target_min:
        return False
    if target_max is not None and (not isinstance(source_max, int) or source_max > target_max):
        return False
    if target.get("uniqueItems") is True and source.get("uniqueItems") is not True and source_max != 1:
        return False
    source_items = source.get("items", True)
    target_items = target.get("items", True)
    if isinstance(source_items, Sequence) and not isinstance(source_items, (str, bytes, bytearray, Mapping)):
        return False
    if isinstance(target_items, Sequence) and not isinstance(target_items, (str, bytes, bytearray, Mapping)):
        return False
    if target_items is True:
        return True
    if target_items is False:
        return source_items is False or source_max == 0
    if source_items is False:
        return True
    if source_items is True:
        return False
    return _schema_assignable(source_root, source_items, target_root, target_items, visited)


def _object_property_schema(schema: Mapping[str, object], name: str) -> object:
    properties = schema.get("properties", {})
    if isinstance(properties, Mapping) and name in properties:
        return properties[name]
    return schema.get("additionalProperties", True)


def _object_constraints_assignable(
    source_root: Mapping[str, object],
    source: Mapping[str, object],
    target_root: Mapping[str, object],
    target: Mapping[str, object],
    visited: frozenset[tuple[int, int]],
) -> bool:
    unsupported = {
        "dependencies",
        "dependentRequired",
        "dependentSchemas",
        "patternProperties",
        "propertyNames",
        "unevaluatedProperties",
    }
    if unsupported & (set(source) | set(target)):
        return False
    source_properties = source.get("properties", {})
    target_properties = target.get("properties", {})
    if not isinstance(source_properties, Mapping) or not isinstance(target_properties, Mapping):
        return False
    source_required = set(source.get("required", ()))
    target_required = set(target.get("required", ()))
    if not target_required <= source_required:
        return False
    source_min = max(int(source.get("minProperties", 0)), len(source_required))
    target_min = max(int(target.get("minProperties", 0)), len(target_required))
    if source_min < target_min:
        return False
    source_additional = source.get("additionalProperties", True)
    target_additional = target.get("additionalProperties", True)
    source_max = source.get("maxProperties")
    if source_max is None and source_additional is False:
        source_max = len(source_properties)
    target_max = target.get("maxProperties")
    if target_max is not None and (not isinstance(source_max, int) or source_max > target_max):
        return False

    for name, source_property in source_properties.items():
        target_property = _object_property_schema(target, name)
        if target_property is False:
            return False
        if target_property is not True and not _schema_assignable(
            source_root,
            source_property,
            target_root,
            target_property,
            visited,
        ):
            return False
    if source_additional is not False:
        for name, target_property in target_properties.items():
            if name in source_properties or target_property is True:
                continue
            if not _schema_assignable(
                source_root,
                source_additional,
                target_root,
                target_property,
                visited,
            ):
                return False
        if target_additional is False:
            return False
        if target_additional is not True and not _schema_assignable(
            source_root,
            source_additional,
            target_root,
            target_additional,
            visited,
        ):
            return False
    return True


def _schema_type_slice(schema: Mapping[str, object], schema_type: str) -> Mapping[str, object]:
    return {**schema, "type": schema_type}


def _schema_assignable(  # noqa: C901, PLR0911
    source_root: Mapping[str, object],
    source_schema: object,
    target_root: Mapping[str, object],
    target_schema: object,
    visited: frozenset[tuple[int, int]] = frozenset(),
) -> bool:
    source = _dereference_schema(source_root, source_schema)
    target = _dereference_schema(target_root, target_schema)
    if not isinstance(source, Mapping) or not isinstance(target, Mapping):
        return False
    pair = (id(source), id(target))
    if pair in visited:
        return False
    visited |= {pair}

    source_one_of = source.get("oneOf")
    if source_one_of is not None and not _one_of_is_unambiguous(source_root, source_one_of):
        return False
    target_one_of = target.get("oneOf")
    if target_one_of is not None and not _one_of_is_unambiguous(target_root, target_one_of):
        return False

    source_values = _schema_finite_values(source_root, source)
    if source_values is not None:
        return bool(source_values) and all(
            _schema_accepts_instance(target_root, target, value) for value in source_values
        )
    if _schema_finite_values(target_root, target) is not None:
        return False

    for keyword in ("oneOf", "anyOf"):
        branches = source.get(keyword)
        if branches is None:
            continue
        if _has_assertion_siblings(source, keyword):
            return False
        return all(
            _schema_assignable(source_root, branch, target_root, target, visited)
            for branch in branches
        )
    if "allOf" in source:
        return False

    source_types = _schema_types(source_root, source)
    if source_types is None:
        return False
    for keyword in ("oneOf", "anyOf"):
        branches = target.get(keyword)
        if branches is None:
            continue
        if _has_assertion_siblings(target, keyword):
            return False
        return all(
            any(
                _schema_assignable(
                    source_root,
                    _schema_type_slice(source, source_type),
                    target_root,
                    branch,
                    visited,
                )
                for branch in branches
            )
            for source_type in source_types
        )
    target_all_of = target.get("allOf")
    if target_all_of is not None:
        if _has_assertion_siblings(target, "allOf"):
            return False
        return all(
            _schema_assignable(source_root, source, target_root, branch, visited)
            for branch in target_all_of
        )
    if any(keyword in target for keyword in ("if", "not", "then", "else")):
        return False

    target_types = _schema_types(target_root, target)
    if target_types is None:
        return False
    for source_type in source_types:
        compatible_targets = {
            target_type
            for target_type in target_types
            if source_type == target_type or (source_type == "integer" and target_type == "number")
        }
        if not compatible_targets:
            return False
        if source_type == "string" and not _string_constraints_assignable(source, target):
            return False
        if source_type in {"integer", "number"} and not _numeric_constraints_assignable(source, target):
            return False
        if source_type == "array" and not _array_constraints_assignable(
            source_root,
            source,
            target_root,
            target,
            visited,
        ):
            return False
        if source_type == "object" and not _object_constraints_assignable(
            source_root,
            source,
            target_root,
            target,
            visited,
        ):
            return False
    return True


def _schema_nodes_assignable(
    source_root: Mapping[str, object],
    source_nodes: tuple[object, ...],
    target_root: Mapping[str, object],
    target_nodes: tuple[object, ...],
) -> bool:
    return bool(source_nodes) and bool(target_nodes) and all(
        any(_schema_assignable(source_root, source, target_root, target) for target in target_nodes)
        for source in source_nodes
    )


def _validate_json_schema_instance(
    schema: Mapping[str, object],
    instance: object,
    error_code: str,
) -> None:
    try:
        validator_type = validators.validator_for(schema)
        validator_type(schema, format_checker=validator_type.FORMAT_CHECKER).validate(instance)
    except (JsonSchemaValidationError, RecursionError, TypeError, ValueError):
        raise CandidateCompilationError(error_code) from None
    except Exception:
        # Treat unavailable references and validator backend failures as invalid input schemas.
        raise CandidateCompilationError(error_code) from None


def _topological_proposals(
    candidate: PlanCandidateV3,
) -> tuple[tuple[PlanStepProposalV3, ...], dict[int, int]]:
    by_proposed_number: dict[int, PlanStepProposalV3] = {}
    for step in candidate.proposed_steps:
        if step.proposed_step_number in by_proposed_number:
            raise CandidateCompilationError("candidate_step_identity_duplicate")
        by_proposed_number[step.proposed_step_number] = step
    known = set(by_proposed_number)
    for step in candidate.proposed_steps:
        if step.proposed_step_number in step.depends_on or not set(step.depends_on).issubset(known):
            raise CandidateCompilationError("candidate_dependency_invalid")

    remaining = list(candidate.proposed_steps)
    ordered: list[PlanStepProposalV3] = []
    emitted: set[int] = set()
    while remaining:
        ready = [step for step in remaining if set(step.depends_on).issubset(emitted)]
        if not ready:
            raise CandidateCompilationError("candidate_dependency_cycle")
        step = ready[0]
        ordered.append(step)
        emitted.add(step.proposed_step_number)
        remaining.remove(step)
    identity_map = {
        step.proposed_step_number: index
        for index, step in enumerate(ordered, start=1)
    }
    return tuple(ordered), identity_map


def _ancestors(steps: tuple[PlanStepV3, ...], step_number: int) -> set[int]:
    by_number = {step.step_number: step for step in steps}
    result: set[int] = set()
    pending = list(by_number[step_number].depends_on)
    while pending:
        dependency = pending.pop()
        if dependency in result:
            continue
        result.add(dependency)
        pending.extend(by_number[dependency].depends_on)
    return result


class CompetitiveTextCandidateCompiler:
    """Compiles non-authoritative proposals into immutable server-owned plans."""

    def __init__(
        self,
        *,
        catalog: CompetitiveTextCatalog,
        artifacts: PlanningArtifactPort,
        id_generator: IdGeneratorPort,
        clock: ClockPort,
    ) -> None:
        self._catalog = catalog
        self._artifacts = artifacts
        self._id_generator = id_generator
        self._clock = clock

    def _validate_catalog(self) -> None:
        try:
            verified_catalog = load_competitive_text_catalog()
        except (KeyError, OSError, TypeError, ValueError):
            raise CandidateCompilationError("catalog_verification_failed") from None
        if self._catalog != verified_catalog:
            raise CandidateCompilationError("catalog_verification_failed")

    def _read_snapshot(self, request: CandidateCompilationRequestV3) -> ResearchControlSnapshotV3:
        reference = request.capabilities.control_snapshot_artifact
        if (
            reference.kind != "research_control_snapshot"
            or reference.schema_version != "research-control-snapshot-v3"
        ):
            raise CandidateCompilationError("control_snapshot_artifact_identity_mismatch")
        snapshot = self._artifacts.read_control_snapshot(reference)
        if snapshot is None:
            raise CandidateCompilationError("control_snapshot_unavailable")
        if canonical_json_v3_sha256(snapshot) != reference.content_hash:
            raise CandidateCompilationError("control_snapshot_hash_mismatch")
        if snapshot.catalog_id != self._catalog.catalog_id or snapshot.catalog_hash != self._catalog.catalog_hash:
            raise CandidateCompilationError("control_snapshot_catalog_mismatch")
        self._validate_snapshot(snapshot)
        return snapshot

    @staticmethod
    def _validate_schema_documents(
        actor: FrozenActorV3,
        documents: Mapping[str, FrozenDocumentV3],
    ) -> tuple[Mapping[str, object], Mapping[str, object]]:
        input_document = documents.get(actor.input_schema_document_id)
        output_document = documents.get(actor.output_schema_document_id)
        if input_document is None or output_document is None:
            raise CandidateCompilationError("actor_schema_snapshot_missing")
        input_schema = _schema(input_document)
        output_schema = _schema(output_document)
        return input_schema, output_schema

    def _validate_snapshot(self, snapshot: ResearchControlSnapshotV3) -> None:
        expected_actor_keys = {
            *(("tool", item.id) for item in self._catalog.actors.tools),
            *(("skill", item.id) for item in self._catalog.actors.skills),
            *(("llm", item.id) for item in self._catalog.actors.llm),
            *(("reviewer", item.id) for item in self._catalog.actors.reviewers),
        }
        actors = {(item.actor_type, item.actor_id): item for item in snapshot.actors}
        if set(actors) != expected_actor_keys:
            raise CandidateCompilationError("control_snapshot_actor_set_mismatch")
        documents = {item.document_id: item for item in snapshot.documents}
        supported_catalog_kinds = {
            "json_schema",
            "skill_instructions",
            "knowledge",
            "evidence_policy",
            "review_rubric",
            "report_template",
            "synthesis_prompt",
        }
        for catalog_document in self._catalog.documents:
            if catalog_document.kind not in supported_catalog_kinds:
                continue
            frozen_document = documents.get(catalog_document.id)
            expected_content = load_catalog_document(self._catalog, catalog_document.id)
            if (
                frozen_document is None
                or frozen_document.kind != catalog_document.kind
                or frozen_document.content_hash != canonical_json_v3_sha256(expected_content)
            ):
                raise CandidateCompilationError("control_snapshot_catalog_document_mismatch")
        expected_instructions = {
            ("tool", "tavily-web-search"): None,
            ("skill", "competitive-web-research"): "competitive-web-research-instructions",
            ("skill", "competitive-analysis"): "competitive-analysis-instructions",
            ("llm", "competitive-text-synthesis-v1"): "competitive-text-synthesis-prompt",
            ("reviewer", "competitive-text-quality-reviewer-v1"): "competitive-analysis-review-v3",
        }
        expected_instruction_kinds = {
            "skill": "skill_instructions",
            "llm": "synthesis_prompt",
            "reviewer": "review_rubric",
        }
        tool_by_id = {item.id: item for item in self._catalog.actors.tools}
        skill_by_id = {item.id: item for item in self._catalog.actors.skills}
        for key, actor in actors.items():
            if not actor.enabled or not actor.eligible:
                raise CandidateCompilationError("control_snapshot_actor_not_eligible")
            if actor.instruction_document_id != expected_instructions[key]:
                raise CandidateCompilationError("actor_descriptor_mapping_mismatch")
            if actor.instruction_document_id is not None:
                instruction = documents.get(actor.instruction_document_id)
                if instruction is None or instruction.kind != expected_instruction_kinds[actor.actor_type]:
                    raise CandidateCompilationError("actor_instruction_document_kind_invalid")
            _input_schema, output_schema = self._validate_schema_documents(actor, documents)
            expected_root = self._expected_output_root(actor.actor_type, actor.actor_id, self._catalog)
            if not _schema_allows_pointer(output_schema, expected_root):
                raise CandidateCompilationError("actor_output_schema_mapping_mismatch")
            if actor.actor_type == "tool":
                tool = tool_by_id[actor.actor_id]
                if (
                    actor.execution_mode != "real"
                    or actor.tier != tool.tier
                    or actor.approval_role != tool.approval_role
                    or actor.required_tool_ids
                    or actor.optional_tool_ids
                    or actor.input_schema_document_id != "source-tavily-input-schema"
                    or actor.output_schema_document_id != "source-tavily-output-schema"
                ):
                    raise CandidateCompilationError("actor_descriptor_mapping_mismatch")
            elif actor.actor_type == "skill":
                skill = skill_by_id[actor.actor_id]
                if (
                    actor.tier is not None
                    or actor.approval_role is not None
                    or actor.required_tool_ids != skill.required_tools
                    or actor.optional_tool_ids != skill.enabled_optional_tools
                    or actor.output_schema_document_id != "source-skill-result-envelope-schema"
                ):
                    raise CandidateCompilationError("actor_descriptor_mapping_mismatch")
            elif (
                actor.tier is not None
                or actor.approval_role is not None
                or actor.required_tool_ids
                or actor.optional_tool_ids
            ):
                raise CandidateCompilationError("actor_descriptor_mapping_mismatch")

    def _validate_resolution(self, request: CandidateCompilationRequestV3) -> None:
        required_gaps = [item.code for item in request.capabilities.gaps if item.required]
        if required_gaps:
            raise CandidateCompilationError(*required_gaps)
        expected_decisions = {
            *(("tool", item.id) for item in self._catalog.actors.tools),
            *(("skill", item.id) for item in self._catalog.actors.skills),
        }
        actual_decisions = {
            (item.actor_type, item.actor_id): item
            for item in request.capabilities.decisions
        }
        if set(actual_decisions) != expected_decisions:
            raise CandidateCompilationError("capability_decision_set_mismatch")
        tool_by_id = {item.id: item for item in self._catalog.actors.tools}
        for key, decision in actual_decisions.items():
            if decision.status != "eligible" or tuple(item.code for item in decision.reasons) != ("eligible",):
                raise CandidateCompilationError("capability_decision_state_mismatch")
            if any(item.related_id != key[1] for item in decision.reasons):
                raise CandidateCompilationError("capability_decision_state_mismatch")
            if decision.pending_inputs:
                raise CandidateCompilationError("capability_pending_input_mismatch")
        for tool in self._catalog.actors.tools:
            decision = actual_decisions[("tool", tool.id)]
            approvals = tuple(
                (item.capability_type, item.capability_id, item.authority)
                for item in decision.required_approvals
            )
            if approvals != (("tool", tool.id, tool.approval_role),):
                raise CandidateCompilationError("capability_owner_approval_mismatch")
            if decision.optional_tool_decisions:
                raise CandidateCompilationError("optional_tool_decision_mismatch")
        for skill in self._catalog.actors.skills:
            decision = actual_decisions[("skill", skill.id)]
            expected_approvals = tuple(
                ("tool", tool_id, tool_by_id[tool_id].approval_role)
                for tool_id in skill.required_tools
            )
            actual_approvals = tuple(
                (item.capability_type, item.capability_id, item.authority)
                for item in decision.required_approvals
            )
            if actual_approvals != expected_approvals:
                raise CandidateCompilationError("capability_owner_approval_mismatch")
            optional_decisions = tuple(
                (item.tool_id, item.status, item.reason_code)
                for item in decision.optional_tool_decisions
            )
            expected_optional_decisions = tuple(
                (tool_id, "unavailable", "not_enabled_in_slice")
                for tool_id in skill.source_optional_tools
            )
            if optional_decisions != expected_optional_decisions:
                raise CandidateCompilationError("optional_tool_decision_mismatch")
        excluded_types = {
            "competitive-app-analysis": "skill",
            "digital-human-competitive-analysis": "skill",
            "playwright-page-capture": "tool",
        }
        declared_exclusions = tuple(
            (item.capability_type, item.capability_id, item.code, item.required)
            for item in request.capabilities.gaps
        )
        expected_exclusions = tuple(
            (excluded_types[item.id], item.id, item.reason, False)
            for item in self._catalog.excluded_source_capabilities
        )
        if declared_exclusions != expected_exclusions:
            raise CandidateCompilationError("optional_capability_exclusions_mismatch")

    def _validate_coverage(
        self,
        candidate: PlanCandidateV3,
        graph: ProblemGraphV1,
    ) -> tuple[str, ...]:
        required = tuple(question.id for question in graph.questions if question.priority == "required")
        covered = {question_id for step in candidate.proposed_steps for question_id in step.question_ids}
        if covered != set(required):
            raise CandidateCompilationError("candidate_question_coverage_mismatch")
        tool_covered = {
            question_id
            for step in candidate.proposed_steps
            if step.actor_type == "tool" and step.actor_id == "tavily-web-search"
            for question_id in step.question_ids
        }
        if tool_covered != set(required):
            raise CandidateCompilationError("public_evidence_step_coverage_mismatch")
        return required

    @staticmethod
    def _expected_output_root(actor_type: str, actor_id: str, catalog: CompetitiveTextCatalog) -> str:
        if actor_type == "tool":
            return "/results"
        if actor_type == "skill":
            skill = next((item for item in catalog.actors.skills if item.id == actor_id), None)
            if skill is None:
                raise CandidateCompilationError("candidate_actor_unknown")
            return skill.output_root
        collection = catalog.actors.llm if actor_type == "llm" else catalog.actors.reviewers
        actor = next((item for item in collection if item.id == actor_id), None)
        if actor is None:
            raise CandidateCompilationError("candidate_actor_unknown")
        return actor.output_root

    def _compile_steps(
        self,
        request: CandidateCompilationRequestV3,
        snapshot: ResearchControlSnapshotV3,
    ) -> tuple[PlanStepV3, ...]:
        ordered, identity_map = _topological_proposals(request.candidate)
        actors = {(item.actor_type, item.actor_id): item for item in snapshot.actors}
        documents = {item.document_id: item for item in snapshot.documents}
        decisions = {
            (item.actor_type, item.actor_id): item
            for item in request.capabilities.decisions
        }
        excluded = {item.id for item in self._catalog.excluded_source_capabilities}
        compiled: list[PlanStepV3] = []
        for proposal in ordered:
            if proposal.actor_id in excluded:
                raise CandidateCompilationError("excluded_capability_in_candidate")
            actor = actors.get((proposal.actor_type, proposal.actor_id))
            if actor is None or not actor.enabled or not actor.eligible:
                raise CandidateCompilationError("candidate_actor_not_eligible")
            if proposal.actor_type in {"tool", "skill"}:
                decision = decisions.get((proposal.actor_type, proposal.actor_id))
                if decision is None or decision.status != "eligible":
                    raise CandidateCompilationError("candidate_actor_decision_not_eligible")
            if proposal.actor_type == "tool":
                tool = next((item for item in self._catalog.actors.tools if item.id == proposal.actor_id), None)
                if tool is None or actor.execution_mode != "real" or actor.tier != "core":
                    raise CandidateCompilationError("core_tool_real_adapter_unavailable")
                if (
                    not proposal.requires_approval
                    or proposal.approval_role != tool.approval_role
                    or actor.approval_role != tool.approval_role
                ):
                    raise CandidateCompilationError("tool_owner_approval_required")
            elif proposal.requires_approval:
                raise CandidateCompilationError("non_tool_step_cannot_replace_tool_approval")

            input_document = documents.get(actor.input_schema_document_id)
            output_document = documents.get(actor.output_schema_document_id)
            if input_document is None or output_document is None:
                raise CandidateCompilationError("actor_schema_snapshot_missing")
            input_schema = _schema(input_document)
            output_schema = _schema(output_document)
            expected_root = self._expected_output_root(
                proposal.actor_type,
                proposal.actor_id,
                self._catalog,
            )
            output_pointers = {item.pointer for item in proposal.expected_outputs}
            if expected_root not in output_pointers:
                raise CandidateCompilationError("actor_output_root_missing")
            for pointer in output_pointers:
                if not _schema_allows_pointer(output_schema, pointer):
                    raise CandidateCompilationError("expected_output_schema_pointer_missing")

            proposed_input = thaw_json_value(proposal.input)
            mapped_dependencies = tuple(identity_map[item] for item in proposal.depends_on)
            mapped_bindings: list[PlanInputBindingV3] = []
            target_pointer_keys: set[tuple[str, ...]] = set()
            for binding in proposal.input_bindings:
                _pointer_tokens(binding.source_pointer)
                target_pointer_key = _pointer_tokens(binding.target_pointer)
                if target_pointer_key in target_pointer_keys:
                    raise CandidateCompilationError("binding_target_duplicate")
                target_pointer_keys.add(target_pointer_key)
                if binding.source_step_number not in proposal.depends_on:
                    raise CandidateCompilationError("binding_source_not_direct_dependency")
                source_number = identity_map[binding.source_step_number]
                source = compiled[source_number - 1]
                if not any(
                    binding.source_pointer == output.pointer
                    or binding.source_pointer.startswith(f"{output.pointer}/")
                    for output in source.expected_outputs
                ):
                    raise CandidateCompilationError("binding_source_output_missing")
                source_actor = actors[(source.actor_type, source.actor_id)]
                source_output_document = documents.get(source_actor.output_schema_document_id)
                if source_output_document is None:
                    raise CandidateCompilationError("actor_schema_snapshot_missing")
                source_output_schema = _schema(source_output_document)
                source_schema_nodes = _schemas_at_pointer(source_output_schema, binding.source_pointer)
                if not source_schema_nodes:
                    raise CandidateCompilationError("binding_source_schema_pointer_missing")
                target_schema_nodes = _schemas_at_pointer(input_schema, binding.target_pointer)
                if not target_schema_nodes:
                    raise CandidateCompilationError("binding_target_schema_pointer_missing")
                if not _schema_nodes_assignable(
                    source_output_schema,
                    source_schema_nodes,
                    input_schema,
                    target_schema_nodes,
                ):
                    raise CandidateCompilationError("binding_schema_incompatible")
                if _resolve_pointer(proposed_input, binding.target_pointer) is _MISSING:
                    raise CandidateCompilationError("binding_target_missing")
                mapped_bindings.append(
                    PlanInputBindingV3(
                        source_step_number=source_number,
                        source_pointer=binding.source_pointer,
                        target_pointer=binding.target_pointer,
                    )
                )

            _validate_json_schema_instance(input_schema, proposed_input, "candidate_input_schema_invalid")
            decision = decisions.get((proposal.actor_type, proposal.actor_id))
            if decision is not None:
                for pending in decision.pending_inputs:
                    target = f"/{pending.role.replace('~', '~0').replace('/', '~1')}"
                    if not _schema_allows_pointer(input_schema, target):
                        raise CandidateCompilationError("pending_input_schema_target_missing")
                    value = _resolve_pointer(proposed_input, target)
                    if value is _MISSING or value is None:
                        raise CandidateCompilationError("pending_input_target_unresolved")

            values: dict[str, Any] = {
                "step_number": len(compiled) + 1,
                "name": proposal.name,
                "actor_type": proposal.actor_type,
                "actor_id": proposal.actor_id,
                "question_ids": proposal.question_ids,
                "depends_on": mapped_dependencies,
                "input": proposal.input,
                "input_bindings": tuple(mapped_bindings),
                "expected_outputs": proposal.expected_outputs,
                "acceptance_criteria": proposal.acceptance_criteria,
                "required": True,
                "requires_approval": proposal.requires_approval,
                "approval_role": proposal.approval_role,
                "timeout_seconds": 60 if proposal.actor_type == "tool" else 120,
                "max_sends": 2 if proposal.actor_type == "tool" else 1,
                "invocation_semantics": {
                    "tool": "tool_read",
                    "skill": "skill_once",
                    "llm": "llm_once",
                    "reviewer": "reviewer_once",
                }[proposal.actor_type],
                "actor_snapshot_hash": canonical_json_v3_sha256(actor),
                "input_schema_hash": input_document.content_hash,
                "output_schema_hash": output_document.content_hash,
            }
            values["contract_hash"] = canonical_json_v3_sha256(values)
            compiled.append(PlanStepV3.model_validate(values))
        return tuple(compiled)

    def _validate_required_tool_prerequisites(self, steps: tuple[PlanStepV3, ...]) -> None:
        skill_by_id = {item.id: item for item in self._catalog.actors.skills}
        by_number = {step.step_number: step for step in steps}
        for step in steps:
            if step.actor_type != "skill":
                continue
            skill = skill_by_id[step.actor_id]
            ancestors = _ancestors(steps, step.step_number)
            for tool_id in skill.required_tools:
                matching = {
                    number
                    for number in ancestors
                    if by_number[number].actor_type == "tool" and by_number[number].actor_id == tool_id
                }
                if not matching:
                    raise CandidateCompilationError("required_tool_prerequisite_missing")
                if not any(binding.source_step_number in matching for binding in step.input_bindings):
                    raise CandidateCompilationError("required_tool_binding_missing")

    @staticmethod
    def _validate_problem_dependencies(steps: tuple[PlanStepV3, ...], graph: ProblemGraphV1) -> None:
        question_steps: dict[str, set[int]] = defaultdict(set)
        for step in steps:
            for question_id in step.question_ids:
                question_steps[question_id].add(step.step_number)
        for question in graph.questions:
            for step_number in question_steps[question.id]:
                ancestors = _ancestors(steps, step_number)
                for dependency_id in question.depends_on:
                    if dependency_id in steps[step_number - 1].question_ids:
                        continue
                    if not (question_steps[dependency_id] & ancestors):
                        raise CandidateCompilationError("problem_dependency_not_preserved")

    def compile(self, request: CandidateCompilationRequestV3) -> ExecutionPlanV3:
        self._validate_catalog()
        if request.requirement.content_hash != canonical_json_v3_sha256(request.requirement.payload):
            raise CandidateCompilationError("requirement_content_hash_mismatch")
        if request.requirement.payload.planning_blocked:
            raise CandidateCompilationError("requirement_clarification_required")
        self._validate_resolution(request)
        evidence_policy = validate_competitive_problem_graph(
            request.problem_graph,
            request.requirement.payload,
            self._catalog,
        )
        self._validate_coverage(request.candidate, request.problem_graph)
        snapshot = self._read_snapshot(request)
        steps = self._compile_steps(request, snapshot)
        self._validate_required_tool_prerequisites(steps)
        self._validate_problem_dependencies(steps, request.problem_graph)
        activated_nodes = tuple(item.id for item in self._catalog.decision_nodes)
        return ExecutionPlanV3(
            schema_version="execution-plan-v3",
            task_type="competitive_research",
            requirement_version_id=request.requirement.id,
            requirement_content_hash=request.requirement.content_hash,
            problem_graph_artifact=request.problem_graph_artifact,
            candidate_id=request.candidate.candidate_id,
            deliverable_type="competitive_analysis_report",
            payload_schema_version="competitive-analysis-text-v1",
            evidence_requirements=evidence_policy,
            capability_decisions=request.capabilities.decisions,
            capability_gaps=request.capabilities.gaps,
            steps=steps,
            candidate_title=request.candidate.title,
            candidate_rationale=request.candidate.rationale,
            candidate_tradeoffs=request.candidate.tradeoffs,
            activated_nodes=activated_nodes,
            control_snapshot_artifact=request.capabilities.control_snapshot_artifact,
        )

    def compile_version(
        self,
        *,
        run_id: str,
        version: int,
        request: CandidateCompilationRequestV3,
    ) -> ExecutionPlanVersionV3:
        if request.requirement.run_id != run_id:
            raise CandidateCompilationError("plan_run_mismatch")
        plan = self.compile(request)
        return ExecutionPlanVersionV3(
            id=self._id_generator.new("plan"),
            run_id=run_id,
            requirement_version_id=request.requirement.id,
            version=version,
            schema_version="execution-plan-v3",
            plan_hash=canonical_json_v3_sha256(plan),
            payload=plan,
            created_at=self._clock.now(),
        )
