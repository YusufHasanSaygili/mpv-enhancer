"""Launch and close the installed application shell for release verification."""

from mpv_enhancer.app import create_application
from mpv_enhancer.ui.main_window import MainWindow


def main() -> int:
    """Return success when the installed shell becomes visible and closes."""
    app = create_application(["mpv-enhancer-release-smoke"])
    window = MainWindow()
    window.show()
    app.processEvents()
    if not window.isVisible():
        raise RuntimeError("The MPV Enhancer release shell did not become visible.")
    window.close()
    app.processEvents()
    if window.isVisible():
        raise RuntimeError("The MPV Enhancer release shell did not close cleanly.")
    print("Installed MPV Enhancer shell launch smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
