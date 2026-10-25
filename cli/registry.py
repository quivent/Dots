"""Private local references to actual Dots; no model runtime or inference loop."""
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import uuid

from .api import ApiError


class Registry:
    def __init__(self, launcher):
        from .main import Launcher
        self.guard = Launcher(runtime=launcher.runtime / 'agents')
        self.path = self.guard.runtime / 'registry.json'

    def read(self):
        if not self.path.exists():
            return {'version': 1, 'agents': [], 'selected': None}
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or data.get('version') != 1
                or not isinstance(data.get('agents'), list)
                or any(not isinstance(e, dict) or not all(isinstance(e.get(k), str) for k in
                       ('id', 'display_name', 'backend', 'status'))
                       or e.get('backend') not in ('chatgpt', 'hosted')
                       or (e.get('remote_id') is not None and not isinstance(e['remote_id'], str))
                       for e in data['agents'])):
            raise ApiError('Invalid saved Dot registry: ' + str(self.path))
        return data

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self.path.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(data, stream, indent=2, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def resolve(self, target=None, by_id=False):
        data = self.read()
        entries = data['agents']
        if by_id and not target:
            raise ApiError('Supply a saved Dot ID with --by-id.')
        if target:
            matches = [e for e in entries if e['id'] == target]
            if not matches and not by_id:
                matches = [e for e in entries if e['display_name'].casefold() == target.casefold()]
        else:
            matches = [e for e in entries if e['id'] == data.get('selected')]
            if not matches and len(entries) == 1:
                matches = entries
        if len(matches) != 1:
            raise ApiError('Choose a saved Dot by name or ID from dots list. Import account Dots with dots import --source chatgpt, or create one with dots create NAME.')
        return matches[0]

    def reserve(self, name):
        with self.guard.locked():
            data = self.read()
            if any(e['display_name'].casefold() == name.casefold() for e in data['agents']):
                raise ApiError('That saved Dot name already exists. Inspect dots show NAME and dots list --source chatgpt. '
                               'If creation succeeded, recover it with dots import ID --by-id --source chatgpt --name NAME. '
                               'If it did not, remove the local reference with dots forget NAME before retrying.')
            entry = {'id': str(uuid.uuid4()), 'display_name': name, 'backend': 'chatgpt',
                     'remote_id': None, 'status': 'creating',
                     'creation_started_at': datetime.now(timezone.utc).isoformat()}
            data['agents'].append(entry)
            self.save(data)
            return entry

    def creation_failed(self, entry, message):
        with self.guard.locked():
            data = self.read()
            current = next((e for e in data['agents'] if e['id'] == entry['id']), None)
            if current is not None and not current.get('remote_id'):
                current.update(creation_error=message, creation_outcome='unknown')
                self.save(data)

    def remember(self, profile, backend='chatgpt', alias=None, reserved_id=None):
        if not isinstance(profile, dict) or not isinstance(profile.get('id'), str) or not profile['id']:
            raise ApiError('Cannot save a Dot without a provider identity.')
        with self.guard.locked():
            data = self.read()
            entry = next((e for e in data['agents'] if e['id'] == reserved_id or
                          (e['backend'] == backend and e.get('remote_id') == profile['id'])), None)
            name = alias or (entry['display_name'] if entry else profile.get('display_name', profile['id']))
            # Explicit import can reconcile an uncertain creation using the
            # provider's identity, without issuing another creation request.
            if entry is None:
                entry = next((e for e in data['agents'] if e['backend'] == backend
                              and e['status'] == 'creating' and not e.get('remote_id')
                              and e['display_name'].casefold() == name.casefold()), None)
            if any(e is not entry and e['display_name'].casefold() == name.casefold() for e in data['agents']):
                raise ApiError('That local alias already exists. Use dots import DOT --name ANOTHER_NAME --source ' + backend + '.')
            if entry is None:
                entry = {'id': str(uuid.uuid4())}
                data['agents'].append(entry)
            entry.update(display_name=name, backend=backend, remote_id=profile['id'], status='saved',
                         provider_name=profile.get('display_name', name),
                         is_paused=profile.get('is_paused'), messaging_room_id=profile.get('messaging_room_id'))
            entry.pop('creation_error', None)
            entry.pop('creation_outcome', None)
            if not data.get('selected'):
                data['selected'] = entry['id']
            self.save(data)
            return dict(entry)

    def select(self, entry):
        with self.guard.locked():
            data = self.read()
            data['selected'] = entry['id']
            self.save(data)

    def rename(self, entry, name):
        with self.guard.locked():
            data = self.read()
            if any(e['id'] != entry['id'] and e['display_name'].casefold() == name.casefold() for e in data['agents']):
                raise ApiError('That local alias already exists.')
            current = next(e for e in data['agents'] if e['id'] == entry['id'])
            current['display_name'] = name
            self.save(data)
            return current

    def forget(self, entry):
        with self.guard.locked():
            data = self.read()
            data['agents'] = [e for e in data['agents'] if e['id'] != entry['id']]
            if data.get('selected') == entry['id']:
                data['selected'] = None
            self.save(data)
