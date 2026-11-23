# Used games restock watcher

Checks the Games Unlimited used-games collection every 2 hours and publishes an
RSS feed of **new listings** and games that come **back in stock**.

## Setup (about 5 minutes)

1. Create a new **public** GitHub repo (public so your feed reader can fetch
   the feed without a login).
2. Add these files, keeping the folder layout:
   ```
   check_restocks.py
   .github/workflows/check.yml
   ```
   (The web UI works: "Add file → Create new file" and type
   `.github/workflows/check.yml` as the name.)
3. Go to the **Actions** tab, enable workflows if asked, pick
   **Check used games** → **Run workflow**. The first run saves a baseline
   and creates `feed.xml`; it records no events.
4. Subscribe to this URL in your feed reader:
   ```
   https://raw.githubusercontent.com/YOUR-USERNAME/YOUR-REPO/main/feed.xml
   ```

From then on, any game that's new or flips from sold out to in stock appears
as a new feed item, including a second or third copy of the same game.

## Notes

- **Schedule:** edit the `cron` line in `check.yml`. Times are UTC, and GitHub
  sometimes starts scheduled runs late.
- **Inactivity:** GitHub can pause scheduled workflows in a public repo after
  60 days without activity, and emails you when it does. If that happens,
  re-enable it on the Actions tab.
- **Sold-out games:** this store removes sold-out games from the collection
  instead of marking them sold out. `seen.json` remembers every product ever
  listed, so when one reappears it's labeled "Back in stock" rather than
  "New listing". (Games sold out before the first run aren't in it yet, so the
  first restock of each of those will say "New listing".)
- **Limits:** the store's data only says whether a game is in stock, not how
  many copies. If they get a second copy while the first is still unsold,
  nothing changes, so there's nothing to report.
- **Other collections:** set `COLLECTION` (and `FEED_TITLE`) as environment
  variables in the workflow step to watch something else.
- **Safety net:** if a fetch returns nothing, or far fewer products than last
  time, the script refuses to overwrite its saved state, so a store hiccup
  won't flood you with fake "new" items.
