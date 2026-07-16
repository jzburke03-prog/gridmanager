#!/usr/bin/env python3
"""Grid Keeper launcher.

Run this file with ANY Python (PyCharm's Run button, `python3 run_game.py`,
or `./run_game.py`) — it re-executes itself with the project's .venv39
interpreter, which is the one that has pygame installed. The default .venv
is Python 3.14, which pygame does not support yet.
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(ROOT, ".venv39", "Scripts" if os.name == "nt" else "bin",
                        "python.exe" if os.name == "nt" else "python3")
GAME_DIR = os.path.join(ROOT, "energy_grid_game")
GAME = os.path.join(GAME_DIR, "main.py")


def main():
    if not os.path.exists(VENV_PY):
        if os.name == "nt":
            sys.exit(
                "Game environment not found. Create it with:\n"
                "  py -3.9 -m venv .venv39\n"
                "  .venv39\\Scripts\\pip install -r requirements.txt"
            )
        sys.exit(
            "Game environment not found. Create it with:\n"
            "  /usr/bin/python3 -m venv .venv39\n"
            "  .venv39/bin/pip install -r requirements.txt"
        )

    # If we're not already the venv interpreter, replace this process with it.
    if os.path.realpath(sys.executable) != os.path.realpath(VENV_PY):
        if os.name == "nt":
            # Windows has no execv-style process replacement; spawn and wait instead.
            import subprocess
            result = subprocess.run([VENV_PY, GAME] + sys.argv[1:])
            sys.exit(result.returncode)
        os.execv(VENV_PY, [VENV_PY, GAME] + sys.argv[1:])

    # Already the right interpreter: run the game in-process.
    sys.path.insert(0, GAME_DIR)
    import main as game_main
    game_main.main()


if __name__ == "__main__":
    main()
