# -*- coding: utf-8 -*-
"""Pages build watch: after a report workflow pushes, GitHub fires a
pages-build-deployment for the new commit. That build occasionally hangs in
"building" for hours (observed 2026-11-17: stuck ~2h45m while the workflow run
itself showed success — the site stayed on the previous day's report), and a
hung Pages build is invisible to the run's own `Open issue on failure` step,
which only sees failures inside the run.

This step polls the Pages builds API for a completed build of the pushed
commit and self-heals the observed failure mode: if nothing completes within
--first-wait seconds, it POSTs a rebuild request (the same remedy that fixed
the 2026-11-17 incident by hand) and keeps watching for --second-wait more
seconds. Only then does it exit non-zero, letting the workflow's existing
failure step open the automation-failure alert.

API notes (GITHUB_TOKEN, workflow declares `pages: write`):
  GET  /repos/{repo}/pages/builds   list builds, newest first
  POST /repos/{repo}/pages/builds   request a rebuild of the branch tip; while
        an older build is stuck this replaces it (the stale one flips to
        `errored` and a fresh queued build is created).
The branch tip always contains everything this workflow just pushed, so a
successful build of ANY commit created after this step started also ships our
content — both it and an exact commit match are accepted as success.

Usage (workflow):
    GH_TOKEN: ${{ github.token }}
    python scripts/watch_pages_build.py --sha "$(git rev-parse HEAD)"

Exit codes: 0 = built; 1 = not built after the rebuild window (alert fires).
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
HDRS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "market-brief-pages-watch",
}


def _ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def _call(repo, token, method):
    req = urllib.request.Request(
        "%s/repos/%s/pages/builds" % (API, repo), method=method, headers=dict(
            HDRS, Authorization="Bearer %s" % token))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
        return json.loads(raw.decode("utf-8")) if raw else None
    except urllib.error.HTTPError as e:
        raise RuntimeError("%s %s: %s" % (method, e.code, (e.read() or b"")[:200]))


def main():
    ap = argparse.ArgumentParser(description="watch the GitHub Pages build of a pushed commit")
    ap.add_argument("--sha", required=True, help="full 40-char commit sha that was just pushed")
    ap.add_argument("--first-wait", type=int, default=360,
                    help="seconds to wait for the build before requesting a rebuild (default 360)")
    ap.add_argument("--second-wait", type=int, default=300,
                    help="seconds to keep watching after the rebuild request (default 300)")
    ap.add_argument("--poll", type=int, default=20, help="poll interval seconds (default 20)")
    a = ap.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print(json.dumps({"ok": False, "error": "GH_TOKEN/GITHUB_REPOSITORY not set"}))
        sys.exit(1)

    start = datetime.datetime.now(datetime.timezone.utc)
    deadline = start + datetime.timedelta(seconds=a.first_wait)
    rebuilt = False
    while True:
        try:
            builds = _call(repo, token, "GET") or []
        except Exception as e:  # noqa: BLE001 — transient API errors: keep polling
            print("watch: GET failed (%s)" % e, flush=True)
            builds = []
        mine = [b for b in builds if b.get("commit") == a.sha]
        state = mine[0].get("status") if mine else "no build yet"
        done = any(b.get("status") == "built" and (b.get("commit") == a.sha
                    or _ts(b.get("created_at")) >= start) for b in builds)
        print("watch: ours=%s done=%s rebuilt=%s" % (state, done, rebuilt), flush=True)
        now = datetime.datetime.now(datetime.timezone.utc)
        if done:
            print("watch: Pages build completed for %s" % a.sha[:8])
            sys.exit(0)
        errored = any(b.get("status") == "errored" for b in mine)
        if not rebuilt and (errored or now >= deadline):
            why = "our build errored" if errored else "no completed build in %ss" % a.first_wait
            print("watch: %s -> requesting rebuild" % why, flush=True)
            try:
                _call(repo, token, "POST")
            except Exception as e:  # noqa: BLE001 — rebuild request is best-effort
                print("watch: rebuild request failed (%s)" % e, flush=True)
            rebuilt = True
            deadline = now + datetime.timedelta(seconds=a.second_wait)
        elif rebuilt and now >= deadline:
            print("watch: FAIL — Pages build for %s not completed after rebuild window" % a.sha[:8])
            for b in builds[:5]:
                print("  %s %s %s" % (b.get("status"), b.get("created_at"),
                                      str(b.get("commit"))[:8]))
            sys.exit(1)
        time.sleep(a.poll)


if __name__ == "__main__":
    main()
