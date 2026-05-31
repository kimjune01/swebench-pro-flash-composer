#!/usr/bin/env python3
"""flashcomp_pilot.py — per-instance pilot: Cursor Composer 2.5 (recon+craft) + Gemini 2.5 Flash (adversary+audit).

Replicates the swebench-pro inquiry loop with a cheaper cross-family model pair
(Composer × Flash instead of Sonnet × GPT-5.5). Same skill contracts, same outer-loop
structure, same gate routing — different models. This is §4.5a of the paper.

Model roles:
  recon     → Composer 2.5  (tool-use: explores codebase, writes hypothesis graph)
  volley1   → Flash (API)   (static: flags compositional blind spots before craft)
  craft     → Composer 2.5  (tool-use: implements patch, iterates gate)
  capture   → [built-in]    (source-only diff, test files stripped)
  audit     → Flash (API)   (static: reads patch+gate, emits VERDICT+RE-ENTER)
  gate      → [built-in]    (routes on RE-ENTER; outer loop up to MAX_OUTER)

Outer loop mirrors the parent:
  - RESOLVED → terminate
  - RE-ENTER recon → re-run recon with accumulated hypothesis graph
  - RE-ENTER craft → re-run craft with same handoff
  - Budget exhausted → INCOMPLETE

PREREQUISITES (source the sibling's .proenv first):
  . /path/to/swebench-pro/driver/.proenv   # sets SWEAP_OS_REPO + PY
  BENCH=pro python3 /path/to/swebench-pro/driver/make_task.py <iid>
  python3 driver/flashcomp_pilot.py tasks/generated/<iid>.json <iid>

Platform note (phase 0): runs locally on Mac under amd64 emulation (OrbStack), identical to
swebench-pro's dev path (PROCEDURE §4). EC2 deferred to phase 1 — cursor-agent ships macOS
ARM64 native modules that don't install on Linux x86_64 without a separate Cursor Linux build.
"""
import json, sys, pathlib, subprocess, time, shlex, os, re, fnmatch

REPO  = pathlib.Path(__file__).resolve().parent.parent
HERE  = REPO / "runs" / "dev"
SKILLS = REPO / "skills"

RECON_SKILL = (SKILLS / "recon" / "skill.md").read_text()
CRAFT_SKILL = (SKILLS / "craft" / "skill.md").read_text()
AUDIT_SKILL = (SKILLS / "audit" / "skill.md").read_text()

GEMINI_MODEL   = os.environ.get("FLASH_MODEL",    "gemini-2.5-flash")
COMPOSER_MODEL = os.environ.get("COMPOSER_MODEL", "composer-2.5")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
CURSOR_API_KEY = os.environ.get("CURSOR_API_KEY", "")

RECON_CAP = int(os.environ.get("RECON_CAP", "2000"))
CRAFT_CAP = int(os.environ.get("CRAFT_CAP", "3600"))
AUDIT_CAP = int(os.environ.get("AUDIT_CAP", "1200"))
MAX_OUTER = int(os.environ.get("MAX_OUTER", "5"))   # outer-loop budget (matches parent)

PLATFORM  = os.environ.get("PLATFORM", "linux/amd64")  # amd64 emulation on Mac (OrbStack)
WORKSPACE = "/workspace"

# REMOTE_BOX=user@host:pem_path — when set, all docker commands run on EC2 via SSH.
# cursor-agent + flash() remain local; only the container lifecycle is remote.
_REMOTE_BOX = os.environ.get("REMOTE_BOX", "")  # e.g. "ec2-user@1.2.3.4:/tmp/sweb-coord1-xyz.pem"


def _parse_remote_box():
    """Parse REMOTE_BOX=user@host:pem_path → (user_at_host, pem_path) or (None, None)."""
    if not _REMOTE_BOX:
        return None, None
    colon = _REMOTE_BOX.rfind(":")
    if colon < 0:
        return _REMOTE_BOX, None
    return _REMOTE_BOX[:colon], _REMOTE_BOX[colon + 1:]


_SSH_HOST, _SSH_PEM = _parse_remote_box()
_SSH_BASE = (["ssh", "-i", _SSH_PEM,
               "-o", "StrictHostKeyChecking=no",
               "-o", "ConnectTimeout=15",
               _SSH_HOST]
             if _SSH_HOST else None)


# ── helpers ───────────────────────────────────────────────────────────────────

def _docker_ize(cmd):
    """Add --platform to docker pull/run so amd64 eval images run under emulation.
    Mirrors swebench-pro's rung5_driver._localize() for the local-dev path.
    Only used on the local (non-REMOTE_BOX) path — EC2 is native x86_64."""
    cmd = cmd.replace("docker run -d ", f"docker run -d --platform {PLATFORM} ")
    cmd = cmd.replace("docker pull ",   f"docker pull --platform {PLATFORM} ")
    return cmd

