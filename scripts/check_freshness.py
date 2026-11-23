"""Weekly freshness check for the hand-maintained parts of the newsroom.

Writes reminder.md (and prints STALE) when something needs a person:
  - site/gcc_weekly.json is more than 8 days old (GCC Research card has gone quiet)
  - site/events.json has no verified event in the next 30 days
The workflow turns reminder.md into a GitHub issue, which GitHub emails to the repo owner.
"""
import datetime as dt
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
today = dt.datetime.now(IST).date()
problems = []

try:
    w = json.load(open(os.path.join(ROOT, "site", "gcc_weekly.json"), encoding="utf-8"))
    wk = dt.date.fromisoformat(w.get("week_of", "2000-01-01"))
    age = (today - wk).days
    if age > 8:
        problems.append(
            f"**GCC Research card is {age} days old** (last brief: week of {wk:%d %b %Y}).\n"
            "  Paste this week's GCC Index Weekly Intelligence Brief into Claude (or into `site/gcc_weekly.json`), "
            "verify each claim in news reports, and publish.")
except Exception as e:
    problems.append(f"**Could not read site/gcc_weekly.json** ({e}).")

try:
    ev = json.load(open(os.path.join(ROOT, "site", "events.json"), encoding="utf-8"))
    soon = []
    for e in ev.get("items", []):
        start = dt.date.fromisoformat(e["start"])
        end = dt.date.fromisoformat(e.get("end") or e["start"])
        if end >= today and (start - today).days <= 30:
            soon.append(e["name"])
    if not soon:
        problems.append(
            "**No verified events in the next 30 days.** Ask Claude to research upcoming GCC, HR/talent, AI and "
            "startup events in India (verify each on the organiser's own site) and add them to `site/events.json`.")
except Exception as e:
    problems.append(f"**Could not read site/events.json** ({e}).")

if problems:
    body = ("The newsroom's automatic weekly update could not keep these up to date by itself. "
            "Please take a look:\n\n" + "\n\n".join(f"- {p}" for p in problems) +
            f"\n\n_Checked {today:%A %d %b %Y}. This issue closes itself once everything is fresh again._")
    open(os.path.join(ROOT, "reminder.md"), "w", encoding="utf-8").write(body)
    print("STALE")
else:
    print("FRESH")
