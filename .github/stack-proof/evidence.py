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
