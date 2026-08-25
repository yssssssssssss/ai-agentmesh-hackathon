from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from agentmesh.models import SkillDefinition

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]+")
_FIELD_WEIGHTS: dict[str, float] = {
    "name": 10.0,
    "aliases": 6.0,
    "title": 3.0,
    "description": 2.0,
    # short-description is curated routing metadata, so it deserves title-level weight.
    "metadata": 3.0,
}
_FIELD_LABELS = {
    "name": "名称",
    "aliases": "别名",
    "title": "标题",
    "description": "描述",
    "metadata": "元数据",
}
_SEARCHABLE_METADATA_KEYS = {"short-description"}
_QUERY_SYNONYMS = (
    ("同行怎么做", "竞品分析"),
    ("看看同行", "竞品分析"),
    ("跟用户聊", "用户访谈"),
    ("和用户聊", "用户访谈"),
    ("该问什么", "访谈提纲"),
    ("怎么问", "访谈提纲"),
    ("发个表", "问卷"),
    ("能点的页面样稿", "交互原型"),
    ("用户调研", "用户研究"),
    ("用研", "用户研究"),
    ("商品详情页", "商详页 可用性测试 审稿"),
    ("调研", "研究"),
    ("创建", "生成"),
)
_REQUEST_PREAMBLES = ("请帮我", "麻烦帮我", "可以帮我", "能不能帮我", "帮我", "我想", "我需要", "我要", "请")
_REQUEST_ACTIONS = ("做一个", "做一份", "生成一个", "生成一份", "创建一个", "创建一份", "产出一个", "产出一份")
_NEGATION_MARKERS = (
    "不需要",
    "不要",
    "无需",
    "不想",
    "不使用",
    "不用",
    "不做",
    "请勿",
    "别用",
    "别做",
    "避免",
    "禁止",
    "排除",
    "do not",
    "don't",
    "don’t",
    "dont",
    "not use",
    "without",
    "avoid",
    "exclude",
    "skip",
)
_NEGATION_CLAUSE_RE = re.compile(
    rf"(?<![a-z])(?:{'|'.join(re.escape(marker) for marker in sorted(_NEGATION_MARKERS, key=len, reverse=True))})(?![a-z])"
    r"(?:\s*(?:使用|调用|执行|选择|采用|use|invoke|run|select|choose))?\s*([^，,。.!！？；;\n]{1,160})",
    re.IGNORECASE,
)
_NEGATION_CLAUSE_STOP_RE = re.compile(
    r"(?:然后|接着|改为|改用|而是|请|帮我|同时|并且)|\b(?:then|instead|but|please)\b",
    re.IGNORECASE,
)
_LOW_SIGNAL_TERMS = frozenset(
    {"一个", "一份", "一张", "怎么", "么样", "如何", "帮我", "我想", "想做", "需要", "可以"}
)
_DESCRIPTION_BOUNDARY_RE = re.compile(r"(?:边界|boundary)\s*[:：]", re.IGNORECASE)
_BM25_K1 = 1.2
_BM25_B = 0.5
_MIN_QUERY_COVERAGE = 0.4
_MIN_LABEL_COVERAGE = 0.15


@dataclass(frozen=True, slots=True)
class SkillDirectoryMatch:
    skill: SkillDefinition
    score: float
    reason: str


@dataclass(frozen=True, slots=True)
class SkillDirectoryCandidate:
    match: SkillDirectoryMatch
    query_coverage: float
    label_coverage: float
    direct_label_match: bool
    negated_query: bool

    @property
    def accepted(self) -> bool:
        return not self.negated_query and (
            self.query_coverage >= _MIN_QUERY_COVERAGE
            or self.label_coverage >= _MIN_LABEL_COVERAGE
            or self.direct_label_match
        )


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold().removeprefix("$")
    for source, target in _QUERY_SYNONYMS:
        normalized = normalized.replace(source, target)
    return " ".join(_TOKEN_RE.findall(normalized))


def _normalize_query(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold().strip().removeprefix("$")
    changed = True
    while changed:
        changed = False
        for prefix in (*_REQUEST_PREAMBLES, *_REQUEST_ACTIONS):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :].lstrip(" ，,。:：")
                changed = True
                break
    return _normalize(normalized)


