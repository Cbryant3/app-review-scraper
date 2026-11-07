# App Review Scraper

Pulls the **most recent reviews** for any app from the **Apple App Store** and **Google Play** into one CSV, ready for theme tagging.

**Default: the 25 most recent English reviews per app from each store, whatever their date.** If an app has fewer than 25 reviews from the last 12 months, the tool still fills the 25 with older ones. The `last_12_months` column marks each review `yes` or `no`, so you can report how many are recent.

The FA26 capstone brief asks for the 25 most recent reviews from the last 12 months. To pull strictly that way, add `--months 12`. Either way, state in your method which one your pod used, so all pods stay comparable.

## Setup (once)

1. Install Python 3.9 or newer.
2. In a terminal, in this folder, run:
   ```
   pip install -r requirements.txt
   ```

## Run it

**Option A: use the app list (fastest)**

`apps.csv` already lists the apps named in the brief:

| name | App Store | Google Play |
|---|---|---|
| IVY Wellness Coach | 1005052173 | com.bellabeat.cacao |
| IVY Period & Pregnancy Tracker | 436762566 | org.nanobit.perioddiary |
| Flo | 1038369065 | org.iggymedia.periodtracker |
| Oura | 1043837948 | com.ouraring.oura |
| Calm | 571800810 | com.calm.android |

Delete the rows your pod doesn't need (or add new ones), then run:
```
python app_review_scraper.py --apps-file apps.csv -o pod3_reviews
```

**Option B: answer the prompts**
```
python app_review_scraper.py
```
It walks you through 3 steps:
1. **Apps:** a name for each app plus its App Store and/or Google Play link. Add as many as you want.
2. **Settings:** reviews per store (25), date limit (0 = none), App Store country (us) and file name. Press Enter to keep the suggested answer in `[brackets]`.
3. **Check and start:** a summary, including the full path the file will be saved to. Type `y` to start.

If you mistype something (a bad country code, a link from the wrong store), it tells you what's wrong and asks again.

## Options

| Option | What it does | Default |
|---|---|---|
| `--apps-file` | CSV of apps (`name,apple,play`) | prompts you |
| `--limit` | Most recent reviews to take per app, per store | `25` |
| `--months` | Only allow reviews from the last N months (e.g. `12`) | no limit |
| `--countries` | App Store countries; the newest across all of them are kept | `us` |
| `--play-country` | Google Play country | `us` |
| `--all-languages` | Keep non-English reviews | off (English only) |
| `-o` | Output file name (`.csv` added for you) | `reviews_<date>_<time>.csv` |
| `--no-pause` | Close right away instead of waiting for Enter | waits |

## Finding an app's store ID

- **App Store:** the number after `id` in the link: `apps.apple.com/us/app/.../id`**`1005052173`**
- **Google Play:** the part after `?id=`, up to any `&`: `play.google.com/store/apps/details?id=`**`com.bellabeat.cacao`**`&...`

Pasting the full link works too.

## Output columns

| Column | Meaning |
|---|---|
| store | `app_store` or `google_play` |
| country | Store country the review came from |
| review_id | Store's ID for the review |
| date | Review date (YYYY-MM-DD) |
| rating | Stars, 1–5 |
| title | Review title (App Store only) |
| text | Review text |
| app_version | App version the reviewer had |
| thumbs_up | Helpful votes |
| dev_reply, dev_reply_date | Developer's reply (Google Play only) |
| app | The name you gave the app |
| lang | `en` when the English filter was used |
| rank | 1 = newest, within each app and store |
| last_12_months | `yes` if posted in the last 12 months, else `no` |
| theme | **Empty.** Fill in one theme per review when you tag them |

## When it finishes

The window stays open until you press Enter, so you can read the summary and coverage report, even if something went wrong. If you run it from a script and don't want it to wait, add `--no-pause`.

## If the App Store shows 0 reviews

The tool says why, both while it runs and in the coverage report:

- **"newest written review on Apple here is from 2021-05-01"**: only happens when you set `--months`. The app has written reviews, but none in that range. Record the date of the newest one, or run again without `--months`.
- **"Apple has no written reviews for this app in this country"**: check the App Store ID. If it's right, the app only has star ratings there.
- **"Apple's server didn't answer properly"**: a connection problem. Try again and copy the `!` line if it keeps happening.

Many apps get thousands of star ratings but very few written reviews, so a small or empty App Store sample is normal for small apps like IVY Wellness Coach.

## Old vs. recent reviews

The coverage report has a **last 12mo** column showing how many of each app's 25 were posted in the last 12 months. If it's low (e.g. 3 of 25), **that's a finding; write it down**, e.g. "only 3 of the 25 most recent App Store reviews are from the last 12 months (checked Nov 7, 2026)". It shows how little recent feedback the app gets.

If an app has fewer than 25 reviews in total, the tool takes what exists and marks it `<-- short`. For the App Store you can try adding countries (`--countries us,gb,ca,au`), but say so in your method.

## English only

Reviews written clearly in another language are skipped, and the tool reports how many. Reviews under 4 words ("Nice", "Accurate") are always kept, because language detection isn't reliable on a few words. Add `--all-languages` to keep everything.

## Notes

- Developer replies only come through for Google Play.
- Record the date you ran the tool; the brief asks for a date on every figure.
- Log use of this tool in your pod's AI Disclosure Statement.
