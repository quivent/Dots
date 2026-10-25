"""Package the canonical documents without maintaining a second asset tree."""
from runpy import run_path
from setuptools import setup

setup(data_files=[('share/dots', run_path('cli/resources.py')['GUIDE_FILES'])])
