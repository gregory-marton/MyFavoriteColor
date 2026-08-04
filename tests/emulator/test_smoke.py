"""T001 package smoke tests.

Co-authored-by: GPT-5, Aug 2026
"""

import pathlib

import smotoremu


def test_package_exposes_version():
    assert isinstance(smotoremu.__version__, str)
    assert smotoremu.__version__


def test_pyproject_declares_smotoremu_package():
    pyproject = pathlib.Path(__file__).resolve().parents[2] / "pyproject.toml"
    text = pyproject.read_text()

    assert 'name = "smotoremu"' in text
    assert 'requires-python = ">=3.11"' in text
