"""Compatibility import for the existing local tracker."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli.cli import *

if __name__ == '__main__':
    raise SystemExit(main())
