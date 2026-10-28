"""Write docs/diagnostics-catalog-2026-10-28.md from robotdx.diagnostics.catalog (the catalog is code; this is its view).

    env -u VIRTUAL_ENV uv run --isolated --project /home/bam/sim2real/diagnostics_ref python /home/bam/sim2real/diagnostics_ref/tools/build_catalog_doc.py
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from robotdx.diagnostics.catalog import ENTRIES, PARTS, PRIMITIVES, by_part

OUT = Path("/home/bam/sim2real/docs/diagnostics-catalog-2026-10-28.md")
CONSUMER = {"both": "both", "robotdx": "RobotDx", "sim2real": "sim2real"}


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def main() -> int:
    prov = Counter(entry.prov for entry in ENTRIES)
    lines = [
        "# Stock diagnostics, KPIs and gates per robot part type (2026-10-28)",
        "",
        "Generated from `diagnostics_ref/robotdx/diagnostics/catalog.py` by `tools/build_catalog_doc.py`; edit the code, not this file.",
        "The library that computes them and why it is shaped this way: [diagnostics-library-2026-10-28.md](diagnostics-library-2026-10-28.md).",
        "",
        f"**{len(ENTRIES)} diagnostics over {len(PARTS)} part types, built from {len(PRIMITIVES)} stock primitives "
        f"({sum(p.implemented for p in PRIMITIVES.values())} implemented in the reference).** Provenance: "
        f"{prov['his']} his (quoted verbatim, file and line; a test re-reads each quote at its source), {prov['his code']} from his old code, "
        f"{prov['agent']} agent defaults awaiting his yes, {prov['proposed']} proposed here with prior art.",
        "",
        "How to read a row: the **primitive** is the stock function; the **config** is what makes it this part's diagnostic; **gate** names the",
        "acceptance gate it feeds (T1-T11 bam_rack_twin, K-ladder servo-ID note / pidtuna); **role** is headline, driver or health; **hint** is the",
        "data-ui view (PEP 0010 §10); **for** is RobotDx (one robot's live history), sim2real (datasets of runs) or both.",
        "",
        "Two families carry Zach's two errors (Jul 31 2026: \"the error between actual sim and actual real, and the error between actual real and",
        "target\"): `real_vs_target` and `sim_vs_real`. Every sim-vs-real number is read against the rig's own floor (`repeatability`).",
        "`truthfulness` is a reading against an independent reference (torque vs a weighed load, encoder vs camera, depth vs a known plane).",
        "",
        "## Stock primitives",
        "",
        "| primitive | family | hint | emits | in reference | computes | config | prior art |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in PRIMITIVES.values():
        lines.append(f"| `{p.name}` | {p.family} | `{p.hint}` | {p.emits} | {'yes' if p.implemented else 'specified'} | {cell(p.computes)} | "
                     f"{cell(p.config)} | {cell(p.prior_art)} |")
    for part, entries in by_part().items():
        lines += ["", f"## {PARTS[part]}", "",
                  "| diagnostic | checks | primitive · config | output | gate | role | hint | for | provenance |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for e in entries:
            source = f"{e.prov}: \"{cell(e.quote)}\" ({cell(e.where)})"
            if e.today:
                source += f"; today: {cell(e.today)}"
            hint = f"`{e.the_hint}`" + (f" + {cell(e.view_extra)}" if e.view_extra else "")
            lines.append(f"| **{cell(e.title)}** `{e.id}` | {cell(e.checks)} | `{e.primitive}` · {cell(e.config)} | {cell(e.output)} | {cell(e.gate) or '-'} | "
                         f"{e.role} | {hint} | {CONSUMER[e.consumers]} | {source} |")
    OUT.write_text("\n".join(lines) + "\n")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
