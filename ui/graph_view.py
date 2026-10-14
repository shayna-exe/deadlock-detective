"""Wait-For Graph drawing on a Tkinter Canvas.

Everything drawn comes from the NetworkX graph passed to ``GraphView.update_graph``;
only the legend strip is static (it explains symbols, it does not depict state).
"""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import Dict, Iterable, List, Sequence, Set, Tuple

NODE_R = 28
COLORS = {
    "bg": "#ffffff",
    "text": "#1f2933",
    "muted": "#52606d",
    "edge": "#52606d",
    "cycle": "#b42318",
    "running": ("#e6f0fa", "#2b5c8a"),
    "blocked": ("#fdf0d5", "#b7791f"),
    "aborted": ("#e5e7eb", "#9aa5b1"),
}


def circular_layout(names: Sequence[str], width: float, height: float) -> Dict[str, Tuple[float, float]]:
    """Place nodes evenly on a circle (pure function, no Tk needed)."""
    n = len(names)
    cx, cy = width / 2, height / 2 - 6
    if n == 0:
        return {}
    if n == 1:
        return {names[0]: (cx, cy)}
    # Ellipse that uses the available space but leaves room for the node,
    # its "holds" caption and the edge labels.
    rx = max(40.0, width / 2 - NODE_R - 70)
    ry = max(40.0, height / 2 - NODE_R - 34)
    start = math.pi if n == 2 else -math.pi / 2
    return {
        name: (cx + rx * math.cos(start + 2 * math.pi * i / n),
               cy + ry * math.sin(start + 2 * math.pi * i / n))
        for i, name in enumerate(names)
    }


def cycle_edge_set(cycles: Iterable[Sequence[str]]) -> Set[Tuple[str, str]]:
    """Edges (u, v) belonging to any of the given cycles."""
    edges: Set[Tuple[str, str]] = set()
    for cycle in cycles:
        cycle = list(cycle)
        edges.update(zip(cycle, cycle[1:] + cycle[:1]))
    return edges


def _unit(dx: float, dy: float) -> Tuple[float, float]:
    d = math.hypot(dx, dy) or 1.0
    return dx / d, dy / d


