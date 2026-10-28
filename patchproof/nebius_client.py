"""Small OpenAI-compatible client for Nebius Token Factory inference."""

import os
import time
from dataclasses import dataclass

from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, OpenAI, RateLimitError


DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
DEFAULT_MODEL = "nvidia/Nemotron-3_5-Lightning"


class MissingCredentialsError(RuntimeError):
    """No local Nebius key is configured."""


class NebiusRequestError(RuntimeError):
    """A safe, user-readable inference error without request headers or secrets."""


@dataclass(frozen=True)
class InferenceResponse:
    model: str
    text: str
    elapsed_sec: float
    usage: dict | None = None


class NebiusClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL):
        if not api_key.strip():
            raise MissingCredentialsError("NEBIUS_API_KEY is not set.")
        if not base_url.startswith("https://"):
            raise ValueError("NEBIUS_BASE_URL must use HTTPS.")
        if not model.strip():
            raise ValueError("NEBIUS_MODEL must be set to an available model ID.")
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=35.0, max_retries=0)

    @classmethod
    def from_environment(cls) -> "NebiusClient":
        key = os.environ.get("NEBIUS_API_KEY", "").strip()
        if not key:
            raise MissingCredentialsError("NEBIUS_API_KEY is not set.")
        return cls(
            api_key=key,
            base_url=os.environ.get("NEBIUS_BASE_URL", DEFAULT_BASE_URL).strip(),
            model=os.environ.get("NEBIUS_MODEL", DEFAULT_MODEL).strip(),
        )

    def generate_patch(self, *, issue: str, source: str, test_output: str) -> InferenceResponse:
        prompt = (
            "Repair this bundled Python bug. Return only a standard unified diff, with exactly these file headers:\n"
            "--- a/bug.py\n+++ b/bug.py\n"
            "Modify only bug.py. Do not include markdown fences, explanations, shell commands, or test changes.\n\n"
            f"Issue:\n{issue[:4000]}\n\nCurrent bug.py:\n```python\n{source[:12000]}\n```\n\n"
            f"Actual test output from the latest attempt:\n{test_output[-6000:]}\n"
        )
        started = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You propose minimal Python fixes. Your output is untrusted and will be strictly validated."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1600,
                temperature=0,
            )
        except AuthenticationError as exc:
            raise NebiusRequestError("Nebius authentication failed. Check the configured API key.") from exc
        except RateLimitError as exc:
            raise NebiusRequestError("Nebius rate limit or quota reached. Try again later or check account limits.") from exc
        except APITimeoutError as exc:
            raise NebiusRequestError("Nebius inference timed out.") from exc
        except APIConnectionError as exc:
            raise NebiusRequestError("Could not connect to Nebius Token Factory. Check network access.") from exc
        except APIStatusError as exc:
            if exc.status_code == 404:
                message = "Nebius endpoint or configured model was not found. Verify the model ID and account access."
            elif exc.status_code == 403:
                message = "Nebius denied access. Check account and model permissions."
            else:
                message = f"Nebius API returned HTTP {exc.status_code}."
            raise NebiusRequestError(message) from exc
        except Exception as exc:
            # Do not surface SDK exception text: it may include request details.
            raise NebiusRequestError(f"Nebius request failed ({type(exc).__name__}).") from exc

        elapsed = time.perf_counter() - started
        text = response.choices[0].message.content if response.choices else None
        if not isinstance(text, str) or not text.strip():
            raise NebiusRequestError("Nebius returned no patch text.")
        usage = response.usage.model_dump() if response.usage is not None else None
        return InferenceResponse(model=response.model or self.model, text=text, elapsed_sec=elapsed, usage=usage)
