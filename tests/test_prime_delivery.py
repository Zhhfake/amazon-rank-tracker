import unittest
from unittest.mock import patch

import rank_tracker_core as core


class RankCaptureTests(unittest.TestCase):
    def make_ranker(self, page):
        ranker = core.AmazonRanker.__new__(core.AmazonRanker)
        ranker.blocked = False
        ranker.consecutive_failures = 0
        ranker._recovery_attempted = False
        ranker._fetch_page = lambda _url: page
        ranker._is_blocked_page = lambda _html: False
        return ranker

    def test_returns_natural_rank_without_delivery_text(self):
        page = '''
        <div data-component-type="s-search-result" data-asin="B000000001">Other product</div>
        <div data-component-type="s-search-result" data-asin="B0H5J2F9JL">
          Join Prime to get FREE delivery Tomorrow, Nov 18
        </div>
        '''
        result = self.make_ranker(page).find_ranks("screen protector", ["B0H5J2F9JL"], max_pages=1)

        self.assertEqual(result["B0H5J2F9JL"], "Page 1 · #2")
        self.assertEqual(core.parse_rank(result["B0H5J2F9JL"]), 2)
        self.assertNotIn("Prime", result["B0H5J2F9JL"])

    def test_sponsored_result_does_not_count_as_natural_rank(self):
        page = '''
        <div data-component-type="s-search-result" data-asin="B0H5J2F9JL">
          Sponsored. Join Prime to get FREE delivery Tomorrow, Nov 18
        </div>
        '''
        result = self.make_ranker(page).find_ranks("screen protector", ["B0H5J2F9JL"], max_pages=1)

        self.assertEqual(result["B0H5J2F9JL"], "—")
        self.assertIsNone(core.parse_rank(result["B0H5J2F9JL"]))

    def test_complete_scan_logs_missing_asin_separately_from_rank_value(self):
        page = '<div data-component-type="s-search-result" data-asin="B000000001">Other product</div>'
        with patch("builtins.print") as printer:
            result = self.make_ranker(page).find_ranks("screen protector", ["B0H5J2F9JL"], max_pages=1)

        self.assertEqual(result["B0H5J2F9JL"], "—")
        self.assertIsNone(core.parse_rank(result["B0H5J2F9JL"]))
        self.assertIn("扫描 1/1 页（完成）", printer.call_args.args[0])

    def test_empty_search_page_is_logged_as_incomplete(self):
        with patch("builtins.print") as printer:
            result = self.make_ranker("").find_ranks("screen protector", ["B0H5J2F9JL"], max_pages=1)

        self.assertEqual(result["B0H5J2F9JL"], "—")
        self.assertIn("扫描 1/1 页（未完成）", printer.call_args.args[0])

    def test_rank_column_styles_include_light_cell_borders(self):
        with patch.object(core, "feishu_api") as api:
            core.apply_rank_colors(
                "token",
                "sheet1",
                3,
                3,
                [["Page 1 · #2"], ["—"]],
                date_row=1,
                zipcode_row=2,
            )

        style_data = api.call_args.args[2]["data"]
        border_update = next(item for item in style_data if "borderType" in item["style"])
        self.assertEqual(border_update["ranges"], ["sheet1!D2:D4"])
        self.assertEqual(border_update["style"], {
            "borderType": "FULL_BORDER",
            "borderColor": "#D9E1E8",
        })


if __name__ == "__main__":
    unittest.main()