def normalize_skill_query(text: str) -> str:
    """Return the stable lexical form shared by directory retrieval backends."""
    return _normalize_query(text)


def skill_query_has_negation(text: str) -> bool:
    """Return whether deterministic matching must defer to semantic interpretation."""
    normalized_text = unicodedata.normalize("NFKC", text).casefold()
    return _NEGATION_CLAUSE_RE.search(normalized_text) is not None


def explicitly_negated_skill_ids(text: str, skills: Iterable[SkillDefinition]) -> set[str]:
    """Resolve only Skills named or described inside an explicit negative clause."""
    normalized_text = unicodedata.normalize("NFKC", text).casefold()
    fragments = []
    for match in _NEGATION_CLAUSE_RE.finditer(normalized_text):
        fragment = _NEGATION_CLAUSE_STOP_RE.split(match.group(1), maxsplit=1)[0]
        normalized_fragment = _normalize(fragment)
        if normalized_fragment:
            fragments.append(normalized_fragment)
    if not fragments:
        return set()

    negated: set[str] = set()
    for skill in skills:
        labels = [_normalize(skill.name), _normalize(skill.title), *(_normalize(alias) for alias in skill.aliases)]
        description = _normalize(positive_skill_description(skill.description))
        for fragment in fragments:
            label_match = any(
                label and (label in fragment or (len(fragment) >= 3 and fragment in label))
                for label in labels
            )
            description_match = len(fragment) >= 4 and fragment in description
            if label_match or description_match:
                negated.add(skill.id)
                break
    return negated


def _tokens(text: str) -> list[str]:
    terms: list[str] = []
    for token in _TOKEN_RE.findall(unicodedata.normalize("NFKC", text).casefold()):
        if token.isascii():
            if token not in _LOW_SIGNAL_TERMS:
                terms.append(token)
            continue
        if len(token) <= 2:
            if token not in _LOW_SIGNAL_TERMS:
                terms.append(token)
            continue
        terms.extend(
            term
            for index in range(len(token) - 1)
            if (term := token[index : index + 2]) not in _LOW_SIGNAL_TERMS
        )
    return terms


def _terms(text: str) -> set[str]:
    return set(_tokens(_normalize(text)))


def _inverse_document_frequency(term: str, document_count: int, document_frequency: Counter[str]) -> float:
    return math.log(
        1 + (document_count - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5)
    )


def _field_score(
    query: str,
    query_terms: set[str],
    value: str,
    *,
    weight: float,
    document_count: int,
    document_frequency: Counter[str],
    average_length: float,
) -> float:
    target = _normalize(value)
    if not target:
        return 0.0
    target_counts = Counter(_tokens(target))
    target_length = sum(target_counts.values())
    length_ratio = target_length / max(average_length, 1.0)
    score = 0.0
    for term in query_terms & target_counts.keys():
        frequency = target_counts[term]
        inverse_frequency = _inverse_document_frequency(term, document_count, document_frequency)
        saturation = frequency * (_BM25_K1 + 1) / (
            frequency + _BM25_K1 * (1 - _BM25_B + _BM25_B * length_ratio)
        )
        score += weight * inverse_frequency * saturation
    if query == target:
        score += weight * 10
    elif len(query) >= 2 and query in target:
        score += weight * 3
    elif len(target) >= 3 and target in query:
        score += weight * 2
    return score


def _query_coverage(
    query_terms: set[str],
    matched_terms: set[str],
    *,
    document_count: int,
    document_frequency: Counter[str],
) -> float:
    total = sum(_inverse_document_frequency(term, document_count, document_frequency) for term in query_terms)
    if total <= 0:
        return 0.0
    matched = sum(
        _inverse_document_frequency(term, document_count, document_frequency)
        for term in query_terms & matched_terms
    )
    return matched / total


def _label_match(query: str, fields: dict[str, str]) -> bool:
    labels = [fields["name"], fields["title"], *fields["aliases"].split()]
    for value in labels:
        label = _normalize(value).removesuffix(" skill").removesuffix(" 技能")
        if query == label or (len(query) >= 2 and query in label) or (len(label) >= 3 and label in query):
            return True
    return False


