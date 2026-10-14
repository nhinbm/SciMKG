#!/usr/bin/env python3
"""Download the ConceptNet 5.7.0 dump and build its zh/en index in runs/preprocessing/conceptnet/.

Ex01 also does this on its first run; this script lets it happen ahead of time.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.ex01.conceptnet import FOLDER, ensure_index
from experiments.ex01.core import Journal

if __name__ == "__main__":
    print(ensure_index(Journal(FOLDER, "preprocessing")))
