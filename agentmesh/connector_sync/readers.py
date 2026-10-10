from __future__ import annotations

import os
import re
import stat
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from math import isfinite
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import httpx

from agentmesh.canonical_json import canonical_json_bytes, canonical_json_sha256, strict_json_loads
from agentmesh.connector_sync.contracts import ConnectorObservationV1, ConnectorPageV1, ConnectorSyncError
from agentmesh.models import now_utc


def retry_after_seconds(value: str) -> float:
    if not value or len(value) > 128:
        return 0
    try:
        delay = float(value)
    except ValueError:
        try:
            at = parsedate_to_datetime(value)
            if at.utcoffset() is None:
                return 0
            delay = (at - now_utc()).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return 0
    return max(0, delay) if isfinite(delay) else 0


class RepoDocsReader:
    provider = 'repo_docs'
    supports_incremental = False

    def __init__(self, root: Path, *, namespace: str, page_size: int = 5):
        self.root = root.resolve()
        self.namespace = namespace
        if not namespace or len(namespace) > 200 or type(page_size) is not int or not 1 <= page_size <= 20:
            raise ConnectorSyncError('connector_configuration_invalid', status_code=422)
        self.page_size = page_size

    def configuration_hash(self) -> str:
        return canonical_json_sha256({'provider': self.provider, 'root': str(self.root),
                                     'namespace': self.namespace, 'page_size': self.page_size})

    def read_page(self, position: str | None, *, since: datetime | None = None) -> ConnectorPageV1:
        if not self.root.is_dir():
            raise ConnectorSyncError('connector_root_unavailable', status_code=503)
        files, pending, visited = [], [self.root], 0
        try:
            while pending:
                with os.scandir(pending.pop()) as entries:
                    for entry in entries:
                        visited += 1
                        if visited > 1000:
                            raise ConnectorSyncError('connector_inventory_limit', status_code=422)
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif Path(entry.name).suffix.lower() in {'.md', '.txt', '.rst'}:
                            relative = Path(entry.path).relative_to(self.root).as_posix()
                            if len(relative) > 300:
                                raise ConnectorSyncError('connector_path_invalid', status_code=422)
                            files.append(relative)
        except OSError:
            raise ConnectorSyncError('connector_root_unavailable', status_code=503) from None
        remaining = [name for name in sorted(files) if position is None or name > position]
        selected = remaining[:self.page_size]
        observations = []
        for name in selected:
            text = self._read(name)
            digest = sha256(text.encode('utf-8')).hexdigest()
            observations.append(ConnectorObservationV1(external_id=name, title=name,
                reference=f'repo-doc://{quote(self.namespace, safe="")}/{quote(name)}',
                version='repo_text_v1:' + digest, text=text))
        return ConnectorPageV1(observations=observations,
                               next_position=selected[-1] if len(remaining) > len(selected) else None)

    def _read(self, relative: str) -> str:
        flags = os.O_RDONLY | os.O_NOFOLLOW
        descriptors = []
        try:
            descriptor = os.open(self.root, flags | os.O_DIRECTORY)
            descriptors.append(descriptor)
            parts = Path(relative).parts
            for part in parts[:-1]:
                descriptor = os.open(part, flags | os.O_DIRECTORY, dir_fd=descriptor)
                descriptors.append(descriptor)
            descriptor = os.open(parts[-1], flags | os.O_NONBLOCK, dir_fd=descriptor)
            with os.fdopen(descriptor, 'rb') as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise ConnectorSyncError('connector_document_unavailable', status_code=503)
                raw = handle.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ConnectorSyncError('connector_document_too_large', status_code=422)
            return raw.decode('utf-8')
        except (OSError, UnicodeError):
            raise ConnectorSyncError('connector_document_unavailable', status_code=503) from None
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)


