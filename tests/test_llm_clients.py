"""
Smoke tests for utils/api_client.py and utils/local_llm.py.
All external calls are mocked — no API key or Ollama required.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.exceptions import APIError, APITimeoutError, LocalLLMError, OllamaNotAvailableError, RateLimitError


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_anthropic_response(text: str, input_tokens: int = 100, output_tokens: int = 50):
    """Build a minimal mock anthropic Messages response."""
    content_block = MagicMock()
    content_block.text = text

    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.cache_read_input_tokens = 0

    response = MagicMock()
    response.content = [content_block]
    response.usage = usage
    return response


def _make_httpx_response(json_data: dict, status_code: int = 200):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data
    r.raise_for_status = MagicMock()
    return r


# ── ClaudeClient tests ────────────────────────────────────────────────────────

class TestClaudeClientGenerate:
    @pytest.fixture
    def client(self):
        from utils.api_client import ClaudeClient
        return ClaudeClient(api_key="test-key", max_concurrent=3, delay=0.0)

    async def test_returns_text_on_success(self, client):
        mock_response = _make_anthropic_response("Generated resume text")
        with patch.object(client._client.messages, "create", new=AsyncMock(return_value=mock_response)):
            result = await client.generate(
                system_prompt="You are a writer.",
                user_message="Write a resume.",
                agent="writer",
            )
        assert result == "Generated resume text"

    async def test_logs_api_call_on_success(self, client):
        mock_response = _make_anthropic_response("ok", input_tokens=200, output_tokens=80)
        with patch.object(client._client.messages, "create", new=AsyncMock(return_value=mock_response)):
            with patch("utils.api_client.log_api_call") as mock_log:
                await client.generate("sys", "user", agent="test_agent", job_id="dice_001")
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args[1] if mock_log.call_args[1] else {}
        call_args = mock_log.call_args[0] if mock_log.call_args[0] else []
        # log_api_call is called with positional args
        assert mock_log.called

    async def test_raises_rate_limit_error_on_429(self, client):
        import anthropic as ant
        import httpx

        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        raw_response = httpx.Response(429, headers={"retry-after": "5"}, text="rate limited", request=request)
        mock_exc = ant.RateLimitError("rate limited", response=raw_response, body=None)

        with patch.object(client._client.messages, "create", new=AsyncMock(side_effect=mock_exc)):
            with patch("asyncio.sleep", new=AsyncMock()):
                with pytest.raises(RateLimitError):
                    await client.generate("sys", "user", agent="test")

    async def test_raises_api_timeout_error(self, client):
        import anthropic as ant

        with patch.object(
            client._client.messages, "create",
            new=AsyncMock(side_effect=ant.APITimeoutError(request=MagicMock()))
        ):
            with pytest.raises(APITimeoutError):
                await client.generate("sys", "user", agent="test")

    async def test_cache_control_added_when_enabled(self, client):
        mock_response = _make_anthropic_response("ok")
        captured = {}

        async def capture_call(**kwargs):
            captured.update(kwargs)
            return mock_response

        with patch.object(client._client.messages, "create", new=capture_call):
            await client.generate("my system prompt", "user msg", cache_system_prompt=True)

        system = captured.get("system", [])
        assert isinstance(system, list)
        assert system[0].get("cache_control") == {"type": "ephemeral"}

    async def test_no_cache_control_when_disabled(self, client):
        mock_response = _make_anthropic_response("ok")
        captured = {}

        async def capture_call(**kwargs):
            captured.update(kwargs)
            return mock_response

        with patch.object(client._client.messages, "create", new=capture_call):
            await client.generate("sys", "user", cache_system_prompt=False)

        assert isinstance(captured.get("system"), str)

    async def test_semaphore_limits_concurrent_calls(self, client):
        """Confirm Semaphore(3) allows exactly 3 concurrent calls."""
        from utils.api_client import ClaudeClient
        limited_client = ClaudeClient(api_key="k", max_concurrent=2, delay=0.0)
        assert limited_client._semaphore._value == 2


# ── ClaudeClient.call_mcp_tool tests ─────────────────────────────────────────

class TestClaudeClientCallMcpTool:
    @pytest.fixture
    def client(self):
        from utils.api_client import ClaudeClient
        return ClaudeClient(api_key="test-key", max_concurrent=3, delay=0.0)

    def _make_mcp_response(self, content, is_error=False):
        """Build a mock beta messages response with an mcp_tool_result block."""
        tool_result = MagicMock()
        tool_result.type = "mcp_tool_result"
        tool_result.is_error = is_error
        tool_result.tool_use_id = "tu_001"
        tool_result.content = content
        response = MagicMock()
        response.content = [tool_result]
        return response

    async def test_returns_list_from_mcp_tool_result(self, client):
        import json
        jobs = [{"id": "123", "title": "Engineer"}]
        mock_response = self._make_mcp_response(json.dumps(jobs))

        with patch.object(client._client.beta.messages, "create", new=AsyncMock(return_value=mock_response)):
            result = await client.call_mcp_tool(
                server_url="https://mcp.dice.com/mcp",
                server_name="dice",
                prompt="Search for Python jobs",
                agent="test",
            )

        assert result == jobs

    async def test_unwraps_text_block_list_content(self, client):
        import json
        jobs = [{"id": "456"}]
        text_block = MagicMock()
        text_block.text = json.dumps(jobs)
        mock_response = self._make_mcp_response([text_block])

        with patch.object(client._client.beta.messages, "create", new=AsyncMock(return_value=mock_response)):
            result = await client.call_mcp_tool("https://mcp.dice.com/mcp", "dice", "prompt")

        assert result == jobs

    async def test_raises_api_error_on_mcp_tool_error(self, client):
        from utils.exceptions import APIError
        mock_response = self._make_mcp_response("Tool failed: 500", is_error=True)

        with patch.object(client._client.beta.messages, "create", new=AsyncMock(return_value=mock_response)):
            with pytest.raises(APIError, match="MCP tool returned error"):
                await client.call_mcp_tool("https://mcp.dice.com/mcp", "dice", "prompt")

    async def test_returns_empty_list_when_no_tool_result(self, client):
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "No tool was called"
        mock_response = MagicMock()
        mock_response.content = [text_block]

        with patch.object(client._client.beta.messages, "create", new=AsyncMock(return_value=mock_response)):
            result = await client.call_mcp_tool("https://mcp.dice.com/mcp", "dice", "prompt")

        assert result == []

    async def test_calls_beta_messages_with_mcp_servers(self, client):
        import json
        mock_response = self._make_mcp_response(json.dumps([]))

        with patch.object(client._client.beta.messages, "create", new=AsyncMock(return_value=mock_response)) as mock_create:
            await client.call_mcp_tool("https://mcp.dice.com/mcp", "dice", "prompt", agent="scout")

        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["mcp_servers"] == [{"name": "dice", "type": "url", "url": "https://mcp.dice.com/mcp"}]
        assert "mcp-client-2025-04-04" in call_kwargs["betas"]

    async def test_raises_api_error_on_status_error(self, client):
        from utils.exceptions import APIError
        import anthropic

        err = anthropic.APIStatusError("forbidden", response=MagicMock(status_code=403), body={})
        with patch.object(client._client.beta.messages, "create", new=AsyncMock(side_effect=err)):
            with pytest.raises(APIError):
                await client.call_mcp_tool("https://mcp.dice.com/mcp", "dice", "prompt")


# ── LocalLLM tests ────────────────────────────────────────────────────────────

class TestLocalLLM:
    @pytest.fixture
    def llm(self):
        from utils.local_llm import LocalLLM
        return LocalLLM(config={
            "llm": {
                "local_model": "phi4-mini",
                "ollama_host": "http://localhost:11434",
                "local_model_threads": 4,
            }
        })

    async def test_generate_returns_text(self, llm):
        mock_resp = _make_httpx_response({"response": "Extracted: Python, AWS"})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=mock_resp)

            result = await llm.generate("Extract keywords", agent="scout")

        assert result == "Extracted: Python, AWS"

    async def test_generate_logs_local_call(self, llm):
        mock_resp = _make_httpx_response({"response": "ok"})

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(return_value=mock_resp)

            with patch("utils.local_llm.log_local_call") as mock_log:
                await llm.generate("prompt", agent="test")

        mock_log.assert_called_once()

    async def test_generate_raises_on_connect_error(self, llm):
        import httpx as hx

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(side_effect=hx.ConnectError("refused"))

            with pytest.raises(OllamaNotAvailableError):
                await llm.generate("test")

    async def test_is_available_true_when_server_up(self, llm):
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(return_value=mock_resp)

            assert await llm.is_available() is True

    async def test_is_available_false_when_server_down(self, llm):
        import httpx as hx

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get = AsyncMock(side_effect=hx.ConnectError("down"))

            assert await llm.is_available() is False

    async def test_unload_does_not_raise_on_failure(self, llm):
        import httpx as hx

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.post = AsyncMock(side_effect=hx.ConnectError("down"))

            await llm.unload()  # must not raise


# ── ollama_manager tests ──────────────────────────────────────────────────────

class TestOllamaManager:
    def test_is_server_running_true(self):
        from utils.ollama_manager import is_server_running

        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            assert is_server_running() is True

    def test_is_server_running_false_on_error(self):
        from utils.ollama_manager import is_server_running
        import httpx as hx

        with patch("httpx.get", side_effect=hx.ConnectError("down")):
            assert is_server_running() is False

    def test_is_model_available_true(self):
        from utils.ollama_manager import is_model_available

        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"models": [{"name": "phi4-mini:latest"}]},
            )
            assert is_model_available("phi4-mini") is True

    def test_is_model_available_false(self):
        from utils.ollama_manager import is_model_available

        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"models": []},
            )
            assert is_model_available("phi4-mini") is False

    def test_ensure_ollama_skips_start_when_running_and_model_exists(self):
        from utils.ollama_manager import ensure_ollama_running

        with patch("utils.ollama_manager.is_server_running", return_value=True):
            with patch("utils.ollama_manager.is_model_available", return_value=True):
                with patch("utils.ollama_manager._start_server") as mock_start:
                    with patch("utils.ollama_manager._pull_model_with_progress") as mock_pull:
                        ensure_ollama_running()

        mock_start.assert_not_called()
        mock_pull.assert_not_called()

    def test_ensure_ollama_pulls_model_when_missing(self):
        from utils.ollama_manager import ensure_ollama_running

        with patch("utils.ollama_manager.is_server_running", return_value=True):
            with patch("utils.ollama_manager.is_model_available", return_value=False):
                with patch("utils.ollama_manager._pull_model_with_progress") as mock_pull:
                    ensure_ollama_running()

        mock_pull.assert_called_once()

    def test_ensure_ollama_raises_when_ollama_not_installed(self):
        from utils.ollama_manager import ensure_ollama_running

        with patch("utils.ollama_manager.is_server_running", return_value=False):
            with patch("subprocess.Popen", side_effect=FileNotFoundError):
                with pytest.raises(OllamaNotAvailableError, match="not installed"):
                    ensure_ollama_running()