def run(cmd, timeout=600, inp=None):
    """Run a shell command, routing docker to EC2 via SSH when REMOTE_BOX is set.

    REMOTE_BOX path: sends the raw cmd to the EC2 host over SSH (no _docker_ize —
    EC2 is native x86_64). stdin piping works the same way (input= passes through).
    Local path: wraps in bash -c after injecting --platform flags for OrbStack emulation.
    """
    if _SSH_BASE:
        return subprocess.run(_SSH_BASE + [cmd],
                              capture_output=True, text=True, timeout=timeout, input=inp)
    return subprocess.run(["bash", "-c", _docker_ize(cmd)],
                          capture_output=True, text=True, timeout=timeout, input=inp)

def log(obj):
    HERE.mkdir(parents=True, exist_ok=True)
    with open(HERE / "flashcomp_run.jsonl", "a") as f:
        f.write(json.dumps(obj) + "\n")
    sys.stderr.write(f"[{obj.get('instance')}] {obj.get('stage')}: {obj.get('msg', '')}\n")
    sys.stderr.flush()


# ── model invocations ─────────────────────────────────────────────────────────

def flash(prompt_text, tag, timeout=None):
    """Gemini 2.5 Flash via Google GenAI Python API.

    Uses the API directly (no CLI subprocess) so auth comes from the env var,
    keys loaded from ~/.zshrc, and timeout is enforced at the HTTP layer.
    """
    from google import genai as _genai
    HERE.mkdir(parents=True, exist_ok=True)
    (HERE / f"fc_prompt_{tag}.txt").write_text(prompt_text)
    t0 = time.time()
    try:
        client = _genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt_text,
        )
        stdout = response.text or ""
    except Exception as e:
        stdout = f"[GEMINI API ERROR: {type(e).__name__}: {str(e)[:400]}]"
    dt = time.time() - t0
    (HERE / f"fc_out_{tag}.txt").write_text(stdout)
    return stdout, dt


def composer(prompt_text, tag, timeout=3600):
    """Cursor Composer 2.5 — headless (--print) + auto-approve-all (--yolo).

    DeepSWE lessons applied:
      #1  --trust --workspace mandatory (without these cursor-agent silently cd's to its
          remembered trust dir and edits the wrong tree).
      #2  CURSOR_API_KEY passed via subprocess env (doesn't survive bare bash spawn even
          with source ~/.zshrc; explicit env on each invocation is the only safe path).
      #8  foreground subprocess.run > async dispatch (no &-orphan, no pid-wait complexity).
    """
    workspace = HERE / f"fc_ws_{tag}"
    workspace.mkdir(parents=True, exist_ok=True)
    (HERE / f"fc_prompt_{tag}.txt").write_text(prompt_text)
    env = {**os.environ, "CURSOR_API_KEY": CURSOR_API_KEY}
    t0 = time.time()
    timed_out = False
    try:
        p = subprocess.run(
            ["cursor-agent", "--print", "--model", COMPOSER_MODEL,
             "--trust", "--workspace", str(workspace), "--yolo",
             prompt_text],
            capture_output=True, text=True, timeout=timeout, env=env)
        stdout, stderr = p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        timed_out = True
        # text=True means stdout/stderr may already be str; guard both cases
        raw_out, raw_err = e.stdout or "", e.stderr or ""
        stdout = raw_out if isinstance(raw_out, str) else raw_out.decode("utf-8", "replace")
        stderr = raw_err if isinstance(raw_err, str) else raw_err.decode("utf-8", "replace")
    dt = time.time() - t0
    (HERE / f"fc_out_{tag}.txt").write_text(stdout + "\n---STDERR---\n" + stderr)
    return stdout, dt, timed_out


# ── container setup (adapted from swebench-pro/driver/pro_pilot.py) ───────────

def restore_cmd(inst):
    """Gold-test restore is the last line of before_repo_set_cmd (same as pro_pilot)."""
    return inst["before_repo_set_cmd"].strip().splitlines()[-1].strip()

def pro_setup(inst):
    iid = inst["instance_id"]; img = inst["image_name"]; root = inst.get("repo_dir", "/app")
    run(f"docker pull {img} 2>&1 | tail -1", timeout=2400)
    cid = run(f"docker run -d --entrypoint sleep {img} infinity").stdout.strip()
    if not cid or len(cid) < 12:
        log({"instance": iid, "stage": "setup", "msg": f"run failed: {cid[:80]}"}); return None
    base = inst["base_commit"]
    run(f"docker exec {cid} bash -lc 'cd {root} && git reset --hard {base} -q && "
        f"git checkout {base} -q 2>/dev/null; {restore_cmd(inst)} 2>/dev/null; echo OK'")
    run(f"docker exec {cid} bash -lc 'mkdir -p {WORKSPACE}'")
    for name, content in (("run_script.sh", inst["run_script"]),
                           ("parser.py",     inst["parser_script"]),
                           ("f2p.json",      json.dumps(inst["fail_to_pass"]))):
        # Pipe directly — avoids /tmp/_pf race when multiple pilots run concurrently
        run(f"docker exec -i {cid} bash -c 'cat > {WORKSPACE}/{name}'", inp=content)
    return cid, root


