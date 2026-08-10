"""Unit tests for persistent recording in mirror/bridge mode.

Co-authored-by: Gemini 3.6 Flash, Aug 2026
"""

import os
import json
import pytest

from smotoremu.cli import HardwareBridge, HardwareServerSession


def test_recording_state_toggle_and_persistence(tmp_path):
    state_file = tmp_path / "recording_state.json"
    rec_dir = tmp_path / "recordings"

    hb = HardwareBridge()
    session = HardwareServerSession(hb, state_file=str(state_file), rec_dir=str(rec_dir))

    # Initial state should be not recording
    assert session.is_recording is False

    # Start recording
    session.handle('{"v":1,"type":"record","recording":true}')
    assert session.is_recording is True
    assert os.path.exists(state_file)

    # Simulate hardware event while recording
    session.record_event({"kind": "button", "detail": "up"})

    # Stop recording
    session.handle('{"v":1,"type":"record","recording":false}')
    assert session.is_recording is False

    # Check generated recording file
    rec_files = list(rec_dir.glob("*.jsonl"))
    assert len(rec_files) == 1
    content = rec_files[0].read_text()
    assert '"kind": "button"' in content or '"kind":"button"' in content


def test_recording_survives_reconnect(tmp_path):
    state_file = tmp_path / "recording_state.json"
    rec_dir = tmp_path / "recordings"

    hb = HardwareBridge()
    session1 = HardwareServerSession(hb, state_file=str(state_file), rec_dir=str(rec_dir))
    session1.handle('{"v":1,"type":"record","recording":true}')
    assert session1.is_recording is True

    # Reconnect/new session using same state file
    session2 = HardwareServerSession(hb, state_file=str(state_file), rec_dir=str(rec_dir))
    assert session2.is_recording is True
