#!/usr/bin/env python3
"""Launch the Ex02 experiment CLI from the repository checkout."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from experiments.ex02.cli import entrypoint

if __name__ == "__main__":
    entrypoint()
