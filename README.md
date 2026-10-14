# Deadlock Detective

**A Deadlock Detection, Process Monitoring, and Recovery Simulation System**

Deadlock Detective is a Python-based desktop application developed as an Operating Systems academic project. It combines deadlock simulation, Wait-For Graph analysis, process monitoring, explainable recommendations, recovery simulation, and incident reporting in a Tkinter GUI.

**Workflow:** Monitor → Track → Detect → Explain → Recommend → Recover → Verify → Report

## Features

### 1. Deadlock Simulation and Detection
- Simulates processes competing for shared locks.
- Supports lock acquisition, requests, releases, and FIFO lock hand-off.
- Builds a Wait-For Graph (WFG).
- Detects deadlocks using a hand-written Depth-First Search (DFS) cycle detection algorithm.
- Identifies potential lock-order risks from historical acquisition patterns.

### 2. Graph Visualization
- Displays process dependencies and lock labels.
- Highlights cycles associated with deadlocks.
- Shows cycle information and whether the graph is current or stale.

### 3. Recovery Laboratory
- Compares potential recovery candidates before applying a simulated recovery.
- Predicts graph changes and compares them with the actual result.
- Simulates process abortion and lock release.
- Re-runs deadlock detection to verify the outcome.

### 4. What-If Laboratory
- Edits and validates simulation scenarios.
- Supports manual lock release.
- Compares the graph before and after an operation.

### 5. Live Process Monitoring
- Monitors real operating-system processes using `psutil`.
- Displays process ID, parent process ID, CPU usage, CPU time, memory usage, thread count, and status.
- Supports searching, sorting, filtering, and viewing process details.
- Maintains resource usage history.

### 6. Smart Recommendations
- Provides rule-based recommendations based on CPU and memory measurements.
- Displays the evidence, thresholds, and reasoning behind recommendations.
- Identifies protected processes and unavailable monitoring states.
- Requires confirmation before performing real-process actions.

### 7. Process Management
- Supports process termination, priority changes, suspension, and resumption where available.
- Rechecks process identity before an action.
- Protects selected processes and records action outcomes.

**Important:** Process management can affect real applications. Review the confirmation dialog carefully before performing an action.

### 8. Incidents and Reports
- Records detected simulation deadlocks and their timelines.
- Exports incident reports in JSON format.
- Exports process snapshots in CSV format.
- Includes detection, diagnosis, recovery, and verification information.

### 9. Guided Demonstration and Settings
- Includes a guided demonstration of the detection and recovery workflow.
- Provides configurable monitoring thresholds and intervals.
- Includes an in-app guide to relevant Operating Systems concepts.

## Technologies Used

- **Python** for application logic.
- **Tkinter** for the desktop GUI.
- **NetworkX** for representing and managing graph data.
- **psutil** for operating-system process monitoring.
- **pytest** for automated testing.
- **JSON and CSV** for scenarios, settings, and reports.

## Project Structure

```text
deadlock-detective/
├── main.py
├── session.py
├── services.py
├── requirements.txt
├── pytest.ini
├── simulator/
├── detector/
├── diagnosis/
├── recovery/
├── lab/
├── process_monitor/
├── incidents/
├── ui/
├── config/
├── data/
├── reports/
└── tests/
```

- `main.py`: Application entry point.
- `session.py`: Simulation session and state management.
- `services.py`: Application service integration.
- `simulator/`: Process and lock simulation.
- `detector/`: Wait-For Graph construction and cycle detection.
- `diagnosis/`: Deadlock explanations and recommendations.
- `recovery/`: Simulated recovery operations.
- `lab/`: Recovery comparisons and what-if scenarios.
- `process_monitor/`: Live monitoring and process management.
- `incidents/`: Incident lifecycle and report generation.
- `ui/`: Tkinter interface and dashboard tabs.
- `config/`: Local monitoring settings.
- `data/`: Simulation scenarios.
- `tests/`: Automated tests.

## Requirements

- Python 3.10 or newer.
- Windows, Linux, or macOS with a supported Tkinter installation.
- Dependencies listed in `requirements.txt`.

## Installation and Running

### Windows using VS Code and PowerShell

**1. Clone the repository**

```powershell
git clone https://github.com/shayna-exe/deadlock-detective.git
cd deadlock-detective
```

Alternatively, download the repository as a ZIP from GitHub and extract it.

**2. Create a virtual environment**

```powershell
python -m venv .venv
```

**3. Activate the environment**

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, use Command Prompt:

```bat
.venv\Scripts\activate.bat
```

**4. Install dependencies**

```powershell
python -m pip install -r requirements.txt
```

**5. Run the application**

```powershell
python main.py
```

### Run the tests

With the virtual environment activated, execute:

```powershell
python -m pytest -v
```

The tests use simulated process data for process-monitoring and action logic. GUI tests may require a working graphical display.

## How to Use

1. Open the **Overview** tab to view the application status and available features.
2. Open **Deadlock Simulator**, load a scenario, and step through or run its events.
3. Select **Detect Deadlocks** to analyze the current Wait-For Graph.
4. Open the **Recovery Lab** to compare recovery candidates and simulate recovery.
5. Use the **What-If Lab** to edit scenarios and compare outcomes.
6. Start monitoring in **Live Processes** to view real process resource usage.
7. Review the evidence in **Smart Recommendations** before considering any real-process action.
8. Use **Incidents & Reports** to export reports and process snapshots.

Live process monitoring does not start automatically, and real-process actions require confirmation.

## How Deadlock Detection Works

A Wait-For Graph represents processes as nodes. An edge from process `P1` to process `P2` means that `P1` is waiting for a lock currently held by `P2`.

For example:

```text
P1 holds A
P2 holds B
P1 requests B
P2 requests A

P1 → P2 → P1
```

This cycle represents a deadlock in the simulated system because both processes are waiting for locks held by the other.

The DFS detector uses three node states:

- **WHITE:** Not visited.
- **GRAY:** Currently on the DFS path.
- **BLACK:** Finished processing.

An edge to a GRAY node indicates a cycle. The algorithm runs in **O(V + E)** time, where `V` is the number of graph vertices and `E` is the number of edges.

## Simulation vs. Real Process Monitoring

Deadlock Detective has two distinct subsystems:

- **Simulation:** Detects deadlocks among processes and locks modeled inside the application.
- **Live monitoring:** Collects resource measurements from real operating-system processes.

The live monitor cannot inspect arbitrary applications' internal mutexes, so it does not independently detect deadlocks inside those applications.

Likewise, historical lock-order conflicts indicate a potential risk, not proof of a current deadlock.

## Limitations

- Deadlock detection applies to the simulated lock system, not arbitrary running applications.
- The simulator models exclusive locks and uses a simplified resource model.
- Recommendations use configurable CPU and memory thresholds; they do not understand an application's purpose.
- Low CPU usage does not prove that an application is unnecessary.
- Memory savings from closing a process are estimates.
- Process-management operations vary by operating system and permissions.
- Recovery uses a heuristic for selecting a victim and does not guarantee an optimal choice.

## Future Improvements

- Expand the simulation model to cover additional resource-allocation scenarios.
- Improve visualization and analysis of resource dependencies.
- Extend automated testing across supported operating systems.
- Improve packaging and distribution as a standalone desktop application.

## License

No license has been specified yet.
