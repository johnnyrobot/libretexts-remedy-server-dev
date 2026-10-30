"""Fetch or verify the reviewed veraPDF installer before executing any of it."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def verify(path, pin):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != pin['sizeBytes']:
        raise ValueError('veraPDF installer integrity mismatch')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != pin['sha256']:
        raise ValueError('veraPDF installer integrity mismatch')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    pin = json.loads((ROOT / 'tools/build-inputs/verapdf-installer.json').read_text())
    if args.destination.is_symlink():
        raise ValueError('veraPDF installer destination must not be a symlink')
    if args.verify_only or args.destination.exists():
        verify(args.destination, pin)
        print('Reviewed veraPDF installer verified')
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=args.destination.parent, prefix='.verapdf-', delete=False) as output:
            temporary = Path(output.name)
            size = 0
            deadline = time.monotonic() + 120
            with urlopen(pin['url'], timeout=30) as response:
                while True:
                    if time.monotonic() > deadline:
                        raise TimeoutError('veraPDF installer download deadline exceeded')
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > pin['sizeBytes']:
                        raise ValueError('veraPDF installer exceeds reviewed size')
                    output.write(chunk)
        verify(temporary, pin)
        temporary.replace(args.destination)
        print('Reviewed veraPDF installer fetched and verified')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)  # only this invocation's temporary file


if __name__ == '__main__':
    main()
