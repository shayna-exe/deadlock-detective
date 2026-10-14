"""Deadlock Detective - entry point.  Run with:  python main.py"""
import sys
from pathlib import Path

if sys.version_info < (3, 10):
    sys.exit("Deadlock Detective needs Python 3.10 or newer.")

SCENARIO_FILE = Path(__file__).resolve().parent / "data" / "scenarios.json"


def main() -> int:
    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError:
        print("Tkinter is not available in this Python installation.", file=sys.stderr)
        return 1
    try:
        import networkx  # noqa: F401
    except ImportError:
        print("NetworkX is missing. Run:  pip install -r requirements.txt", file=sys.stderr)
        return 1

    from session import SimulationSession
    from simulator import ScenarioError, load_scenarios
    from ui.dashboard import Dashboard

    root = tk.Tk()
    try:
        session = SimulationSession(load_scenarios(SCENARIO_FILE))
    except ScenarioError as exc:
        messagebox.showerror("Deadlock Detective", f"Could not load scenarios:\n{exc}")
        root.destroy()
        return 1
    Dashboard(root, session)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