def install_gate(inst, cid, root):
    """Install /tmp/gate-fc-<tag> and /tmp/box-fc-<tag> helpers (matches pro_pilot.py).
    bash -c, NOT -lc: a login shell resets PATH and hides baked toolchains (regression #1
    from swebench-pro's PROCEDURE.md §4a harness fault list).

    Scripts live on the Mac so cursor-agent (which runs locally) can call them as
    `bash {gate}` / `bash {box} '<cmd>'`.  When REMOTE_BOX is set, they emit SSH
    commands to reach the container on EC2 instead of talking to a local docker daemon.
    """
    files   = ",".join(inst["selected_test_files"])
    summary = (
        "import json;o=json.load(open('/workspace/output.json'));"
        "f2p=set(json.load(open('/workspace/f2p.json')));"
        "st={t['name']:t['status'] for t in o.get('tests',[])};"
        "pas=[t for t in f2p if st.get(t)=='PASSED'];"
        "fail=[t for t in f2p if st.get(t)!='PASSED'];"
        "print('=== GATE F2P %d/%d PASSED ==='%(len(pas),len(f2p)));"
        "print('FAILING:',fail) if fail else print('ALL F2P PASSED');"
    )
    g = (f"cd {root} && {restore_cmd(inst)} 2>/dev/null; "
         f"bash {WORKSPACE}/run_script.sh {shlex.quote(files)} "
         f"> {WORKSPACE}/stdout.log 2> {WORKSPACE}/stderr.log; "
         f"python {WORKSPACE}/parser.py {WORKSPACE}/stdout.log "
         f"{WORKSPACE}/stderr.log {WORKSPACE}/output.json; "
         f"python -c {shlex.quote(summary)}")
    # Include PID so concurrent runs of the same instance don't cross-wire containers.
    run_id = f"{inst['instance_id'].replace('/', '_')}-{os.getpid()}"
    gate = f"/tmp/gate-fc-{run_id}"
    box  = f"/tmp/box-fc-{run_id}"

    if _SSH_BASE:
        # ── REMOTE_BOX path: gate/box scripts SSH to EC2 ─────────────────────
        # Scripts are bash files executed locally via `bash {gate}` / `bash {box} '<cmd>'`.
        # SSH receives its remote command as a single quoted shell word; shlex.quote
        # wraps each remote command so the local bash passes it verbatim to ssh(1),
        # which then hands it to the remote shell.
        ssh_prefix = (f"ssh -i {shlex.quote(_SSH_PEM)} "
                      f"-o StrictHostKeyChecking=no -o ConnectTimeout=15 "
                      f"{shlex.quote(_SSH_HOST)}")
        # gate: remote command is `docker exec CID bash -c '<g>'`
        remote_gate_cmd = f"docker exec {cid} bash -c {shlex.quote(g)} 2>&1 | tail -150"
        pathlib.Path(gate).write_text(
            f"#!/bin/bash\n"
            f"{ssh_prefix} {shlex.quote(remote_gate_cmd)}\n")
        # box: two-step pipe — push stdin into /tmp/_bc, then exec it
        # Step 1 uses `ssh ... cmd` with stdin piped from `printf`; step 2 is a
        # second SSH for the exec (no stdin needed).
        remote_put  = f"docker exec -i {cid} bash -c 'cat>/tmp/_bc'"
        remote_exec = f"docker exec {cid} bash -c 'cd {root} && bash /tmp/_bc'"
        bx = (f"printf '%s' \"$*\" | {ssh_prefix} {shlex.quote(remote_put)} && "
              f"{ssh_prefix} {shlex.quote(remote_exec)}")
        pathlib.Path(box).write_text(f"#!/bin/bash\n{bx}\n")
    else:
        # ── Local path: gate/box scripts talk to local docker daemon ─────────
        pathlib.Path(gate).write_text(
            f"#!/bin/bash\ndocker exec {cid} bash -c {shlex.quote(g)} 2>&1 | tail -150\n")
        bx = (f"printf '%s' \"$*\" | docker exec -i {cid} bash -c 'cat >/tmp/_bc' && "
              f"docker exec {cid} bash -c 'cd {root} && bash /tmp/_bc'")
        pathlib.Path(box).write_text(f"#!/bin/bash\n{bx}\n")

    subprocess.run(["chmod", "+x", gate, box])
    return box, gate


# ── recon / craft / audit ─────────────────────────────────────────────────────

