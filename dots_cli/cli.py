"""Local Dot launch actions. Opening a conversation never implies a submitted task."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from . import __version__

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

    def create(self, name=None, no_open=False):
        if name:
            name = self.validate_name(name)
            with self.locked():
                data = self.settings()
                if any(e['name'].casefold() == name.casefold() for e in data['dots']):
                    raise ValueError('That local name already exists. Use dots use NAME or choose another name.')
                data['dots'].append(dict(name=name, url=''))
                data['selected'] = name
                self.save_settings(data)
                self.record(dict(time=datetime.now(timezone.utc).isoformat(), action='create', outcome='local_entry_saved', name=name, submitted=False))
        if not no_open:
            self.launch('setup')
        return dict(name=name, cloud_created=False, message='Complete onboarding in ChatGPT: open dots, follow the introduction, choose a name. Then attach the conversation URL with dots configure URL' + (' --name ' + repr(name) if name else '') + '.')

    def use(self, name):
        name = self.validate_name(name)
        with self.locked():
            data = self.settings()
            entry = next((e for e in data['dots'] if e['name'].casefold() == name.casefold()), None)
            if not entry:
                raise ValueError('No saved Dot with that name. Run dots list.')
            data['selected'] = entry['name']
            self.save_settings(data)
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
        with self.locked():
            data = self.settings()
            name = name or data['selected'] or 'default'
            entry = next((e for e in data['dots'] if e['name'].casefold() == name.casefold()), None)
            if entry is None:
                entry = dict(name=name, url='')
                data['dots'].append(entry)
            entry['url'] = url
            data['selected'] = entry['name']
            self.save_settings(data)
        return {'ok': True, 'message': 'Dot link saved.' if url else 'Dot link cleared.', 'url': url}

    def resource(self, name):
        local = self.project / name
        return local if local.is_file() else ASSETS / name

    def init_project(self):
        self.project.mkdir(parents=True, exist_ok=True)
        for name in ('README.md', 'FIRST-MESSAGE.md', 'TRIALS.md', 'INSTALL.md', 'LAUNCHER.md', 'index.html', 'setup.html'):
            target = self.project / name
            try:
                with target.open('x', encoding='utf-8') as f:
                    f.write((ASSETS / name).read_text(encoding='utf-8'))
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

    def local_readiness(self):
        result = self.project / 'FIRST-RESULT.md'
        return dict(project=str(self.project), app_available=self.app_available(),
                    conversation_saved=bool(self.settings()['url']),
                    result_exists=result.is_file() and result.stat().st_size > 0,
                    presets_available=all(p['text'] for p in self.presets()),
                    workspace_ready=all((self.project / name).is_file() for name in ('README.md', 'FIRST-MESSAGE.md')))

    def status(self):
        return dict(url=self.settings()['url'], app_available=self.app_available(), presets=self.presets(),
                    history=self.history(), project=str(self.project),
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
        elif action == 'setup':
            if self.app_available():
                command = {'argv': ['/usr/bin/open', '-a', str(self.app), 'codex://dots']} if self.platform == 'darwin' else self.url_command('codex://dots')
                command['fallback_argv'] = self.url_command('https://chatgpt.com/dots')['argv']
                commands.append(command)
            else:
                commands.append(self.url_command('https://chatgpt.com/dots'))
        elif action == 'activity':
            target = self.validate_url(url)
            if not target:
                raise ValueError('A Dot activity URL is required.')
            commands.append(self.url_command(target))
        elif action == 'web':
            commands.append(self.url_command('https://chatgpt.com/'))
        elif action == 'guide':
            commands.append(self.url_command(SETUP_URL))
        elif action == 'folder':
            executable = '/usr/bin/open' if self.platform == 'darwin' else 'explorer.exe' if self.platform == 'win32' else 'xdg-open'
            commands.append({'argv': [executable, str(self.project)]})
        else:
            raise ValueError('Unknown launcher action.')
        return commands

    def url_command(self, url):
        return {'argv': ['/usr/bin/open', url] if self.platform == 'darwin' else [sys.executable, '-m', 'dots_cli.browser', url]}

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
                    try:
                        result = self.runner(command['argv'], input=command.get('input'), text=True, encoding='utf-8', capture_output=True, timeout=15)
                    except (OSError, subprocess.SubprocessError):
                        if not command.get('fallback_argv'):
                            raise
                        result = self.runner(command['fallback_argv'], text=True, encoding='utf-8', capture_output=True, timeout=15)
                    else:
                        if result.returncode and command.get('fallback_argv'):
                            result = self.runner(command['fallback_argv'], text=True, encoding='utf-8', capture_output=True, timeout=15)
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
    from .ui import DotsParser, console, show_list, show_activity, show_preflight, show_doctor
    if '--no-color' in (sys.argv[1:] if argv is None else argv):
        console.no_color=True
    parser=DotsParser(prog='dots', description='Manage account Dots and local setup tools.')
    parser.add_argument('--version', action='version', version='dots ' + __version__)
    parser.add_argument('--no-color', action='store_true', help='Disable terminal colors')
    sub=parser.add_subparsers(dest='command', metavar='COMMAND')
    from .cloud import add_commands
    add_commands(sub)
    descriptions = {'open': 'Open the saved conversation and optionally copy a prompt',
                    'app': 'Open the desktop app and optionally copy a prompt',
                    'copy': 'Copy a prompt to the clipboard',
                    'run': 'Copy a task and open its conversation (paste and send yourself)'}
    for name in ['open','app','copy','run']:
        p=sub.add_parser(name, help=descriptions[name], description=descriptions[name])
        choice=p.add_mutually_exclusive_group()
        choice.add_argument('--preset',choices=['first','local','followup'])
        choice.add_argument('--prompt',help='Text to copy; passed as clipboard data, never shell code')
        p.add_argument('--dry-run',action='store_true',help='Show commands without executing or logging them')
    for name, help_text in [('status', 'Show launcher settings and recent actions as JSON'),
                            ('history', 'Show recent local launch outcomes'),
                            ('folder', 'Open the project in the system file manager'),
                            ('web', 'Open ChatGPT in a browser'),
                            ('guide', 'Open the official onboarding instructions')]:
        sub.add_parser(name, help=help_text)
    sub.add_parser('update', help='Update this CLI from quivent/Dots on GitHub (main)')
    installation = sub.add_parser('installation', help='List the individual installation and setup commands')
    installation.add_argument('--json', action='store_true', help='Print the command list as JSON')
    setup = sub.add_parser('setup', help='Start here; show setup steps or run them in order')
    setup.add_argument('setup_action', nargs='?', choices=['run', 'onboard'],
                       help='run: execute the sequence; onboard: launch Dot onboarding. Omit to list steps.')
    setup.add_argument('--json', action='store_true', help='Print the step list or onboarding result as JSON; unavailable with run')
    preflight = sub.add_parser('preflight', help='Check local readiness and current Dot account access without signing in')
    preflight.add_argument('--json', action='store_true', help='Print preflight results as JSON')
    doctor=sub.add_parser('doctor', help='Run full read-only diagnostics for troubleshooting')
    doctor.add_argument('--json', action='store_true', help='Print the full diagnostic report as JSON')
    prompt=sub.add_parser('prompt', help='Print a task prompt without opening apps or writing the clipboard')
    prompt.add_argument('preset', choices=['first','local','followup'], nargs='?', default='first', help='Prompt to print (default: first)')
    serve = sub.add_parser('serve', help='Open the local setup desk with launcher buttons')
    serve.add_argument('--port', type=int, default=8768, help='Local HTTP port (default: 8768; 0 selects a free port)')
    serve.add_argument('--no-open', action='store_true', help='Start the local server without opening a browser')
    configure=sub.add_parser('configure', help='Save or clear a Dot conversation URL')
    configure.add_argument('url',help='Paste the conversation URL; empty string clears it')
    configure.add_argument('--name', help='Name this local conversation shortcut')
    args=parser.parse_args(argv); launcher=Launcher()
    if args.no_color:
        console.no_color=True
    try:
        if not args.command:
            parser.print_help()
            return 0
        if args.command == 'update':
            from .update import update
            return update()
        if args.command in ('preflight', 'doctor'):
            from . import diagnostics
            result = diagnostics.preflight(launcher) if args.command == 'preflight' else diagnostics.doctor(launcher)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                (show_preflight if args.command == 'preflight' else show_doctor)(result)
            failed = result.get('error') or result['connection'] == 'error' or any(item['state'] == 'error' for item in result.get('diagnostics', []))
            return 1 if failed else 0
        if args.command in ('setup', 'installation'):
            from .workflow import SETUP_STEPS, run_setup
            from .ui import show_setup
            if getattr(args, 'setup_action', None) == 'run':
                if args.json:
                    raise ValueError('setup run is interactive. Use dots setup --json to inspect its steps.')
                return run_setup()
            if getattr(args, 'setup_action', None) == 'onboard':
                result = launcher.launch('setup')
                if args.json:
                    print(json.dumps(result, indent=2))
                else:
                    print(result['message'])
            elif args.json:
                print(json.dumps({'run': 'dots setup run', 'steps': [dict(command='dots ' + ' '.join(step['args']), description=step['description']) for step in SETUP_STEPS]}, indent=2))
            else:
                show_setup()
            return 0
        from .cloud import run as run_cloud
        cloud_result = run_cloud(args, launcher)
        if cloud_result is not None:
            return cloud_result
        if args.command=='prompt':
            print(next(p['text'] for p in launcher.presets() if p['id']==args.preset))
            return 0
        if args.command=='serve':
            from .server import serve
            serve(launcher, port=args.port, open_browser=not args.no_open)
            return 0
        if args.command=='configure': result=launcher.configure(args.url, args.name)
        elif args.command=='status': result=launcher.status()
        elif args.command=='history': result=launcher.history()
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
