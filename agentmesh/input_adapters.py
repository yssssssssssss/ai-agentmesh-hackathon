from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_RUN_INPUT_BYTES = 20 * 1024 * 1024
MAX_RUN_INPUT_TOTAL_BYTES = 40 * 1024 * 1024
MAX_RUN_INPUT_ARTIFACTS = 20
MAX_NORMALIZED_INPUT_CHARS = 100_000
MAX_RUN_NORMALIZED_INPUT_CHARS = 200_000
MAX_NODE_INPUT_BYTES = 100_000
MAX_CSV_ROWS = 10_000
MAX_CSV_COLUMNS = 128
MAX_CSV_CELL_CHARS = 10_000


class RunInputAdapterError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ParsedRunInput:
    adapter_id: str
    adapter_version: str
    media_type: str
    normalized_text: str
    structured_payload: dict[str, Any] | None


def _decode_utf8(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise RunInputAdapterError("input_encoding_invalid") from error


def _validate_text_budget(text: str) -> None:
    if len(text) > MAX_NORMALIZED_INPUT_CHARS:
        raise RunInputAdapterError("input_content_too_large")


def _media_type_for(file_name: str, declared_media_type: str) -> str:
    suffix = Path(file_name).suffix.lower()
    expected = {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".csv": "text/csv",
    }.get(suffix)
    if expected is None:
        raise RunInputAdapterError("input_media_type_unsupported")
    normalized_declared = declared_media_type.split(";", 1)[0].strip().lower()
    if normalized_declared not in {expected, "application/octet-stream", ""}:
        raise RunInputAdapterError("input_media_type_mismatch")
    return expected


def adapter_identity_for_media_type(media_type: str) -> tuple[str, str] | None:
    if media_type in {"text/plain", "text/markdown"}:
        return "text", "1"
    if media_type == "text/csv":
        return "csv", "1"
    return None


def parse_run_input(
    *,
    file_name: str,
    declared_media_type: str,
    content: bytes,
    accepted_media_types: list[str],
    required_columns: list[str] | None = None,
) -> ParsedRunInput:
    if len(content) > MAX_RUN_INPUT_BYTES:
        raise RunInputAdapterError("input_file_too_large")
    media_type = _media_type_for(file_name, declared_media_type)
    if media_type not in accepted_media_types:
        raise RunInputAdapterError("input_media_type_unsupported")
    text = _decode_utf8(content)
    _validate_text_budget(text)
    if media_type in {"text/plain", "text/markdown"}:
        if not text.strip():
            raise RunInputAdapterError("input_content_empty")
        return ParsedRunInput(
            adapter_id="text",
            adapter_version="1",
            media_type=media_type,
            normalized_text=text.replace("\r\n", "\n").replace("\r", "\n"),
            structured_payload=None,
        )

    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as error:
        raise RunInputAdapterError("input_csv_shape_invalid") from error
    if not rows:
        raise RunInputAdapterError("input_csv_header_invalid")
    header = rows[0]
    if not header or any(not column.strip() for column in header):
        raise RunInputAdapterError("input_csv_header_invalid")
    normalized_header = [column.strip() for column in header]
    if len(set(normalized_header)) != len(normalized_header):
        raise RunInputAdapterError("input_csv_duplicate_header")
    if len(normalized_header) > MAX_CSV_COLUMNS:
        raise RunInputAdapterError("input_csv_shape_invalid")
    data_rows = rows[1:]
    if len(data_rows) > MAX_CSV_ROWS:
        raise RunInputAdapterError("input_csv_shape_invalid")
    for row in data_rows:
        if len(row) != len(normalized_header):
            raise RunInputAdapterError("input_csv_shape_invalid")
        if any(len(cell) > MAX_CSV_CELL_CHARS for cell in row):
            raise RunInputAdapterError("input_csv_cell_too_large")
    missing_columns = sorted(set(required_columns or []) - set(normalized_header))
    if missing_columns:
        raise RunInputAdapterError("input_csv_schema_mismatch")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(normalized_header)
    writer.writerows(data_rows)
    normalized_text = output.getvalue()
    _validate_text_budget(normalized_text)
    return ParsedRunInput(
        adapter_id="csv",
        adapter_version="1",
        media_type=media_type,
        normalized_text=normalized_text,
        structured_payload={
            "columns": normalized_header,
            "row_count": len(data_rows),
            "column_count": len(normalized_header),
            "rows": data_rows,
        },
    )
