"""Canonical shared documents, used from the checkout or installed distribution."""
from importlib.metadata import distribution, PackageNotFoundError
from pathlib import Path

GUIDE_FILES = ('README.md', 'FIRST-MESSAGE.md', 'TRIALS.md', 'INSTALL.md',
               'LAUNCHER.md', 'index.html', 'setup.html')
SOURCE_ROOT = Path(__file__).resolve().parent.parent


def shared_resource(name):
    bundled = SOURCE_ROOT / 'share' / 'dots' / name
    if '__compiled__' in globals() and bundled.is_file():
        return bundled
    if (SOURCE_ROOT / 'pyproject.toml').is_file():
        return SOURCE_ROOT / name
    try:
        package = distribution('dots-cli')
        for entry in package.files or ():
            if entry.as_posix().endswith('/share/dots/' + name):
                return Path(package.locate_file(entry))
    except PackageNotFoundError:
        pass
    raise FileNotFoundError('Shared Dots resource is missing: ' + name)
