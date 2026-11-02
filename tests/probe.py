#!/usr/bin/env python3
"""End-to-end probe for yazi-flow.

Runs the launcher inside a real PTY, answers its cursor query (CSI 6n) with the row a
shell prompt would be on, then parses the screen Yazi paints and checks the layout:

  * the left (parent) pane keeps the highlighted CWD on the decision row,
  * the middle (current) pane puts the hovered entry on that row, runs the following
    entries downward and the preceding ones upward (wrapping, each entry drawn once),
  * a listing that fits below leaves the rows above the decision row empty, and
  * moving the selection scrolls the whole pane by one row, in both directions.

    python3 tests/probe.py            # full matrix
    python3 tests/probe.py -v         # dump the screen of every case

Needs pyte (`python3 -m venv .venv && .venv/bin/pip install pyte`).
"""

from __future__ import annotations

import argparse
import fcntl
import os
import pathlib
import pty
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time

try:
    import pyte
except ImportError:  # pragma: no cover
    sys.exit("probe.py needs pyte: python3 -m venv .venv && .venv/bin/pip install pyte")

HERE = pathlib.Path(__file__).resolve().parent
LAUNCHER = HERE.parent / "bin" / "yazi-flow"
COLS, ROWS = 80, 24
CWD_NAME = "m_cwd"
LEFT_COLS = 12          # width of the parent pane in the default [1, 4, 3] ratio
MID_FROM, MID_TO = 12, 49   # columns of the middle pane, for the "nothing above" check
ALT_SCREEN = b"\x1b[?1049h"


class TolerantScreen(pyte.Screen):
    """pyte 0.8 chokes on the private-mode DSR replies Yazi's emulator asks for."""

    def report_device_status(self, *args, **kwargs):
        return None


def make_tree(root: pathlib.Path, before: int, after: int, kind: str = "files") -> pathlib.Path:
    parent = root / "parent"
    parent.mkdir(parents=True)
    names = [f"a{i:02d}" for i in range(before)] + [CWD_NAME] + [f"z{i:02d}" for i in range(after)]
    for name in names:
        (parent / name).mkdir()

    cwd = parent / CWD_NAME
    if kind == "dirs":
        for i in range(20):
            d = cwd / f"d{i:02d}"
            d.mkdir()
            (d / "inside.txt").write_text("x")
    else:
        for i in range(40 if kind == "files" else 5):
            (cwd / f"f{i:02d}").write_text("x")
    return cwd


def run_pty(cmd: list[str], cwd: pathlib.Path, prompt_row: int, settle: float = 2.0,
            keys: list[bytes] | None = None) -> bytes:
    env = dict(os.environ)
    env.update({"TERM": "xterm-256color", "COLORTERM": "truecolor", "PWD": str(cwd)})
    env.pop("YAZI_FLOW_ANCHOR", None)
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
    proc = subprocess.Popen(
        cmd, cwd=str(cwd), env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True
    )
    os.close(slave)

    buf = b""
    answered = False
    deadline = time.time() + settle
    while time.time() < deadline:
        ready, _, _ = select.select([master], [], [], 0.1)
        if not ready:
            continue
        try:
            chunk = os.read(master, 65536)
        except OSError:
            break
        if not chunk:
            break
        buf += chunk
        # Answer the launcher's DSR query only; Yazi's own probes must stay unanswered.
        if not answered and b"\x1b[6n" in buf and ALT_SCREEN not in buf:
            os.write(master, f"\x1b[{prompt_row};1R".encode())
            answered = True

    # One key at a time: Yazi coalesces a burst into a single arrow event, and escape
    # sequences must go out in one write.
    for key in keys or []:
        os.write(master, key)
        end = time.time() + 0.15
        while time.time() < end:
            ready, _, _ = select.select([master], [], [], 0.03)
            if not ready:
                continue
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
    if keys:
        end = time.time() + 0.5
        while time.time() < end:
            ready, _, _ = select.select([master], [], [], 0.1)
            if not ready:
                continue
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk

    try:
        os.write(master, b"q")
    except OSError:
        pass
    end = time.time() + 1.5
    while time.time() < end:
        ready, _, _ = select.select([master], [], [], 0.1)
        if not ready:
            continue
        try:
            chunk = os.read(master, 65536)
        except OSError:
            break
        if not chunk:
            break
        buf += chunk
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
    os.close(master)
    return buf


def screen_of(buf: bytes):
    scr = TolerantScreen(COLS, ROWS)
    pyte.Stream(scr).feed(buf.decode("utf-8", "replace"))
    return scr


def row_of(scr, needle: str, cols: int = COLS) -> int | None:
    """First 0-based row holding `needle`, skipping the header (0) and the status bar."""
    for y in range(1, scr.lines - 1):
        text = "".join(scr.buffer[y][x].data for x in range(cols))
        if needle in text:
            return y
    return None


def middle_blank(scr, row: int) -> bool:
    return "".join(scr.buffer[row][x].data for x in range(MID_FROM, MID_TO)).strip() == ""


def anchor_screen_row(prompt_row: int) -> int:
    """0-based screen row of the decision row: the prompt row minus the header above the
    panes and the status bar below them, kept inside the pane."""
    limit = ROWS - 2
    anchor = max(0, min(prompt_row - 2, limit - 1))
    return 1 + anchor


def layout_rows(n: int, prompt_row: int, cursor: int = 0) -> dict[str, int]:
    """Where each entry lands, per the flow model:

    the hovered entry stays on the decision row, the entries after it run downward, and
    the ones before it run upward (wrapping around the ends of the directory, each entry
    drawn once). With the first entry selected, the last one sits right above it.
    """
    height = ROWS - 2
    keep = max(0, min(prompt_row - 2, height - 1))
    down = max(0, height - keep - 1)

    rows = {}
    for k in range(min(n, height)):
        if k <= down:
            row, idx = keep + k, cursor + k
        else:
            row, idx = keep - (k - down), cursor - (k - down)
        rows[idx % n] = row
    return {f"f{idx:02d}": 1 + row for idx, row in rows.items()}


