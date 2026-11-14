# AETHER read-only CDN preview

This directory is an isolated, static-only frontend experiment intended to measure whether the public research archive can be shown without waking the Flask web service.

## Safety and scope

- Prefers the one-record `data/research-latest.json` snapshot from GitHub Raw and falls back to the full `data/research.json` archive only while the snapshot is unavailable.
- Does not call `/api/run`, `/api/results`, `/health`, SQLite, Stripe, or any private/customer endpoint.
- Does not submit experiments, mutate the archive, or access secrets.
- Uses text-only DOM rendering for archive-supplied strings.
- Stores only the public archive in browser local storage and renders the last valid copy immediately on repeat visits; failed refreshes retain it with an explicit potentially-stale label.
- Treats local storage as optional: malformed data, disabled storage, and quota errors never block a fresh network response.
- Limits rendered experiment rows and bounds each fetch with a timeout.
- Caps manual cache-bypass refreshes to one request every 30 seconds, even when the five-minute automatic refresh window is active.
- Caches a missing optional compact snapshot for up to 15 minutes to avoid repeated 404 requests; manual refresh checks for publication immediately.
- The interactive Flask app remains separate and unchanged.

## Staged static-site settings

After this pull request is reviewed, a separate free Render Static Site can be evaluated with:

- Repository: `youreejerry7-wq/aether-infinity`
- Branch: the reviewed branch for an isolated preview, or a later reviewed `main` after approval
- Build command: `echo "No build step required"`
- Publish directory: `cdn-preview`

Do not create, replace, or redirect the production web service as part of this PR. First deploy a separate preview site, verify its own URL and browser behavior, and compare its first-load and repeat-load latency against the existing Flask homepage. Only consider a production-domain change after explicit owner review.

The static page itself is served from Render's static-site CDN. Its compact snapshot and fallback archive come from GitHub's public raw-content endpoint, so freshness and GitHub availability remain external dependencies. The scheduled workflow keeps the compact snapshot equal to the newest full-archive record; until that file is published on main, the frontend falls back to the full archive. The link to the interactive Flask lab is optional and may incur the free web service's wake-up delay.

## Local checks

Run the dependency-free regression suite with:

```sh
node --test tests/test_cdn_preview.cjs
```

The GitHub Actions workflow also performs a read-only HTTP/CORS check against the public archive. No new paid dependencies or services are introduced by this code.

## Current isolated Render staging preview

- URL: https://aether-cdn-preview.onrender.com
- Render service: `srv-dbrh49rtqb8s73ei5o4g` (separate from the production Flask service)
- Build command: `echo "No build step required"`
- Publish directory: `cdn-preview`
- Render environment: `SKIP_INSTALL_DEPS=true` so the static site does not install the repository's unrelated Python requirements.

Two GitHub-hosted runner observations on 2026-11-13 returned HTTP 200:
- Static HTML: **190–230 ms**, 3,042 bytes
- Static `app.js`: **148–279 ms**, 8,159 bytes
- Immediate repeat HTML: **49–65 ms**, 3,042 bytes

These are point observations, not a controlled cold-start or global CDN benchmark. The archive remains a public GitHub Raw dependency. The Flask service and production domain remain unchanged.
