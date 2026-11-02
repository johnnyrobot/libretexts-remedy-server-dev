"""Retention restores original opaque bytes; it never manufactures acceptance."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('retained_handoff', ROOT / 'deploy/stack/retained_handoff.py')


def module():
    value = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(value)
    return value


def fixture(tmp_path):
    parts = tmp_path / 'parts'
    parts.mkdir()
    records = []
    for index, data in enumerate((b'original ', b'ZIP bytes\x00\xff')):
        name = f'handoff.zip.part{index:02d}'
        (parts / name).write_bytes(data)
        records.append({'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    record = tmp_path / 'retention.json'
    record.write_text(json.dumps({'schema': 'remedy-retained-handoff-v1',
        'original': {'bytes': 20, 'sha256': hashlib.sha256(b'original ZIP bytes\x00\xff').hexdigest()},
        'parts': records}))
    return record, parts


def restore(record, parts, output):
    return module().restore(record, parts, output, hashlib.sha256(record.read_bytes()).hexdigest())


def test_restores_exact_original_bytes_without_overwriting(tmp_path):
    record, parts = fixture(tmp_path)
    output = tmp_path / 'restored'
    result = restore(record, parts, output)
    assert result.read_bytes() == b'original ZIP bytes\x00\xff'
    with pytest.raises(FileExistsError):
        restore(record, parts, output)


@pytest.mark.parametrize('damage', ['changed', 'short', 'missing', 'symlink', 'fifo',
    'unsafe-name', 'duplicate', 'wrong-whole', 'wrong-record', 'oversized-record', 'oversized-part'])
def test_refuses_damage_without_publishing_a_complete_zip(tmp_path, damage):
    record, parts = fixture(tmp_path)
    value = json.loads(record.read_bytes())
    part = parts / value['parts'][0]['name']
    if damage == 'changed':
        part.write_bytes(b'changed!!')
    elif damage == 'short':
        part.write_bytes(b'short')
    elif damage == 'missing':
        part.rename(parts / 'removed')
    elif damage == 'symlink':
        part.rename(parts / 'original')
        part.symlink_to(parts / 'original')
    elif damage == 'fifo':
        import os
        part.rename(parts / 'original')
        os.mkfifo(part)
    elif damage == 'unsafe-name':
        value['parts'][0]['name'] = '../outside'
    elif damage == 'duplicate':
        value['parts'][1]['name'] = value['parts'][0]['name']
    elif damage == 'wrong-whole':
        value['original']['sha256'] = '0' * 64
    elif damage == 'oversized-part':
        value['parts'][0]['bytes'] = 1024 ** 3 + 1
    record.write_text(json.dumps(value))
    trusted_hash = hashlib.sha256(record.read_bytes()).hexdigest()
    if damage == 'wrong-record':
        record.write_bytes(record.read_bytes() + b' ')
    elif damage == 'oversized-record':
        record.write_bytes(b' ' * 65537)
    output = tmp_path / 'restored'
    with pytest.raises((ValueError, OSError)):
        module().restore(record, parts, output, trusted_hash)
    assert not (output / 'handoff.zip').exists()


def test_cli_restores_using_independently_pinned_record(tmp_path):
    import subprocess
    import sys
    record, parts = fixture(tmp_path)
    result = subprocess.run([sys.executable, str(ROOT / 'deploy/stack/retained_handoff.py'),
        '--record', str(record), '--record-sha256', hashlib.sha256(record.read_bytes()).hexdigest(),
        '--parts', str(parts), '--output', str(tmp_path / 'restored')], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'restored/handoff.zip').read_bytes() == b'original ZIP bytes\x00\xff'

