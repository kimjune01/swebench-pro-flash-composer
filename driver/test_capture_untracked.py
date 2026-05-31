#!/usr/bin/env python3
"""Regression test for the capture_patch untracked-file fix.

Proves the bug and the fix at the git level (no docker needed):

  OLD capture: `git diff HEAD`                 → drops untracked new files
  NEW capture: `git add -A; git diff --cached HEAD` → captures them

A composer fix that creates a new file (a new module, a new config) was silently
recorded as `no_patch_produced` under the old capture. The parent codex harness
(pro_pilot.py) always staged first, which is why it never hit this. See
docs/cost.md / the hypothesis graph for the full provenance.

Run:  python3 driver/test_capture_untracked.py   (exit 0 = pass)
"""
import subprocess, tempfile, pathlib, sys

def sh(cwd, cmd):
    return subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True).stdout

def main():
    with tempfile.TemporaryDirectory() as d:
        sh(d, "git init -q && git config user.email t@t && git config user.name t")
        (pathlib.Path(d) / "existing.py").write_text("x = 1\n")
        sh(d, "git add -A && git commit -qm base")

        # Composer's 'fix': edit a tracked file AND create a new untracked file.
        (pathlib.Path(d) / "existing.py").write_text("x = 2\n")
        (pathlib.Path(d) / "newmodule.py").write_text("def fix():\n    return 42\n")

        old = sh(d, "git diff HEAD")
        new = sh(d, "git add -A -- . >/dev/null 2>&1; git diff --cached HEAD")

        # OLD behaviour (the bug): tracked edit shows, new file is DROPPED.
        assert "existing.py" in old, "sanity: tracked edit should always show"
        bug_reproduced = "newmodule.py" not in old
        # NEW behaviour (the fix): both show.
        fix_works = "newmodule.py" in new and "existing.py" in new

        print(f"  OLD `git diff HEAD`            → new file captured: {'newmodule.py' in old}")
        print(f"  NEW `add -A; diff --cached`    → new file captured: {'newmodule.py' in new}")

        if not bug_reproduced:
            print("UNEXPECTED: old capture already saw the new file — test no longer valid")
            return 1
        if not fix_works:
            print("FAIL: new capture did not recover the untracked new file")
            return 1
        print("PASS: fix recovers the new-file patch the old capture dropped")
        return 0

if __name__ == "__main__":
    sys.exit(main())
