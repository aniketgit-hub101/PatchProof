# PatchProof

PatchProof is an evidence-first Python bug-repair demo. It runs the bundled
fixture's real tests before requesting a patch, applies a model-proposed unified
diff to a temporary copy, reruns the fixture's fixed test command, and reports
the observed output. A generated patch is never treated as proof by itself.

The local MVP contains three small deterministic fixtures. Execution is limited
to these trusted, bundled examples; the app does not accept repository uploads
or model-selected commands. Temporary directories and subprocesses are not a
security sandbox, so this is a local hackathon demo, not a safe service for
untrusted code.

## Requirements

- Python 3.13 is supported by this project (the code uses the standard library
  plus the packages in `requirements.txt`). Python 3.11+ is recommended.
- `requirements.txt` pins the direct application and test dependencies to the
  versions exercised locally. Pip still resolves their transitive dependencies;
  this file is not a complete environment lockfile.
- A Nebius Token Factory API key with access to the configured model is needed
  for live inference. Without it, the app still runs real baseline tests and
  reports `UNABLE_TO_VERIFY`; it does not use a mock model response.

## Windows PowerShell setup

From the repository root:

```powershell
py -3.13 --version
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` locally and set `NEBIUS_API_KEY`. Do not commit `.env` or paste the
key into chat. The other defaults are:

```dotenv
NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1/
NEBIUS_MODEL=nvidia/Nemotron-3_5-Lightning
```

If you prefer not to write the key to a file, set it in the current PowerShell
session using a hidden prompt, then launch the app from that same session:

```powershell
$secure = Read-Host "Nebius API key" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $env:NEBIUS_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    $secure.Dispose()
}
```

## Run

Run the bundled tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Compile the Python files:

```powershell
Get-ChildItem -Recurse -Filter *.py | Where-Object { $_.FullName -notmatch '\\.venv\\' } | ForEach-Object { .\.venv\Scripts\python.exe -m py_compile $_.FullName }
```

Run the Nebius connectivity smoke test:

```powershell
.\.venv\Scripts\python.exe scripts\nebius_smoke_test.py
```

Start the app:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

## Workflow and verdicts

1. Select a bundled bug and start repair.
2. PatchProof executes the predetermined `python -m pytest` command in a
   temporary copy and records the baseline.
3. If the baseline reproduces the fixture bug and a Nebius key is configured,
   the selected NVIDIA Nemotron model proposes a unified diff.
4. PatchProof rejects path traversal, modifications outside the fixture source
   allowlist, malformed hunks, and context that does not exactly match.
5. The patch is applied to a fresh temporary copy and the same actual tests
   run. Up to three attempts are allowed; retries receive the previous actual
   test failure.
6. `VERIFIED` is shown only when tests execute and pass, the patch is valid, and
   protected tests remain unchanged. API/configuration failures are
   `UNABLE_TO_VERIFY`; an attempted repair that does not pass is `FAILED`.

The test subprocess receives a restricted environment so API credentials are
not inherited by fixture code. This reduces accidental exposure but is not a
security boundary against arbitrary code.

## Layout

```text
app.py
patchproof/       workflow, Nebius client, runner, diff validation, contracts
fixtures/         three trusted cases and protected tests
tests/            unit and real fixture-runner tests
scripts/          Nebius smoke test
```

## Current verification status

The repository reports observed local test and compile results when commands
are run. No benchmark or deployment result is claimed here. Live inference
requires a configured key and successful access to the selected model.
