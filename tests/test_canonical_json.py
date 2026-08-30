from decimal import Decimal

import pytest

from agentmesh.canonical_json import canonical_json_bytes, canonical_json_sha256, strict_json_loads


def test_canonical_json_preserves_decimal_values_and_rejects_ambiguous_input() -> None:
    value = {"z": Decimal("1.2300"), "negative_zero": Decimal("-0"), "nested": [2, Decimal("1E+3")]}

    encoded = canonical_json_bytes(value)

    assert encoded == b'{"negative_zero":0,"nested":[2,1000],"z":1.23}'
    assert canonical_json_sha256(value) == canonical_json_sha256(strict_json_loads(encoded))
    with pytest.raises(TypeError, match="binary floating point"):
        canonical_json_bytes({"score": 0.5})
    with pytest.raises(ValueError, match="duplicate normalized keys"):
        strict_json_loads('{"e\u0301": 1, "é": 2}')
