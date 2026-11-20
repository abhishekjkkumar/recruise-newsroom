# Recruise Live Newsroom

TV display for the Recruise office: live business, AI, India & GCC, talent, startup and curiosity news, in Recruise brand style.

- `site/` – the page (HTML/CSS/JS, logos). Fixed 1920x1080 layout that scales to any screen.
- `scripts/build_news.py` – collects real stories from public RSS feeds (BBC, CNBC, Guardian, ET, Mint, BusinessLine, TechCrunch, The Verge, MIT Tech Review, Inc42, YourStory, ETHRWorld, NASA, Space.com, ScienceDaily, Google News searches for GCC/talent/funding, Wikipedia On this day). Nothing is written or invented; every story links to its publisher.
- `.github/workflows/newsroom.yml` – runs the collector about every 15 minutes and republishes to GitHub Pages.

## On the TV
Open the link once in the TV browser and go full screen. It needs no login. News refreshes on its own every 10 minutes, the feature story rotates every 18 seconds, and the page reloads itself when the design changes.

## Recruise Corner
Edit `site/recruise.json` on GitHub (pencil icon), add items, commit. The TV shows them within ~15 minutes. Photos: upload to `site/assets/` and use `"image": "assets/photo.jpg"`. Use `"until": "2026-12-31"` to hide a post after a date.
