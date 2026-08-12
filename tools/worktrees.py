"""List the repo's git worktrees and remove the ones that are finished.

⚠ Why this exists: a leftover worktree is not inert. It is a second, older
copy of the whole tree — `app/admin` included — sitting at a path an agent or
an editor will happily open, and it reads as current. This epic ended with one
from a LANDED epic (`admin-app-redesign`, 16 commits behind) still on disk, and
a session nearly continued work in it.

**Safe to remove** means all three, checked per worktree:

  - it is not the tree you are standing in (removing that pulls the rug);
  - `git status --porcelain` is empty — no uncommitted or untracked work.
    ⚠ Untracked counts: a worktree's `work/product.db` is gitignored, but so is
    anything else a session left there;
  - its branch (or detached HEAD) is fully contained in `main`. Nothing is
    lost, because every commit is already reachable from `main`.

Anything failing one of those is REPORTED, never removed. The whole point is
to make "is this finished?" a question with an answer rather than a guess, and
a script that deletes an agent's unmerged work to keep the list tidy is worse
than the mess.

    python tools/worktrees.py            # list, and say what each one is
    python tools/worktrees.py --prune    # remove exactly the safe ones

Run it at the end of a session, or whenever `git worktree list` surprises you.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _git(*args: str, cwd: Path | None = None) -> str:
    out = subprocess.run(["git", *args], cwd=str(cwd or REPO),
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace")
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {out.stderr.strip()}")
    return out.stdout


class Tree:
    def __init__(self, path: Path, head: str, branch: str | None,
                 is_main: bool, current: bool) -> None:
        self.path = path
        self.head = head
        self.branch = branch
        self.is_main = is_main
        self.current = current
        self.dirty: list[str] = []
        self.merged = False

    @property
    def name(self) -> str:
        return self.branch or f"(detached {self.head[:7]})"

    @property
    def safe(self) -> bool:
        return (not self.is_main and not self.current
                and not self.dirty and self.merged)

    def why_not(self) -> str:
        if self.is_main:
            return "the primary tree"
        if self.current:
            return "you are standing in it"
        if self.dirty:
            n = len(self.dirty)
            return (f"{n} uncommitted/untracked file{'s' if n != 1 else ''} — "
                    f"e.g. {self.dirty[0]}")
        if not self.merged:
            ahead = _git("rev-list", "--count", f"main..{self.head}").strip()
            return f"{ahead} commit(s) NOT in main"
        return ""


def collect() -> list[Tree]:
    """Parse `git worktree list --porcelain` into something answerable."""
    here = Path.cwd().resolve()
    trees: list[Tree] = []
    path = head = branch = None
    detached = False

    def flush() -> None:
        nonlocal path, head, branch, detached
        if path is None:
            return
        p = Path(path).resolve()
        # The FIRST record is the primary tree — git lists it first, and it is
        # the one `.git` is a directory in rather than a file.
        is_main = not trees
        current = here == p or p in here.parents
        trees.append(Tree(p, head or "", None if detached else branch,
                          is_main, current))
        path = head = branch = None
        detached = False

    for line in _git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            flush()
            path = line[len("worktree "):]
        elif line.startswith("HEAD "):
            head = line[len("HEAD "):]
        elif line.startswith("branch "):
            branch = line[len("branch "):].replace("refs/heads/", "")
        elif line.strip() == "detached":
            detached = True
    flush()

    for t in trees:
        if t.is_main:
            continue
        t.dirty = [ln[3:] for ln in
                   _git("status", "--porcelain", "--untracked-files=normal",
                        cwd=t.path).splitlines()]
        t.merged = subprocess.run(
            ["git", "merge-base", "--is-ancestor", t.head, "main"],
            cwd=str(REPO), capture_output=True).returncode == 0
    return trees


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prune", action="store_true",
                    help="remove the worktrees reported as safe")
    args = ap.parse_args(argv)

    trees = collect()
    safe = [t for t in trees if t.safe]

    for t in trees:
        mark = "SAFE  " if t.safe else "keep  "
        note = "" if t.safe else f"  <- {t.why_not()}"
        print(f"{mark}{t.name:<40} {t.path}{note}")

    if not safe:
        print("\nNothing to remove.")
        return 0

    if not args.prune:
        print(f"\n{len(safe)} finished worktree(s). "
              f"Remove with: python tools/worktrees.py --prune")
        return 0

    for t in safe:
        _git("worktree", "remove", str(t.path))
        print(f"removed {t.path}")
    # Drops records for directories deleted by hand, which otherwise keep the
    # branch marked as checked out and block `git worktree add` on it.
    _git("worktree", "prune")
    return 0


if __name__ == "__main__":
    sys.exit(main())