def recon(inst, box, gate, hgraph="", depth=0):
    iid = inst["instance_id"]
    tag = f"recon_{iid.replace('/', '_')}_d{depth}"
    added = "\n".join(l[1:] for l in inst["test_patch"].splitlines()
                      if l.startswith("+") and not l.startswith("+++"))
    testfiles = [l[6:] for l in inst["test_patch"].splitlines() if l.startswith("+++ b/")]
    prior = (
        f"\nPRIOR HYPOTHESIS GRAPH (hypotheses from previous iterations — do NOT re-propose "
        f"already-killed root causes; extend the graph with new nodes):\n{hgraph[:4000]}\n"
        if hgraph else ""
    )
    adapter = (
        f"You will follow the /recon skill below. Diagnose from the code alone and print "
        f"your handoff to stdout starting `# Recon:`.\n\n"
        f"ENVIRONMENT:\n"
        f"- Code is in an offline Docker container. Run ALL reads via: `bash {box} '<cmd>'` "
        f"(it already cd's to repo root — do NOT prepend cd). No internet, no gh.\n"
        f"- Run the failing tests: `bash {gate}`\n"
        f"- The fix must be SOURCE-ONLY: test files are gold-locked (the gate restores them "
        f"before every run). Never hand off 'edit/weaken the test' as a fix — diagnose the "
        f"source cause that makes the GOLD tests pass.\n"
        f"- Failing tests live in: {testfiles}\n\n"
        f"FAIL_TO_PASS (must pass): {str(inst['fail_to_pass'])[:600]}\n\n"
        f"PROBLEM:\n{inst['problem_statement'][:4000]}\n\n"
        f"ADDED FAILING TESTS:\n{added[:2500]}\n"
        f"{prior}"
        f"\n===================== THE /recon SKILL =====================\n{RECON_SKILL}\n"
        f"\nREAD-ONLY PHASE: do NOT edit any source files. Only read, run the gate, "
        f"and produce the `# Recon:` handoff. All edits happen in the craft phase.\n"
    )
    out, dt, timed_out = composer(adapter, tag, timeout=RECON_CAP)
    log({"instance": iid, "stage": "recon", "depth": depth, "wall_s": round(dt), "timed_out": timed_out})
    return out


def craft(inst, box, gate, handoff, volley_concerns=None, depth=0):
    iid = inst["instance_id"]
    tag = f"craft_{iid.replace('/', '_')}_d{depth}"
    vc_section = (
        f"\nFLASH ADVERSARY CONCERNS (compositional blind spots flagged before implementation):\n"
        f"{volley_concerns}\n"
        if volley_concerns else ""
    )
    adapter = (
        f"You will follow the /craft skill below. Generate a patch from the recon handoff "
        f"and iterate the gate until the FAIL_TO_PASS tests pass.\n\n"
        f"ENVIRONMENT:\n"
        f"- Offline container. Edit/read files via: `bash {box} '<cmd>'` (already at repo "
        f"root — do NOT prepend cd; use sed/python3/patch inside it).\n"
        f"- Verify with the gate: `bash {gate}` (max 8 iterations).\n"
        f"- SOURCE-ONLY. Test files are gold-locked: the gate restores them to the reference "
        f"version before every run, so any edit you make to a test is silently reverted and "
        f"never graded. A green gate must come from changing SOURCE, not weakening a test.\n"
        f"- No codex available. Iterate the gate directly without external review.\n"
        f"- When all FAIL_TO_PASS pass in the gate, print RESOLVED.\n"
        f"- If the diagnosis looks wrong after 3 stuck iterations, "
        f"print `NOT-RESOLVED — re-diagnose`.\n\n"
        f"FAIL_TO_PASS (must pass): {str(inst['fail_to_pass'])[:600]}\n\n"
        f"RECON HANDOFF (canonical — act on this):\n{handoff[:7000]}\n"
        f"{vc_section}"
        f"\n===================== THE /craft SKILL =====================\n{CRAFT_SKILL}\n"
    )
    out, dt, timed_out = composer(adapter, tag, timeout=CRAFT_CAP)
    log({"instance": iid, "stage": "craft", "depth": depth, "wall_s": round(dt), "timed_out": timed_out})
    return out, timed_out


def flash_volley(iid, handoff, inst, depth=0):
    """Flash adversary on Composer's recon handoff — flags compositional blind spots.

    Flash has no tool-use (API only) — purely static analysis of the handoff text.
    Structural analog of the codex volley in the parent: cross-family adversary reviews
    the diagnosis before implementation begins.
    """
    tag = f"volley1_{iid.replace('/', '_')}_d{depth}"
    added = "\n".join(l[1:] for l in inst["test_patch"].splitlines()
                      if l.startswith("+") and not l.startswith("+++"))
    adapter = (
        f"You are reviewing a recon handoff from a coding agent. Your job is adversarial: "
        f"find what the agent missed, not what it got right.\n\n"
        f"PROBLEM:\n{inst['problem_statement'][:3000]}\n\n"
        f"ADDED FAILING TESTS (what must pass after the fix):\n{added[:2000]}\n\n"
        f"RECON HANDOFF (the agent's diagnosis):\n{handoff[:5000]}\n\n"
        f"Flag compositional blind spots — axis-crossing conditions, interaction effects, "
        f"shared-state hazards, or edge cases the handoff did NOT explicitly address. "
        f"Be specific and terse. If the handoff is complete, say so.\n\n"
        f"Format: numbered list, up to 8 items. Each: one sentence naming the concern "
        f"and why the current handoff misses it. No praise, no preamble.\n"
    )
    out, dt = flash(adapter, tag, timeout=300)
    log({"instance": iid, "stage": "volley1", "depth": depth, "wall_s": round(dt)})
    return out


