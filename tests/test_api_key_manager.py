"""Unit tests for API key management, masking, atomic .env edits, and scoped injection."""
import os
import tempfile
from pathlib import Path

import pytest

from api_key_manager import (
    get_env_file_keys,
    is_env_in_gitignore,
    mask_api_key,
    remove_key_from_env,
    save_keys_to_env,
    scoped_env_override,
)


def test_mask_api_key_edge_cases():
    # Empty string
    assert mask_api_key("") == ""
    assert mask_api_key(None) == ""

    # Short keys (<= 8 chars) must be completely masked
    assert mask_api_key("1") == "•"
    assert mask_api_key("1234") == "••••"
    assert mask_api_key("12345678") == "••••••••"
    assert "1" not in mask_api_key("12345678")

    # Short-medium keys (9-12 chars)
    masked_9 = mask_api_key("123456789")
    assert "•" in masked_9
    assert len(masked_9) > 0

    # Normal length keys
    key_32 = "sk-ant-api03-abcdefghijklmn-1234"
    masked_32 = mask_api_key(key_32)
    assert masked_32.startswith("sk-ant")
    assert masked_32.endswith("1234")
    assert "•" in masked_32
    assert "abcdef" not in masked_32

    # Very long keys
    key_long = "tvly-" + ("x" * 80) + "abcd"
    masked_long = mask_api_key(key_long)
    assert masked_long.startswith("tvly-x")
    assert masked_long.endswith("abcd")
    assert "•" in masked_long


def test_is_env_in_gitignore():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Without .gitignore
        assert is_env_in_gitignore(root) is False

        # With .gitignore containing .env
        (root / ".gitignore").write_text("# Comments\n.env\n*.pyc\n", encoding="utf-8")
        assert is_env_in_gitignore(root) is True

        # With .gitignore not containing .env
        (root / ".gitignore").write_text("# Comments\n*.pyc\n", encoding="utf-8")
        assert is_env_in_gitignore(root) is False


def test_save_keys_to_env_creates_file_if_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / ".gitignore").write_text(".env\n", encoding="utf-8")
        env_file = root / ".env"

        save_keys_to_env(
            env_path=env_file,
            updates={"ANTHROPIC_API_KEY": "test_key_123"},
            repo_root=root,
        )
        assert env_file.exists()
        keys = get_env_file_keys(env_file)
        assert keys.get("ANTHROPIC_API_KEY") == "test_key_123"



def test_save_keys_to_env_preserves_comments_and_formatting():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / ".gitignore").write_text(".env\n", encoding="utf-8")
        env_file = root / ".env"

        initial_content = (
            "# Top level comment\n"
            "\n"
            "# Provider keys\n"
            "EXISTING_VAR=alpha\n"
            "ANTHROPIC_API_KEY=old_anthropic\n"
            "\n"
            "# Trailing comment\n"
        )
        env_file.write_text(initial_content, encoding="utf-8")

        save_keys_to_env(
            env_path=env_file,
            updates={
                "ANTHROPIC_API_KEY": "new_anthropic_val",
                "TAVILY_API_KEY": "new_tavily_val",
            },
            repo_root=root,
        )

        content = env_file.read_text(encoding="utf-8")
        assert "# Top level comment" in content
        assert "# Provider keys" in content
        assert "EXISTING_VAR=alpha" in content
        assert "ANTHROPIC_API_KEY=new_anthropic_val" in content
        assert "TAVILY_API_KEY=new_tavily_val" in content
        assert "# Trailing comment" in content

        keys = get_env_file_keys(env_file)
        assert keys["EXISTING_VAR"] == "alpha"
        assert keys["ANTHROPIC_API_KEY"] == "new_anthropic_val"
        assert keys["TAVILY_API_KEY"] == "new_tavily_val"


