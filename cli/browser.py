"""URL opener with a meaningful process exit code, including missing handlers."""
import sys
import webbrowser
from urllib.parse import urlsplit


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or urlsplit(args[0]).scheme not in ('https', 'http', 'codex'):
        return 2
    try:
        return 0 if webbrowser.open(args[0], new=2) else 1
    except (OSError, webbrowser.Error):
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
