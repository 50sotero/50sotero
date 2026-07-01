import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import generate_code_metrics as metrics


class GenerateCodeMetricsTests(unittest.TestCase):
    def test_parse_next_link(self):
        header = '<https://api.github.com/user/repos?page=3&per_page=100>; rel="next", <https://api.github.com/user/repos?page=50&per_page=100>; rel="last"'
        self.assertEqual(
            metrics.parse_next_link(header),
            "https://api.github.com/user/repos?page=3&per_page=100",
        )

        header_no_next = '<https://api.github.com/user/repos?page=50&per_page=100>; rel="last"'
        self.assertIsNone(metrics.parse_next_link(header_no_next))

        self.assertIsNone(metrics.parse_next_link(""))

        header_malformed = 'https://api.github.com/user/repos?page=3&per_page=100; rel="next"'
        self.assertIsNone(metrics.parse_next_link(header_malformed))

        header_missing_end = '<https://api.github.com/user/repos?page=3&per_page=100; rel="next"'
        self.assertIsNone(metrics.parse_next_link(header_missing_end))

        header_missing_start = 'https://api.github.com/user/repos?page=3&per_page=100>; rel="next"'
        self.assertIsNone(metrics.parse_next_link(header_missing_start))

        header_flipped = '>https://api.github.com/user/repos?page=3&per_page=100<; rel="next"'
        self.assertIsNone(metrics.parse_next_link(header_flipped))

        header_multiple_parts = '<https://api.github.com/user/repos?page=1>; rel="first", <https://api.github.com/user/repos?page=3>; rel="next", <https://api.github.com/user/repos?page=5>; rel="last"'
        self.assertEqual(metrics.parse_next_link(header_multiple_parts), "https://api.github.com/user/repos?page=3")

    def test_format_compact(self):
        self.assertEqual(metrics.format_compact(999), "999")
        self.assertEqual(metrics.format_compact(1_250), "1.2k")
        self.assertEqual(metrics.format_compact(1_799_327), "1.8M")

    def test_first_day_months_ago(self):
        # 1 month ago from March is February
        self.assertEqual(metrics.first_day_months_ago(date(2024, 3, 15), 2), date(2024, 2, 1))
        # 1 month ago from Jan is Dec of previous year (crossing year boundary)
        self.assertEqual(metrics.first_day_months_ago(date(2024, 1, 10), 2), date(2023, 12, 1))
        # 12 months ago
        self.assertEqual(metrics.first_day_months_ago(date(2024, 3, 15), 13), date(2023, 3, 1))
        # 24 months ago
        self.assertEqual(metrics.first_day_months_ago(date(2024, 3, 15), 25), date(2022, 3, 1))
        # 0 months ago (current month)
        self.assertEqual(metrics.first_day_months_ago(date(2024, 3, 15), 1), date(2024, 3, 1))
        # A few months into the previous year
        self.assertEqual(metrics.first_day_months_ago(date(2024, 3, 15), 6), date(2023, 10, 1))
        # 11 months ago, should cross the year boundary correctly
        self.assertEqual(metrics.first_day_months_ago(date(2024, 1, 15), 12), date(2023, 2, 1))
        # Many years ago
        self.assertEqual(metrics.first_day_months_ago(date(2024, 6, 15), 121), date(2014, 6, 1))
        # End of year
        self.assertEqual(metrics.first_day_months_ago(date(2024, 12, 31), 2), date(2024, 11, 1))

    def test_month_starts(self):
        # Same month
        self.assertEqual(metrics.month_starts(date(2024, 3, 5), date(2024, 3, 20)), [date(2024, 3, 1)])
        # Crossing year boundary
        self.assertEqual(
            metrics.month_starts(date(2023, 11, 15), date(2024, 2, 10)),
            [date(2023, 11, 1), date(2023, 12, 1), date(2024, 1, 1), date(2024, 2, 1)]
        )
        # Exactly one year
        self.assertEqual(
            len(metrics.month_starts(date(2023, 1, 1), date(2023, 12, 31))),
            12
        )
        self.assertEqual(metrics.month_starts(date(2023, 1, 1), date(2023, 12, 31))[0], date(2023, 1, 1))
        self.assertEqual(metrics.month_starts(date(2023, 1, 1), date(2023, 12, 31))[-1], date(2023, 12, 1))
        # End before start
        self.assertEqual(metrics.month_starts(date(2024, 3, 15), date(2024, 2, 10)), [])
        # Start and end on first of month
        self.assertEqual(
            metrics.month_starts(date(2024, 1, 1), date(2024, 3, 1)),
            [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]
        )

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

    def test_count_text_lines(self):
        # Empty and whitespace
        self.assertEqual(metrics.count_text_lines("", "Python"), 0)
        self.assertEqual(metrics.count_text_lines("   \n\t\n  ", "Python"), 0)

        # Python single-line comments
        python_code = (
            "# This is a comment\n"
            "def my_func():\n"
            "    # Another comment\n"
            "    pass\n"
        )
        self.assertEqual(metrics.count_text_lines(python_code, "Python"), 2)

        # JavaScript block and single-line comments
        js_code = (
            "/* Multi-line\n"
            "   comment\n"
            "   here */\n"
            "const x = 1;\n"
            "/* Inline */ const y = 2; // Line comment\n"
        )
        self.assertEqual(metrics.count_text_lines(js_code, "JavaScript"), 2)

        # HTML comments
        html_code = (
            "<!--\n"
            "  Some comment\n"
            "-->\n"
            "<div>\n"
            "  <!-- Inline comment --> Hello\n"
            "</div>\n"
        )
        self.assertEqual(metrics.count_text_lines(html_code, "HTML"), 3)

        # Mixed block comments spanning lines
        mixed_code = (
            "\n"
            "/* block start\n"
            "*/ code_after_block_end()\n"
            "code_before_block_start() /*\n"
            "block end */\n"
        )
        self.assertEqual(metrics.count_text_lines(mixed_code, "JavaScript"), 2)

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

    def test_grouped_languages(self):
        loc = metrics.LocMetrics(
            repos_scanned=1,
            total_loc=1000,
            languages=[
                metrics.LanguageMetric("Python", 500, 50.0, 5),
                metrics.LanguageMetric("TypeScript", 200, 20.0, 2),
                metrics.LanguageMetric("JavaScript", 100, 10.0, 1),
                metrics.LanguageMetric("HTML", 100, 10.0, 1),
                metrics.LanguageMetric("CSS", 50, 5.0, 1),
                metrics.LanguageMetric("Shell", 50, 5.0, 1),
            ],
        )

        # Test no grouping needed (count > len(languages))
        grouped_no_other = metrics.grouped_languages(loc, count=10)
        self.assertEqual(len(grouped_no_other), 6)
        self.assertNotIn("Other", [lang.name for lang in grouped_no_other])

        # Test grouping needed (count < len(languages))
        grouped_with_other = metrics.grouped_languages(loc, count=3)
        self.assertEqual(len(grouped_with_other), 4)
        self.assertEqual(grouped_with_other[0].name, "Python")
        self.assertEqual(grouped_with_other[1].name, "TypeScript")
        self.assertEqual(grouped_with_other[2].name, "JavaScript")

        other = grouped_with_other[3]
        self.assertEqual(other.name, "Other")
        self.assertEqual(other.loc, 200)
        self.assertEqual(other.percent, 20.0)
        self.assertEqual(other.files, 3)

    def test_should_skip(self):
        from pathlib import Path, PurePosixPath

        # Test paths that should not be skipped
        self.assertFalse(metrics.should_skip(Path("scripts/generate_code_metrics.py")))
        self.assertFalse(metrics.should_skip(PurePosixPath("tests/test_generate_code_metrics.py")))
        self.assertFalse(metrics.should_skip(Path("README.md")))

        # Test paths that should be skipped
        self.assertTrue(metrics.should_skip(Path(".git/HEAD")))
        self.assertTrue(metrics.should_skip(PurePosixPath(".github/workflows/ci.yml")))
        self.assertTrue(metrics.should_skip(Path("node_modules/package/index.js")))

        # Test paths where a SKIP_DIR is in the middle
        self.assertTrue(metrics.should_skip(Path("project/node_modules/package/index.js")))

        # Test paths that partially match a SKIP_DIR (should not skip)
        self.assertFalse(metrics.should_skip(Path("github_stuff/file.py")))
        self.assertFalse(metrics.should_skip(Path("my_build_script.sh")))

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

    def test_chart_grid(self):
        result = metrics.chart_grid(10, 20)
        expected = (
            '<line x1="10" y1="298" x2="20" y2="298" stroke="#263244"/>'
            '<line x1="10" y1="341" x2="20" y2="341" stroke="#263244"/>'
            '<line x1="10" y1="384" x2="20" y2="384" stroke="#263244"/>'
        )
        self.assertEqual(result, expected)

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

    def test_safe_redirect_handler_strips_auth_header_on_cross_domain(self):
        import urllib.request
        handler = metrics.SafeRedirectHandler()
        req = urllib.request.Request("https://api.github.com/test", headers={"Authorization": "token"})
        new_req = handler.redirect_request(
            req, None, 301, "Moved", None, "https://external.com/test"
        )
        self.assertFalse(new_req.has_header("Authorization"))

    def test_safe_redirect_handler_keeps_auth_header_on_same_domain(self):
        import urllib.request
        handler = metrics.SafeRedirectHandler()
        req = urllib.request.Request("https://api.github.com/test", headers={"Authorization": "token"})
        new_req = handler.redirect_request(
            req, None, 301, "Moved", None, "https://api.github.com/new"
        )
        self.assertTrue(new_req.has_header("Authorization"))
        self.assertEqual(new_req.get_header("Authorization"), "token")


if __name__ == "__main__":
    unittest.main()
