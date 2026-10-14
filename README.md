# Deadlock Detective

**An Intelligent Deadlock Detection, Process Monitoring and Application Lifecycle Management System** (Operating Systems academic project).

Workflow: **MONITOR → TRACK → DETECT → EXPLAIN → RECOMMEND → SIMULATE/RECOVER → VERIFY → REPORT**

The program combines three connected capabilities, and keeps them clearly separate:

| | What it works on | Where |
|---|---|---|
| **A. Deadlock simulation and analysis** | *Simulated* processes and locks inside this program | Simulator, Recovery Lab, What-If Lab tabs |
| **B. Live process monitoring** | *Real* operating-system processes, measured with `psutil` | Live Processes, Resource History tabs |
| **C. Explainable recommendations and safe management** | Real processes, advice only; actions need your confirmation | Smart Recommendations tab |

> **Important honesty note.** The simulator and the live monitor are different subsystems. A deadlock found in the simulator is **not** a deadlock inside a real application. Process monitoring cannot see another program's internal mutexes (that would need instrumentation of that program's locks). A real-process snapshot attached to an incident is *context*, not evidence that those programs are involved.

## Features

- Deterministic lock simulator (ACQUIRE / REQUEST / RELEASE, FIFO hand-off), Wait-For Graph, **hand-written DFS** cycle detection, lock-order risk analysis, plain-language diagnosis, simulated recovery, JSON report (all preserved from the original project).
- **Graph view**: red cycle edges *and* an "in cycle" text marker, lock labels on edges, textual cycle, a **CURRENT / STALE / not-run** indicator, click a process or lock label to inspect it, full legend.
- **Recovery Laboratory**: compares every simulated victim *before* applying (locks held, which waiter receives each lock, in-cycle?, predicted graph), then shows predicted vs actual outcome and *why* the graph changed. Ranking criteria are documented and are a heuristic, not claimed optimal.
- **What-If Laboratory**: scenario editor with full validation (names, events, dry-run replay), manual simulated lock release, before/after graph comparison. Invalid input can never corrupt the running simulation.
- **Live process monitor** (background thread + thread-safe polling): name, PID, parent PID, status, CPU %, cumulative CPU time, RAM, memory %, threads, sample time; search, sort, filter, details panel, configurable interval; honest *warming up* / unavailable / error states.
- **Smart recommendations** (transparent rules, not machine learning): Keep Running, High CPU, High Memory, Potentially Idle, Consider Closing, Consider Lowering Priority, Investigate, Protected, Monitoring Unavailable. Each card shows evidence, rule and thresholds, evidence strength, next step, limitations and a labelled memory *estimate*.
- **Safe real actions**: terminate, force kill (only after a terminate timed out; Linux/macOS), lower priority, suspend, resume. Explicit confirmation showing name, PID and warning, identity re-check before acting, protected-process list, action log, never automatic.
- **Resource history**: bounded real samples, native Tkinter line charts, top consumers, sustained low activity, recommendation timeline.
- **Incidents**: opened automatically when the simulator detects a deadlock; timeline (detection, diagnosis, recommendation, telemetry, decision, recovery, verification); works with or without live monitoring.
- **Reports**: JSON schema 2.0 (superset of the original report) and CSV process snapshot. No command lines, user names or executable paths are exported.
- **Guided demonstration**, **settings with validation**, and an in-app **OS concept guide** that ties every concept to the implementation.

## Folder structure

```
deadlock-detective/
  main.py  session.py  services.py        entry point, simulation controller, app wiring
  requirements.txt  pytest.ini  README.md
  simulator/  detector/  diagnosis/       (original engine, unchanged in behaviour)
  recovery/
    recovery_manager.py                   simulated abort (original)
    lab.py                                recovery comparison / prediction
  lab/
    whatif.py                             graph comparison, scenario editor validation
    demo.py                               guided demonstration state machine
  process_monitor/
    models.py                             ProcessSample / SystemSample
    monitor.py                            psutil collection (robust, injectable psutil)
    activity_tracker.py                   bounded history, sustained-activity maths
    recommendations.py                    rule engine (R1..R9) with explanations
    protection.py                         protected / unidentifiable process logic
    actions.py                            guarded terminate / priority / suspend / resume
    service.py                            background worker + snapshots
    settings.py                           thresholds with validation
    exporters.py                          CSV export, "telemetry unavailable" block
  incidents/
    service.py  models.py                 incident lifecycle and timeline
    report.py                             schema-2.0 report, validation, safe writer
  ui/                                     Tkinter: dashboard, graph_view, one module per tab,
                                          viewmodels.py (Tk-free helpers), widgets.py
  config/monitor_settings.json            created when you press "Apply and save"
  data/scenarios.json  reports/  tests/
```

