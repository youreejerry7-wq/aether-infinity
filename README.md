# AETHER Infinity

A Flask-based research demonstration with two **separate** kinds of experiments:

- **Interactive Monte Carlo demo:** the web page runs a 20,000-sample estimate of pi and stores results in a local SQLite database.
- **Scheduled statistical baselines:** GitHub Actions runs `research.py` on an hourly schedule and commits a bounded archive to `data/research.json`. GitHub may delay or skip scheduled jobs.

These are simulations of known mathematical/statistical baselines, **not discoveries or evidence of new physical phenomena**. A statistical flag means a result deserves independent replication and appropriate multiple-testing correction.

## Run locally

Requires Python 3.12 or a compatible version.

```sh
python -m pip install -r requirements.txt
python app.py
```

The development server listens on port 10000 unless `PORT` is set. For a production-style local server, use the configured Gunicorn entry point:

```sh
gunicorn app:app --bind 0.0.0.0:10000
```

The web app uses `DATABASE_PATH` if set; otherwise it uses `/tmp/aether.sqlite3`. SQLite data at that default location is **ephemeral** on a free web service.

## Read-only smoke checks

With the app running locally:

```sh
curl -fsS http://127.0.0.1:10000/health
curl -fsS http://127.0.0.1:10000/api/results
```

`/health` should return `{"status":"ok"}`. `/api/results` returns recent interactive demo records, initially an empty JSON array. The homepage is `/`.

The `POST /api/run` endpoint **executes** an experiment and writes to SQLite; it is intentionally excluded from the read-only checks above. Review access controls, rate limits, and persistence before treating the demo as production-ready.

## Scheduled research archive

To run one scheduled-style cycle manually in a **disposable working copy**:

```sh
python research.py
```

This executes the four known-baseline tests and **rewrites** `data/research.json` with the newest cycle first, retaining at most 100 cycles. Avoid running it in a working copy with uncommitted archive changes.

The scheduled workflow is `.github/workflows/research.yml`. Its commits update the repository's JSON archive; they do **not** by themselves prove that the Render web service has deployed new application code. The homepage's scheduled-results section fetches the archive from GitHub separately from the SQLite-backed interactive results.

## Interpreting results and limitations

- Each scheduled cycle currently records fair-coin frequency, a uniform threshold, a Monte Carlo estimate of pi, and a rare-event frequency.
- `flag` is a statistical review indicator, not a discovery claim. The current research script uses `|z| > 3.29` as its per-test flag threshold; this is not a multiple-comparison-adjusted discovery threshold.
- The live site's status must be checked independently of the repository's latest commit. A successful GitHub Actions commit does not verify that the homepage or `/health` is reachable.
- Keep AETHER changes separate from VaultCore. Do not put credentials or personal data into research archives.

This README documents the existing behavior; it does not change any application routes, deployment settings, scheduled jobs, or access permissions.
