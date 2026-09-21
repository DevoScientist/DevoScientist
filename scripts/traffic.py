#!/usr/bin/env python3
"""Build assets/traffic.svg from GitHub's own repository-traffic API.

GitHub only keeps 14 days of traffic, so every run merges the latest 14 days into
traffic-data/history.json. The card shows the rolling 14-day numbers plus the totals
tracked since the first run. Standard library only.

Env:  TRAFFIC_TOKEN  fine-grained token, "Administration: read" on your repos
      OWNER          GitHub username (defaults to $GITHUB_REPOSITORY_OWNER)
Usage: python3 scripts/traffic.py            (normal run)
       python3 scripts/traffic.py --mock out.svg   (render sample data, no API calls)
"""
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY = os.path.join(ROOT, "traffic-data", "history.json")
CARD = os.path.join(ROOT, "assets", "traffic.svg")
API = "https://api.github.com"


# --------------------------------------------------------------------------- API
def api(path, token):
    req = urllib.request.Request(
        API + path,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "profile-traffic-card",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def list_repos(owner, token):
    repos, page = [], 1
    while True:
        batch = api(f"/users/{owner}/repos?type=owner&per_page=100&page={page}", token)
        repos += batch
        if len(batch) < 100:
            return [r for r in repos if not r.get("fork")]
        page += 1


def collect(owner, token):
    """Aggregate per-day numbers across all public, non-fork repos."""
    days, totals, ok, failed = {}, dict(views=0, uniques=0, clones=0, clone_uniques=0), 0, 0
    repos = list_repos(owner, token)
    for repo in repos:
        name = repo["name"]
        try:
            v = api(f"/repos/{owner}/{name}/traffic/views", token)
            c = api(f"/repos/{owner}/{name}/traffic/clones", token)
        except urllib.error.HTTPError as e:
            failed += 1
            print(f"  skip {name}: HTTP {e.code}")
            continue
        ok += 1
        totals["views"] += v.get("count", 0)
        totals["uniques"] += v.get("uniques", 0)
        totals["clones"] += c.get("count", 0)
        totals["clone_uniques"] += c.get("uniques", 0)
        for row in v.get("views", []):
            d = days.setdefault(row["timestamp"][:10], dict(views=0, uniques=0, clones=0, clone_uniques=0))
            d["views"] += row["count"]
            d["uniques"] += row["uniques"]
        for row in c.get("clones", []):
            d = days.setdefault(row["timestamp"][:10], dict(views=0, uniques=0, clones=0, clone_uniques=0))
            d["clones"] += row["count"]
            d["clone_uniques"] += row["uniques"]
    return days, totals, len(repos), ok, failed


# ----------------------------------------------------------------------- history
def merge_history(new_days, repo_count):
    hist = {"tracking_since": None, "days": {}}
    if os.path.exists(HISTORY):
        hist = json.load(open(HISTORY))
    for date, vals in new_days.items():
        old = hist["days"].get(date, {})
        # a day's numbers only ever grow, so never let a partial fetch lower them
        hist["days"][date] = {k: max(vals[k], old.get(k, 0)) for k in vals}
    if hist["days"]:
        hist["tracking_since"] = min(hist["days"])
    hist["repos"] = repo_count
    hist["updated"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    json.dump(hist, open(HISTORY, "w"), indent=1, sort_keys=True)
    return hist


# --------------------------------------------------------------------------- SVG
BG, TITLE, TEXT, ICON = "#1a1b27", "#70a5fd", "#38bdae", "#bf91f3"
FONT = "'Segoe UI',Ubuntu,'Helvetica Neue',Arial,sans-serif"
ICONS = {
    "views": '<path d="M2,10C5,4 15,4 18,10C15,16 5,16 2,10Z"/><circle cx="10" cy="10" r="2.6"/>',
    "uniques": '<circle cx="10" cy="6.5" r="3.5"/><path d="M3,17.5C3,11.5 17,11.5 17,17.5"/>',
    "clones": '<rect x="3" y="3" width="10" height="10" rx="2"/><path d="M7,17H15A2,2 0 0 0 17,15V7"/>',
}


def fmt(n):
    return f"{n:,}"


def spark(values, x0, x1, y_base, y_top):
    n = len(values)
    peak = max(max(values), 1)
    h = y_base - y_top
    pts = [(x0 + i * (x1 - x0) / (n - 1), y_base - (v / peak) * h) for i, v in enumerate(values)]
    line = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
    for i in range(1, n - 1):  # smooth curve through midpoints
        mx, my = (pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2
        line += f" Q{pts[i][0]:.1f},{pts[i][1]:.1f} {mx:.1f},{my:.1f}"
    line += f" L{pts[-1][0]:.1f},{pts[-1][1]:.1f}"
    area = line + f" L{x1:.1f},{y_base} L{x0:.1f},{y_base}Z"
    return line, area, peak


def render(hist, totals, repo_count, placeholder=False):
    today = dt.datetime.now(dt.timezone.utc).date()
    dates = [(today - dt.timedelta(days=29 - i)) for i in range(30)]
    daily = [hist["days"].get(d.isoformat(), {}).get("views", 0) for d in dates]
    line, area, peak = spark(daily, 452, 788, 176, 92)
    tracked_views = sum(v["views"] for v in hist["days"].values())
    tracked_clones = sum(v["clones"] for v in hist["days"].values())
    since = hist.get("tracking_since") or "-"
    updated = hist.get("updated") or today.isoformat()

    rows = [("views", "Views", totals["views"]), ("uniques", "Unique visitors", totals["uniques"]), ("clones", "Clones", totals["clones"])]
    body = []
    for i, (key, label, val) in enumerate(rows):
        y = 88 + i * 40
        body.append(f'<g transform="translate(32 {y-16})" fill="none" stroke="{ICON}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{ICONS[key]}</g>')
        body.append(f'<text x="64" y="{y}" font-size="17" fill="{TEXT}">{label}</text>')
        body.append(f'<text x="396" y="{y}" font-size="19" font-weight="600" fill="{TEXT}" text-anchor="end">{fmt(val)}</text>')

    footer1 = ("Waiting for the first daily update" if placeholder else
               f"Tracked since {since}: {fmt(tracked_views)} views · {fmt(tracked_clones)} clones · {repo_count} public repos")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="820" height="248" viewBox="0 0 820 248" role="img" aria-label="Repository traffic, last 14 days">
<title>Repository traffic, last 14 days</title>
<defs>
  <linearGradient id="a" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{ICON}" stop-opacity="0.55"/>
    <stop offset="1" stop-color="{ICON}" stop-opacity="0.03"/>
  </linearGradient>
</defs>
<rect width="820" height="248" rx="8" fill="{BG}"/>
<g font-family="{FONT}">
  <text x="32" y="40" font-size="22" fill="{TITLE}">Repository Traffic</text>
  <text x="788" y="38" font-size="11" fill="{TEXT}" fill-opacity="0.65" text-anchor="end">last 14 days · updated {updated}</text>
  {chr(10).join("  " + b for b in body).strip()}
  <text x="452" y="66" font-size="12" fill="{TEXT}" fill-opacity="0.8">Daily views · last 30 days</text>
  <text x="788" y="66" font-size="11" fill="{TEXT}" fill-opacity="0.65" text-anchor="end">peak {peak}</text>
  <line x1="452" y1="176.5" x2="788" y2="176.5" stroke="{TEXT}" stroke-opacity="0.25"/>
  <path d="{area}" fill="url(#a)"/>
  <path d="{line}" fill="none" stroke="{ICON}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <text x="452" y="192" font-size="10" fill="{TEXT}" fill-opacity="0.65">{dates[0].strftime("%b %d")}</text>
  <text x="788" y="192" font-size="10" fill="{TEXT}" fill-opacity="0.65" text-anchor="end">{dates[-1].strftime("%b %d")}</text>
  <text x="32" y="222" font-size="12" fill="{TEXT}" fill-opacity="0.85">{footer1}</text>
  <text x="32" y="238" font-size="10.5" fill="{TEXT}" fill-opacity="0.55">GitHub keeps 14 days of traffic; older days are stored by this repo. Unique visitors are summed per repository.</text>
</g>
</svg>'''


# -------------------------------------------------------------------------- main
def mock(out):
    import random
    random.seed(7)
    today = dt.datetime.now(dt.timezone.utc).date()
    days = {}
    for i in range(30):
        d = (today - dt.timedelta(days=29 - i)).isoformat()
        days[d] = dict(views=max(0, int(random.gauss(9, 6)) + (12 if i in (8, 9, 21) else 0)), uniques=3, clones=random.randint(0, 6), clone_uniques=2)
    hist = {"tracking_since": min(days), "days": days, "updated": today.isoformat()}
    last14 = list(days.values())[-14:]
    totals = dict(views=sum(v["views"] for v in last14), uniques=sum(v["uniques"] for v in last14) // 2,
                  clones=sum(v["clones"] for v in last14), clone_uniques=0)
    open(out, "w").write(render(hist, totals, 22))


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--mock":
        return mock(sys.argv[2])
    token = os.environ.get("TRAFFIC_TOKEN", "").strip()
    owner = os.environ.get("OWNER") or os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    if not token or not owner:
        sys.exit("TRAFFIC_TOKEN or OWNER is missing - add the TRAFFIC_TOKEN secret (see instructions). Card left unchanged.")
    try:
        days, totals, repo_count, ok, failed = collect(owner, token)
    except urllib.error.HTTPError as e:
        sys.exit(f"GitHub API returned HTTP {e.code} while listing repositories - check the token. Card left unchanged.")
    print(f"{ok} repos read, {failed} skipped")
    if ok == 0:
        sys.exit('No repository traffic could be read. The token needs "Administration: Read" on your repositories. Card left unchanged.')
    hist = merge_history(days, repo_count)
    os.makedirs(os.path.dirname(CARD), exist_ok=True)
    open(CARD, "w").write(render(hist, totals, repo_count))
    print("wrote", CARD)


if __name__ == "__main__":
    main()