def audit(inst, src, final_gate, failbase, changed_files=None, depth=0):
    """Flash static audit on captured patch + gate output. Returns (text, verdict, reenter).

    Flash has no tool-use so we pass only what it can read statically: the source-only
    diff, the pre-patch baseline (so Flash knows which tests were already failing), the
    changed-file list (Flash is weak at diff navigation), and the final gate verdict.
    """
    iid = inst["instance_id"]
    tag = f"audit_{iid.replace('/', '_')}_d{depth}"
    if not changed_files:
        # Fallback: parse from diff header. Regex handles renames; spaces in paths are rare.
        changed_files = sorted({
            m.group(1) for line in src.splitlines()
            if (m := re.match(r"^diff --git a/.+ b/(.+)$", line))
        })
    adapter = (
        f"You will follow the /audit skill below. Review the captured patch and gate output.\n\n"
        f"CHANGED SOURCE FILES ({len(changed_files)} total):\n"
        + "\n".join(f"  {f}" for f in changed_files) + "\n\n"
        f"PRE-PATCH BASELINE (F2P status before the fix — tests failing here were already broken):\n"
        f"{failbase[:1500]}\n\n"
        f"CAPTURED PATCH (source-only diff — test files stripped):\n"
        f"```diff\n{src[:5000]}\n```\n\n"
        f"FINAL GATE OUTPUT:\n{final_gate[:2000]}\n\n"
        f"FAIL_TO_PASS: {str(inst['fail_to_pass'])[:600]}\n"
        f"PASS_TO_PASS: {str(inst.get('pass_to_pass', []))[:600]}\n\n"
        f"Static review only — no container access. Assess:\n"
        f"1. Does the patch address the root cause, or look like a workaround?\n"
        f"2. Does the gate output confirm all FAIL_TO_PASS tests pass?\n"
        f"3. Any obvious regressions (broad changes, deleted logic, test-file edits)?\n\n"
        f"End with two lines exactly:\nVERDICT: <RESOLVED|NOT_RESOLVED|PARTIAL>\n"
        f"RE-ENTER: <recon|craft|none>\n\n"
        f"===================== THE /audit SKILL =====================\n{AUDIT_SKILL}\n"
    )
    out, dt = flash(adapter, tag, timeout=AUDIT_CAP)
    verdict, reenter = "UNKNOWN", "none"
    for line in reversed(out.strip().splitlines()):
        l = line.strip()
        if verdict == "UNKNOWN":
            m = re.match(r"VERDICT:\s*(RESOLVED|NOT_RESOLVED|PARTIAL)", l)
            if m:
                verdict = m.group(1)
        if reenter == "none":
            m = re.match(r"RE-ENTER:\s*(recon|craft|none)", l)
            if m:
                reenter = m.group(1)
        if verdict != "UNKNOWN" and reenter != "none":
            break
    log({"instance": iid, "stage": "audit", "depth": depth,
         "wall_s": round(dt), "verdict": verdict, "reenter": reenter})
    return out, verdict, reenter


# ── patch capture (verbatim _strip_test_blocks from rung5_driver.py) ──────────

_DETRITUS_GLOBS = ("*.bak", "*.bak[0-9]*", "*.orig", "*.rej", "*.pyc", "*.so",
                   "*.aof", "*.rdb", "*.log", "*.min.js", "*.map",
                   "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock")
_DETRITUS_DIRS  = ("__pycache__/", ".pytest_cache/", "result_images/", ".egg-info/",
                   "node_modules/", "dist/", "build/", "coverage/", ".cache/", ".next/")
_MAX_FILE_BLOCK = 262144  # bytes of diff text per file
_TESTFILE_GLOBS = ("test_*.py", "*_test.py", "tests.py", "conftest.py",
                   "*_test.go",
                   "*.test.js", "*.test.jsx", "*.test.ts", "*.test.tsx",
                   "*.spec.js", "*.spec.jsx", "*.spec.ts", "*.spec.tsx")

def _is_detritus(path):
    if any(fnmatch.fnmatch(path, g) for g in _DETRITUS_GLOBS): return True
    return any(seg in path for seg in _DETRITUS_DIRS)

def _is_testfile(path):
    base = path.rsplit("/", 1)[-1]
    if any(fnmatch.fnmatch(base, g) for g in _TESTFILE_GLOBS): return True
    p = f"/{path}"
    return p.startswith("/tests/") or "/tests/" in p or "/test/" in p

def _strip_test_blocks(diff, testfiles):
    tf = set(testfiles or [])
    blocks, cur, bpath = [], [], None
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if cur: blocks.append((bpath, "".join(cur)))
            cur = [line]
            parts = line.split()
            bpath = parts[3][2:] if len(parts) >= 4 and parts[3].startswith("b/") else None
        else:
            cur.append(line)
    if cur: blocks.append((bpath, "".join(cur)))
    out = []
    for bp, text in blocks:
        is_test = (bp in tf) or (bool(bp) and _is_testfile(bp))
        if is_test or (bp and _is_detritus(bp)): continue
        if len(text.encode("utf-8", "replace")) > _MAX_FILE_BLOCK: continue
        out.append(text)
    return "".join(out)

