import json
import sys
import tempfile
import unittest
import unittest.mock
import zipfile
from io import BytesIO
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import generate_code_metrics as metrics


class GenerateCodeMetricsTests(unittest.TestCase):
    def test_stat_box_escapes_html(self):
        svg = metrics.stat_box(54, "<script>", "A & B")
        self.assertIn("&lt;script&gt;", svg)
        self.assertIn("A &amp; B", svg)
        self.assertNotIn("<script>", svg)
        self.assertNotIn("A & B", svg)

    def test_stat_box_renders_svg_group(self):
        svg = metrics.stat_box(54, 1234, "COMMITS", width=150)
        self.assertIn('<rect x="54"', svg)
        self.assertIn('width="150"', svg)
        self.assertIn(">1234<", svg)
        self.assertIn(">COMMITS<", svg)
        self.assertTrue(svg.startswith("<g>"))
        self.assertTrue(svg.endswith("</g>"))

    def test_line_path_single_value(self):
        line, area, max_val = metrics.line_path([10.0], 0, 0, 100, 100)
        self.assertEqual(line, "M 0.0 0.0")
        self.assertEqual(area, "M 0.0 0.0 L 0.0 100 L 0.0 100 Z")
        self.assertEqual(max_val, 10.0)

    def test_line_path_multiple_values(self):
        line, area, max_val = metrics.line_path([0.0, 5.0, 10.0], 0, 0, 100, 100)
        self.assertEqual(line, "M 0.0 100.0 L 50.0 50.0 L 100.0 0.0")
        self.assertEqual(area, "M 0.0 100.0 L 50.0 50.0 L 100.0 0.0 L 100.0 100 L 0.0 100 Z")
        self.assertEqual(max_val, 10.0)

    def test_line_path_max_value(self):
        line, area, max_val = metrics.line_path([0.5], 0, 0, 100, 100)
        self.assertEqual(line, "M 0.0 50.0")
        self.assertEqual(area, "M 0.0 50.0 L 0.0 100 L 0.0 100 Z")
        self.assertEqual(max_val, 1)

    def test_line_path_empty_values(self):
        with self.assertRaises(IndexError):
            metrics.line_path([], 0, 0, 100, 100)

    def test_strip_block_comments(self):
        # Language with no block comments
        state = {"end": None}
        self.assertEqual(metrics.strip_block_comments("x = 1", state, "Python"), "x = 1")
        self.assertEqual(state, {"end": None})

        # Single line block comment
        state = {"end": None}
        self.assertEqual(metrics.strip_block_comments("const x = 1; /* comment */ let y = 2;", state, "TypeScript"), "const x = 1;  let y = 2;")
        self.assertEqual(state, {"end": None})

        # Multiple single line block comments
        state = {"end": None}
        self.assertEqual(metrics.strip_block_comments("a /* 1 */ + b /* 2 */", state, "TypeScript"), "a  + b ")
        self.assertEqual(state, {"end": None})

        # Multi-line block comment start
        state = {"end": None}
        self.assertEqual(metrics.strip_block_comments("const x = 1; /* start", state, "TypeScript"), "const x = 1; ")
        self.assertEqual(state, {"end": "*/"})

        # Multi-line block comment middle
        state = {"end": "*/"}
        self.assertEqual(metrics.strip_block_comments("middle of comment", state, "TypeScript"), "")
        self.assertEqual(state, {"end": "*/"})

        # Multi-line block comment end
        state = {"end": "*/"}
        self.assertEqual(metrics.strip_block_comments("end */ let y = 2;", state, "TypeScript"), " let y = 2;")
        self.assertEqual(state, {"end": None})

        # Different comment tokens
        state = {"end": None}
        self.assertEqual(metrics.strip_block_comments("<div><!-- comment --></div>", state, "HTML"), "<div></div>")
        self.assertEqual(state, {"end": None})

        # Multi-line HTML comment
        state = {"end": None}
        self.assertEqual(metrics.strip_block_comments("<div><!-- start", state, "HTML"), "<div>")
        self.assertEqual(state, {"end": "-->"})

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
        # Multiple years
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


    def test_add_month(self):
        self.assertEqual(metrics.add_month(date(2026, 1, 15)), date(2026, 2, 1))
        self.assertEqual(metrics.add_month(date(2026, 6, 30)), date(2026, 7, 1))
        self.assertEqual(metrics.add_month(date(2026, 12, 31)), date(2027, 1, 1))

    def test_language_for(self):
        self.assertEqual(metrics.language_for(Path("main.py")), "Python")
        self.assertEqual(metrics.language_for(Path("app.ts")), "TypeScript")
        self.assertEqual(metrics.language_for(Path("Dockerfile")), "Dockerfile")
        self.assertEqual(metrics.language_for(Path("dockerfile")), "Dockerfile")
        self.assertEqual(metrics.language_for(Path("App.TS")), "TypeScript")
        self.assertIsNone(metrics.language_for(Path("readme.md")))

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
    def test_archive_loc_counter_caps_parallel_downloads(self):
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w") as zip_file:
            zip_file.writestr("repo-main/src/app.py", "print('hello')\n")
        archive_bytes = archive.getvalue()

        class FakeClient:
            def __init__(self):
                self.paths = []

            def request_bytes(self, path):
                self.paths.append(path)
                return archive_bytes

        class ImmediateFuture:
            def __init__(self, result):
                self._result = result

            def result(self):
                return self._result

        class RecordingExecutor:
            max_workers_seen = []

            def __init__(self, max_workers=None):
                self.max_workers = max_workers
                RecordingExecutor.max_workers_seen.append(max_workers)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def map(self, fn, iterables):
                return [fn(item) for item in iterables]

            def submit(self, fn, *args):
                return ImmediateFuture(fn(*args))

        original_executor = metrics.concurrent.futures.ThreadPoolExecutor
        original_as_completed = metrics.concurrent.futures.as_completed
        try:
            metrics.concurrent.futures.ThreadPoolExecutor = RecordingExecutor
            metrics.concurrent.futures.as_completed = lambda futures: list(futures)
            client = FakeClient()
            repositories = [
                metrics.Repository(name=f"repo-{index}", private=False, default_branch="main")
                for index in range(10)
            ]

            loc = metrics.count_source_loc_from_archives(client, "octo", repositories)
        finally:
            metrics.concurrent.futures.ThreadPoolExecutor = original_executor
            metrics.concurrent.futures.as_completed = original_as_completed

        self.assertEqual(RecordingExecutor.max_workers_seen[-1:], [metrics.MAX_ARCHIVE_WORKERS])
        self.assertEqual(len(client.paths), 10)
        self.assertEqual(loc.repos_scanned, 10)
        self.assertEqual(loc.total_loc, 10)


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

    def test_count_notebook_source_edge_cases(self):
        # String input
        self.assertEqual(metrics.count_notebook_source("x = 1\ny = 2\n# comment"), 2)

        # List of strings input
        self.assertEqual(metrics.count_notebook_source(["x = 1\n", "y = 2\n", "# comment\n"]), 2)

        # None input
        self.assertEqual(metrics.count_notebook_source(None), 0)

        # Empty list input
        self.assertEqual(metrics.count_notebook_source([]), 0)

        # List of non-strings (fallback string conversion)
        self.assertEqual(metrics.count_notebook_source([123, 456.78]), 2)

        # Mixed whitespace and empty lines
        self.assertEqual(metrics.count_notebook_source(["\n", "  \n", "\t\n"]), 0)

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

    def test_process_zip_member_directory_traversal(self):
        from zipfile import ZipInfo
        import zipfile

        member1 = ZipInfo("../../etc/passwd")
        self.assertIsNone(metrics._process_zip_member(None, member1))

        member2 = ZipInfo("/etc/passwd")
        self.assertIsNone(metrics._process_zip_member(None, member2))

        member3 = ZipInfo("repo/../etc/passwd")
        self.assertIsNone(metrics._process_zip_member(None, member3))

    def test_process_zip_member_badzipfile(self):
        from zipfile import ZipInfo, BadZipFile
        from unittest.mock import MagicMock

        mock_zip = MagicMock()
        mock_zip.open.side_effect = BadZipFile

        member = ZipInfo("repo/main.py")
        member.file_size = 100

        # We need language_for to return something, so we provide an extension that is recognized.
        # "repo/main.py" corresponds to Python.
        self.assertIsNone(metrics._process_zip_member(mock_zip, member))

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

    def test_safe_redirect_handler_strips_auth_header_on_cross_host(self):
        import urllib.request
        handler = metrics.SafeRedirectHandler()
        req = urllib.request.Request("https://api.github.com/test", headers={"Authorization": "token"})
        new_req = handler.redirect_request(
            req, None, 301, "Moved", None, "https://external.com/test"
        )
        self.assertIsNotNone(new_req)
        self.assertFalse(new_req.has_header("Authorization"))

    def test_safe_redirect_handler_strips_auth_header_on_cross_scheme(self):
        import urllib.request
        handler = metrics.SafeRedirectHandler()
        req = urllib.request.Request("https://api.github.com/test", headers={"Authorization": "token"})
        new_req = handler.redirect_request(
            req, None, 301, "Moved", None, "http://api.github.com/test"
        )
        self.assertIsNotNone(new_req)
        self.assertFalse(new_req.has_header("Authorization"))

    def test_safe_redirect_handler_strips_auth_header_on_cross_port(self):
        import urllib.request
        handler = metrics.SafeRedirectHandler()
        req = urllib.request.Request("https://api.github.com/test", headers={"Authorization": "token"})
        new_req = handler.redirect_request(
            req, None, 301, "Moved", None, "https://api.github.com:8443/test"
        )
        self.assertIsNotNone(new_req)
        self.assertFalse(new_req.has_header("Authorization"))

    def test_safe_redirect_handler_keeps_auth_header_on_same_origin(self):
        import urllib.request
        handler = metrics.SafeRedirectHandler()
        req = urllib.request.Request("https://api.github.com/test", headers={"Authorization": "token"})
        new_req = handler.redirect_request(
            req, None, 301, "Moved", None, "https://api.github.com/new"
        )
        self.assertIsNotNone(new_req)
        self.assertTrue(new_req.has_header("Authorization"))
        self.assertEqual(new_req.get_header("Authorization"), "token")

    def test_initial_cross_origin_urls_are_rejected_before_request(self):
        class FailingOpener:
            def open(self, req, timeout):
                raise AssertionError("cross-origin request reached the opener")

        client = metrics.GitHubClient("token")
        client.opener = FailingOpener()

        with self.assertRaisesRegex(ValueError, "Cross-origin initial URL rejected"):
            client.request_json("GET", "https://evil.example/data")
        with self.assertRaisesRegex(ValueError, "Cross-origin initial URL rejected"):
            client.request_bytes("http://api.github.com/archive.zip")

    def test_paginated_json_rejects_cross_origin_link_before_request_two(self):
        import urllib.request
        class MockResponse:
            def __init__(self, data, link, url="https://api.github.com/test"):
                self.data = data
                self.headers = {"Link": link} if link else {}
                self.url = url
            def read(self): return self.data
            def geturl(self): return self.url
            def __enter__(self): return self
            def __exit__(self, *args): pass

        class MockOpener:
            def __init__(self):
                self.calls = 0
            def open(self, req, timeout):
                self.calls += 1
                if self.calls == 1:
                    return MockResponse(b'[1, 2]', '<https://evil.com/page=2>; rel="next"')
                return MockResponse(b'[3]', None)

        client = metrics.GitHubClient("token")
        client.opener = MockOpener()
        iterator = client.paginated_json("/test")

        self.assertEqual(next(iterator), 1)
        self.assertEqual(next(iterator), 2)
        with self.assertRaises(ValueError) as cm:
            next(iterator)
        self.assertEqual(str(cm.exception), "Cross-origin pagination URL rejected")
        self.assertEqual(client.opener.calls, 1)

    def test_paginated_json_accepts_same_origin_link(self):
        import urllib.request
        class MockResponse:
            def __init__(self, data, link, url="https://api.github.com/test"):
                self.data = data
                self.headers = {"Link": link} if link else {}
                self.url = url
            def read(self): return self.data
            def geturl(self): return self.url
            def __enter__(self): return self
            def __exit__(self, *args): pass

        class MockOpener:
            def __init__(self):
                self.calls = 0
            def open(self, req, timeout):
                self.calls += 1
                if self.calls == 1:
                    return MockResponse(b'[1, 2]', '<https://api.github.com/page=2>; rel="next"')
                return MockResponse(b'[3]', None)

        client = metrics.GitHubClient("token")
        client.opener = MockOpener()
        results = list(client.paginated_json("/test"))
        self.assertEqual(results, [1, 2, 3])
        self.assertEqual(client.opener.calls, 2)

    def test_paginated_json_accepts_relative_path_link(self):
        import urllib.request
        class MockResponse:
            def __init__(self, data, link, url="https://api.github.com/test"):
                self.data = data
                self.headers = {"Link": link} if link else {}
                self.url = url
            def read(self): return self.data
            def geturl(self): return self.url
            def __enter__(self): return self
            def __exit__(self, *args): pass

        class MockOpener:
            def __init__(self):
                self.calls = 0
            def open(self, req, timeout):
                self.calls += 1
                if self.calls == 1:
                    return MockResponse(b'[1, 2]', '</page=2>; rel="next"')
                return MockResponse(b'[3]', None)

        client = metrics.GitHubClient("token")
        client.opener = MockOpener()
        results = list(client.paginated_json("/test"))
        self.assertEqual(results, [1, 2, 3])
        self.assertEqual(client.opener.calls, 2)

    def test_paginated_json_resolves_relative_link_from_redirect_url(self):
        class MockResponse:
            def __init__(self, data, link, url):
                self.data = data
                self.headers = {"Link": link} if link else {}
                self.url = url
            def read(self): return self.data
            def geturl(self): return self.url
            def __enter__(self): return self
            def __exit__(self, *args): pass

        class MockOpener:
            def __init__(self):
                self.urls = []
            def open(self, req, timeout):
                self.urls.append(req.full_url)
                if len(self.urls) == 1:
                    return MockResponse(
                        b'[1]',
                        '<page-2>; rel="next"',
                        'https://api.github.com/redirected/page-1',
                    )
                return MockResponse(b'[2]', None, req.full_url)

        client = metrics.GitHubClient("token")
        client.opener = MockOpener()

        self.assertEqual(list(client.paginated_json("/initial/page-1")), [1, 2])
        self.assertEqual(
            client.opener.urls,
            [
                "https://api.github.com/initial/page-1",
                "https://api.github.com/redirected/page-2",
            ],
        )

    def test_loc_metrics_ties_are_sorted_by_language_name(self):
        loc = metrics.loc_metrics_from_totals(
            {"TypeScript": 10, "Python": 10, "Go": 20},
            {"TypeScript": 1, "Python": 1, "Go": 1},
            1,
        )

        self.assertEqual([language.name for language in loc.languages], ["Go", "Python", "TypeScript"])

    def test_load_fixture(self):
        fixture_data = {
            "repositories": [
                {"name": "demo-public", "private": False, "default_branch": "main"},
                {"name": "demo-private", "private": True, "default_branch": "develop"},
            ],
            "commits": [
                {
                    "repo": "demo-public",
                    "private": False,
                    "sha": "a",
                    "date": "2026-06-01T10:00:00Z",
                    "additions": 120,
                    "deletions": 20,
                    "files": 3,
                }
            ],
            "languages": [
                {"language": "Python", "loc": 90, "files": 2},
                {"language": "TypeScript", "loc": 30, "files": 1},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.json"
            path.write_text(json.dumps(fixture_data), encoding="utf-8")

            repos, commits, loc = metrics.load_fixture(path)

            self.assertEqual(len(repos), 2)
            self.assertEqual(repos[0].name, "demo-public")
            self.assertFalse(repos[0].private)
            self.assertEqual(repos[0].default_branch, "main")
            self.assertEqual(repos[1].name, "demo-private")
            self.assertTrue(repos[1].private)
            self.assertEqual(repos[1].default_branch, "develop")

            self.assertEqual(len(commits), 1)
            self.assertEqual(commits[0].repo, "demo-public")
            self.assertFalse(commits[0].private)
            self.assertEqual(commits[0].sha, "a")
            self.assertEqual(commits[0].date, datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc))
            self.assertEqual(commits[0].additions, 120)
            self.assertEqual(commits[0].deletions, 20)
            self.assertEqual(commits[0].files, 3)

            self.assertEqual(loc.total_loc, 120)
            self.assertEqual(len(loc.languages), 2)
            self.assertEqual(loc.languages[0].name, "Python")
            self.assertEqual(loc.languages[0].loc, 90)
            self.assertEqual(loc.languages[0].files, 2)
            self.assertEqual(loc.languages[1].name, "TypeScript")
            self.assertEqual(loc.languages[1].loc, 30)
            self.assertEqual(loc.languages[1].files, 1)

    @unittest.mock.patch.dict("os.environ", {"GITHUB_REPOSITORY_OWNER": "default_user"})
    def test_parse_args_defaults(self):
        args = metrics.parse_args([])
        self.assertEqual(args.user, "default_user")
        self.assertEqual(args.output, "assets/code-metrics.svg")
        self.assertEqual(args.months, 12)
        self.assertEqual(args.token_env, "METRICS_TOKEN")
        self.assertIsNone(args.fixture)

    def test_parse_args_explicit_values(self):
        argv = [
            "--user", "test_org",
            "--output", "test_out.svg",
            "--months", "6",
            "--token-env", "CUSTOM_TOKEN",
            "--fixture", "test_fixture.json"
        ]
        args = metrics.parse_args(argv)
        self.assertEqual(args.user, "test_org")
        self.assertEqual(args.output, "test_out.svg")
        self.assertEqual(args.months, 6)
        self.assertEqual(args.token_env, "CUSTOM_TOKEN")
        self.assertEqual(args.fixture, Path("test_fixture.json"))

    def test_days_in_period_month(self):
        # 1. Period completely covering the month
        self.assertEqual(metrics.days_in_period_month(date(2023, 1, 1), date(2022, 12, 1), date(2023, 2, 28)), 31)

        # 2. Period starting in the middle of the month and extending beyond it
        self.assertEqual(metrics.days_in_period_month(date(2023, 1, 1), date(2023, 1, 15), date(2023, 2, 15)), 17)

        # 3. Period starting before the month and ending in the middle
        self.assertEqual(metrics.days_in_period_month(date(2023, 1, 1), date(2022, 12, 15), date(2023, 1, 15)), 15)

        # 4. Period entirely contained within the month
        self.assertEqual(metrics.days_in_period_month(date(2023, 1, 1), date(2023, 1, 10), date(2023, 1, 20)), 11)

        # 5. Period entirely before the month
        self.assertEqual(metrics.days_in_period_month(date(2023, 1, 1), date(2022, 11, 1), date(2022, 12, 31)), 0)

        # 6. Period entirely after the month
        self.assertEqual(metrics.days_in_period_month(date(2023, 1, 1), date(2023, 2, 1), date(2023, 3, 1)), 0)

        # 7. Leap year for February (e.g., month of Feb 2024 -> 29 days vs Feb 2023 -> 28 days)
        # Period covers the whole month of Feb 2024
        self.assertEqual(metrics.days_in_period_month(date(2024, 2, 1), date(2024, 1, 1), date(2024, 3, 1)), 29)
        # Period covers the whole month of Feb 2023
        self.assertEqual(metrics.days_in_period_month(date(2023, 2, 1), date(2023, 1, 1), date(2023, 3, 1)), 28)

    @unittest.mock.patch("sys.stderr")
    def test_parse_args_invalid_type(self, mock_stderr):
        with self.assertRaises(SystemExit):
            metrics.parse_args(["--months", "not_an_int"])

if __name__ == "__main__":
    unittest.main()
