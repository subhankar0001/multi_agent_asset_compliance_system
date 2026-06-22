#!/usr/bin/env python3
"""
Local Lambda invocation helper via SAM CLI.

Usage:
    # Run the full app locally (not Lambda-style, just FastAPI)
    python scripts/local_invoke.py --mode uvicorn

    # Invoke a specific endpoint via SAM local
    python scripts/local_invoke.py --mode sam --endpoint /api/v1/ingest

Requires:
    - SAM CLI installed: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html
    - .env file with all required environment variables
    - pip install -r requirements-dev.txt
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent


def run_uvicorn() -> None:
    """Start FastAPI with uvicorn for local development (hot reload enabled)."""
    print("Starting FastAPI with uvicorn (hot reload enabled)...")
    print("API docs: http://localhost:8000/docs")
    print("Health:   http://localhost:8000/health\n")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--reload",
            "--port",
            "8000",
            "--host",
            "0.0.0.0",
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )


def run_sam_local(endpoint: str) -> None:
    """Start SAM local API (emulates Lambda + API Gateway)."""
    env_file = PROJECT_ROOT / ".env.json"
    if not env_file.exists():
        print(
            "ERROR: .env.json not found. SAM local requires environment variables in JSON format.\n"
            "Create .env.json from .env:\n"
            "  python scripts/local_invoke.py --mode env-to-json"
        )
        sys.exit(1)

    print(f"Starting SAM local API on port 3000...")
    print(f"Endpoint: http://localhost:3000{endpoint}\n")
    subprocess.run(
        [
            "sam",
            "local",
            "start-api",
            "--env-vars",
            str(env_file),
            "--port",
            "3000",
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )


def env_to_json() -> None:
    """Convert .env file to SAM-compatible .env.json format."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        print("ERROR: .env file not found.")
        sys.exit(1)

    env_vars: dict = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env_vars[key.strip()] = value.strip()

    # SAM env-vars format: {"FunctionName": {"KEY": "value"}}
    sam_env = {"ComplianceFunction": env_vars}
    output_path = PROJECT_ROOT / ".env.json"
    output_path.write_text(json.dumps(sam_env, indent=2))
    print(f"Written SAM env vars to {output_path}")
    print("NOTE: .env.json is gitignored — do not commit it.")


def main() -> None:
    """Parse arguments and dispatch to the appropriate mode."""
    parser = argparse.ArgumentParser(description="Local development helper for Asset Compliance AI")
    parser.add_argument(
        "--mode",
        choices=["uvicorn", "sam", "env-to-json"],
        default="uvicorn",
        help="Run mode: uvicorn (default), sam local, or convert .env to .env.json",
    )
    parser.add_argument(
        "--endpoint",
        default="/api/v1/ingest",
        help="Endpoint path for SAM local mode",
    )
    args = parser.parse_args()

    if args.mode == "uvicorn":
        run_uvicorn()
    elif args.mode == "sam":
        run_sam_local(args.endpoint)
    elif args.mode == "env-to-json":
        env_to_json()


if __name__ == "__main__":
    main()
