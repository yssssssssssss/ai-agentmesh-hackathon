from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_dataset(tmp_path, dataset):
    path = tmp_path / 'cases.json'
    path.write_text(json.dumps(dataset))
    return subprocess.run([sys.executable, str(ROOT / 'eval/run_memory_eval.py'), '--dataset', str(path)],
                          cwd=ROOT, capture_output=True, text=True, timeout=120, check=False)


def test_frozen_memory_replay_is_offline_and_does_not_touch_host_database(tmp_path):
    host_database = tmp_path / 'host.sqlite3'
    host_database.write_bytes(b'keep this database unchanged')
    result = subprocess.run(
        [sys.executable, str(ROOT / 'eval/run_memory_eval.py')], cwd=ROOT,
        env={**os.environ, 'AGENTMESH_DB_PATH': str(host_database)}, capture_output=True, text=True,
        timeout=120, check=False,
    )
    assert host_database.read_bytes() == b'keep this database unchanged'
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(result.stdout)
    assert report['case_count'] == report['passed_count'] == 120
    assert set(report['by_category'].values()) == {20} and len(report['by_category']) == 6
    assert report['model_tokens'] == 0 and report['real_model_quality'] is False
    assert report['answer_correctness'] is None
    assert report['fact_extraction_quality'] is None
    assert len(report['dataset_sha256']) == 64


def test_memory_replay_rejects_a_wrong_literal_expectation(tmp_path):
    dataset = json.loads((ROOT / 'eval/memory_cases_v1.json').read_text())
    dataset['cases'][0]['expected']['values'] = ['an independently wrong answer']
    result = _run_dataset(tmp_path, dataset)
    assert result.returncode == 1, result.stderr + result.stdout
    report = json.loads(result.stdout)
    assert report['passed_count'] == 119
    assert report['cases'][0]['mismatches'] == ['values']


def test_memory_replay_rejects_duplicate_holdout_ids(tmp_path):
    dataset = json.loads((ROOT / 'eval/memory_cases_v1.json').read_text())
    dataset['cases'][-1] = dataset['cases'][0]
    result = _run_dataset(tmp_path, dataset)
    assert result.returncode == 2 and 'dataset_case_distribution_invalid' in result.stderr


def test_memory_replay_rejects_a_non_object_dataset(tmp_path):
    result = _run_dataset(tmp_path, ['invalid fixture'])
    assert result.returncode == 2 and result.stderr.strip() == 'dataset_case_distribution_invalid'


def test_real_memory_evaluation_requires_explicit_model_batch_and_budget():
    result = subprocess.run([sys.executable, str(ROOT / 'eval/run_memory_eval.py'), '--mode', 'real'],
                            cwd=ROOT, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 2
    assert result.stderr.strip() == 'real_evaluation_requires_explicit_model_batch_and_budget'


def test_unconfigured_real_model_returns_blocked_without_fabricating_quality(tmp_path):
    dataset = json.loads((ROOT / 'eval/memory_cases_v1.json').read_text())
    categories = dict.fromkeys({case['category'] for case in dataset['cases']}, 0)
    selected = []
    for case in dataset['cases']:
        if categories[case['category']] < 4:
            selected.append(case['id'])
            categories[case['category']] += 1
    path = tmp_path / 'pilot.json'
    result = subprocess.run([sys.executable, str(ROOT / 'eval/run_memory_eval.py'), '--mode', 'real',
        '--model', 'offline_fixture_unconfigured_8971', '--case-ids', ','.join(selected), '--token-cap', '500000',
        '--output', str(path)], cwd=ROOT, capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 2, result.stderr + result.stdout
    report = json.loads(path.read_text())
    assert report['status'] == 'blocked' and report['error_code'] == 'model_not_configured'
    assert report['real_model_quality'] is False and report['model_tokens'] == 0 and report['cases'] == []
    assert 'FORBIDDEN_PEER_VALUE' not in path.read_text()
