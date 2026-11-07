#!/usr/bin/env python3
"""
App Review Scraper
Pulls the most recent reviews for one or more apps from the Apple App Store
and Google Play into one CSV, ready for theme tagging.

Default: the 25 most recent English reviews per app from EACH store,
whatever their date. A 'last_12_months' column marks which ones were posted
in the last 12 months. Use --months to only allow reviews from a date range.

Interactive:   python app_review_scraper.py
From a list:   python app_review_scraper.py --apps-file apps.csv
Help:          python app_review_scraper.py --help

Needs: pip install -r requirements.txt
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import traceback
import urllib.request
from collections import defaultdict
from datetime import date, datetime

DEFAULT_LIMIT = 25
DEFAULT_MONTHS = 0  # 0 = no date limit; just the most recent reviews
RECENT_MONTHS = 12  # for the last_12_months column
APPLE_MAX_PAGES = 10  # Apple's feed stops at 10 pages x 50 reviews

FIELDS = ["store", "country", "review_id", "date", "rating", "title",
          "text", "app_version", "thumbs_up", "dev_reply", "dev_reply_date",
          "app", "lang", "rank", "last_12_months", "theme"]


# ---------------------------------------------------------------- inputs

def parse_apple_id(value):
    """Accept '436762566', 'id436762566', or a full apps.apple.com link."""
    value = (value or "").strip()
    if not value:
        return ""
    m = re.search(r"id(\d+)", value) or re.fullmatch(r"(\d+)", value)
    if not m:
        raise ValueError(f"Can't find an App Store ID in: {value}")
    return m.group(1)


def parse_play_id(value):
    """Accept 'com.example.app' or a full play.google.com link."""
    value = (value or "").strip()
    if not value:
        return ""
    m = re.search(r"[?&]id=([\w.]+)", value)
    if m:
        return m.group(1)
    if "google.com" in value or "/" in value:
        raise ValueError(f"That link has no '?id=' part: {value}")
    if re.fullmatch(r"[A-Za-z][\w]*(\.[\w]+)+", value):
        return value
    raise ValueError(f"Can't find a Google Play package name in: {value}")


def ask(prompt, default=None, required=False):
    suffix = f" [{default}]" if default not in (None, "") else ""
    while True:
        answer = input(f"{prompt}{suffix}: ").strip()
        if answer:
            return answer
        if default is not None:
            return str(default)
        if not required:
            return ""
        print("  This one is required.")


def ask_int(prompt, default, minimum=1):
    while True:
        raw = ask(prompt, default)
        try:
            n = int(raw.replace(",", ""))
            if n >= minimum:
                return n
        except ValueError:
            pass
        print(f"  Enter a whole number of at least {minimum}, like {default}.")


def parse_countries(raw):
    items = [x.strip().lower() for x in raw.replace(" ", ",").split(",") if x.strip()]
    bad = [x for x in items if not re.fullmatch(r"[a-z]{2}", x)]
    return list(dict.fromkeys(items)), bad


def ask_countries(default):
    while True:
        items, bad = parse_countries(ask("App Store countries", ",".join(default)))
        if items and not bad:
            return items
        print(f"  Not a valid code: {', '.join(bad)}. Use two-letter codes like us, gb."
              if bad else "  Enter at least one.")


def ask_apps():
    apps = []
    print("\nSTEP 1: Apps")
    print("  For each app, paste its store link (or ID) from the App Store and/or")
    print("  Google Play. Press Enter to skip a store the app isn't on.")
    while True:
        print(f"\n-- App {len(apps) + 1} --")
        name = ask("Name for this app (labels its rows in the CSV)", required=True)
        while True:
            try:
                apple = play = ""
                first = ask("App Store link or ID (or press Enter to skip)")
                if "play.google.com" in first:
                    play = parse_play_id(first)
                    print(f"  That's a Google Play link, so it's been added as Google Play: {play}")
                    if ask("Also add an App Store link? (y/n)", "n").lower() == "y":
                        apple = parse_apple_id(ask("App Store link or ID"))
                else:
                    apple = parse_apple_id(first)
                    if apple:
                        print(f"  Found App Store ID: {apple}")
                    play = parse_play_id(ask("Google Play link or package name (or press Enter to skip)"))
                    if play:
                        print(f"  Found Google Play package: {play}")
            except ValueError as e:
                print(f"  {e}")
                continue
            if apple or play:
                break
            print("  Each app needs at least one store link. Try again.")
        apps.append({"name": name, "apple": apple, "play": play})
        print(f"  Added {name}.")
        if ask("Add another app, e.g. a competitor? (y/n)", "n").lower() != "y":
            return apps


def load_apps_file(path):
    """CSV with columns: name, apple, play (either store may be blank)."""
    apps = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            if not any(row.values()):
                continue
            try:
                app = {"name": row.get("name", ""),
                       "apple": parse_apple_id(row.get("apple")),
                       "play": parse_play_id(row.get("play"))}
            except ValueError as e:
                sys.exit(f"{path} line {i}: {e}")
            if not app["name"] or not (app["apple"] or app["play"]):
                sys.exit(f"{path} line {i}: needs a name and at least one store")
            apps.append(app)
    if not apps:
        sys.exit(f"{path} has no apps in it")
    return apps


def months_ago(n, today=None):
    today = today or date.today()
    y, m = divmod(today.year * 12 + today.month - 1 - n, 12)
    m += 1
    days = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(today.day, days)).isoformat()


# ---------------------------------------------------------------- language filter

COMMON_EN = set("""the a an and or but is are was were be been it its this that i me my
you your we they she he her his to of in on for with at by from not no so very app use
using love like good great just have has had do does did can can't don't it's i'm all if
when what how will would get got one track tracking helpful easy only now new update""".split())


def make_english_check():
    """Returns a function that flags clearly non-English text, or None if
    langdetect isn't installed. Reviews under 4 words are always kept,
    since language detection is unreliable on a few words."""
    try:
        from langdetect import DetectorFactory, LangDetectException, detect_langs
    except ImportError:
        print("! English filter needs:  pip install langdetect  (keeping all languages)")
        return None
    DetectorFactory.seed = 0  # same answer every run

    def is_non_english(text):
        words = re.findall(r"[^\W\d_]+", text)
        if len(words) < 4:
            return False
        latin = re.findall(r"[a-z']+", text.lower())
        if latin and sum(w in COMMON_EN for w in latin) / len(latin) >= 0.2:
            return False
        try:
            top = detect_langs(text)[0]
        except LangDetectException:
            return False
        return top.lang != "en" and top.prob >= 0.9
    return is_non_english


# ---------------------------------------------------------------- fetchers

def fetch_json(url, retries=2):
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                body = r.read().decode("utf-8", "replace")
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                raise RuntimeError("Apple sent back a web page instead of review "
                                   f"data (starts with: {body[:60]!r})")
        except Exception:
            if attempt == retries:
                raise
            time.sleep(2 * (attempt + 1))


def pull_apple(app, countries, limit, cutoff, non_english, stats, diag):
    """Newest reviews per country (feed is newest-first), stopping at the
    date cutoff or once `limit` usable reviews are found in that country.
    `diag` collects, per country, why nothing may have come back."""
    rows = []
    for cc in countries:
        found, older = [], False
        info = diag.setdefault((app["name"], cc), {"seen": 0, "newest": "", "error": ""})
        for page in range(1, APPLE_MAX_PAGES + 1):
            url = (f"https://itunes.apple.com/{cc}/rss/customerreviews/"
                   f"page={page}/id={app['apple']}/sortby=mostrecent/json")
            try:
                data = fetch_json(url)
            except Exception as e:
                print(f"    ! App Store {cc} page {page}: {e}")
                info["error"] = str(e)
                break
            entries = data.get("feed", {}).get("entry", [])
            if isinstance(entries, dict):
                entries = [entries]
            entries = [e for e in entries if "im:rating" in e]
            if not entries:
                break
            for e in entries:
                d = e.get("updated", {}).get("label", "")[:10]
                info["seen"] += 1
                info["newest"] = max(info["newest"], d)
                if cutoff and d and d < cutoff:
                    older = True
                    break
                title = e.get("title", {}).get("label", "")
                text = e.get("content", {}).get("label", "")
                if non_english and non_english(f"{title} {text}"):
                    stats["non_english"] += 1
                    continue
                found.append({
                    "store": "app_store", "country": cc,
                    "review_id": e["id"]["label"], "date": d,
                    "rating": int(e["im:rating"]["label"]),
                    "title": title, "text": text,
                    "app_version": e.get("im:version", {}).get("label", ""),
                    "thumbs_up": e.get("im:voteSum", {}).get("label", ""),
                    "dev_reply": "", "dev_reply_date": "",
                    "app": app["name"], "lang": "en" if non_english else "",
                })
                if len(found) >= limit:
                    break
            if older or len(found) >= limit:
                break
            time.sleep(0.4)
        why = ""
        if not found:
            if info["error"]:
                why = " (Apple's server didn't answer properly; see the '!' line above)"
            elif info["seen"] == 0:
                why = " (Apple has no written reviews for this app in this country)"
            else:
                why = (f" (newest written review on Apple here is from {info['newest']},"
                       " older than your date range)")
        print(f"    App Store {cc}: {len(found)} found{why}")
        rows += found
    rows.sort(key=lambda r: r["date"], reverse=True)  # newest across countries
    return rows[:limit]


def pull_play(app, limit, cutoff, country, non_english, stats):
    try:
        from google_play_scraper import Sort, reviews
    except ImportError:
        print("    ! Skipping Google Play: run  pip install google-play-scraper")
        return []
    rows, token, done = [], None, False
    while not done:
        try:
            batch, token = reviews(app["play"], lang="en", country=country,
                                   sort=Sort.NEWEST, count=100,
                                   continuation_token=token)
        except Exception as e:
            print(f"    ! Google Play: {e}")
            break
        if not batch:
            break
        for r in batch:
            d = r["at"].strftime("%Y-%m-%d") if r.get("at") else ""
            if cutoff and d and d < cutoff:
                done = True
                break
            text = r.get("content") or ""
            if non_english and non_english(text):
                stats["non_english"] += 1
                continue
            rows.append({
                "store": "google_play", "country": country,
                "review_id": r["reviewId"], "date": d,
                "rating": r["score"], "title": "", "text": text,
                "app_version": r.get("reviewCreatedVersion") or "",
                "thumbs_up": r.get("thumbsUpCount", 0),
                "dev_reply": r.get("replyContent") or "",
                "dev_reply_date": r["repliedAt"].strftime("%Y-%m-%d")
                if r.get("repliedAt") else "",
                "app": app["name"], "lang": "en" if non_english else "",
            })
            if len(rows) >= limit:
                done = True
                break
        if token is None or getattr(token, "token", None) is None:
            break
        time.sleep(0.4)
    print(f"    Google Play: {len(rows)} found")
    return rows


# ---------------------------------------------------------------- report

def coverage_report(rows, apps, limit, months, diag=None):
    window = f"last {months} months" if months else "any date"
    recent_cut = months_ago(RECENT_MONTHS)
    groups = defaultdict(list)
    for r in rows:
        groups[(r["app"], r["store"])].append(r)
    print(f"\nCoverage report (goal: {limit} most recent per app per store, {window})")
    print(f"{'app':30} {'store':12} {'got':>7} {'oldest':>11} {'newest':>11} {'avg':>5} {'last 12mo':>10}")
    short = []
    for x in apps:
        for store, key in (("app_store", "apple"), ("google_play", "play")):
            if not x[key]:
                continue
            rs = groups.get((x["name"], store), [])
            got = f"{len(rs)}/{limit}"
            recent = sum(r["date"] >= recent_cut for r in rs)
            if not rs:
                print(f"{x['name'][:30]:30} {store:12} {got:>7}   <-- none found (reason below)")
                short.append((x["name"], store, 0))
                continue
            dates = sorted(r["date"] for r in rs)
            avg = sum(int(r["rating"]) for r in rs) / len(rs)
            flag = "  <-- short" if len(rs) < limit else ""
            print(f"{x['name'][:30]:30} {store:12} {got:>7} {dates[0]:>11} "
                  f"{dates[-1]:>11} {avg:>5.2f} {recent:>10}{flag}")
            if len(rs) < limit:
                short.append((x["name"], store, len(rs)))
    zero_apple = [n for n, st, c in short if st == "app_store" and c == 0]
    for name in zero_apple:
        for (app, cc), info in (diag or {}).items():
            if app != name:
                continue
            if info["error"]:
                print(f"\n{name} / App Store {cc}: the request failed: {info['error']}")
                print("  Check your internet connection and try again. If it keeps happening,")
                print("  send this message to whoever maintains the tool.")
            elif info["seen"] == 0:
                print(f"\n{name} / App Store {cc}: Apple returned no written reviews at all.")
                print("  Check the App Store ID. If it's right, the app has star ratings but no")
                print("  written reviews in this country.")
            else:
                print(f"\n{name} / App Store {cc}: no written reviews in the {window}.")
                print(f"  The newest one on Apple is from {info['newest']}. Remove --months to take")
                print("  the most recent reviews whatever their date.")
    if short:
        print(f"\nShort: fewer than {limit} reviews exist ({window}). That is a finding")
        print("in itself; record it. To try for more, add App Store countries")
        print("(e.g. --countries us,gb,ca,au).")
    print(f"\n'last 12mo' = how many were posted in the last {RECENT_MONTHS} months (since {recent_cut}).")
    print("The same thing is marked per review in the 'last_12_months' column.")


# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(
        description="Pull the most recent App Store and Google Play reviews into "
                    "one CSV. Run with no options to be prompted for everything.")
    p.add_argument("--apps-file", help="CSV with columns name,apple,play")
    p.add_argument("--limit", type=int, help=f"Reviews per app per store (default {DEFAULT_LIMIT})")
    p.add_argument("--months", type=int, help="Only allow reviews from the last N months (default: no limit)")
    p.add_argument("--countries", help="App Store countries, e.g. us,gb (default us)")
    p.add_argument("--play-country", default="us", help="Google Play country (default us)")
    p.add_argument("--all-languages", action="store_true",
                   help="Keep non-English reviews (default: English only)")
    p.add_argument("-o", "--output", help="Output CSV file name")
    p.add_argument("--no-pause", action="store_true",
                   help="Close right away when finished (don't wait for Enter)")
    a = p.parse_args()

    print("=== App Review Scraper ===")
    print("Pulls the most recent reviews from the App Store and Google Play into one CSV.")
    interactive = not a.apps_file
    if interactive:
        print("Tip: press Enter to keep the suggested answer shown in [brackets].")
        print("     Press Ctrl+C at any time to cancel.")
    apps = load_apps_file(a.apps_file) if a.apps_file else ask_apps()
    has_apple = any(x["apple"] for x in apps)

    if interactive:
        print("\nSTEP 2: Settings")
        print(f"\n  How many of the most recent reviews to take from EACH store, per app.")
        print(f"  The capstone brief uses {DEFAULT_LIMIT}.")
    limit = a.limit or (ask_int("Reviews per app per store", DEFAULT_LIMIT)
                        if interactive else DEFAULT_LIMIT)
    if interactive and a.months is None:
        print("\n  Date limit: 0 = no limit (just take the most recent reviews, even if")
        print("  some are older). Or enter a number like 12 to only allow reviews from")
        print("  the last 12 months. Either way, a column marks which are from the last 12 months.")
    months = a.months if a.months is not None else (
        ask_int("Date limit in months (0 = no limit)", DEFAULT_MONTHS, minimum=0)
        if interactive else DEFAULT_MONTHS)
    countries = ["us"]
    if has_apple:
        if a.countries:
            countries, bad = parse_countries(a.countries)
            if bad or not countries:
                sys.exit(f"Not a valid country code: {', '.join(bad) or a.countries}")
        elif interactive:
            print("\n  App Store country to pull from: us = United States. If an app is")
            print("  short on reviews, you can add more, like us,gb,ca,au; the newest")
            print("  reviews across all of them are kept.")
            countries = ask_countries(["us"])

    default_out = f"reviews_{datetime.now():%Y%m%d_%H%M}.csv"
    if interactive and not a.output:
        print("\n  File name for the results (.csv is added for you).")
    out = a.output or (ask("File name", default_out) if interactive else default_out)
    out = out.strip().strip('"')
    if not out.lower().endswith(".csv"):
        out += ".csv"
    out_path = os.path.abspath(out)
    cutoff = months_ago(months) if months else ""

    print("\nSTEP 3: Check and start")
    for x in apps:
        stores = []
        if x["apple"]:
            stores.append(f"App Store {x['apple']}")
        if x["play"]:
            stores.append(f"Google Play {x['play']}")
        print(f"  App:        {x['name']}  ({', '.join(stores)})")
    print(f"  Reviews:    up to {limit} most recent per app per store")
    print(f"  Date range: {f'{cutoff} to today (last {months} months)' if months else 'any date (most recent first)'}")
    if has_apple:
        print(f"  App Store:  {', '.join(countries)}")
    print(f"  Language:   {'all' if a.all_languages else 'English only'}")
    print(f"  Save to:    {out_path}")
    if os.path.exists(out_path):
        print("  Note: a file with this name exists and will be replaced.")
    if interactive and ask("Start? (y/n)", "y").lower() != "y":
        sys.exit("Cancelled. Nothing was downloaded.")
    print("\nPulling reviews...")

    non_english = None if a.all_languages else make_english_check()
    stats = defaultdict(int)
    diag = {}
    rows = []
    for app in apps:
        print(f"\n== {app['name']} ==")
        for pull in ([lambda: pull_apple(app, countries, limit, cutoff, non_english, stats, diag)]
                     if app["apple"] else []) + \
                    ([lambda: pull_play(app, limit, cutoff, a.play_country, non_english, stats)]
                     if app["play"] else []):
            got = pull()
            recent_cut = months_ago(RECENT_MONTHS)
            for i, r in enumerate(got, start=1):
                r["rank"], r["theme"] = i, ""
                r["last_12_months"] = "yes" if r["date"] >= recent_cut else "no"
            rows += got

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"\nDone! Saved {len(rows)} reviews to:\n  {out_path}")
    if stats["non_english"]:
        print(f"(Skipped {stats['non_english']} non-English reviews.)")
    print("The empty 'theme' column is there for tagging each review with one theme.")
    coverage_report(rows, apps, limit, months, diag)


def pause():
    """Keep the window open so people can read the results (matters when
    the script is opened by double-clicking)."""
    if "--no-pause" in sys.argv:
        return
    try:
        input("\nPress Enter to close this window...")
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    code = 0
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
        code = 1
    except SystemExit as e:
        if e.code not in (None, 0):
            print(e.code if isinstance(e.code, str) else f"Stopped (code {e.code}).")
            code = 1
    except Exception:
        print("\nSomething went wrong. Copy everything below when asking for help:\n")
        traceback.print_exc()
        code = 1
    pause()
    sys.exit(code)
