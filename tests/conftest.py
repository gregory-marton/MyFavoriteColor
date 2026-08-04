import sys
import os

# Co-authored-by: GPT-5, Aug 2026

pytest_plugins = ["smotoremu.testing"]

# Add the repo root to sys.path so tests work from any cwd.
tests_dir = os.path.dirname(__file__)
repo_root = os.path.abspath(os.path.join(tests_dir, os.pardir))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
