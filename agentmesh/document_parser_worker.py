"""Fixed parser entry point. No app/store/runtime imports or inherited credentials."""
from __future__ import annotations

import json
import os
import resource
import sys
from pathlib import Path


def _set_limits() -> None:
    for key, ceiling in [(resource.RLIMIT_CPU, 90), (resource.RLIMIT_FSIZE, 32 * 1024 * 1024),
                         (resource.RLIMIT_NOFILE, 128), (resource.RLIMIT_CORE, 0)]:
        _soft, hard = resource.getrlimit(key)
        limit = ceiling if hard == resource.RLIM_INFINITY else min(ceiling, hard)
        resource.setrlimit(key, (limit, limit))
    # Darwin rejects this RLIMIT_AS ceiling; RSS of the process tree is still
    # monitored by the parent on both supported platforms, with a 100ms interval.
    if sys.platform.startswith('linux'):
        _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        ceiling = 1024 * 1024 * 1024
        limit = ceiling if hard == resource.RLIM_INFINITY else min(ceiling, hard)
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))


def main() -> None:
    os.umask(0o077)
    try:
        _set_limits()
    except (OSError, ValueError):
        Path('output.json').write_text('{"error":"document_parser_resource_limits_unavailable"}')
        return
    from agentmesh.documents import (
        CompositeDocumentParser,
        DocumentIngestionRequest,
        DocumentParseError,
        UnsupportedDocumentTypeError,
        validate_parsed_limits,
    )

    try:
        metadata = json.loads(Path('request.json').read_bytes())
        with Path('input.bin').open('rb') as stream:
            content = stream.read(20 * 1024 * 1024 + 1)
        if len(content) > 20 * 1024 * 1024:
            raise DocumentParseError('document_parser_failed')
        parsed = CompositeDocumentParser().parse(DocumentIngestionRequest(**metadata, content=content))
        validate_parsed_limits(parsed)
        result = {'result': parsed.model_dump(mode='json')}
    except UnsupportedDocumentTypeError:
        result = {'error': 'document_type_unsupported'}
    except UnicodeDecodeError:
        result = {'error': 'document_text_encoding_invalid'}
    except DocumentParseError as error:
        result = {'error': str(error)}
    except MemoryError:
        result = {'error': 'document_parser_memory_exceeded'}
    except Exception:
        result = {'error': 'document_parser_failed'}
    encoded = json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(encoded) > 2 * 1024 * 1024:
        encoded = b'{"error":"document_parser_output_too_large"}'
    Path('output.json').write_bytes(encoded)


if __name__ == '__main__':
    main()
