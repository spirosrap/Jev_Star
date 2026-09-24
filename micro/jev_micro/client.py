"""Native, batched Jev Choice requests. Never log credentials or HTTP bodies."""

import asyncio
import math
import os
import re
from pathlib import Path

import httpx


# OpenRouter's TypeSafe-compatible route. Same Jev model and /v1/systemone
# payload. Override with JEV_API_ENDPOINT.
ENDPOINT = os.environ.get(
    "JEV_API_ENDPOINT",
    "https://openrouter.ai/api/v1/systemone",
).strip()


class JevError(RuntimeError):
    pass


def load_api_key(config_file: Path) -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key and config_file.is_file():
        match = re.search(r"(?m)^openrouter\s*:\s*(\S+)\s*$",
                          config_file.read_text(encoding="utf-8-sig"))
        key = match.group(1) if match else ""
    if not key:
        key = (os.environ.get("AI_GATEWAY_API_KEY", "").strip()
               or os.environ.get("TYPESAFE_API_KEY", "").strip())
        if not key and config_file.is_file():
            match = re.search(r"(?m)^api\s*:\s*(\S+)\s*$",
                              config_file.read_text(encoding="utf-8-sig"))
            key = match.group(1) if match else ""
    if not key:
        raise JevError("Set OPENROUTER_API_KEY or supply a config file with an openrouter: entry.")
    return key


def validate_response(data, payload):
    """Require exactly one legal Choice per requested living unit."""
    try:
        questions = payload["questions"]
        answers = data["answers"]
        if set(answers) != set(questions):
            raise ValueError("question_keys")
        clean = {}
        for key, question in questions.items():
            answer = answers[key]
            criteria = question["criteria"]
            if answer["type"] != "choice" or answer["choice"] not in criteria:
                raise ValueError("choice")
            probabilities = answer["probabilities"]
            if set(probabilities) != set(criteria):
                raise ValueError("probabilities")
            values = [answer["confidence"], *probabilities.values()]
            if any(type(v) not in (int, float) or not math.isfinite(v)
                   or not 0 <= v <= 1 for v in values):
                raise ValueError("range")
            if not math.isclose(sum(probabilities.values()), 1, abs_tol=0.02):
                raise ValueError("distribution")
            clean[key] = {"type": "choice", "choice": answer["choice"],
                          "confidence": answer["confidence"],
                          "probabilities": dict(probabilities)}
        raw_usage = data.get("usage", {})
        if not isinstance(raw_usage, dict):
            raise ValueError("usage")
        usage = {k: v for k, v in raw_usage.items() if type(v) is int}
        if any(v < 0 for v in usage.values()):
            raise ValueError("usage")
        return {"model": data.get("model"), "answers": clean, "usage": usage}
    except (KeyError, TypeError, ValueError, AttributeError):
        raise JevError("invalid_response") from None


class JevClient:
    def __init__(self, api_key, timeout=5.0, transport=None):
        self.timeout = timeout
        self.http = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout, transport=transport)

    async def choose(self, payload):
        try:
            response = await asyncio.wait_for(
                self.http.post(ENDPOINT, json=payload), timeout=self.timeout)
        except (asyncio.TimeoutError, httpx.TimeoutException):
            raise JevError("request_timeout") from None
        except httpx.HTTPError:
            raise JevError("transport_error") from None
        if response.status_code != 200:
            raise JevError(f"http_{response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise JevError("invalid_json") from None
        return validate_response(data, payload)

    async def close(self):
        await self.http.aclose()