def capture_patch(inst, cid, root):
    iid = inst["instance_id"]; tag = iid.replace("/", "_")
    run(f"docker exec {cid} bash -lc 'cd {root} && "
        r"find . -path ./.git -prune -o \( -name '*.bak' -o -name '*.bak[0-9]*' "
        r"-o -name '*.orig' -o -name '*.pyc' -o -name '*.so' \) -print -delete "
        r">/dev/null 2>&1; "
        r"find . -path ./.git -prune -o -type d \( -name __pycache__ -o -name "
        r".pytest_cache -o -name result_images -o -name '*.egg-info' \) "
        r"-exec rm -rf {} + >/dev/null 2>&1; "
        # Stage everything (incl. untracked new files) so `git diff --cached HEAD`
        # captures composer fixes that create new files. Bare `git diff HEAD` omits
        # untracked files → real fixes silently dropped to no_patch. Mirrors the parent
        # harness (pro_pilot.py). Detritus is already swept above; test files are stripped
        # post-hoc by _strip_test_blocks, so over-staging here is harmless.
        r"git add -A -- . >/dev/null 2>&1; "
        f"echo OK'", timeout=120)
    diff = run(f"docker exec {cid} bash -c 'cd {root} && git diff --cached HEAD'",
               timeout=120).stdout
    # Use --name-only for the file list: authoritative, handles renames, no parse fragility
    names_raw = run(f"docker exec {cid} bash -c 'cd {root} && git diff --cached --name-only HEAD'",
                    timeout=30).stdout.strip().splitlines()
    gold_testpaths = {l[6:] for l in inst.get("test_patch", "").splitlines()
                      if l.startswith("+++ b/")}
    src = _strip_test_blocks(diff, gold_testpaths)
    src_files = sorted(n for n in names_raw if not _is_testfile(n) and not _is_detritus(n))
    (HERE / f"fc_patch_{tag}.diff").write_text(src)
    if not src.strip():
        log({"instance": iid, "stage": "capture", "msg": "EMPTY patch"})
    return src, src_files


GRADER_TIMEOUT = int(os.environ.get("GRADER_TIMEOUT", "7200"))  # 2h hard ceiling

