import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import generate_code_metrics as metrics


class GenerateCodeMetricsTests(unittest.TestCase):
    def test_format_compact(self):
        self.assertEqual(metrics.format_compact(999), "999")
        self.assertEqual(metrics.format_compact(1_250), "1.2k")
        self.assertEqual(metrics.format_compact(1_799_327), "1.8M")

    def test_safe_redirect_handler_strips_auth(self):
        import urllib.request
        req = urllib.request.Request("http://example.com", headers={"Authorization": "Bearer secret"})
        handler = metrics.SafeRedirectHandler()

        # Cross-origin redirect
        new_req_cross = handler.redirect_request(req, None, 302, "Found", {}, "http://otherdomain.com")
        self.assertFalse(new_req_cross.has_header("Authorization"))

        # Same-origin redirect
        new_req_same = handler.redirect_request(req, None, 302, "Found", {}, "http://example.com/otherpath")
        self.assertTrue(new_req_same.has_header("Authorization"))

    def test_paginated_json_rejects_cross_origin_next_link_before_request(self):
        class FakeResponse:
            def __init__(self, payload, link=""):
                self._payload = payload
                self.headers = {"Link": link}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(self._payload).encode("utf-8")

        class FakeOpener:
            def __init__(self):
                self.requests = []
                self.responses = [
                    FakeResponse(
                        [{"id": 1}],
                        '<https://tokens.example.test/repos?page=2>; rel="next"',
                    ),
                    FakeResponse([]),
                ]

            def open(self, req, timeout):
                self.requests.append(req)
                return self.responses.pop(0)

        client = metrics.GitHubClient("secret")
        client.opener = FakeOpener()

        with self.assertRaisesRegex(ValueError, "outside GitHub API origin"):
            list(client.paginated_json("/repos/octo/demo/commits"))

        self.assertEqual(len(client.opener.requests), 1)

    def test_loc_counter_uses_source_languages_and_skips_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.ts").write_text(
                "const value = 1;\n\n// comment\nexport const next = value + 1;\n",
                encoding="utf-8",
            )
            (root / "package-lock.json").write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
            (root / "workflow.yml").write_text("name: ci\n", encoding="utf-8")

            loc = metrics.count_source_loc([root])

        self.assertEqual(loc.total_loc, 2)
        self.assertEqual(loc.languages[0].name, "TypeScript")
        self.assertEqual(loc.languages[0].loc, 2)

    def test_notebook_counter_counts_code_cells_not_json(self):
        notebook = {
            "cells": [
                {"cell_type": "markdown", "source": ["# Heading\n"]},
                {"cell_type": "code", "source": ["x = 1\n", "\n", "# comment\n", "print(x)\n"]},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "analysis.ipynb"
            path.write_text(json.dumps(notebook), encoding="utf-8")

            self.assertEqual(metrics.count_notebook_lines(path), 2)

    def test_monthly_series_uses_partial_current_month(self):
        commits = [
            metrics.CommitStat(
                repo="demo",
                private=False,
                sha="a",
                date=datetime(2026, 6, 1, tzinfo=timezone.utc),
                additions=10,
                deletions=5,
                files=1,
            ),
            metrics.CommitStat(
                repo="demo",
                private=False,
                sha="b",
                date=datetime(2026, 6, 10, tzinfo=timezone.utc),
                additions=5,
                deletions=0,
                files=1,
            ),
        ]

        series = metrics.build_monthly_series(
            commits,
            start=date(2026, 6, 1),
            end=date(2026, 6, 10),
        )

        self.assertEqual(series[0].commits, 2)
        self.assertEqual(series[0].commits_per_day, 0.2)
        self.assertEqual(series[0].lines_per_day, 2)

    def test_render_svg_uses_source_loc_mix(self):
        card = metrics.MetricsCard(
            owner="octo",
            period_label="Jan 2026-Jun 2026",
            updated_label="Jun 10, 2026",
            repo_count=3,
            public_repos=2,
            private_repos=1,
            total_commits=12,
            active_days=6,
            avg_commits_per_day=2.0,
            avg_lines_per_day=50,
            total_additions=200,
            total_deletions=100,
            total_changed=300,
            source_loc=120,
            monthly=[
                metrics.MonthMetric("Jan", "2026-01", 31, 3, 20, 10),
                metrics.MonthMetric("Feb", "2026-02", 28, 9, 100, 30),
            ],
            languages=[
                metrics.LanguageMetric("Python", 90, 75.0, 2),
                metrics.LanguageMetric("TypeScript", 30, 25.0, 1),
            ],
        )

        svg = metrics.render_svg(card)

        self.assertIn("SOURCE LOC MIX", svg)
        self.assertIn("Python", svg)
        self.assertIn("75%", svg)
        self.assertIn("Source LOC: 120", svg)


if __name__ == "__main__":
    unittest.main()
