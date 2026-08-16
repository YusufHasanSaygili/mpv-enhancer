"""Run the complete local quality gate without a command shell."""

import json
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
QUALITY_BUILD_DIRECTORY = REPOSITORY_ROOT / "build"
SECRET_SCAN_EXCLUSIONS = r"(^|[\\/])uv\.lock$"


def main() -> int:
    QUALITY_BUILD_DIRECTORY.mkdir(parents=True, exist_ok=True)
    checks = (
        (
            "Ruff format",
            [sys.executable, "-m", "ruff", "format", "--check", "."],
        ),
        ("Ruff lint", [sys.executable, "-m", "ruff", "check", "."]),
        ("Mypy", [sys.executable, "-m", "mypy", "src/mpv_enhancer"]),
        (
            "Pytest and coverage",
            [
                sys.executable,
                "-m",
                "pytest",
                "--basetemp=build/pytest-quality",
                "--cov=mpv_enhancer",
                "--cov-report=term-missing",
            ],
        ),
    )
    for label, command in checks:
        print(f"\n==> {label}", flush=True)
        result = subprocess.run(command, cwd=REPOSITORY_ROOT, check=False)
        if result.returncode != 0:
            return result.returncode

    print("\n==> Secret scan", flush=True)
    return _run_secret_scan()


def _run_secret_scan() -> int:
    command = [
        sys.executable,
        "-m",
        "detect_secrets",
        "scan",
        "--exclude-files",
        SECRET_SCAN_EXCLUSIONS,
    ]
    result = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return result.returncode

    scan = json.loads(result.stdout)
    findings = scan.get("results", {})
    if findings:
        print("Potential secrets detected:", file=sys.stderr)
        for filename, matches in findings.items():
            for match in matches:
                print(
                    f"  {filename}:{match['line_number']} {match['type']}",
                    file=sys.stderr,
                )
        return 1
    print("No potential secrets detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
