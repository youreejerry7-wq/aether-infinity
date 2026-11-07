# AETHER read-only CDN preview

This directory is an isolated, static-only frontend experiment intended to measure whether the public research archive can be shown without waking the Flask web service.

## Safety and scope

- Reads only the public `data/research.json` file from GitHub Raw.
- Does not call `/api/run`, `/api/results`, `/health`, SQLite, Stripe, or any private/customer endpoint.
- Does not submit experiments, mutate the archive, or access secrets.
- Uses text-only DOM rendering for archive-supplied strings.
- Limits rendered experiment rows and bounds each fetch with a timeout.
- The interactive Flask app remains separate and unchanged.

## Staged static-site settings

After this pull request is reviewed, a separate free Render Static Site can be evaluated with:

- Repository: `youreejerry7-wq/aether-infinity`
- Branch: the reviewed branch or a later reviewed `main)
- Build command: `echo "No build step required"`
- Publish directory: `cdn-preview`

Do not create, replace, or redirect the production web service as part of this PR. First deploy a separate preview site, verify its own URL and browser behavior, and compare its first-load and repeat-load latency against the existing Flask homepage. Only consider a production-domain change after explicit owner review.

The static page itself is expected to be served from Render's static-site CDN. Its archive data still comes from GitHub's public raw-content endpoint, so archive freshness and GitHub availability remain external dependencies. The link to the interactive Flask lab is optional and may incur the free web service's wake-up delay.

## Local checks

Run the dependency-free regression suite with:

```sh
node --test tests/test_cdn_preview.cjs
```

The GitHub Actions workflow also performs a read-only HTTP/CORS check against the public archive. No new paid dependencies or services are introduced by this code.