def _metadata_text(skill: SkillDefinition) -> str:
    return " ".join(
        f"{key} {value}"
        for key, value in sorted(skill.metadata.items())
        if key.casefold() in _SEARCHABLE_METADATA_KEYS
    )


def positive_skill_description(description: str) -> str:
    """Exclude declared negative-boundary examples from retrieval evidence."""
    return _DESCRIPTION_BOUNDARY_RE.split(description, maxsplit=1)[0]


def _search_fields(skill: SkillDefinition) -> dict[str, str]:
    return {
        "name": skill.name,
        "aliases": " ".join(skill.aliases),
        "title": skill.title,
        "description": positive_skill_description(skill.description),
        "metadata": _metadata_text(skill),
    }


def _match_reason(query_terms: set[str], fields: dict[str, str], field_scores: dict[str, float]) -> str:
    details: list[str] = []
    for field in _FIELD_WEIGHTS:
        if field_scores[field] <= 0:
            continue
        matching_terms = sorted(query_terms & _terms(fields[field]), key=lambda term: (-len(term), term))[:3]
        suffix = f"（{'、'.join(matching_terms)}）" if matching_terms else ""
        details.append(f"{_FIELD_LABELS[field]}{suffix}")
    return "匹配：" + "、".join(details)


def rank_skill_directory(
    task: str,
    skills: Iterable[SkillDefinition],
) -> list[SkillDirectoryCandidate]:
    """Rank authorized Skills and retain confidence evidence for later fusion."""
    query = _normalize_query(task)
    query_terms = _terms(query)
    if not query or not query_terms:
        return []

    candidates = list(skills)
    fields_by_skill_id = {skill.id: _search_fields(skill) for skill in candidates}
    document_frequency: Counter[str] = Counter()
    terms_by_skill_id: dict[str, set[str]] = {}
    field_lengths: dict[str, list[int]] = {field: [] for field in _FIELD_WEIGHTS}
    for skill_id, fields in fields_by_skill_id.items():
        document_terms: set[str] = set()
        for field, value in fields.items():
            tokens = _tokens(_normalize(value))
            field_lengths[field].append(len(tokens))
            document_terms.update(tokens)
        terms_by_skill_id[skill_id] = document_terms
        document_frequency.update(document_terms)
    average_lengths = {
        field: sum(lengths) / len(lengths) if lengths else 0.0
        for field, lengths in field_lengths.items()
    }

    ranked: list[SkillDirectoryCandidate] = []
    for skill in candidates:
        fields = fields_by_skill_id[skill.id]
        field_scores = {
            field: _field_score(
                query,
                query_terms,
                value,
                weight=_FIELD_WEIGHTS[field],
                document_count=len(candidates),
                document_frequency=document_frequency,
                average_length=average_lengths[field],
            )
            for field, value in fields.items()
        }
        score = round(sum(field_scores.values()), 6)
        if score <= 0:
            continue
        label_terms = _terms(fields["name"]) | _terms(fields["title"]) | _terms(fields["aliases"])
        query_coverage = _query_coverage(
            query_terms,
            terms_by_skill_id[skill.id],
            document_count=len(candidates),
            document_frequency=document_frequency,
        )
        label_coverage = _query_coverage(
            query_terms,
            label_terms,
            document_count=len(candidates),
            document_frequency=document_frequency,
        )
        label_match = _label_match(query, fields)
        negated_query = skill_query_has_negation(query)
        ranked.append(
            SkillDirectoryCandidate(
                match=SkillDirectoryMatch(
                    skill=skill,
                    score=score,
                    reason=_match_reason(query_terms, fields, field_scores),
                ),
                query_coverage=query_coverage,
                label_coverage=label_coverage,
                direct_label_match=label_match and not negated_query,
                negated_query=negated_query,
            )
        )

    ranked.sort(key=lambda item: (-item.match.score, item.match.skill.name, item.match.skill.id))
    return ranked


def match_skill_directory(
    task: str,
    skills: Iterable[SkillDefinition],
    *,
    limit: int,
) -> list[SkillDirectoryMatch]:
    """Rank already-authorized Skills using only their catalog metadata."""
    return [candidate.match for candidate in rank_skill_directory(task, skills) if candidate.accepted][:limit]
