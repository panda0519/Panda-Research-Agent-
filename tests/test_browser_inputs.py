"""Tests for browser_inputs.py: Input resolution logic."""
import os
import tempfile
from pathlib import Path

import pytest

from browser_inputs import RunInputs, resolve_run_inputs


def test_resolve_topic_only():
    res = resolve_run_inputs(
        topic="  On-device Speech Diarization  ",
        context="Target ARM64 with <200ms latency",
    )
    assert res.is_valid is True
    assert res.topic == "On-device Speech Diarization"
    assert res.context == "Target ARM64 with <200ms latency"
    assert res.error_message is None


def test_resolve_file_only_uses_first_non_empty_line():
    file_content = "\n\n  # Edge AI Audio Processing  \nRequirements:\n- Latency < 100ms\n- Memory < 50MB\n"
    res = resolve_run_inputs(
        topic="",
        context="",
        problem_file_name="requirements.md",
        problem_file_text=file_content,
    )
    assert res.is_valid is True
    assert res.topic == "# Edge AI Audio Processing"
    assert "--- From uploaded file: requirements.md ---" in res.context
    assert "Requirements:" in res.context
    assert res.error_message is None


def test_resolve_both_topic_and_file_keeps_topic_and_appends_file():
    file_content = "Extra constraints:\n- Offline mode only"
    res = resolve_run_inputs(
        topic="Custom Real-Time Diarizer",
        context="Base context: ARM64 target",
        problem_file_name="constraints.txt",
        problem_file_text=file_content,
    )
    assert res.is_valid is True
    assert res.topic == "Custom Real-Time Diarizer"
    assert "Base context: ARM64 target" in res.context
    assert "--- From uploaded file: constraints.txt ---" in res.context
    assert "Extra constraints:" in res.context


def test_resolve_neither_topic_nor_file_is_invalid():
    res = resolve_run_inputs(
        topic="   ",
        context="Context without topic",
        problem_file_name=None,
        problem_file_text=None,
    )
    assert res.is_valid is False
    assert res.topic == ""
    assert res.error_message is not None


def test_resolve_empty_and_whitespace_file():
    # Empty file with no topic -> invalid
    res_empty = resolve_run_inputs(
        topic="",
        context="",
        problem_file_name="empty.txt",
        problem_file_text="   \n\t  \n  ",
    )
    assert res_empty.is_valid is False
    assert res_empty.topic == ""

    # Empty file with valid topic -> valid with topic kept
    res_with_topic = resolve_run_inputs(
        topic="Valid Diarization Topic",
        context="Some context",
        problem_file_name="empty.txt",
        problem_file_text="   \n\t  \n  ",
    )
    assert res_with_topic.is_valid is True
    assert res_with_topic.topic == "Valid Diarization Topic"
    assert res_with_topic.context == "Some context"


def test_resolve_long_first_line_truncation():
    long_line = "X" * 200
    file_content = f"{long_line}\nSecond line with details"
    res = resolve_run_inputs(
        topic="",
        context="",
        problem_file_name="long_spec.txt",
        problem_file_text=file_content,
        max_first_line_len=120,
    )
    assert res.is_valid is True
    assert len(res.topic) == 120
    assert res.topic == "X" * 120
    assert "--- From uploaded file: long_spec.txt ---" in res.context


def test_resolve_file_without_name_defaults():
    res = resolve_run_inputs(
        topic="",
        context="",
        problem_file_name=None,
        problem_file_text="First line topic\nRest of problem text",
    )
    assert res.is_valid is True
    assert res.topic == "First line topic"
    assert "--- From uploaded file: uploaded_file ---" in res.context
