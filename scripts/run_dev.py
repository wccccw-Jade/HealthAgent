import sys
from pathlib import Path

import uvicorn

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))


def main() -> None:
    # Keep relative .env, SQLite, and checkpoint paths anchored at the project root
    # even when this script is launched from another directory.
    import os

    os.chdir(ROOT_DIR)
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=[str(ROOT_DIR)],
    )


if __name__ == "__main__":
    main()