def _log_grader_kill(iid, reason, cid=None):
    """Structured kill log — mirrors swebench-pro's grader_kills.jsonl.
    Lets retry_grader_kills strip spurious LOSSes from the ledger."""
    rec = {"instance_id": iid, "reason": reason, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if cid:
        rec["grader_cid"] = cid
    HERE.mkdir(parents=True, exist_ok=True)
    with open(HERE / "grader_kills.jsonl", "a") as f:
        f.write(json.dumps(rec) + "\n")
    log({"instance": iid, "stage": "grade_kill", **rec})


def _parse_eval_val(val):
    """Schema varies: bare bool ({iid: True}) or nested dict ({iid: {"resolved": True}})."""
    if isinstance(val, bool):
        return val
    if isinstance(val, dict):
        return val.get("resolved")
    return None


def _scp_to_box(local_path, remote_path):
    """Copy a local file to the EC2 box (only valid on the REMOTE_BOX path)."""
    subprocess.run(
        ["scp", "-i", _SSH_PEM, "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=15", str(local_path), f"{_SSH_HOST}:{remote_path}"],
        check=True, capture_output=True, text=True, timeout=180)


def official_grade(inst, src):
    """Grade a patch with the official harness.

    Grading is colocated with the agent's docker host: when REMOTE_BOX is set the
    grader runs ON the EC2 box (against the box's daemon + cached images), so a Mac
    Docker outage can never again turn a win into a None/LOSS.  Falls back to local
    grading (SWEAP_OS_REPO + Mac Docker) only when there is no remote box.
    """
    repo = os.environ.get("SWEAP_OS_REPO", "")
    iid  = inst["instance_id"]
    if not _SSH_HOST and not repo:
        log({"instance": iid, "stage": "grade",
             "msg": "no REMOTE_BOX and no SWEAP_OS_REPO — skipping grade"})
        return None
    tag  = iid.replace("/", "_")
    try:
        import pandas as pd
    except ImportError:
        log({"instance": iid, "stage": "grade", "msg": "pandas not available — skip grade"}); return None
    samp = HERE / f"fc_sample_{tag}.jsonl"
    pred = HERE / f"fc_pred_{tag}.json"
    row  = {k: inst[k] for k in inst if k not in ("run_script", "parser_script")}
    row["fail_to_pass"] = json.dumps(inst["fail_to_pass"])
    row["pass_to_pass"] = json.dumps(inst.get("pass_to_pass", []))
    row["selected_test_files_to_run"] = json.dumps(inst["selected_test_files"])
    pd.DataFrame([row]).to_json(samp, orient="records", lines=True)
    json.dump([{"instance_id": iid, "patch": src, "prefix": ""}], open(pred, "w"))

    if _SSH_HOST:
        return _official_grade_remote(iid, tag, samp, pred)
    return _official_grade_local(iid, tag, samp, pred, repo)


def _official_grade_remote(iid, tag, samp, pred):
    """Ship sample+patch to the box and grade against its docker daemon."""
    dhub = os.environ.get("DOCKERHUB_USER", "jefzda")
    rdir = f"/tmp/fcgrade_{tag}"
    try:
        run(f"mkdir -p {rdir}/out", timeout=60)
        _scp_to_box(samp, f"{rdir}/sample.jsonl")
        _scp_to_box(pred, f"{rdir}/pred.json")
    except Exception as exc:
        log({"instance": iid, "stage": "grade", "msg": f"remote grade ship failed: {exc}"})
        return None
    cmd = (f"cd ~/swebench-pro-os && python3 swe_bench_pro_eval.py "
           f"--raw_sample_path {rdir}/sample.jsonl --patch_path {rdir}/pred.json "
           f"--output_dir {rdir}/out --scripts_dir run_scripts --num_workers 1 "
           f"--use_local_docker --dockerhub_username {dhub} --redo")
    try:
        run(cmd, timeout=GRADER_TIMEOUT)
    except subprocess.TimeoutExpired:
        # Reap grader containers the box left behind, log the kill, surface None.
        run(f"docker ps --filter label=instance_id={iid} -q | xargs -r docker kill", timeout=120)
        _log_grader_kill(iid, "GRADER_TIMEOUT_REMOTE")
        return None
    r = run(f"cat {rdir}/out/eval_results.json 2>/dev/null", timeout=60)
    run(f"rm -rf {rdir}", timeout=60)
    if not (r.stdout or "").strip():
        return None
    try:
        return _parse_eval_val(json.loads(r.stdout).get(iid))
    except Exception:
        return None


def _official_grade_local(iid, tag, samp, pred, repo):
    """Grade against the Mac's docker daemon (fallback when no REMOTE_BOX)."""
    out_dir = HERE / f"fc_grade_{tag}"
    py = os.environ.get("PY", sys.executable)
    try:
        subprocess.run(
            [py, "swe_bench_pro_eval.py",
             "--raw_sample_path", str(samp), "--patch_path", str(pred),
             "--output_dir", str(out_dir), "--scripts_dir", "run_scripts",
             "--num_workers", "1", "--use_local_docker",
             "--dockerhub_username", os.environ.get("DOCKERHUB_USER", "jefzda"),
             "--redo"],
            cwd=repo, timeout=GRADER_TIMEOUT)
    except subprocess.TimeoutExpired:
        # Grader hung — log kill for retry_grader_kills audit, reap any docker containers
        # it left behind (mirrors swebench-pro's grader_kills.jsonl discipline).
        grader_cids = subprocess.run(
            ["docker", "ps", "--filter", f"label=instance_id={iid}", "-q"],
            capture_output=True, text=True).stdout.strip()
        for gcid in grader_cids.splitlines():
            subprocess.run(["docker", "kill", gcid], capture_output=True)
        _log_grader_kill(iid, "GRADER_TIMEOUT", grader_cids or None)
        return None
    res = out_dir / "eval_results.json"
    if not res.exists():
        return None
    return _parse_eval_val(json.load(open(res)).get(iid))


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Phase 0: Flash+Composer one-shot pilot")
    ap.add_argument("task_json",   help="path to task JSON (from make_task.py)")
    ap.add_argument("instance_id", help="instance_id to run")
    args = ap.parse_args()

    tasks = json.load(open(args.task_json))
    inst  = next((t for t in tasks if t["instance_id"] == args.instance_id), None)
    if inst is None:
        sys.exit(f"instance_id {args.instance_id!r} not found in {args.task_json}")
    if inst.get("bench") != "pro":
        sys.exit("not a Pro task — run: BENCH=pro python3 <sibling>/driver/make_task.py <iid>")

    # Preflight: fail fast before spinning up Docker
    if not GEMINI_API_KEY:
        sys.exit("GEMINI_API_KEY not set — export it or source ~/.zshrc")
    if not CURSOR_API_KEY:
        sys.exit("CURSOR_API_KEY not set — export it or source ~/.zshrc")

    # alias uppercase FAIL_TO_PASS so skill prompts that use either form work
    inst.setdefault("FAIL_TO_PASS", inst["fail_to_pass"])
    inst.setdefault("PASS_TO_PASS", inst.get("pass_to_pass", []))

    iid = inst["instance_id"]
    HERE.mkdir(parents=True, exist_ok=True)
    t_start    = time.time()
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    log({"instance": iid, "stage": "pilot_start",
         "model_pair": f"{GEMINI_MODEL}+{COMPOSER_MODEL}"})

    s = pro_setup(inst)
    if not s:
        rec = {"instance_id": iid, "state": "INCOMPLETE", "detail": "setup failed",
               "secs": round(time.time() - t_start),
               "started_at": started_at,
               "ended_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        print("RESULT_JSON " + json.dumps(rec))
        return
    cid, root = s

    # Initialize result vars so RESULT_JSON is always emittable even on crash.
    src = ""; src_files = []; final_gate = ""; verdict = "UNKNOWN"; failbase = ""
    tag = iid.replace("/", "_")
    crashed = False   # harness exception before capture — endogenous, LOSS not INCOMPLETE

    # Always kill the craft container on exit — even on crash/interrupt.
    try:
        box, gate = install_gate(inst, cid, root)

        # Fail-on-base baseline — also warms caches (first gate run may pull deps)
        failbase = run(f"bash {gate}", timeout=1800).stdout
        (HERE / f"fc_failbase_{tag}.txt").write_text(failbase)

        # ── Outer inquiry loop (mirrors parent MAX_OUTER=5) ───────────────────────
        # hgraph accumulates killed/witnessed hypotheses across re-entries so recon
        # never re-proposes already-disproven root causes.
        hgraph = ""
        reenter = "recon"   # first iteration always starts with recon
        handoff = ""

        for depth in range(MAX_OUTER):
            if reenter == "recon":
                handoff = recon(inst, box, gate, hgraph, depth)
                volley  = flash_volley(iid, handoff, inst, depth)
            # reenter == "craft" skips recon, re-uses prior handoff with same volley

            _craft_out, craft_timed_out = craft(inst, box, gate, handoff,
                                                volley if reenter == "recon" else None,
                                                depth)

            # Gate runs before capture so the working tree is post-gate when diffed.
            final_gate = run(f"bash {gate}", timeout=1800).stdout
            (HERE / f"fc_fingate_{tag}_d{depth}.txt").write_text(final_gate)

            src, src_files = capture_patch(inst, cid, root)

            _aout, verdict, reenter = audit(inst, src, final_gate, failbase,
                                            src_files, depth)

            # Append this iteration to the hypothesis graph accumulator.
            hgraph += (f"\n\n## Iteration {depth + 1}  verdict={verdict}\n"
                       f"{handoff[:3000]}\n\nAudit summary: {_aout[:500]}\n")
            (HERE / f"fc_hgraph_{tag}.md").write_text(hgraph)

            log({"instance": iid, "stage": "gate", "depth": depth,
                 "verdict": verdict, "reenter": reenter,
                 "gate_green": "ALL F2P PASSED" in final_gate})

            if verdict == "RESOLVED":
                break
            if craft_timed_out:
                break                   # capture whatever landed; no retry on timeout
            if reenter == "none":
                break                   # audit says stop
            # reenter == "recon" or "craft" → continue loop

    except Exception as exc:
        crashed = True
        log({"instance": iid, "stage": "crash", "msg": str(exc)})
    finally:
        run(f"docker kill {cid} 2>/dev/null")

    # Grade + classify. LOSS is reserved for a REAL graded failure: a patch was produced
    # AND the grader returned False. Everything else that never earned a fair graded
    # result is INCOMPLETE (retryable, recorded non-terminal so it stays runnable instead
    # of inflating the loss count). The coordinator bounds retries at --max-attempts.
    #   - no patch / empty diff  → the agent didn't launch (quota, broken pipe, infra)
    #   - pre-capture crash      → infra, not a capability failure
    #   - grader returned None   → ungraded, not a verdict
    if src.strip():
        resolved = official_grade(inst, src)
        detail   = f"official_resolved={resolved} agent_verdict={verdict}"
        state    = ("WIN"  if resolved is True
                    else "LOSS" if resolved is False
                    else "INCOMPLETE")          # None = ungraded → retry, don't bank a loss
    elif crashed:
        resolved = None
        detail   = f"INCOMPLETE:harness_exception_before_capture agent_verdict={verdict}"
        state    = "INCOMPLETE"
    else:
        resolved = None
        detail   = f"INCOMPLETE:no_patch_produced agent_verdict={verdict}"
        state    = "INCOMPLETE"
    ended_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rec = {
        "instance_id": iid,
        "state":       state,
        "detail":      detail,
        "secs":        round(time.time() - t_start),
        "started_at":  started_at,
        "ended_at":    ended_at,
        "model_pair":  f"{GEMINI_MODEL}+{COMPOSER_MODEL}",
    }
    # RESULT_JSON line — coordinator.py parses this prefix (same schema as sibling)
    print("RESULT_JSON " + json.dumps(rec))
    log({"instance": iid, "stage": "done", **rec})
    print(f"\n=== PILOT {iid} ==="
          f"\n  state: {state}"
          f"\n  patch_bytes: {len(src)}"
          f"\n  gate(final): {'GREEN' if 'ALL F2P PASSED' in final_gate else 'RED'}"
          f"\n  OFFICIAL RESOLVED: {resolved}")


if __name__ == "__main__":
    main()