def test_remove_key_from_env_surgical():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / ".gitignore").write_text(".env\n", encoding="utf-8")
        env_file = root / ".env"

        initial_content = (
            "# Environment config\n"
            "ANTHROPIC_API_KEY=key_a\n"
            "GEMINI_API_KEY=key_b\n"
            "TAVILY_API_KEY=key_c\n"
        )
        env_file.write_text(initial_content, encoding="utf-8")

        remove_key_from_env(env_path=env_file, key_to_remove="GEMINI_API_KEY", repo_root=root)

        content = env_file.read_text(encoding="utf-8")
        assert "# Environment config" in content
        assert "ANTHROPIC_API_KEY=key_a" in content
        assert "GEMINI_API_KEY" not in content
        assert "TAVILY_API_KEY=key_c" in content


def test_save_keys_fails_if_env_not_in_gitignore():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / ".gitignore").write_text("# No env\n", encoding="utf-8")
        env_file = root / ".env"

        with pytest.raises(PermissionError, match="Security Check Failed"):
            save_keys_to_env(
                env_path=env_file,
                updates={"ANTHROPIC_API_KEY": "key"},
                repo_root=root,
            )


def test_scoped_env_override_lifecycle_and_restoration():
    var_existing = "TEST_SCOPED_VAR_EXISTING"
    var_new = "TEST_SCOPED_VAR_NEW"

    os.environ[var_existing] = "original_val"
    if var_new in os.environ:
        del os.environ[var_new]

    try:
        with scoped_env_override({var_existing: "temporary_val", var_new: "new_temp_val"}):
            assert os.environ[var_existing] == "temporary_val"
            assert os.environ[var_new] == "new_temp_val"

        assert os.environ[var_existing] == "original_val"
        assert var_new not in os.environ

        with pytest.raises(RuntimeError):
            with scoped_env_override({var_existing: "error_temp", var_new: "error_new"}):
                assert os.environ[var_existing] == "error_temp"
                raise RuntimeError("Simulated failure")

        assert os.environ[var_existing] == "original_val"
        assert var_new not in os.environ

    finally:
        os.environ.pop(var_existing, None)
        os.environ.pop(var_new, None)


def test_scoped_env_override_back_to_back_isolation():
    key_name = "ANTHROPIC_API_KEY"
    original_val = os.environ.get(key_name)

    try:
        with scoped_env_override({key_name: "session_fake_key_1111111"}):
            assert os.environ[key_name] == "session_fake_key_1111111"

        assert os.environ.get(key_name) == original_val

        with scoped_env_override({key_name: "session_fake_key_2222222"}):
            assert os.environ[key_name] == "session_fake_key_2222222"

        assert os.environ.get(key_name) == original_val
    finally:
        if original_val is None:
            os.environ.pop(key_name, None)
        else:
            os.environ[key_name] = original_val



def test_key_connection_empty_key():
    from api_key_manager import test_key_connection
    success, code, msg = test_key_connection("ANTHROPIC_API_KEY", "")
    assert success is False
    assert code is None
    assert "No API key" in msg


def test_key_connection_mocked(monkeypatch):
    from unittest.mock import MagicMock
    import httpx
    from api_key_manager import test_key_connection

    # Mock 200 response
    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.text = "SECRET_PAYLOAD_BODY_THAT_MUST_NEVER_LEAK"

    # Mock 401 response
    mock_resp_401 = MagicMock()
    mock_resp_401.status_code = 401
    mock_resp_401.text = "ERROR_SECRET_KEY_INVALID"

    def mock_get(self, url, *args, **kwargs):
        if "anthropic" in str(url):
            return mock_resp_200
        return mock_resp_401

    monkeypatch.setattr(httpx.Client, "get", mock_get)
    monkeypatch.setattr(httpx.Client, "post", lambda self, url, *args, **kwargs: mock_resp_200)


    # Anthropic success
    ok, code, msg = test_key_connection("ANTHROPIC_API_KEY", "sk-ant-testkey")
    assert ok is True
    assert code == 200
    assert "SECRET_PAYLOAD" not in msg

    # Gemini failure (mock_get returns 401 for non-anthropic)
    ok_gem, code_gem, msg_gem = test_key_connection("GEMINI_API_KEY", "gemini-testkey")
    assert ok_gem is False
    assert code_gem == 401
    assert "ERROR_SECRET_KEY" not in msg_gem

