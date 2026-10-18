"""Local Dot launch actions. Opening a conversation never implies a submitted task."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from urllib.parse import urlsplit

PACKAGE_ROOT = Path(__file__).resolve().parent
ASSETS = PACKAGE_ROOT / 'assets'
SOURCE_ROOT = PACKAGE_ROOT.parent
PROJECT = Path(os.environ.get('DOTS_PROJECT', str(SOURCE_ROOT if (SOURCE_ROOT / 'pyproject.toml').is_file() else Path.home() / 'Dots'))).expanduser().resolve()
TRACKER_RUNTIME = Path.home() / 'tracker-factory/trackers/dots/runtime'
DEFAULT_RUNTIME = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'Dots/runtime' if os.name == 'nt' else Path.home() / '.local/share/dots/runtime'
RUNTIME = Path(os.environ.get('DOTS_DATA_HOME', str(TRACKER_RUNTIME if TRACKER_RUNTIME.is_dir() else DEFAULT_RUNTIME))).expanduser()
SETUP_URL = 'https://learn.chatgpt.com/docs/dots/getting-started'
MAX_PROMPT = 12000

if os.name == 'nt':
    import msvcrt
else:
    import fcntl

class Launcher:
    def __init__(self, project=PROJECT, runtime=RUNTIME, runner=subprocess.run, app=None, platform=None):
        self.platform = platform or sys.platform
        default_app = Path('/Applications/ChatGPT.app') if self.platform == 'darwin' else Path(shutil.which('ChatGPT.exe') or str(Path.home() / 'AppData/Local/Microsoft/WindowsApps/ChatGPT.exe'))
        self.project, self.runtime, self.runner, self.app = Path(project), Path(runtime), runner, Path(app) if app is not None else default_app

    @contextmanager
    def locked(self):
        self.runtime.mkdir(parents=True, exist_ok=True)
        with (self.runtime / 'dots-launcher.lock').open('a+b') as lock:
            if os.name == 'nt':
                lock.seek(0, os.SEEK_END)
                if lock.tell() == 0:
                    lock.write(b'\0'); lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == 'nt':
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def settings(self):
        try:
            data = json.loads((self.runtime / 'dots-launcher.json').read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {'url': '', 'selected': '', 'dots': []}
        if not isinstance(data, dict):
            raise ValueError('Launcher settings are invalid. Save the Dot link again.')
        url = self.validate_url(data.get('url', ''))
        entries = data.get('dots')
        if entries is None:
            entries = [{'name': 'default', 'url': url}] if url else []
            selected = 'default' if url else ''
        else:
            if not isinstance(entries, list):
                raise ValueError('Invalid local Dot registry.')
            entries = [dict(name=self.validate_name(e['name']), url=self.validate_url(e.get('url', ''))) for e in entries if isinstance(e, dict) and 'name' in e]
            selected = data.get('selected', '')
            if selected and not any(e['name'] == selected for e in entries):
                raise ValueError('Selected Dot is missing from the local registry.')
        current = next((e for e in entries if e['name'] == selected), None)
        return dict(url=current['url'] if current else '', selected=selected, dots=entries)

    @staticmethod
    def validate_name(name):
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80 or not name.isprintable():
            raise ValueError('Use a printable Dot name of 1–80 characters.')
        return name.strip()

    def save_settings(self, data):
        current = next((e for e in data['dots'] if e['name'] == data['selected']), None)
        data['url'] = current['url'] if current else ''  # Existing tracker compatibility.
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.runtime, delete=False) as f:
            json.dump(data, f); f.write('\n'); temp = f.name
        os.replace(temp, self.runtime / 'dots-launcher.json')

    def list_dots(self):
        data = self.settings()
        return [dict(**entry, selected=entry['name'] == data['selected'], state='link saved' if entry['url'] else 'setup pending') for entry in data['dots']]

    def _update_registry(self, action, name=None, url=''):
        with self.locked():
            data = self.settings()
            name = name or data['selected'] or 'default'
            entry = next((e for e in data['dots'] if e['name'].casefold() == name.casefold()), None)
            if action == 'create' and entry is not None:
                raise ValueError('That local name already exists. Use dots use NAME or choose another name.')
            if entry is None:
                if action == 'use':
                    raise ValueError('No saved Dot with that name. Run dots list.')
                entry = dict(name=name, url='')
                data['dots'].append(entry)
            if action == 'configure':
                entry['url'] = url
            data['selected'] = entry['name']
            self.save_settings(data)
            if action == 'create':
                self.record(dict(time=datetime.now(timezone.utc).isoformat(), action='create', outcome='local_entry_saved', name=name, submitted=False))
            return entry

    def create(self, name=None, no_open=False):
        if name:
            name = self.validate_name(name)
            self._update_registry('create', name)
        if not no_open:
            self.launch('setup')
        return dict(name=name, cloud_created=False, message='Complete onboarding in ChatGPT: open dots, follow the introduction, choose a name. Then attach the conversation URL with dots configure URL' + (' --name ' + repr(name) if name else '') + '.')

    def use(self, name):
        entry = self._update_registry('use', self.validate_name(name))
        return dict(ok=True, message='Selected ' + entry['name'] + ('.' if entry['url'] else ' (setup pending; attach its conversation URL).'))

    @staticmethod
    def validate_url(value):
        if not isinstance(value, str) or len(value) > 2048:
            raise ValueError('Enter a ChatGPT conversation URL.')
        value = value.strip()
        if not value:
            return ''
        u = urlsplit(value)
        if (u.scheme != 'https' or u.netloc != 'chatgpt.com' or u.username or u.password
                or not u.path.strip('/') or any(ord(c) < 33 for c in value)):
            raise ValueError('Use the HTTPS conversation link copied from chatgpt.com, not the home page.')
        return value

    def configure(self, url, name=None):
        url = self.validate_url(url)
        if name is not None:
            name = self.validate_name(name)
        self._update_registry('configure', name, url)
        return {'ok': True, 'message': 'Dot link saved.' if url else 'Dot link cleared.', 'url': url}

    def resource(self, name):
        shared = SOURCE_ROOT if (SOURCE_ROOT / 'pyproject.toml').is_file() else Path(sysconfig.get_path('data')) / 'share/dots'
        return next((root / name for root in (self.project, ASSETS, shared) if (root / name).is_file()), ASSETS / name)

    def init_project(self):
        self.project.mkdir(parents=True, exist_ok=True)
        for name in ('README.md', 'FIRST-MESSAGE.md', 'TRIALS.md', 'INSTALL.md', 'LAUNCHER.md', 'index.html', 'setup.html'):
            target = self.project / name
            try:
                with target.open('x', encoding='utf-8') as f:
                    f.write(self.resource(name).read_text(encoding='utf-8'))
            except FileExistsError:
                pass  # Preserve user files and concurrent initialization.
        ignore = self.project / '.gitignore'
        if ignore.is_symlink():
            raise ValueError('Workspace .gitignore cannot be a symlink.')
        try:
            existing = ignore.read_text(encoding='utf-8')
        except FileNotFoundError:
            existing = ''
        rules = ('.env', '.env.*', 'FIRST-RESULT.md', 'dots-trials.md', 'runtime/')
        missing = [rule for rule in rules if rule not in existing.splitlines()]
        if missing:
            with ignore.open('a', encoding='utf-8') as f:
                f.write(('\n' if existing and not existing.endswith('\n') else '') + '\n'.join(missing) + '\n')

    def presets(self):
        text = self.resource('FIRST-MESSAGE.md').read_text(encoding='utf-8')
        first, separator, rest = text.partition('## After connecting this computer')
        if not separator:
            first, _, rest = text.partition('## After connecting this Mac')
        local = rest.split('## Record what happened')[0]
        quote = lambda value: '\n'.join(line[2:] for line in value.splitlines() if line.startswith('> ')).replace('~/Dots', str(self.project))
        return [dict(id='first', label='First conversation', text=quote(first)),
                dict(id='local', label='A task in this folder', text=quote(local)),
                dict(id='followup', label='Continue our work', text='Pick up our Dots evaluation. Tell me what actually finished, what remains untested, and the single most useful next step. Use the existing work and keep the reply concise.')]

    def app_available(self):
        if self.platform == 'win32':
            return self.app.is_file()
        if self.platform != 'darwin':
            return False
        try:
            data = plistlib.loads((self.app / 'Contents/Info.plist').read_bytes())
            return data.get('CFBundleIdentifier') == 'com.openai.codex'
        except (OSError, ValueError):
            return False

    def history(self):
        try:
            lines = (self.runtime / 'dots-launches.jsonl').read_text(encoding='utf-8').splitlines()[-12:]
        except FileNotFoundError:
            return []
        result=[]
        for line in reversed(lines):
            try: result.append(json.loads(line))
            except ValueError: continue
        return result

    def prepare(self, prompt, dry_run=False):
        """Copy a prompt and open the saved conversation, app, or web fallback."""
        if not dry_run:
            self.init_project()
        if self.settings()['url']:
            return self.launch('dot', prompt, dry_run=dry_run)
        if self.app_available():
            return self.launch('app', prompt, dry_run=dry_run)
        if dry_run:
            return dict(dry_run=True, commands=self.plan('copy', prompt) + self.plan('setup'), submitted=False)
        self.launch('copy', prompt)
        result = self.launch('setup')
        result['message'] = 'Prompt copied and ChatGPT opened in your browser. Paste and send in your dot.'
        return result

    def snapshot(self):
        return dict(url=self.settings()['url'], app_available=self.app_available(),
                    project=str(self.project), presets=self.presets())

    def result_exists(self):
        result = self.project / 'FIRST-RESULT.md'
        return result.is_file() and result.stat().st_size > 0

    def local_readiness(self):
        state = self.snapshot()
        state['conversation_saved'] = bool(state.pop('url'))
        state['presets_available'] = all(p['text'] for p in state.pop('presets'))
        return dict(state, result_exists=self.result_exists(),
                    workspace_ready=all((self.project / name).is_file() for name in ('README.md', 'FIRST-MESSAGE.md')))

    def status(self):
        return dict(self.snapshot(), history=self.history(),
                    delivery='Prompts are copied for you to paste and send. No task is submitted automatically.')

    def plan(self, action, prompt='', url=None):
        if not isinstance(prompt, str) or len(prompt) > MAX_PROMPT or '\0' in prompt:
            raise ValueError(f'Use a text prompt of at most {MAX_PROMPT} characters.')
        commands=[]
        if action in ('dot', 'app') and prompt.strip():
            commands.append(self.clipboard_command(prompt))
        if action == 'dot':
            url = self.settings()['url']
            if not url:
                raise ValueError('Save your Dot conversation link first, or choose Open ChatGPT.')
            commands.append(self.url_command(url))
        elif action == 'app':
            if not self.app_available():
                raise ValueError('The current ChatGPT desktop app was not found. Use the setup guide to open ChatGPT on the web.')
            commands.append(self.app_command())
        elif action == 'copy':
            if not prompt.strip(): raise ValueError('Write or select a prompt to copy.')
            commands.append(self.clipboard_command(prompt))
        elif action in ('setup', 'web', 'guide'):
            target = {'setup': 'https://chatgpt.com/dots', 'web': 'https://chatgpt.com/', 'guide': SETUP_URL}[action]
            command = self.url_command(target)
            if action == 'setup' and self.app_available():
                fallback = command['argv']
                command = {'argv': ['/usr/bin/open', '-a', str(self.app), 'codex://dots']} if self.platform == 'darwin' else self.url_command('codex://dots')
                command['fallback_argv'] = fallback
            commands.append(command)
        elif action == 'activity':
            target = self.validate_url(url)
            if not target:
                raise ValueError('A Dot activity URL is required.')
            commands.append(self.url_command(target))
        elif action == 'folder':
            executable = '/usr/bin/open' if self.platform == 'darwin' else 'explorer.exe' if self.platform == 'win32' else 'xdg-open'
            commands.append({'argv': [executable, str(self.project)]})
        else:
            raise ValueError('Unknown launcher action.')
        return commands

    def url_command(self, url):
        return {'argv': ['/usr/bin/open', url] if self.platform == 'darwin' else [sys.executable, '-m', 'cli.browser', url]}

    def app_command(self):
        return {'argv': ['/usr/bin/open', '-a', str(self.app)] if self.platform == 'darwin' else [str(self.app)]}

    def clipboard_command(self, prompt):
        if self.platform == 'darwin':
            argv = ['/usr/bin/pbcopy']
        elif self.platform == 'win32':
            # Prompt data goes through UTF-8 stdin, never into PowerShell code.
            script = '[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false); $text = [Console]::In.ReadToEnd(); Set-Clipboard -Value $text'
            argv = ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script]
        elif shutil.which('wl-copy'):
            argv = ['wl-copy']
        elif shutil.which('xclip'):
            argv = ['xclip', '-selection', 'clipboard']
        else:
            raise ValueError('No clipboard tool found. Use dots prompt PRESET to print the text, or install wl-copy/xclip on Linux.')
        return dict(argv=argv, input=prompt, clipboard=True)

    def launch(self, action, prompt='', dry_run=False, url=None):
        commands=self.plan(action,prompt,url)
        if dry_run: return {'dry_run': True, 'commands': commands, 'submitted': False}
        copied=False
        with self.locked():
            try:
                if action == 'setup' or prompt.strip():
                    self.init_project()
                for command in commands:
                    fallback = command.get('fallback_argv')
                    try:
                        result = self.runner(command['argv'], input=command.get('input'), text=True, encoding='utf-8', capture_output=True, timeout=15)
                    except (OSError, subprocess.SubprocessError):
                        if not fallback:
                            raise
                        result = None
                    if fallback and (result is None or result.returncode):
                        result = self.runner(fallback, text=True, encoding='utf-8', capture_output=True, timeout=15)
                    if result.returncode:
                        raise ValueError('Could not complete the launch. Check that the app, clipboard tool, or browser is available.')
                    copied |= command.get('clipboard', False)
            except (OSError, subprocess.SubprocessError, ValueError) as error:
                record=dict(time=datetime.now(timezone.utc).isoformat(), action=action, outcome='failed', copied=copied, submitted=False)
                self.record(record)
                raise ValueError(('Prompt was copied, but the launch failed. ' if copied else '') + str(error)) from error
            messages={'dot':'Dot link handed to your browser.' + (' Paste and send the copied prompt in your Dot.' if copied else ''),
                      'app':'ChatGPT launch requested.' + (' Open your Dot, then paste and send the copied prompt.' if copied else ''),
                      'copy':'Prompt copied. Paste it into your Dot and send.',
                      'setup':'Dot onboarding launch requested.',
                      'activity':'Dot activity page launch requested.',
                      'web':'ChatGPT opened in your browser. Choose dots to begin setup.',
                      'guide':'Official setup guide opened.', 'folder':'Project folder opened.'}
            record=dict(time=datetime.now(timezone.utc).isoformat(), action=action, outcome='copied' if action=='copy' else 'launch_requested', copied=copied, submitted=False)
            self.record(record)
        return dict(ok=True, message=messages[action], **record)

    def record(self, record):
        fd=os.open(self.runtime/'dots-launches.jsonl',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        with os.fdopen(fd,'a', encoding='utf-8') as f: f.write(json.dumps(record)+'\n')

    def dispatch(self, data):
        if not isinstance(data,dict): raise ValueError('Expected an action object.')
        action=data.get('action')
        if action=='configure': return self.configure(data.get('url',''))
        return self.launch(action,data.get('prompt',''))


def main(argv=None):
    if os.name == 'nt':
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, 'reconfigure'):
                stream.reconfigure(encoding='utf-8')
    from .ui import console, show_preflight, show_doctor
    if '--no-color' in (sys.argv[1:] if argv is None else argv):
        console.no_color=True
    from .commands import build_parser
    parser = build_parser()
    args=parser.parse_args(argv); launcher=Launcher()
    if args.no_color:
        console.no_color=True
    try:
        if not args.command:
            parser.print_help()
            return 0
        if args.handler == 'update':
            from .update import update
            return update()
        if args.handler == 'diagnostics':
            from . import diagnostics
            result = getattr(diagnostics, args.command)(launcher)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                (show_preflight if args.command == 'preflight' else show_doctor)(result)
            failed = result.get('error') or result['connection'] == 'error' or any(item['state'] == 'error' for item in result.get('diagnostics', []))
            return 1 if failed else 0
        if args.handler == 'setup':
            from .workflow import setup_plan, run_setup
            from .ui import show_setup
            setup_action = getattr(args, 'setup_action', None)
            if setup_action == 'run':
                if args.json:
                    raise ValueError('setup run is interactive. Use dots setup --json to inspect its steps.')
                return run_setup()
            if setup_action == 'onboard':
                result = launcher.launch('setup')
            elif args.json:
                result = setup_plan()
            else:
                show_setup()
                return 0
            print(json.dumps(result, indent=2) if args.json else result['message'])
            return 0
        if args.handler == 'cloud':
            from .cloud import run
            return run(args, launcher)
        if args.handler=='prompt':
            print(next(p['text'] for p in launcher.presets() if p['id']==args.preset))
            return 0
        if args.handler=='serve':
            from .server import serve
            serve(launcher, port=args.port, open_browser=not args.no_open)
            return 0
        if args.handler=='configure': result=launcher.configure(args.url, args.name)
        elif args.handler == 'inspect': result=getattr(launcher, args.command)()
        else:
            prompt=getattr(args,'prompt',None) or ''
            if getattr(args,'preset',None): prompt=next(p['text'] for p in launcher.presets() if p['id']==args.preset)
            if args.command=='run':
                if not prompt.strip():
                    raise ValueError('Choose --preset first, --preset local, --preset followup, or --prompt TEXT.')
                result=launcher.prepare(prompt, dry_run=args.dry_run)
            else:
                result=launcher.launch('dot' if args.command=='open' else args.command,prompt,getattr(args,'dry_run',False))
        print(json.dumps(result,indent=2,ensure_ascii=False));return 0
    except (ValueError,OSError) as error:
        print(str(error),file=sys.stderr);return 1

if __name__=='__main__': raise SystemExit(main())
