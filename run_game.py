#!/usr/bin/env python3
"""Grid Keeper launcher.

Run this file with ANY Python (PyCharm's Run button, `python3 run_game.py`,
or `./run_game.py`). When the project's .venv39 exists, it re-executes there;
otherwise it uses the current interpreter if the game dependencies are already
available.
"""
import importlib
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(ROOT, ".venv39", "Scripts" if os.name == "nt" else "bin",
                        "python.exe" if os.name == "nt" else "python3")
GAME_DIR = os.path.join(ROOT, "energy_grid_game")
GAME = os.path.join(GAME_DIR, "main.py")


def _setup_message():
    if os.name == "nt":
        return (
            "Game environment not found. Create it with:\n"
            "  py -3.9 -m venv .venv39\n"
            "  .venv39\\Scripts\\pip install -r requirements.txt"
        )
    return (
        "Game environment not found. Create it with:\n"
        "  /usr/bin/python3 -m venv .venv39\n"
        "  .venv39/bin/pip install -r requirements.txt"
    )


def _current_interpreter_has_deps():
    try:
        for module_name in ("pygame", "moderngl", "numpy"):
            importlib.import_module(module_name)
    except ImportError as exc:
        return False, exc
    return True, None


def _run_with_current_interpreter():
    sys.path.insert(0, GAME_DIR)
    import main as game_main
    game_main.main()


def main():
    if not os.path.exists(VENV_PY):
        has_deps, import_error = _current_interpreter_has_deps()
        if has_deps:
            _run_with_current_interpreter()
            return
        sys.exit(f"{_setup_message()}\n\nCurrent interpreter dependency check failed: {import_error}")

    # If we're not already the venv interpreter, replace this process with it.
    if os.path.realpath(sys.executable) != os.path.realpath(VENV_PY):
        if os.name == "nt":
            # Windows has no execv-style process replacement; spawn and wait instead.
            import subprocess
            result = subprocess.run([VENV_PY, GAME] + sys.argv[1:])
            sys.exit(result.returncode)
        os.execv(VENV_PY, [VENV_PY, GAME] + sys.argv[1:])

    # Already the right interpreter: run the game in-process.
    _run_with_current_interpreter()


if __name__ == "__main__":
    main()
