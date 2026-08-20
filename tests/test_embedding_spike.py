import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _load_spike_module() -> ModuleType:
    script = REPOSITORY_ROOT / "scripts" / "windows_embedding_spike.py"
    spec = importlib.util.spec_from_file_location("windows_embedding_spike", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def test_spike_builds_a_structured_uint32_wid_command() -> None:
    spike = _load_spike_module()

    arguments = spike.build_mpv_arguments(0x1_0000_0001)

    assert "--wid=1" in arguments
    assert "--no-config" in arguments
    assert "--input-vo-keyboard=no" in arguments
    assert arguments[-1].startswith("av://lavfi:testsrc")
    assert all(";" not in argument for argument in arguments)


def test_embedding_adr_records_evidence_risks_and_rollback() -> None:
    architecture = (REPOSITORY_ROOT / "docs" / "architecture.md").read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "ADR-0001",
        "Accepted",
        "Windows 11",
        "--wid",
        "Resize",
        "Full-screen",
        "process plus JSON IPC",
        "Risks",
        "Rollback point",
    )
    for fragment in required_fragments:
        assert fragment in architecture