def sample(n: int, cursor: int = 0) -> list[int]:
    picks = {cursor, min(cursor + 1, n - 1), 0, n - 2, n - 1}
    return sorted(i for i in picks if 0 <= i < n)


def case(label: str, before: int, after: int, prompt_row: int, left: str,
         positions: list[tuple[str, int]], verbose: bool, keys: list[bytes] | None = None,
         kind: str = "files", left_fixed: bool = False, blank_above: int | None = None) -> bool:
    with tempfile.TemporaryDirectory(prefix="yazi-flow-") as tmp:
        cwd = make_tree(pathlib.Path(tmp), before, after, kind)
        scr = screen_of(run_pty([str(LAUNCHER)], cwd, prompt_row, keys=keys))
        want = anchor_screen_row(prompt_row)

        problems = []
        got_left = row_of(scr, left, LEFT_COLS)
        cursor_row = row_of(scr, positions[0][0]) if positions else None
        if got_left != (want if (not keys or left_fixed) else cursor_row):
            problems.append(f"left({left})={got_left} want={want if (not keys or left_fixed) else cursor_row}")
        for name, row in positions:
            got = row_of(scr, name)
            if got != row:
                problems.append(f"{name}@{got} want {row}")
        if blank_above is not None:
            filled = [y for y in range(1, blank_above) if not middle_blank(scr, y)]
            if filled:
                problems.append(f"rows {filled} above the decision row are not empty")

        ok = not problems
        detail = " ".join(f"{n}@{r}" for n, r in positions)
        print(f"{'ok  ' if ok else 'FAIL'} {label}: prompt_row={prompt_row} "
              f"left({left})={got_left} {detail}"
              + ("" if ok else "  <- " + "; ".join(problems)))
        if verbose or not ok:
            for y in range(scr.lines):
                line = "".join(scr.buffer[y][x].data for x in range(COLS)).rstrip()
                mark = " <==" if y == want else ""
                print(f"     {y:02d}|{line[:60]}|{mark}")
        return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ns = ap.parse_args()

    # (label, before, after, prompt_row, left needle, entry count, cursor after keys, keys)
    UP, DOWN, ENTER = b"\x1b[A", b"\x1b[B", b"l"
    cases = [
        ("deep cwd, prompt at bottom", 100, 99, 24, CWD_NAME, 40, 0, []),
        ("deep cwd, prompt mid screen", 100, 99, 18, CWD_NAME, 40, 0, []),
        ("deep cwd, prompt high", 100, 99, 8, CWD_NAME, 40, 0, []),
        ("only child cwd (like /home/knt419)", 0, 0, 24, CWD_NAME, 40, 0, []),
        ("cwd near end of listing", 30, 5, 24, CWD_NAME, 40, 0, []),
        ("short listing stays below (5 files)", 3, 3, 8, CWD_NAME, 5, 0, []),
        ("down arrow scrolls the view (j x5)", 100, 99, 18, CWD_NAME, 40, 5, [b"j"] * 5),
        ("up arrow at the top scrolls, no collapse", 100, 99, 24, CWD_NAME, 40, 39, [UP]),
        ("up arrow twice", 100, 99, 24, CWD_NAME, 40, 38, [UP, UP]),
        ("up arrow wraps a short listing", 3, 3, 8, CWD_NAME, 5, 4, [UP]),
        ("down arrow at the bottom wraps", 100, 99, 18, CWD_NAME, 40, 0,
         [DOWN] * 0 + [b"G", DOWN]),
    ]
    failures = 0
    for label, before, after, row, left, n, cursor, keys in cases:
        kind = "files" if n == 40 else "few"
        expected = layout_rows(n, row, cursor)
        positions = [(name, expected[name]) for name in
                     [f"f{i:02d}" for i in sample(n, cursor)] if name in expected]
        blank = anchor_screen_row(row) if n == 5 else None
        if not case(label, before, after, row, left, positions, ns.verbose, keys, kind,
                    left_fixed=bool(keys), blank_above=blank):
            failures += 1

    # a cd keeps the decision row: the chosen directory is highlighted there and its own
    # contents start on that row
    with tempfile.TemporaryDirectory(prefix="yazi-flow-") as tmp:
        cwd = make_tree(pathlib.Path(tmp), 100, 99, "dirs")
        scr = screen_of(run_pty([str(LAUNCHER)], cwd, 18, keys=[b"j"] * 5 + [ENTER]))
        want = anchor_screen_row(18)
        got_left, got_mid = row_of(scr, "d05", LEFT_COLS), row_of(scr, "inside.txt")
        ok = got_left == want and got_mid == want
        print(f"{'ok  ' if ok else 'FAIL'} cd keeps the decision row: "
              f"left(d05)={got_left} inside.txt={got_mid} want={want}")
        if not ok:
            failures += 1
        cases.append("cd")

    # Stock Yazi, same tree: the jump this project removes.
    with tempfile.TemporaryDirectory(prefix="yazi-flow-") as tmp:
        cwd = make_tree(pathlib.Path(tmp), 100, 99)
        scr = screen_of(run_pty([str(LAUNCHER), "--no-flow"], cwd, 24))
        stock = row_of(scr, CWD_NAME, LEFT_COLS)
        print(f"info stock yazi (no flow): prompt_row=24 left_highlight_row={stock} "
              f"(= {24 - 1 - (stock or 0)} rows of gaze travel)")

    print(f"\n{len(cases) - failures}/{len(cases)} cases aligned")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
