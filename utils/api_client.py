"""
Claude API client — built on the official anthropic SDK.
Features: prompt caching, asyncio rate limiting, automatic retry, token logging.
Uses asyncio.get_running_loop() (not deprecated get_event_loop()).
"""
import asyncio
import json
from typing import Any, List, Optional

import anthropic

from utils.exceptions import APIError, APITimeoutError, RateLimitError
from utils.logger import log_api_call, run_log

MODEL = "claude-sonnet-4-6"

# HTTP status codes that warrant a retry
_RETRYABLE_STATUS = {429, 529}
_MAX_RETRIES = 3


class ClaudeClient:
    """
    Async Claude API client. Instantiate once and pass to all agents.
    Enforces max_concurrent parallel calls and a minimum delay between calls.
    """

    def __init__(self, api_key: str, max_concurrent: int = 3, delay: float = 2.0):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._delay = delay
        self._last_call: float = 0.0

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 1000,
        temperature: float = 0.3,
        agent: str = "unknown",
        job_id: Optional[str] = None,
        lane: Optional[str] = None,
        cache_system_prompt: bool = True,
    ) -> str:
        """
        Call Claude API with rate limiting, prompt caching, and token logging.
        Retries up to 3 times on 429/529 using the retry-after header.
        cache_system_prompt=True wraps system prompt in cache_control so
        repeated calls with the same prompt hit the cache (~10% of input cost).
        """
        system_content = (
            [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]
            if cache_system_prompt
            else system_prompt
        )

        async with self._semaphore:
            return await self._call_with_retry(
                system_content=system_content,
                user_message=user_message,
                max_tokens=max_tokens,
                temperature=temperature,
                agent=agent,
                job_id=job_id,
                lane=lane,
            )

    async def _call_with_retry(
        self,
        system_content,
        user_message: str,
        max_tokens: int,
        temperature: float,
        agent: str,
        job_id: Optional[str],
        lane: Optional[str],
    ) -> str:
        loop = asyncio.get_running_loop()

        for attempt in range(_MAX_RETRIES):
            # Enforce minimum delay between calls
            elapsed = loop.time() - self._last_call
            if elapsed < self._delay:
                await asyncio.sleep(self._delay - elapsed)

            start = loop.time()
            try:
                response = await self._client.messages.create(
                    model=MODEL,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system_content,
                    messages=[{"role": "user", "content": user_message}],
                )

                duration_ms = (loop.time() - start) * 1000
                self._last_call = loop.time()

                usage = response.usage
                cached = getattr(usage, "cache_read_input_tokens", 0) or 0

                log_api_call(
                    agent=agent,
                    model=MODEL,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    duration_ms=duration_ms,
                    job_id=job_id,
                    lane=lane,
                    cached_tokens=cached,
                )

                return response.content[0].text

            except anthropic.RateLimitError as exc:
                retry_after = _parse_retry_after(exc, default=60.0)
                if attempt < _MAX_RETRIES - 1:
                    run_log("WARNING", agent, f"Rate limit hit, retrying in {retry_after}s (attempt {attempt + 1})", job_id=job_id)
                    await asyncio.sleep(retry_after)
                    continue
                raise RateLimitError(
                    f"Rate limit exceeded after {_MAX_RETRIES} attempts",
                    retry_after=retry_after,
                    agent=agent,
                    job_id=job_id,
                )

            except anthropic.APITimeoutError as exc:
                raise APITimeoutError(f"API timeout: {exc}", agent=agent, job_id=job_id)

            except anthropic.APIStatusError as exc:
                if exc.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES - 1:
                    wait = _parse_retry_after(exc, default=30.0)
                    run_log("WARNING", agent, f"API {exc.status_code}, retrying in {wait}s", job_id=job_id)
                    await asyncio.sleep(wait)
                    continue
                raise APIError(
                    f"API error {exc.status_code}: {exc.message}",
                    status_code=exc.status_code,
                    agent=agent,
                    job_id=job_id,
                )

        raise APIError("Exhausted retries", agent=agent, job_id=job_id)


    async def call_mcp_tool(
        self,
        server_url: str,
        server_name: str,
        prompt: str,
        agent: str = "unknown",
    ) -> Any:
        """
        Call a remote MCP tool via Claude as a proxy.

        Anthropic's infrastructure connects to the MCP server, so
        host-allowlisted endpoints (e.g. mcp.dice.com) work correctly.
        Returns the raw parsed content from the first non-error mcp_tool_result
        block, or an empty list if no tool result was produced.
        """
        async with self._semaphore:
            loop = asyncio.get_running_loop()
            elapsed = loop.time() - self._last_call
            if elapsed < self._delay:
                await asyncio.sleep(self._delay - elapsed)

            try:
                response = await self._client.beta.messages.create(
                    model=MODEL,
                    max_tokens=4096,
                    mcp_servers=[{
                        "name": server_name,
                        "type": "url",
                        "url": server_url,
                    }],
                    messages=[{"role": "user", "content": prompt}],
                    betas=["mcp-client-2025-04-04"],
                )
                self._last_call = loop.time()
            except anthropic.APIStatusError as exc:
                raise APIError(
                    f"MCP API error {exc.status_code}: {exc.message}",
                    status_code=exc.status_code,
                    agent=agent,
                )

            # Extract the first successful mcp_tool_result block
            for block in response.content:
                if getattr(block, "type", None) == "mcp_tool_result":
                    if block.is_error:
                        raise APIError(
                            f"MCP tool returned error: {block.content}",
                            agent=agent,
                        )
                    content = block.content
                    if isinstance(content, str):
                        return json.loads(content)
                    # List[BetaTextBlock]
                    for item in content:
                        if hasattr(item, "text"):
                            return json.loads(item.text)

            # Fallback: Claude described the results as text — parse last text block
            for block in reversed(response.content):
                if getattr(block, "type", None) == "text":
                    try:
                        return json.loads(block.text)
                    except json.JSONDecodeError:
                        pass

            return []


def _parse_retry_after(exc, default: float) -> float:
    """Extract retry-after seconds from an API exception header, or return default."""
    try:
        return float(exc.response.headers.get("retry-after", default))
    except Exception:
        return default
