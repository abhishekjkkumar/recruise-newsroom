# Recruise Live Newsroom

TV display for the Recruise office: live business, AI, India & GCC, talent, startup and curiosity news, in Recruise brand style.

- `site/` – the page (HTML/CSS/JS, logos). Fixed 1920x1080 layout that scales to any screen.
- `scripts/build_news.py` – collects real stories from public RSS feeds and Google News searches, filtered to Recruise's world. Nothing is written or invented; every story links to its publisher.
- Sections: India & GCC Radar · Hiring & Layoffs · Talent & Leadership · AI & Technology · Startups & Funding · India Business · Global Business · Economy, plus Curiosity Corner and Recruise Corner.
- Freshness rule: nothing older than 48 hours. Stories 24-48h old appear only if important (covered by several publishers, or a GCC story) or a section would otherwise be empty.
- Ranking: newest first, lifted for "hot" stories (several publishers) and India/GCC angles. On a slow day the screen falls back in this order: GCC > hiring > talent > India business > global business > economy.
- Sources include ETHRWorld, People Matters, HR Katha, Economic Times, Mint, BusinessLine, CNBC, BBC, TechCrunch, The Verge, MIT Technology Review, Inc42, YourStory, NASA, Space.com, ScienceDaily, Wikipedia, and Google News searches for GCC openings, India entries, hiring plans, layoffs, staffing/TA, leadership appointments, IT majors and startup funding.
- `scripts/run_loop.sh` + `.github/workflows/newsroom.yml` – each GitHub Actions run stays up ~6 hours and republishes the news every 15 minutes to the `gh-pages` branch, which GitHub Pages serves.

## On the TV
Open the link once in the TV browser and go full screen. It needs no login. News refreshes on its own every 10 minutes, the feature story rotates every 18 seconds, and the page reloads itself when the design changes.

## Recruise Corner
Edit `site/recruise.json` on GitHub (pencil icon), add items, commit. The TV shows them within ~15 minutes. Photos: upload to `site/assets/` and use `"image": "assets/photo.jpg"`. Use `"until": "2026-12-31"` to hide a post after a date.
