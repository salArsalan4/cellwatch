# CellWatch dashboard (frontend)

A static HTML/CSS/JS dashboard over the query API — no framework, no build
step, no npm. Three files (`index.html`, `style.css`, `app.js`) plus a
bundled JSON evidence snapshot in `evidence/`.

## Two modes

- **Static evidence** (default): reads the JSON files in `evidence/` and
  renders from them. Works from any static host, forever — including after
  the AWS Academy Learner Lab account is decommissioned. This is what makes
  the dashboard usable as a portfolio piece past the term project's deadline.
- **Live API**: calls the deployed query API directly from the browser,
  using a base URL + API key you paste into Settings. Only useful while the
  lab account (or a redeployed personal-account stack) is actually up.

Open Settings (top right) to switch modes or point Live mode at a
deployment. The base URL and API key are stored only in `localStorage` —
never written to a file, never committed.

## Run it locally

Evidence fetches use `fetch()`, which most browsers block under `file://`.
Serve the directory instead:

```bash
cd frontend
python3 -m http.server 8000
# open http://localhost:8000
```

## Regenerating evidence

`scripts/build_evidence.py` writes the five files under `evidence/`
(`meta.json`, `cells.json`, `kpis.json`, `alerts.json`, `health.json`). Two
modes, same output shape:

```bash
# Synthetic: simulates a small fleet locally (generator.cells +
# services/common/detection.py) -- no AWS needed. What's currently checked
# in; regenerate any time to refresh the timestamps or reshuffle the seed.
uv run python frontend/scripts/build_evidence.py --mode synthetic

# Live: captures a real snapshot from the deployed query API. Run this
# before tearing down the Learner Lab account -- it's the actual "demo
# evidence capture" step, and it's what should ship in the repo for the
# final submission (replace the synthetic files with this output).
uv run python frontend/scripts/build_evidence.py --mode live \
  --base-url "$(terraform -chdir=infra output -raw query_url)" \
  --api-key "<value from: aws apigateway get-api-key --api-key $(terraform -chdir=infra output -raw query_api_key_id) --include-value --query value --output text>"
```

`evidence/meta.json`'s `synthetic` field tells the dashboard (and anyone
reading the repo) which kind is currently bundled; the evidence banner in
the UI surfaces this too.

## CORS (why Live mode needs a Terraform change)

The query API didn't originally allow cross-origin browser requests — it
was only ever called by curl/k6/the load test. Live mode needed two things,
both already applied to `infra/` and `services/query/handler.py`:

1. `services/query/handler.py` — `APIGatewayRestResolver` now takes a
   `CORSConfig`, so real GET/ANY responses carry
   `Access-Control-Allow-Origin`.
2. `infra/modules/control-plane/api_gateway.tf` — a dedicated `OPTIONS`
   method with a `MOCK` integration and `api_key_required = false`, because
   a browser's CORS preflight request never carries the `x-api-key` header
   and would otherwise be rejected by API Gateway before Lambda ever runs.

Both default to `Access-Control-Allow-Origin: *`. That's intentionally
permissive — every route behind it is read-only and still gated by the
query API key — but if you want to lock it to your deployed dashboard's
origin, set `cors_allow_origin` in `infra/` (e.g.
`"https://cellwatch.pages.dev"`) and re-apply.

**This requires a `terraform apply`** (adds an API Gateway method +
integration + a Lambda env var) before Live mode will work — it isn't live
yet just because the code changed.

## Deploying (Cloudflare Pages / GitHub Pages)

Both are "point at a directory of static files" hosts — nothing here needs
a server, so either works with zero config:

- **Cloudflare Pages**: connect the repo, set the build output directory to
  `frontend/`, no build command.
- **GitHub Pages**: Settings → Pages → deploy from a branch, folder
  `/frontend` (or copy `frontend/`'s contents to a `gh-pages` branch root if
  the repo-subfolder option isn't available for your plan).

Either way, once deployed the dashboard defaults to static-evidence mode
automatically — it only tries Live mode if you've explicitly configured and
saved a base URL + key in that browser's Settings panel. So the same
deployed page keeps working (on evidence) long after the Learner Lab
account, and any personal-account redeploy, are gone.
