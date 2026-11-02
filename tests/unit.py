#!/usr/bin/env python3
"""Unit checks for the launcher's pure helpers (no terminal needed).

    python3 tests/unit.py
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import pathlib
import tempfile

LAUNCHER = pathlib.Path(__file__).resolve().parent.parent / "bin" / "yazi-flow"

_loader = importlib.machinery.SourceFileLoader("yazi_flow", str(LAUNCHER))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
yf = importlib.util.module_from_spec(_spec)
_loader.exec_module(yf)

CASES: list[tuple[str, bool]] = []


def check(name: str, condition: bool) -> None:
    CASES.append((name, bool(condition)))


def main() -> int:
    # DSR replies: ESC [ <row> ; <col> R
    check("dsr row 20", yf.parse_dsr("\x1b[20;1R") == 20)
    check("dsr row 1", yf.parse_dsr("\x1b[1;1R") == 1)
    check("dsr no reply", yf.parse_dsr("garbage") is None)
    check("dsr partial", yf.parse_dsr("\x1b[12;3") is None)
    check("dsr row 0", yf.parse_dsr("\x1b[0;1R") is None)

    # prompt row -> pane row, with the header/status rows taken out
    check("anchor bottom row", yf.anchor_for(24, 24) == 21)
    check("anchor mid screen", yf.anchor_for(18, 24) == 16)
    check("anchor top row", yf.anchor_for(1, 24) == 0)
    check("anchor clamps small", yf.anchor_for(24, 10) == 7)
    check("anchor clamps big", yf.anchor_for(99, 24) == 21)

    # binary lookup
    os.environ["YAZI_FLOW_YAZI"] = "/tmp/custom-yazi"
    check("explicit binary wins", yf.yazi_binary() == "/tmp/custom-yazi")
    del os.environ["YAZI_FLOW_YAZI"]

    with tempfile.TemporaryDirectory(prefix="yazi-flow-unit-") as tmp:
        root = pathlib.Path(tmp) / "yazi-flow"
        root.mkdir()
        (root / "yazi-flow-yazi.exe").write_text("")
        original_name, original_appdata = yf.os.name, os.environ.get("LOCALAPPDATA")
        try:
            yf.os.name = "nt"                      # exercise the Windows branch
            os.environ["LOCALAPPDATA"] = tmp
            check("windows finds .exe", yf.yazi_binary() == str(root / "yazi-flow-yazi.exe"))
        finally:
            yf.os.name = original_name
            if original_appdata is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = original_appdata

    for name, ok in CASES:
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    failed = sum(1 for _, ok in CASES if not ok)
    print(f"\n{len(CASES) - failed}/{len(CASES)} unit checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
