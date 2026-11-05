"""A result's code stamp names the code that computed it: writing results is not a code change (2026-11-05).

Every example and drift result carries provenance.code, HEAD's short sha, with "+dirty" when the code under it was not committed.
`python -m sysid all --write` writes results/<id>.json one example at a time, so a stamp that counted sysid/results as code read
"+dirty" on every example after the first: the results committed on 2026-11-05 all said 782bd5e+dirty, on every oracle page.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from sysid import result

FILES = ("sysid/arm.py", "sysid/examples/ur5e/world.json", "sysid/results/ur5e.json", "type_cards/registry.py", "site/landing.py")


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                   check=True, capture_output=True)


def committed_repo(root: Path) -> Path:
    for rel in FILES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("0\n")
    git(root, "init", "-q")
    git(root, "add", "--", *FILES)
    git(root, "commit", "-q", "-m", "base")
    return root


def test_writing_results_is_not_a_code_change(tmp_path):
    repo = committed_repo(tmp_path)
    clean = result.code_version(repo)
    assert clean not in ("", "unknown") and "+dirty" not in clean
    (repo / "sysid/results/ur5e.json").write_text("1\n")
    (repo / "sysid/results/conveyor.json").write_text("1\n")
    assert result.code_version(repo) == clean, "a rewritten or new results file stamped the code dirty"
    (repo / "site/landing.py").write_text("1\n")
    assert result.code_version(repo) == clean, "the site renders results; it does not compute them"


def test_a_change_to_what_computes_results_is_dirty(tmp_path):
    for rel in ("sysid/arm.py", "sysid/examples/ur5e/world.json", "type_cards/registry.py", "sysid/new_module.py"):
        repo = committed_repo(tmp_path / rel.replace("/", "_"))
        clean = result.code_version(repo)
        (repo / rel).write_text("1\n")
        assert result.code_version(repo) == clean + "+dirty", rel


# bam_ws is imported in place (CAN 11 runs bam_rack_twin and the bam_ws packages it imports from their checkout), so its stamp is the
# same rule on another repo: the branch actually checked out (not an assumed "main"), the last commit that touched an imported root,
# and +dirty when one of those roots has uncommitted changes.

def test_an_imported_checkout_is_stamped_by_what_was_imported(tmp_path):
    repo = tmp_path / "bam_ws"
    imported = ("src/dev/bam_rack_twin", "src/core/moteus_servo/src")
    for rel in ("src/dev/bam_rack_twin/twin.py", "src/core/moteus_servo/src/servo.py", "src/core/like_keras/notes.md"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("0\n")
    git(repo, "init", "-q", "-b", "work")
    git(repo, "add", "--", ".")
    git(repo, "commit", "-q", "-m", "base")
    roots = [repo / r for r in imported]
    head = lambda: subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()  # noqa: E731
    stamp = result.checkout_version(repo, roots)
    assert (stamp["branch"], stamp["commit"], stamp["dirty"]) == ("work", head(), False) and stamp["date"], stamp

    (repo / "src/core/like_keras/notes.md").write_text("1\n")
    assert result.checkout_version(repo, roots) == stamp, "an uncommitted change outside the imported roots"
    git(repo, "commit", "-q", "-am", "unrelated")
    assert result.checkout_version(repo, roots) == stamp, "a commit outside the imported roots"

    (repo / "src/core/moteus_servo/src/servo.py").write_text("1\n")
    assert result.checkout_version(repo, roots) == {**stamp, "dirty": True}, "an uncommitted change to an imported dependency"
    git(repo, "commit", "-q", "-am", "servo")
    moved = result.checkout_version(repo, roots)
    assert moved["commit"] == head() != stamp["commit"] and not moved["dirty"], moved


# Beyond bam_ws: CAN 11's bam_rack_twin also imports io-diagnostics and robot_msgs from their own checkouts, and the arm examples load
# Menagerie's models from a cached checkout. Every result names every checkout outside this repo it imported code or loaded a model
# from, each stamped by the rule above; paths in this repo, in a virtualenv, or in no checkout at all are not imports to stamp.

def test_every_checkout_outside_this_repo_is_stamped(tmp_path):
    here = committed_repo(tmp_path / "sim2real")
    imports = {}
    for name, rel in (("bam_ws", "src/dev/bam_rack_twin/twin.py"), ("menagerie", "universal_robots_ur5e/ur5e.xml"),
                      ("io-diagnostics", "io_diagnostics/entity.py")):
        repo = tmp_path / name
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("0\n")
        git(repo, "init", "-q", "-b", "main")
        git(repo, "add", "--", ".")
        git(repo, "commit", "-q", "-m", "base")
        imports[name] = repo / rel
    loose = tmp_path / "not_a_checkout"
    loose.mkdir()
    venv = tmp_path / "bam_ws" / ".venv/lib/site-packages"
    venv.mkdir(parents=True)
    (venv / "numpy.py").write_text("0\n")  # a virtualenv sits in a checkout as untracked files: stamping it would read +dirty
    paths = [imports["bam_ws"].parent, imports["menagerie"], imports["io-diagnostics"].parent, here / "sysid", loose, venv,
             tmp_path / "missing"]
    stamps = result.external_checkouts(paths, exclude=here)
    assert [Path(s["repo"]).name for s in stamps] == ["bam_ws", "io-diagnostics", "menagerie"], stamps
    assert all(s["branch"] == "main" and s["commit"] and not s["dirty"] for s in stamps), stamps

    (imports["menagerie"]).write_text("1\n")  # a model file loaded in place, changed and not committed
    dirty = {Path(s["repo"]).name: s["dirty"] for s in result.external_checkouts(paths, exclude=here)}
    assert dirty == {"bam_ws": False, "io-diagnostics": False, "menagerie": True}, dirty


def test_a_description_names_the_model_files_it_loads():
    for example, expected in (("ur5e", "universal_robots_ur5e/ur5e.xml"), ("dual_arm_cell", "robotiq_2f85/2f85.xml"),
                              ("conveyor", "sysid/examples/conveyor/conveyor.xml")):
        paths = [str(p) for p in result.description_paths(example)]
        assert any(p.endswith(expected) for p in paths), (example, paths)
