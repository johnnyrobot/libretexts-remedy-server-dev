"""One sanitization policy for logs from synthetic product rehearsals."""
from pathlib import Path

SYNTHETIC_CREDENTIALS = (
    'synthetic-server-key', 'synthetic-provider-key', 'synthetic-scanner-key',
    'synthetic-adapt-token', 'synthetic-control-only', 'synthetic-secret',
    'synthetic-key', 'synthetic-user', 'a1' * 32,
)


def write_product_log(path: Path, content: str, sensitive_values=()) -> None:
    for credential in (*SYNTHETIC_CREDENTIALS, *sensitive_values):
        content = content.replace(credential, '[synthetic credential redacted]')
    path.write_text(content[-80000:])


def collect_browser_evidence(work: Path, output: Path, targets, sensitive_values=()) -> None:
    """Allow only known browser outputs; never glob private fixture directories."""
    for target in targets:
        if '/' in target or '\\' in target:
            raise ValueError('invalid evidence target')
        directory = work / ('browser-' + target)
        for name in ('synthetic-review.png', 'synthetic-stale.png', 'synthetic-failure.png', 'browser-error.json'):
            source = directory / name
            if source.is_symlink() or not source.is_file():
                continue
            destination = output / (directory.name + '-' + name)
            if source.suffix == '.json':
                write_product_log(destination, source.read_text(), sensitive_values)
            else:
                destination.write_bytes(source.read_bytes())
