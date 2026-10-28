"""Make a real Nebius Token Factory model-list and inference request."""

from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv


load_dotenv()

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
DEFAULT_MODEL = "nvidia/Nemotron-3_5-Lightning"


def request_json(url: str, api_key: str, payload: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("API returned an unexpected JSON response.")
    return result


def safe_api_message(exc: HTTPError, api_key: str) -> str:
    """Return a bounded API error message with any echoed key redacted."""
    messages = {
        401: "Authentication failed (HTTP 401). Check the local API key.",
        403: "Access denied (HTTP 403). Check account or model access.",
        404: "Endpoint or model not found (HTTP 404). Check the base URL and model ID.",
        429: "Rate limit or quota reached (HTTP 429). Try again later or check account limits.",
    }
    if exc.code in messages:
        return messages[exc.code]

    try:
        body = exc.read(4096).decode("utf-8", errors="replace")
        parsed = json.loads(body)
        error = parsed.get("error", {}) if isinstance(parsed, dict) else {}
        detail = error.get("message") if isinstance(error, dict) else None
    except (OSError, json.JSONDecodeError):
        detail = None
    if isinstance(detail, str):
        detail = detail.replace(api_key, "[REDACTED]").replace("\n", " ").strip()
        if detail:
            lowered = detail.lower()
            if "model" in lowered and any(term in lowered for term in ("not found", "unavailable", "not available")):
                return f"Configured model is unavailable (HTTP {exc.code}): {detail[:240]}"
            return f"Nebius API rejected the request (HTTP {exc.code}): {detail[:240]}"
    return f"Nebius API request failed (HTTP {exc.code})."


def network_error_message(exc: BaseException) -> str:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "Request timed out after 30 seconds."
    if isinstance(exc, ssl.SSLError):
        return "TLS connection failed. Check the network and endpoint configuration."
    reason = getattr(exc, "reason", exc)
    return f"Network request failed ({type(reason).__name__})."


def main() -> int:
    api_key = os.environ.get("NEBIUS_API_KEY", "").strip()
    if not api_key:
        print("NEBIUS_API_KEY is not set. Configure it in your local environment before running this smoke test.", file=sys.stderr)
        return 2

    base_url = os.environ.get("NEBIUS_BASE_URL", DEFAULT_BASE_URL).strip()
    if not base_url.endswith("/"):
        base_url += "/"
    model = os.environ.get("NEBIUS_MODEL", DEFAULT_MODEL).strip()
    parsed_base_url = urlparse(base_url)
    if parsed_base_url.scheme != "https" or not parsed_base_url.netloc:
        print("NEBIUS_BASE_URL must be a valid HTTPS URL.", file=sys.stderr)
        return 2
    if not model:
        print("NEBIUS_MODEL is empty. Set it to an available Token Factory model ID.", file=sys.stderr)
        return 2

    try:
        models = request_json(urljoin(base_url, "models"), api_key)
        model_data = models.get("data")
        if not isinstance(model_data, list):
            print("Model discovery returned an unexpected response; cannot verify configured model.", file=sys.stderr)
            return 1
        model_ids = [entry.get("id") for entry in model_data if isinstance(entry, dict)]
        print(f"Model discovery succeeded: {len(model_ids)} model IDs returned.")
        if model not in model_ids:
            print(f"Configured model is not listed for this account: {model}", file=sys.stderr)
            print("Inference outcome: not attempted (model unavailable in discovery response).", file=sys.stderr)
            return 1
        print(f"Configured model is available: {model}")

        started = time.perf_counter()
        result = request_json(
            urljoin(base_url, "chat/completions"),
            api_key,
            {
                "model": model,
                "messages": [{"role": "user", "content": "Reply with exactly: PatchProof live inference works."}],
                "max_tokens": 40,
                "temperature": 0,
            },
        )
        elapsed = time.perf_counter() - started
        choices = result.get("choices", [])
        content = choices[0].get("message", {}).get("content") if choices else None
        if not isinstance(content, str) or not content.strip():
            print(f"Inference outcome: failed for model {model}; response contained no text content.", file=sys.stderr)
            return 1
        print(f"Inference outcome: succeeded for model {result.get('model', model)} in {elapsed:.2f}s.")
        print(f"Real response: {content[:300]}")
        return 0
    except HTTPError as exc:
        print(safe_api_message(exc, api_key), file=sys.stderr)
        print(f"Request outcome: failed for model {model}.", file=sys.stderr)
        return 1
    except (URLError, TimeoutError, socket.timeout, ssl.SSLError) as exc:
        print(network_error_message(exc), file=sys.stderr)
        print(f"Request outcome: failed for model {model}.", file=sys.stderr)
        return 1
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Nebius returned an invalid response ({type(exc).__name__}).", file=sys.stderr)
        print(f"Request outcome: failed for model {model}.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
