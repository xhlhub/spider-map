import os
from pathlib import Path

os.chdir(Path(__file__).resolve().parents[1])

from app import app as app 