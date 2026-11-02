"""Reassemble retained original ZIP bytes offline; never reseal or authorize use.

Python 3.11+, Linux/macOS. Obtain the record digest from the reviewed source,
not from the download directory. No network, credentials or archive extraction.
Failures retain a private incomplete directory; retry with a new output path.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regular_file(path):
    stream = os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb')
    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
        stream.close()
        raise ValueError('regular input file required')
    return stream


def restore(record_path, parts_directory, output_directory, record_sha256):
    """Verify trusted inventory, each part, and whole ZIP before publishing it."""
    require(re.fullmatch(r'[a-f0-9]{64}', record_sha256), 'record SHA256 required')
    with regular_file(record_path) as stream:
        raw = stream.read(65537)
    require(len(raw) <= 65536 and hashlib.sha256(raw).hexdigest() == record_sha256,
            'retention record digest mismatch or oversized record')
    record = json.loads(raw)
    require(isinstance(record, dict) and record.get('schema') == 'remedy-retained-handoff-v1',
            'unsupported retention record')
    original, parts = record['original'], record['parts']
    require(isinstance(original, dict) and type(original.get('bytes')) is int and
            0 < original['bytes'] <= 16 * 1024 ** 3 and
            isinstance(original.get('sha256'), str) and re.fullmatch(r'[a-f0-9]{64}', original['sha256']),
            'invalid original byte count or digest')
    require(isinstance(parts, list) and 1 <= len(parts) <= 16, 'one to sixteen ordered parts required')
    names = set()
    for part in parts:
        require(isinstance(part, dict) and isinstance(part.get('name'), str) and
                re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}', part['name']) and
                part['name'] not in names and type(part.get('bytes')) is int and
                0 < part['bytes'] <= 1024 ** 3 and isinstance(part.get('sha256'), str) and
                re.fullmatch(r'[a-f0-9]{64}', part['sha256']), 'invalid or duplicate part')
        names.add(part['name'])
    require(sum(part['bytes'] for part in parts) == original['bytes'], 'part sizes differ from original')
    output = Path(output_directory)
    output.mkdir(mode=0o700)
    partial = output / 'handoff.zip.partial'
    complete = output / 'handoff.zip'
    whole = hashlib.sha256()
    with partial.open('xb') as outgoing:
        os.chmod(partial, 0o600)
        for part in parts:
            digest = hashlib.sha256()
            with regular_file(Path(parts_directory) / part['name']) as incoming:
                require(os.fstat(incoming.fileno()).st_size == part['bytes'], 'part size mismatch: ' + part['name'])
                remaining = part['bytes']
                while remaining:
                    chunk = incoming.read(min(1024 ** 2, remaining))
                    require(chunk, 'truncated part: ' + part['name'])
                    remaining -= len(chunk)
                    digest.update(chunk)
                    whole.update(chunk)
                    outgoing.write(chunk)
                require(not incoming.read(1), 'part grew: ' + part['name'])
            require(digest.hexdigest() == part['sha256'], 'part digest mismatch: ' + part['name'])
        require(whole.hexdigest() == original['sha256'], 'original ZIP digest mismatch')
        outgoing.flush()
        os.fsync(outgoing.fileno())
    # Exclusive publication; an unexpected preexisting destination is preserved.
    os.link(partial, complete)
    return complete


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', required=True, type=Path)
    parser.add_argument('--record-sha256', required=True)
    parser.add_argument('--parts', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path, help='new private directory; existing paths refuse')
    args = parser.parse_args()
    try:
        path = restore(args.record, args.parts, args.output, args.record_sha256)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f'Retention refused: {error}. Preserve incomplete output; retry in a new directory.\n')
    print(path)
    print('Original ZIP integrity verified. Follow its original seal/import instructions; no deployment acceptance granted.')


if __name__ == '__main__':
    main()