class GraphView(ttk.Frame):
    """Canvas that shows the current Wait-For Graph plus a legend strip."""

    def __init__(self, parent, font_family: str = "TkDefaultFont") -> None:
        super().__init__(parent)
        self._font = (font_family, 11, "bold")
        self._small = (font_family, 9)
        self._graph = None
        self._cycle_edges: Set[Tuple[str, str]] = set()
        self._cycles: List[List[str]] = []
        self._selected: Tuple = ()           # ("node", name) or ("edge", u, v)
        self._hits_nodes: List[Tuple[float, float, str]] = []
        self._hits_edges: List[Tuple[float, float, str, str]] = []
        self.status_var = tk.StringVar(value="Detection has not been run.")
        self.cycle_var = tk.StringVar(value="")
        self.detail_var = tk.StringVar(value="Click a process or a lock label to inspect its dependencies.")
        self._status_label = ttk.Label(self, textvariable=self.status_var, font=(font_family, 10, "bold"))
        self._status_label.pack(side="top", anchor="w")
        # Legend is packed first so it always keeps its height when space is tight.
        self.legend = tk.Canvas(self, background=COLORS["bg"], height=84, highlightthickness=0)
        self.legend.pack(side="bottom", fill="x")
        ttk.Label(self, textvariable=self.detail_var, wraplength=520, justify="left",
                  foreground=COLORS["muted"]).pack(side="bottom", anchor="w", fill="x")
        ttk.Label(self, textvariable=self.cycle_var, wraplength=520, justify="left",
                  foreground=COLORS["cycle"], font=(font_family, 10, "bold")).pack(side="bottom", anchor="w", fill="x")
        self.canvas = tk.Canvas(self, background=COLORS["bg"], highlightthickness=1,
                                highlightbackground="#cbd2d9", width=420, height=220)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        self.canvas.bind("<Button-1>", self._click)
        self.legend.bind("<Configure>", lambda _e: self._draw_legend())

    # ------------------------------------------------------------------ API
    def update_graph(self, graph, cycles: Iterable[Sequence[str]] = (), state: str = "current") -> None:
        """``state``: "current" (detection matches the graph), "stale" (state changed since the
        last detection, so no cycle is highlighted) or "unchecked" (detection never run)."""
        cycles = [list(c) for c in cycles]
        self._graph = graph
        self._cycles = cycles
        self._cycle_edges = cycle_edge_set(cycles)
        if state == "unchecked":
            self.status_var.set("Detection not run yet: no cycle is highlighted.")
            self._status_label.configure(foreground=COLORS["muted"])
        elif state == "stale":
            self.status_var.set("STALE: the simulation changed since the last detection. Press Detect Deadlocks.")
            self._status_label.configure(foreground="#8a5a00")
        else:
            self.status_var.set("Detection result is CURRENT for the graph shown.")
            self._status_label.configure(foreground="#1b7a3d")
        self.cycle_var.set("  |  ".join("Cycle: " + " → ".join(c + c[:1]) for c in cycles)
                           if cycles and state == "current" else "")
        if self._selected and not self._still_valid():
            self._selected = ()
        self._redraw()
        self._describe()

    def _still_valid(self) -> bool:
        g = self._graph
        if g is None:
            return False
        if self._selected[0] == "node":
            return self._selected[1] in g
        return g.has_edge(self._selected[1], self._selected[2])

    def _click(self, event) -> None:
        for x, y, name in self._hits_nodes:
            if math.hypot(event.x - x, event.y - y) <= NODE_R:
                self._selected = ("node", name)
                break
        else:
            best = min(((math.hypot(event.x - x, event.y - y), u, v) for x, y, u, v in self._hits_edges),
                       default=None)
            self._selected = ("edge", best[1], best[2]) if best and best[0] <= 26 else ()
        self._redraw()
        self._describe()

    def _describe(self) -> None:
        g, sel = self._graph, self._selected
        if g is None or not sel:
            self.detail_var.set("Click a process or a lock label to inspect its dependencies.")
            return
        in_cycle = {n for e in self._cycle_edges for n in e}
        if sel[0] == "node":
            a = g.nodes[sel[1]]
            holds = ", ".join(a.get("holds") or ()) or "nothing"
            wait = a.get("waiting_for")
            holder = next(iter(g.successors(sel[1])), None)
            text = f"{sel[1]} ({a.get('status')}): holds {holds}"
            text += f"; waits for lock {wait} held by {holder}." if wait else "; is not waiting for any lock."
            text += " It is part of a deadlock cycle." if sel[1] in in_cycle else " It is not in a cycle."
        else:
            u, v = sel[1], sel[2]
            lock = g.edges[u, v].get("lock")
            text = (f"{u} → {v}: {u} waits for lock {lock}, which {v} holds. "
                    + ("This edge is part of a deadlock cycle." if (u, v) in self._cycle_edges
                       else "This edge is not part of a cycle."))
        self.detail_var.set(text)

    # -------------------------------------------------------------- drawing
    def _redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        g = self._graph
        if g is None or g.number_of_nodes() == 0:
            c.create_text(c.winfo_width() / 2, c.winfo_height() / 2, text="No processes to show.",
                          fill=COLORS["muted"], font=self._small)
            return
        self._hits_nodes, self._hits_edges = [], []
        w, h = max(c.winfo_width(), 200), max(c.winfo_height(), 160)
        pos = circular_layout(list(g.nodes), w, h)
        for u, v, data in g.edges(data=True):
            self._draw_edge(pos, u, v, str(data.get("lock", "")), (u, v) in self._cycle_edges)
        in_cycle = {n for e in self._cycle_edges for n in e}
        centre = (w / 2, h / 2 - 6)
        for name, attrs in g.nodes(data=True):
            self._draw_node(pos[name], name, attrs, name in in_cycle, centre)
            self._hits_nodes.append((pos[name][0], pos[name][1], name))
        if not g.number_of_edges():
            c.create_text(w / 2, h - 12, text="No process is waiting for another process.",
                          fill=COLORS["muted"], font=self._small)

    def _draw_node(self, xy, name, attrs, in_cycle: bool, centre) -> None:
        c, (x, y) = self.canvas, xy
        status = str(attrs.get("status", "RUNNING")).lower()
        fill, outline = COLORS.get(status, COLORS["running"])
        if in_cycle:
            outline = COLORS["cycle"]
        if self._selected[:1] == ("node",) and self._selected[1] == name:
            c.create_oval(x - NODE_R - 5, y - NODE_R - 5, x + NODE_R + 5, y + NODE_R + 5, outline="#d97706", width=2)
        c.create_oval(x - NODE_R, y - NODE_R, x + NODE_R, y + NODE_R, fill=fill, outline=outline,
                      width=4 if in_cycle else 2, dash=(4, 3) if status == "aborted" else ())
        c.create_text(x, y - (6 if in_cycle else 0), text=name, font=self._font, fill=COLORS["text"])
        if in_cycle:   # text marker, so the meaning does not rely on colour alone
            c.create_text(x, y + 11, text="in cycle", font=(self._small[0], 8, "bold"), fill=COLORS["cycle"])
        holds = attrs.get("holds") or ()
        # Put the "holds" caption on the outer side of the node, away from the edges.
        ox, oy = _unit(x - centre[0], y - centre[1]) if (x, y) != centre else (0.0, 1.0)
        anchor = "w" if ox > 0.35 else "e" if ox < -0.35 else "center"
        c.create_text(x + ox * (NODE_R + 6), y + oy * (NODE_R + 12), anchor=anchor,
                      text="holds: " + (", ".join(holds) if holds else "-"),
                      font=self._small, fill=COLORS["muted"])

    def _draw_edge(self, pos, u, v, lock: str, in_cycle: bool) -> None:
        c = self.canvas
        color = COLORS["cycle"] if in_cycle else COLORS["edge"]
        width = 3 if in_cycle else 2
        if self._selected[:1] == ("edge",) and self._selected[1:] == (u, v):
            color, width = "#d97706", 4
        (x1, y1), (x2, y2) = pos[u], pos[v]
        if u == v:  # self-loop (the simulator forbids it, but a graph may contain one)
            pts = [x1 - 12, y1 - NODE_R, x1 - 22, y1 - NODE_R - 34, x1 + 22, y1 - NODE_R - 34,
                   x1 + 12, y1 - NODE_R - 2]
            c.create_line(*pts, smooth=True, arrow=tk.LAST, fill=color, width=width, arrowshape=(10, 12, 4))
            self._label(x1, y1 - NODE_R - 30, lock, color)
            return
        ux, uy = _unit(x2 - x1, y2 - y1)
        # Bend each edge to its own right-hand side so opposite edges do not overlap.
        offset = min(34.0, math.hypot(x2 - x1, y2 - y1) * 0.22)
        mx, my = (x1 + x2) / 2 - uy * offset, (y1 + y2) / 2 + ux * offset
        sx, sy = _unit(mx - x1, my - y1)
        ex, ey = _unit(mx - x2, my - y2)
        start = (x1 + sx * NODE_R, y1 + sy * NODE_R)
        end = (x2 + ex * (NODE_R + 3), y2 + ey * (NODE_R + 3))
        c.create_line(*start, mx, my, *end, smooth=True, arrow=tk.LAST, fill=color, width=width,
                      arrowshape=(11, 13, 5))
        # Midpoint of the quadratic curve start-control-end.
        lx = 0.25 * start[0] + 0.5 * mx + 0.25 * end[0]
        ly = 0.25 * start[1] + 0.5 * my + 0.25 * end[1]
        self._label(lx, ly, lock, color)
        self._hits_edges.append((lx, ly, u, v))

    def _label(self, x: float, y: float, text: str, color: str) -> None:
        c = self.canvas
        t = c.create_text(x, y, text=f"Lock {text}", font=self._small, fill=color)
        x0, y0, x1, y1 = c.bbox(t)
        r = c.create_rectangle(x0 - 3, y0 - 1, x1 + 3, y1 + 1, fill=COLORS["bg"], outline="")
        c.tag_lower(r, t)

    def _draw_legend(self) -> None:
        lg = self.legend
        lg.delete("all")
        x = 8
        for label, (fill, outline), dash in (("Running", COLORS["running"], ()),
                                             ("Blocked", COLORS["blocked"], ()),
                                             ("Aborted", COLORS["aborted"], (3, 2))):
            lg.create_oval(x, 8, x + 14, 22, fill=fill, outline=outline, width=2, dash=dash)
            t = lg.create_text(x + 20, 15, text=label, anchor="w", font=self._small, fill=COLORS["text"])
            x = lg.bbox(t)[2] + 14
        x = 8
        for label, color in (("waits for (label = lock)", COLORS["edge"]), ("deadlock cycle", COLORS["cycle"])):
            lg.create_line(x, 35, x + 26, 35, arrow=tk.LAST, fill=color, width=2, arrowshape=(8, 10, 3))
            t = lg.create_text(x + 32, 35, text=label, anchor="w", font=self._small, fill=COLORS["text"])
            x = lg.bbox(t)[2] + 14
        lg.create_oval(x, 28, x + 14, 42, fill=COLORS["running"][0], outline=COLORS["cycle"], width=3)
        t = lg.create_text(x + 20, 35, text="node in a cycle (also labelled \u201cin cycle\u201d)", anchor="w",
                           font=self._small, fill=COLORS["text"])
        lg.create_text(8, 54, text="Edge P1 \u2192 P2 means: P1 is waiting for a lock that P2 currently holds.",
                       anchor="w", font=self._small, fill=COLORS["muted"])
        lg.create_text(8, 72, text="Nodes outside every cycle keep a normal outline; click a node or lock label (orange) to inspect it.",
                       anchor="w", font=self._small, fill=COLORS["muted"])
