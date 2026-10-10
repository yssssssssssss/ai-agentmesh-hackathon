"""Explicit versioned model prices; integer estimates are not Provider invoices."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from agentmesh.canonical_json import strict_json_loads
from agentmesh.memory_context.request_budget import ModelAdmissionError


class RunModelPriceV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    version: str = Field(min_length=1, max_length=80)
    input_micros_per_million_tokens: int = Field(ge=0, le=1000000000000)
    output_micros_per_million_tokens: int = Field(ge=0, le=1000000000000)
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None

    @model_validator(mode='after')
    def ordered_validity(self) -> RunModelPriceV1:
        if self.valid_from is not None and self.valid_until is not None and self.valid_from >= self.valid_until:
            raise ValueError('price validity interval is empty')
        return self

    def active_at(self, at: datetime) -> bool:
        return ((self.valid_from is None or self.valid_from <= at)
                and (self.valid_until is None or at < self.valid_until))

    def estimate_micros(self, input_tokens: int, output_tokens: int) -> int:
        numerator = input_tokens * self.input_micros_per_million_tokens + output_tokens * self.output_micros_per_million_tokens
        # Round each request upwards to a millionth of its declared currency.
        # No binary floating point, conversion between currencies or inferred rate.
        return (numerator + 999999) // 1000000


class RunModelPriceBookV1(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    prices: dict[Annotated[str, Field(min_length=1, max_length=256)], RunModelPriceV1] = Field(default_factory=dict, max_length=64)

    @classmethod
    def from_env(cls) -> RunModelPriceBookV1:
        raw = os.getenv('AGENTMESH_RUN_MODEL_PRICES_JSON', '').strip()
        if not raw:
            return cls()
        try:
            if len(raw.encode('utf-8')) > 65536 or not isinstance(strict_json_loads(raw), dict):
                raise ValueError
            return cls.model_validate_json('{"prices":' + raw + '}')
        except (TypeError, ValueError) as error:
            raise ModelAdmissionError('run_model_price_configuration_invalid') from error
