"""Canonical provider payload derivation shared by the API and streaming paths."""

from __future__ import annotations

from typing import Any


def build_provider_messages(task_inputs: dict[str, Any]) -> list[dict[str, str]] | None:
    """Build the canonical provider message list from workflow task inputs.

    Single source of truth shared by the API path (ProviderExecutor) and the
    streaming path (_StreamingRuntimeBridge) so every provider receives the
    same message model:
      1. workflow-built structured messages are forwarded verbatim (the
         composed system prompt is already first as a SYSTEM message when a
         persona is active);
      2. otherwise the composed system prompt becomes a SYSTEM message and the
         raw request becomes a USER message;
      3. otherwise None, which signals a bare-prompt fallback.
    """
    messages = task_inputs.get("messages")
    if messages:
        return list(messages)
    system_prompt = task_inputs.get("system_prompt")
    prompt = task_inputs.get("prompt") or task_inputs.get("description") or ""
    if system_prompt:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
    return None
