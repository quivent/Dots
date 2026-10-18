"""Compatibility import for the existing local setup server."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dots_cli.server import *
