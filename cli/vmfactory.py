"""Read-only, paired-phone telemetry for an explicitly configured Factory project."""
import json
from pathlib import Path
from .api import ApiError


def factory_request(method, path, query, body, directory):
    if not path.startswith('/vmfactory/'):
        return None
    if method != 'GET' or path != '/vmfactory/snapshot' or query or body:
        raise ValueError('Unsupported Factory request.')
    config = Path(directory) / 'vmfactory.json'
    if not config.exists():
        raise ApiError('This Mac has no Factory project connected.', 404)
    if config.is_symlink() or config.stat().st_mode & 0o077:
        raise ApiError('Factory connection configuration must be private.', 503)
    root = Path(json.loads(config.read_text())['project']).expanduser().resolve()
    support = Path.home() / 'Library/Application Support/VFactory'
    result = {'schema': 'vmfactory.mobile-snapshot/1'}
    for key, path in {
        'tasks': root / 'runtime/engine/vfactory/tasks.json',
        'roster': root / 'runtime/engine/vfactory/crew.json',
        'inventory': root / 'runtime/engine/vfactory/scene-inventory.json',
        'crew': support / 'crew-telemetry.json',
        'worker': support / 'worker-status.json',
        'discoveries': support / 'mobile-discoveries.json',
    }.items():
        if path.is_file() and path.stat().st_size <= 4 * 1024 * 1024:
            result[key] = json.loads(path.read_text())
    return result
