"""Run the workspace CLI without relying on editable .pth loading."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
