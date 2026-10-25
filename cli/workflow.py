"""One setup plan for installation output, setup output, and prerequisite execution."""
SETUP_STEPS = (
    {'args': ('update',), 'description': 'Update the CLI.', 'status': 'independent', 'prerequisite': True},
    {'args': ('preflight',), 'description': 'Check local prerequisites.', 'status': 'independent', 'prerequisite': True},
    {'args': ('auth',), 'description': 'Authenticate and verify account access.', 'status': 'independent', 'prerequisite': True},
    {'args': ('list', '--source', 'chatgpt'), 'description': 'Discover existing account Dots.', 'status': 'independent', 'prerequisite': True,
     'note': 'Catalog discovery can be bypassed with create --first or --additional.'},
    {'args': ('create', 'NAME'), 'description': 'Create the Dot profile.', 'status': 'bundled',
     'note': 'Currently also requests conversation creation and initialization.'},
    {'args': None, 'description': 'Create its conversation.', 'status': 'bundled', 'via': 'dots create NAME',
     'note': 'No independent CLI command yet; requested by dots create.'},
    {'args': None, 'description': 'Initialize the Dot.', 'status': 'bundled', 'via': 'dots create NAME',
     'note': 'No independent CLI command yet; requested by dots create.'},
    {'args': ('room', 'DOT'), 'description': 'Create or recover its messaging room.', 'status': 'conditional',
     'note': 'Only if the creation response has no messaging_room_id.'},
    {'args': ('use', 'DOT'), 'description': 'Select it as primary.', 'status': 'optional',
     'note': 'Optional; other commands can target a Dot explicitly.'},
    {'args': ('show', 'DOT'), 'description': 'Inspect the resulting profile.', 'status': 'independent',
     'note': 'Inspect returned state; profile creation does not prove initialization completed.'},
)


def step_command(step):
    return 'dots ' + ' '.join(step['args']) if step['args'] else None


def setup_plan():
    return {'run': 'dots setup run', 'run_scope': 'prerequisites only', 'steps': [
        {**{key: value for key, value in step.items() if key != 'args'}, 'command': step_command(step)}
        for step in SETUP_STEPS
    ]}


def execute_step(arguments):
    from pathlib import Path
    import subprocess
    import sys
    # Reload the installed package for each step, especially after self-update.
    # A source checkout in the caller's working directory must not shadow it.
    command = ([sys.executable] if '__compiled__' in globals()
               else [sys.executable, '-m', 'cli'])
    return subprocess.run([*command, *arguments],
                          cwd=Path(sys.executable).parent).returncode


def run_setup(execute=None):
    if execute is None:
        execute = execute_step
    from .ui import console
    from rich.text import Text
    steps = [step for step in SETUP_STEPS if step.get('prerequisite')]
    for index, step in enumerate(steps, 1):
        command = step_command(step)
        console.print(Text(f'\n[{index}/{len(steps)}] ' + command, style='bold green'))
        result = execute(list(step['args']))
        if result:
            console.print(Text('Setup stopped at ' + command + '. Run that command to retry, or choose another step independently.', style='yellow'))
            return result
    console.print('\n[green]Prerequisites finished.[/green] [dim]Next: dots create NAME. Use dots installation for the full plan.[/dim]')
    return 0


def run(args, launcher):
    from .ui import output, show_setup
    action = getattr(args, 'setup_action', None)
    if action == 'run':
        if args.json:
            raise ValueError('setup run is interactive. Use dots setup --json to inspect its steps.')
        return run_setup()
    if action == 'onboard':
        output(launcher.launch('setup'), args.json, render=lambda result: print(result['message']))
    elif args.json:
        output(setup_plan(), True)
    else:
        show_setup()
    return 0
