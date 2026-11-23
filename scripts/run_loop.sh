#!/usr/bin/env bash
# Keeps the newsroom fresh: rebuild news.json every 15 minutes for ~5h45m, publishing each
# result to the gh-pages branch. GitHub's own scheduler is too irregular to rely on alone.
set -u
INTERVAL=${INTERVAL_SECONDS:-900}
END=$(( $(date +%s) + ${LOOP_MINUTES:-345} * 60 ))
REPO_URL="https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"

while :; do
  started=$(date +%s)
  # Pick up any design/source changes pushed to main since the loop began
  git fetch -q origin main && git reset -q --hard origin/main
  [ -f site/news.json ] && unset PREVIOUS_URL   # after the first pass, carry over from the local copy

  if python scripts/build_news.py && [ -f site/news.json ]; then
    echo "{\"build\":\"$(git rev-parse HEAD)\"}" > site/version.json
    rm -rf /tmp/out && cp -r site /tmp/out && touch /tmp/out/.nojekyll
    # Version-tag the script and styles so every TV loads the new files after an update
    sed -i "s/?v=dev/?v=$(git rev-parse --short HEAD)/g" /tmp/out/index.html
    (
      cd /tmp/out &&
      git init -q -b gh-pages &&
      git add -A &&
      git -c user.name=newsroom-bot -c user.email=newsroom-bot@users.noreply.github.com \
          commit -qm "news $(date -u +%Y-%m-%dT%H:%MZ)" &&
      git push -qf "$REPO_URL" gh-pages
    ) && echo "published $(date -u +%H:%M)Z" || echo "publish failed, will retry next pass"
  else
    echo "build failed, keeping the last published news"
  fi

  now=$(date +%s)
  [ $(( now + INTERVAL )) -ge "$END" ] && break
  wait_s=$(( INTERVAL - (now - started) ))
  [ "$wait_s" -lt 60 ] && wait_s=60
  sleep "$wait_s"
done