## Installation on Windows (VS Code, PowerShell)

Requires Python 3.10 or newer from python.org (the installer includes Tkinter).

1. Extract the ZIP, e.g. to `C:\Projects\deadlock-detective`.
2. In VS Code: **File → Open Folder…** and choose that folder. Open a terminal (**Terminal → New Terminal**, PowerShell).
3. Create and activate a virtual environment, then install:

```powershell
python --version
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

4. Run the application: `python main.py`
5. Run the tests: `python -m pytest -v`

**If activation is blocked** ("running scripts is disabled"): run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use Command Prompt with `.venv\Scripts\activate.bat`. Alternatively skip activation and call `.venv\Scripts\python.exe main.py`.

**If Tkinter is missing** (`Tkinter is not available`): re-run the python.org installer, choose *Modify*, and make sure **tcl/tk and IDLE** is ticked. On Ubuntu/Debian: `sudo apt install python3-tk`. On macOS use the python.org installer.

**If `psutil` is missing**, the simulator still works; the monitoring tabs explain that `pip install -r requirements.txt` is needed.

## Using the application

1. **Overview** shows simulation status, live monitoring status, top consumers and recommendations. Press **Start demo** for a guided walk-through (load → events → detect → highlight → explain → compare → recover → verify → export).
2. **Deadlock Simulator**: pick a scenario, Load, Step / Run All, **Detect Deadlocks**. Detection is deliberately manual; after the state changes the graph says **STALE**.
3. **Recovery Lab / What-If Lab**: compare victims, apply a simulated recovery, edit scenarios, release locks.
4. **Live Processes**: press **Start monitoring**. CPU % appears after the second sample (the first reading of any process is not meaningful, so it is shown as *warming up*). Idle-style recommendations need several minutes of samples.
5. **Smart Recommendations**: read the evidence; any real operation asks for confirmation first.
6. **Incidents & Reports**: export the JSON incident report or a CSV snapshot.

Monitoring never starts by itself and no process action ever runs at startup.

## What the monitor measures (and does not)

- **CPU %**: current use over the last sample as a share of *all* cores (100 = every core busy). psutil's raw per-core figure can exceed 100 and is kept as `cpu_percent_per_core`.
- **CPU time**: cumulative CPU seconds used since the process started. Not elapsed time, not a percentage.
- **RAM**: resident set size. It may include pages shared with other processes, so it can overstate what closing a program would free.
- Not collected: "is the window responding" (cannot be measured reliably through psutil), command-line arguments, user names.
- PID reuse is handled: identity is `(PID, start time)`.

## Recommendation rules (all thresholds are editable in Settings)

First matching rule wins; others become "also noted".

| Rule | Category | Fires when (defaults) |
|---|---|---|
| R1 | Protected / Action Not Recommended | protected name, reserved PID, OS folder, kernel thread, this program, or unreadable name |
| R2 | Monitoring Unavailable | access denied, no CPU baseline yet, or fewer than 5 samples |
| R3 | Consider Lowering Priority | CPU ≥ 85 % for ≥ 60 s, priority not already lowered |
| R4 | High CPU Usage | CPU ≥ 60 % for ≥ 30 s |
| R5 | Investigate | memory grew ≥ 200 MB over 10 readings without shrinking |
| R6 | Consider Closing | CPU ≤ 1 % for ≥ 600 s and ≥ 200 MB held |
| R7 | Potentially Idle Resource Consumer | CPU ≤ 1 % for ≥ 300 s and ≥ 100 MB held |
| R8 | High Memory Usage | ≥ 1500 MB or ≥ 10 % of physical memory |
| R9 | Keep Running | nothing else matched |

Evidence strength (Weak / Moderate / Strong) describes the measurements only. Low CPU never proves an application is unused, and memory savings are always labelled *estimates*. No performance improvement is ever promised.

## Real-process actions: safety and platform differences

Every action: needs `confirmed=True` from a dialog showing the exact process, PID and warning; is refused for protected, unreadable or unidentifiable processes; re-reads the process immediately before acting and refuses if the PID now belongs to a different process; is logged (name, PID, operation, outcome) without private data.

| Operation | Linux / macOS | Windows |
|---|---|---|
| Terminate | SIGTERM; the program may save and exit | psutil's terminate is **immediate** (no chance to save); the warning says so |
| Force kill | SIGKILL, only after a terminate timed out | not offered (terminate is already forceful) |
| Lower priority | nice value 10 | Below Normal priority class |
| Suspend / Resume | SIGSTOP / SIGCONT | Windows suspend API |

Permissions: you can normally manage only your own processes; other users' processes report *access denied* and are never acted on. These operations can behave differently across systems; I have not been able to test them on a real Windows machine. If this program exits while it has suspended something, it offers to resume it.

## Report format (schema 2.0)

The original report keys are kept unchanged at the top level. New keys: `schema_version`, `report_type`, `generated_at` (ISO 8601), `data_sources`, `incident` (id, timeline, simulation evidence, recoveries, verification), `real_process_telemetry` (with `available` flag and a disclaimer), `resource_monitoring` (availability, errors, thresholds used), `recommendation_evidence`, `real_process_actions`, `before_after`, `what_if_operations`, `final_cycle_detection`. Reports are validated before writing, written atomically, and an existing file is never silently replaced when called programmatically (a numbered name is used; the Save dialog asks before overwriting).

## Running the tests

```powershell
python -m pytest -v
```

Tests use a **fake `psutil`**: no real process is read, suspended or killed. GUI tests need Tkinter and a display and are skipped otherwise (`xvfb-run -a python -m pytest` on Linux).

## How the simulation works

- Processes and locks are declared by a scenario; a scenario is a list of events such as `{"process": "P1", "op": "REQUEST", "lock": "B"}`.
- **ACQUIRE** takes a lock that must be free. **REQUEST** takes it if free, otherwise the process becomes **BLOCKED** and joins the lock's wait queue. **RELEASE** gives a lock back (owner only).
- Locks are exclusive, non-reentrant and non-preemptible. A blocked process cannot do anything until it is granted its lock.
- **Scheduling policy:** FIFO per lock. On release (or when an aborted process's locks are freed) the lock goes straight to the first waiter, which becomes RUNNING again. This is recorded as a `GRANT` history entry.
- Invalid operations (acquire a held lock, release someone else's lock, request your own lock, act while blocked/aborted, unknown process/lock/operation) raise a clear `SimulationError` and leave the state completely unchanged.
- Every step appends readable entries to the history.

## How the Wait-For Graph works

Nodes are processes. An edge `P1 → P2` means "P1 is blocked waiting for a lock that P2 holds", and carries the lock name. With P1 holding A, P2 holding B, P1 requesting B and P2 requesting A:

```
P1 --(B)--> P2
P2 --(A)--> P1        cycle: P1 → P2 → P1
```

Because the locks are non-preemptible and a blocked process cannot release anything, a cycle in this graph means a real deadlock **in the simulated system**. (This is the single-instance-resource case from OS textbooks, where cycle = deadlock.)

## How DFS detects a cycle

`detector/cycle_detector.py` colours each node WHITE (unvisited), GRAY (on the current DFS path) or BLACK (finished). Starting a DFS from every unvisited node (so disconnected parts are covered), it follows edges. If an edge leads to a **GRAY** node, we have walked back onto our own path, so the path from that node to the current node is a cycle. Edges to BLACK nodes are safe. Cycles are reported rotated to start at their smallest name, so the same cycle is never listed twice. NetworkX only stores the graph; it is never asked to find cycles.

A self-loop (a process waiting for itself) is reported as a cycle of length 1. The simulator forbids this situation (re-requesting a lock you hold is rejected as a "wait for yourself" error), so it can only appear in a hand-built graph. `CycleDetector` also remembers the last result so pressing Detect twice on an unchanged state reports "same deadlock as before" rather than a new one.

## Actual deadlock vs. historical lock-order warning

| | Wait-For Graph cycle | Lock-order analysis |
|---|---|---|
| Looks at | the **current** state | the **history** of lock acquisitions |
| Finding | a deadlock exists now | two code paths use opposite orders (A→B and B→A) |
| Certainty | confirmed (in the model) | **potential** risk only |
| Shown as | "Deadlock detected", red cycle | "Potential risk" in its own tab, labelled "not proof of a current deadlock" |

The lock-order scenario shows it: P1 takes A then B, finishes, and only then does P2 take B then A. There is no deadlock now, yet the opposite orders are a risk if they ever overlap.

## Simulated recovery and its limits

Recovery aborts a chosen process (or the suggested victim: the deadlocked process holding the fewest locks, ties by name). The process is removed from any wait queue, all its locks are released, and each released lock is handed to its first waiter (FIFO). The abort and every hand-off appear in the history, the before/after states and changes are displayed, and detection runs again to verify the cycle is gone.

Limits: it only edits the simulation; there is no rollback of the victim's "work" (the model has none); aborting a process outside the cycle is allowed but will not fix the deadlock (the result says so); victim choice is a simple heuristic, not an optimal one.

## Example execution (two-process deadlock)

```
Step 1  P1 ACQUIRE A     -> ACQUIRED
Step 2  P2 ACQUIRE B     -> ACQUIRED
Step 3  P1 REQUEST B     -> BLOCKED (held by P2)
Step 4  P2 REQUEST A     -> BLOCKED (held by P1)
Detect: P1 → P2 → P1  "The loop closed at step 4 when P2 requested lock A."
Recovery: abort P1 -> lock A handed to P2 -> P2 running, no cycle.
```

## Known limitations

- Simulator: exclusive locks only (no read/write locks or TryLock); one lock wait per process; recursive DFS (fine for classroom-sized graphs); the history is unbounded.
- Monitoring cannot detect deadlocks inside other applications.
- Recommendations are threshold rules over CPU and memory; they cannot know what a program is for. Idle detection needs minutes of samples.
- Process priority, suspension and termination differ between operating systems (see above).
- The recovery heuristic (fewest locks held) is not optimal.

## Verification status (please read)

Where this version was built, **Tkinter and `pytest` were not installed and there was no network**. So:

- The new backend (monitor, tracker, rules, actions, service, incidents, reports, lab, demo, view-models) was tested with the repository's tests executed by a small stand-in test runner; the original tests also ran that way. **Please run `python -m pytest -v` yourself with real pytest.**
- The **GUI was not run on a real display**. Its code compiles, and its logic was executed against a permissive stand-in for Tkinter, which proves no NameError/AttributeError in those paths but says nothing about layout, appearance, or real Tk behaviour. Expect to find small visual or widget issues on first run; the GUI tests in `tests/test_gui_*.py` will run for you on Windows.
- Real `psutil` collection was only exercised read-only in a Linux sandbox. It has not been run on Windows.

## Relationship to the original Go repository

`go-deadlock` wraps `sync.Mutex`/`RWMutex` and instruments real programs. Key ideas I studied (mainly `deadlock.go`) and how they map here:

| go-deadlock | Deadlock Detective |
|---|---|
| `lockOrder.cur`: which goroutines currently hold each lock | `LockState` owners/holders |
| `lockOrder.order`: a map of "A before B" pairs; `preLock` reports "Inconsistent locking" when the reverse pair exists | `LockOrderAnalyzer` (same idea, recorded at the attempt like `preLock`, flagged as *potential*) |
| Recursive locking check in `preLock` | the simulator rejects a process requesting a lock it already holds |
| `DeadlockTimeout` watcher (`dw.register` / `onDeadlockTimeout`): "waiting too long" heuristic | replaced by an exact Wait-For Graph cycle check, since the simulation knows every wait |
| Stack traces, goroutine dumps, `OnPotentialDeadlock` callback, `MaxMapSize`, timer pooling, build tags, `TryLock`, `RWMutex` | Go/runtime-specific; **not implemented** |

This is a re-implementation of the concepts in Python, not a port, and it does not claim feature parity. The wait-for-graph cycle detection is a textbook technique that go-deadlock itself does *not* use.

## Viva cheat sheet

- **Architecture:** simulator (state + rules) → graph builder → DFS detector → diagnosis/recommendations → recovery, all orchestrated by `SimulationSession`; `AppServices` adds monitoring, incidents and reports; the Tkinter UI only displays and routes actions. Tests drive the same objects.
- **WFG:** processes are nodes; `P1 → P2` means P1 waits for a lock P2 holds. A cycle means circular wait. With non-preemptible exclusive locks and blocked processes unable to release, circular wait is a deadlock (Coffman conditions: mutual exclusion, hold-and-wait, no preemption, circular wait).
- **DFS:** WHITE/GRAY/BLACK colouring; an edge into a GRAY node is a back edge, which closes a cycle. O(V + E).
- **Recovery:** abort a victim, release its locks, hand each lock to the first waiter, re-run detection. Process termination is one of the two classic recovery strategies (the other is resource preemption). The Recovery Lab predicts the outcome on a copy of the state first.
- **Actual vs potential:** WFG cycle = deadlock now; opposite lock orders in history = risk later.
- **Simulation vs monitoring:** the simulator models locks inside this program; the monitor measures other programs but cannot see their mutexes. They are labelled separately everywhere.
- **CPU % vs CPU time vs RAM:** current share of capacity vs cumulative CPU seconds vs resident memory.
- **Why rules, not AI:** every recommendation is an if-rule over measured values with printed thresholds, so it can be explained and audited.
