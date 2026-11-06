from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from agentmesh.connector_sync.contracts import ConnectorSyncError
from agentmesh.connector_sync.readers import GitHubIssuesReader


@pytest.mark.parametrize('status', [429, 503])
def test_retryable_responses_preserve_provider_wait_without_exposing_response_details(status):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status,
        headers={'Retry-After': '120'}, json={'message': 'private-provider-diagnostic'}))) as client:
        reader = GitHubIssuesReader('example/pilot', client=client)
        with pytest.raises(ConnectorSyncError) as caught:
            reader.read_page(None)
    assert caught.value.retryable is True and caught.value.retry_after == 120
    assert 'private-provider' not in str(caught.value)


def test_github_reader_paginates_read_only_issues_and_excludes_pull_requests():
    def respond(request):
        assert request.method == 'GET'
        assert request.url.host == 'api.github.com'
        assert request.url.path == '/repos/example/pilot/issues'
        assert request.headers['X-GitHub-Api-Version'] == '2026-03-10'
        assert request.url.params['state'] == 'all'
        if request.url.params['page'] == '2':
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[{
            'number': 14, 'title': 'Resolve the blocked build', 'body': 'Waiting for the dependency.',
            'state': 'open', 'updated_at': '2026-10-07T00:00:00Z',
            'html_url': 'https://github.com/example/pilot/issues/14',
            'labels': [{'name': 'ready-for-agent'}], 'assignees': [{'login': 'developer'}],
        }, {'number': 15, 'pull_request': {'url': 'ignored'}}], headers={
            'Link': '<https://api.github.com/repos/example/pilot/issues?page=2&per_page=20>; rel="next"'})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        reader = GitHubIssuesReader('example/pilot', client=client)
        first = reader.read_page(None)
        assert first.next_position == '2' and len(first.observations) == 1
        observation = first.observations[0]
        assert observation.external_id == 'issue:14'
        assert observation.reference == 'https://github.com/example/pilot/issues/14'
        body = json.loads(observation.text)
        assert body['state'] == 'open' and body['body'] == 'Waiting for the dependency.'
        assert body['labels'] == ['ready-for-agent'] and body['assignees'] == ['developer']
        assert reader.read_page(first.next_position).next_position is None


def test_github_reader_rejects_false_body_instead_of_inventing_empty_evidence():
    issue = {'number': 14, 'title': 'Blocked build', 'body': False, 'state': 'open',
             'updated_at': '2026-10-07T00:00:00Z', 'html_url': 'https://github.com/example/pilot/issues/14'}
    with (httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[issue]))) as client,
          pytest.raises(ConnectorSyncError, match='connector_response_invalid')):
        GitHubIssuesReader('example/pilot', client=client).read_page(None)


@pytest.mark.parametrize('next_url', [
    'https://attacker.invalid/repos/example/pilot/issues?page=2',
    'http://api.github.com/repos/example/pilot/issues?page=2',
    'https://api.github.com/repos/other/pilot/issues?page=2',
    'https://api.github.com/repos/example/pilot/issues?page=1',
    'https://api.github.com/repos/example/pilot/issues?page=2&page=3',
    'https://api.github.com/repos/example/pilot/issues?page=2&state=open',
])
def test_github_reader_rejects_untrusted_or_inconsistent_pagination(next_url):
    response = httpx.Response(200, json=[], headers={'Link': f'<{next_url}>; rel="next"'})
    with (httpx.Client(transport=httpx.MockTransport(lambda request: response)) as client,
          pytest.raises(ConnectorSyncError, match='connector_pagination_invalid')):
        GitHubIssuesReader('example/pilot', token='synthetic-secret', credential_version='pilot_v1',
                           client=client).read_page(None)


@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
def test_github_failure_exposes_only_a_static_error_code(status):
    response = httpx.Response(status, text='synthetic-secret upstream diagnostic',
                              headers={'Location': 'https://attacker.invalid/'})
    with (httpx.Client(transport=httpx.MockTransport(lambda request: response)) as client,
          pytest.raises(ConnectorSyncError) as caught):
        GitHubIssuesReader('example/pilot', client=client).read_page(None)
    assert caught.value.code in {'connector_access_unavailable', 'connector_provider_unavailable', 'connector_rate_limited'}
    assert caught.value.retryable is (status in {429, 500})
    assert 'synthetic-secret' not in str(caught.value)


def test_primary_limit_waits_until_reset_and_headerless_limit_waits_at_least_a_minute(monkeypatch):
    from agentmesh.connector_sync import readers

    at = datetime(2026, 10, 7, tzinfo=UTC)
    monkeypatch.setattr(readers, 'now_utc', lambda: at)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(403,
        headers={'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': str(int(at.timestamp()) + 600)}))) as client:
        with pytest.raises(ConnectorSyncError) as caught:
            GitHubIssuesReader('example/pilot', client=client).read_page(None)
        assert caught.value.code == 'connector_rate_limited' and caught.value.retry_after == 600
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(429))) as client:
        with pytest.raises(ConnectorSyncError) as caught:
            GitHubIssuesReader('example/pilot', client=client).read_page(None)
        assert caught.value.retry_after == 60


def test_github_response_limit_is_enforced_before_parsing():
    response = httpx.Response(200, content=b' ' * (2 * 1024 * 1024 + 1))
    with (httpx.Client(transport=httpx.MockTransport(lambda request: response)) as client,
          pytest.raises(ConnectorSyncError, match='connector_response_too_large')):
        GitHubIssuesReader('example/pilot', client=client).read_page(None)


def test_github_canonical_repository_link_preserves_opaque_cursor_on_fixed_repository_url():
    def respond(request):
        assert request.url.path == '/repos/example/pilot/issues'
        if request.url.params['page'] == '2':
            assert request.url.params['after'] == 'Y3Vyc29yOnYyOg=='
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[], headers={'Link':
            '<https://api.github.com/repositories/123/issues?state=all&sort=updated&direction=asc&per_page=20'
            '&page=2&after=Y3Vyc29yOnYyOg%3D%3D>; rel="next"'})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        reader = GitHubIssuesReader('example/pilot', client=client)
        next_position = reader.read_page(None).next_position
        assert next_position is not None
        assert reader.read_page(next_position).next_position is None


def test_github_incremental_pages_keep_the_same_since_boundary():
    since = datetime(2026, 10, 7, tzinfo=UTC)

    def respond(request):
        assert request.url.params['since'] == '2026-10-07T00:00:00Z'
        if request.url.params['page'] == '2':
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[], headers={'Link':
            '<https://api.github.com/repositories/123/issues?page=2&per_page=20'
            '&since=2026-10-07T00%3A00%3A00Z>; rel="next"'})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        reader = GitHubIssuesReader('example/pilot', client=client)
        first = reader.read_page(None, since=since)
        assert reader.read_page(first.next_position, since=since).next_position is None
