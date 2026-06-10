# Code Metrics SVG Generator

This repository includes a reusable, dependency-free Python script that generates the `assets/code-metrics.svg` card shown in the profile README.

## What It Measures

- Authored commits over the last 12 months
- Commits per day, averaged by month
- Lines changed per day, averaged by month
- Added, deleted, and net changed lines
- Active coding days
- Source language percentages by lines of code

The language mix is based on source LOC, not GitHub's byte-based language API. JSON and YAML config/data files are excluded from the language denominator, and Jupyter notebooks count code-cell lines instead of raw notebook JSON.

## Reuse It

Copy these files into a profile README repository:

- `scripts/generate_code_metrics.py`
- `.github/workflows/code-metrics.yml`
- `assets/code-metrics.svg` or a README image link that points to that path

Then reference the generated card from your README:

```md
![Code velocity metrics](assets/code-metrics.svg)
```

## Private Repositories

The workflow works with the default `GITHUB_TOKEN`, but that token can only see repositories available to the workflow. To include private repositories across your account, create a repository secret named `METRICS_TOKEN`.

For a fine-grained token, grant read access to the repositories you want counted and enough metadata access for GitHub API repository and commit reads. For a classic token, use a token with `repo` access.

Private repository names are not rendered in the SVG. The card only shows aggregate counts and metrics.

## Run Locally

```bash
METRICS_TOKEN=ghp_your_token_here python scripts/generate_code_metrics.py --user your-github-user --output assets/code-metrics.svg
```

For public-only data, `GITHUB_TOKEN` is also accepted.

## Test

```bash
python -m unittest discover -s tests -v
```
