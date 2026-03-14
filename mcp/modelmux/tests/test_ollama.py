"""Unit tests for Ollama adapter.

Run with: cd mcp/modelmux && uv run python tests/test_ollama.py
"""

import sys

sys.path.insert(0, "src")

from vyane.adapters.ollama import OllamaAdapter


def test_binary_name():
    adapter = OllamaAdapter()
    assert adapter._binary_name() == "ollama"
    assert adapter.provider_name == "ollama"
    print("[PASS] binary name")


def test_build_command_default_model():
    adapter = OllamaAdapter()
    cmd = adapter.build_command("hello", "/tmp")
    assert cmd == ["ollama", "run", "llama3.2", "hello"]
    print("[PASS] build command default model")


def test_build_command_custom_model():
    adapter = OllamaAdapter()
    cmd = adapter.build_command("hello", "/tmp", extra_args={"model": "deepseek-r1"})
    assert cmd == ["ollama", "run", "deepseek-r1", "hello"]
    print("[PASS] build command custom model (deepseek-r1)")


def test_build_command_qwen():
    adapter = OllamaAdapter()
    cmd = adapter.build_command("test", "/tmp", extra_args={"model": "qwen2.5:72b"})
    assert cmd == ["ollama", "run", "qwen2.5:72b", "test"]
    print("[PASS] build command qwen model")


def test_parse_output_plain_text():
    adapter = OllamaAdapter()
    lines = ["Hello! How can I help you today?", "Let me know if you need anything."]
    text, session_id, error = adapter.parse_output(lines)
    assert text == "Hello! How can I help you today?\nLet me know if you need anything."
    assert session_id == ""
    assert error == ""
    print("[PASS] parse plain text output")


def test_parse_output_filters_download_progress():
    adapter = OllamaAdapter()
    lines = [
        "pulling manifest",
        "pulling abc123... 45% 1.2GB/2.7GB",
        "verifying sha256 digest",
        "Hello! I'm ready to help.",
    ]
    text, session_id, error = adapter.parse_output(lines)
    assert "pulling" not in text
    assert "verifying" not in text
    assert "Hello! I'm ready to help." in text
    print("[PASS] filters download progress lines")


def test_parse_output_empty():
    adapter = OllamaAdapter()
    text, session_id, error = adapter.parse_output([])
    assert text == ""
    assert session_id == ""
    assert error == ""
    print("[PASS] parse empty output")


def test_adapter_in_registry():
    from vyane.adapters import ADAPTERS

    assert "ollama" in ADAPTERS
    assert ADAPTERS["ollama"] is OllamaAdapter
    print("[PASS] ollama in ADAPTERS registry")


def main():
    tests = [
        test_binary_name,
        test_build_command_default_model,
        test_build_command_custom_model,
        test_build_command_qwen,
        test_parse_output_plain_text,
        test_parse_output_filters_download_progress,
        test_parse_output_empty,
        test_adapter_in_registry,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}: {e}")
            failed += 1

    print(f"\n{'=' * 50}")
    print(f"Ollama tests: {passed}/{passed + failed} passed")
    print("=" * 50)
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