class GitHubIssuesReader:
    """Bounded read-only observations; a closed Issue remains an observable source."""

    provider = 'github_issues'
    supports_incremental = True

    def __init__(self, repository: str, *, token: str | None = None, credential_version: str = 'anonymous',
                 client: httpx.Client | None = None):
        if (not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}', repository)
            or len(repository) > 200 or any(part in {'.', '..'} for part in repository.split('/'))
            or not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', credential_version)
            or (token is not None and (not token or credential_version == 'anonymous'))):
            raise ConnectorSyncError('connector_configuration_invalid', status_code=422)
        self.namespace, self._token = repository, token
        self._credential_version, self._client = credential_version, client

    def configuration_hash(self) -> str:
        return canonical_json_sha256({'provider': self.provider, 'repository': self.namespace,
            'credential_version': self._credential_version, 'page_size': 20, 'api_version': '2026-03-10'})

    def read_page(self, position: str | None, *, since: datetime | None = None) -> ConnectorPageV1:
        parameters = {'page': '1'}
        if position:
            if position.isdecimal():
                parameters['page'] = position
            else:
                parsed = parse_qs(position, keep_blank_values=True)
                if set(parsed) != {'page', 'after'} or any(len(value) != 1 for value in parsed.values()):
                    raise ConnectorSyncError('connector_position_invalid', status_code=422)
                parameters = {key: value[0] for key, value in parsed.items()}
        page = parameters['page']
        if (not re.fullmatch(r'[1-9][0-9]{0,3}', page) or int(page) > 1000
            or ('after' in parameters and not re.fullmatch(r'[A-Za-z0-9_+/=-]{1,256}', parameters['after']))):
            raise ConnectorSyncError('connector_position_invalid', status_code=422)
        if since is not None:
            if since.utcoffset() is None:
                raise ConnectorSyncError('connector_position_invalid', status_code=422)
            parameters['since'] = since.astimezone(UTC).isoformat(timespec='seconds').replace('+00:00', 'Z')
        if self._client is not None:
            return self._read_page(self._client, parameters)
        with httpx.Client() as client:
            return self._read_page(client, parameters)

    def _read_page(self, client: httpx.Client, parameters: dict[str, str]) -> ConnectorPageV1:
        path = f'/repos/{self.namespace}/issues'
        headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2026-03-10'}
        if self._token:
            headers['Authorization'] = 'Bearer ' + self._token
        try:
            with client.stream('GET', 'https://api.github.com' + path, headers=headers,
                params={'state': 'all', 'sort': 'updated', 'direction': 'asc', 'per_page': 20, **parameters},
                follow_redirects=False, timeout=10) as response:
                wait = retry_after_seconds(response.headers.get('Retry-After', ''))
                if response.status_code == 429 or (response.status_code == 403 and (
                    'Retry-After' in response.headers or response.headers.get('X-RateLimit-Remaining') == '0')):
                    reset = response.headers.get('X-RateLimit-Reset', '')
                    if response.headers.get('X-RateLimit-Remaining') == '0' and re.fullmatch(r'[0-9]{1,12}', reset):
                        wait = max(wait, int(reset) - now_utc().timestamp())
                    raise ConnectorSyncError('connector_rate_limited', status_code=503, retryable=True,
                                             retry_after=max(5, wait) if wait > 0 else 60)
                if response.status_code in {401, 403, 404}:
                    raise ConnectorSyncError('connector_access_unavailable', status_code=503)
                if response.status_code != 200:
                    raise ConnectorSyncError('connector_provider_unavailable', status_code=503,
                        retryable=response.status_code >= 500, retry_after=wait)
                raw = bytearray()
                for chunk in response.iter_bytes(chunk_size=65536):
                    if len(raw) + len(chunk) > 2 * 1024 * 1024:
                        raise ConnectorSyncError('connector_response_too_large', status_code=422)
                    raw.extend(chunk)
                records = strict_json_loads(raw)
                if not isinstance(records, list) or len(records) > 20:
                    raise ConnectorSyncError('connector_response_invalid', status_code=503)
                next_position = self._next_position(response, path, parameters)
                observations = [self._observation(item) for item in records
                                if isinstance(item, dict) and 'pull_request' not in item]
                if any(not isinstance(item, dict) for item in records):
                    raise ConnectorSyncError('connector_response_invalid', status_code=503)
                return ConnectorPageV1(observations=observations, next_position=next_position)
        except httpx.HTTPError:
            raise ConnectorSyncError('connector_provider_unavailable', status_code=503, retryable=True) from None
        except (ValueError, TypeError, KeyError):
            raise ConnectorSyncError('connector_response_invalid', status_code=503) from None

    @staticmethod
    def _next_position(response: httpx.Response, path: str, parameters: dict[str, str]) -> str | None:
        if len(response.headers.get('Link', '')) > 8192:
            raise ConnectorSyncError('connector_pagination_invalid', status_code=503)
        link = response.links.get('next')
        if not link:
            return None
        url = urlsplit(link['url'])
        query = parse_qs(url.query, keep_blank_values=True)
        page = parameters['page']
        expected = {'state': 'all', 'sort': 'updated', 'direction': 'asc', 'per_page': '20',
                    'page': str(int(page) + 1)}
        if 'since' in parameters:
            expected['since'] = parameters['since']
        canonical_path = re.fullmatch(r'/repositories/[1-9][0-9]{0,19}/issues', url.path)
        after = query.pop('after', None)
        if (url.scheme != 'https' or url.netloc != 'api.github.com'
            or (url.path != path and canonical_path is None) or url.fragment
            or 'page' not in query or int(page) >= 1000
            or (after is not None and (len(after) != 1 or not re.fullmatch(r'[A-Za-z0-9_+/=-]{1,256}', after[0])))
            or any(key not in expected or value != [expected[key]] for key, value in query.items())):
            raise ConnectorSyncError('connector_pagination_invalid', status_code=503)
        # Only carry validated positions; every request uses the configured repository URL.
        return urlencode({'page': expected['page'], 'after': after[0]}) if after else expected['page']

    def _observation(self, item: dict) -> ConnectorObservationV1:
        number, title, body = item['number'], item['title'], item.get('body')
        if body is None:
            body = ''
        updated = item['updated_at']
        if (type(number) is not int or not 1 <= number <= 2147483647
            or not isinstance(title, str) or not title or len(title) > 300
            or not isinstance(body, str) or len(body.encode('utf-8')) > 1024 * 1024
            or item['state'] not in {'open', 'closed'} or not isinstance(updated, str) or len(updated) > 64
            or datetime.fromisoformat(updated).utcoffset() is None):
            raise ConnectorSyncError('connector_response_invalid', status_code=503)
        reference = f'https://github.com/{self.namespace}/issues/{number}'
        if item['html_url'] != reference:
            raise ConnectorSyncError('connector_response_invalid', status_code=503)
        normalized = {'number': number, 'title': title, 'body': body, 'state': item['state'],
            'updated_at': updated, 'labels': self._names(item.get('labels', []), 'name'),
            'assignees': self._names(item.get('assignees', []), 'login')}
        text = canonical_json_bytes(normalized).decode('utf-8')
        if len(text.encode('utf-8')) > 1024 * 1024:
            raise ConnectorSyncError('connector_response_too_large', status_code=422)
        return ConnectorObservationV1(external_id=f'issue:{number}', title=title, reference=reference,
            version=f'github_issue_v1:{updated}:' + sha256(text.encode('utf-8')).hexdigest(), text=text)

    @staticmethod
    def _names(items: list, field: str) -> list[str]:
        if not isinstance(items, list) or len(items) > 100:
            raise ConnectorSyncError('connector_response_invalid', status_code=503)
        names = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get(field), str) or not 1 <= len(item[field]) <= 100:
                raise ConnectorSyncError('connector_response_invalid', status_code=503)
            names.append(item[field])
        return sorted(set(names))
