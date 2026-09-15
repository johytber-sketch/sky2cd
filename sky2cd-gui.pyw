"""Double-clickable launcher for the sky2cd desktop GUI (no console window).

Run with pythonw.exe, or simply double-click this file on Windows.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sky2cd.gui import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
