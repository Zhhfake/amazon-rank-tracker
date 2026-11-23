import unittest

import rank_tracker_core as core


class PrimeDeliveryTests(unittest.TestCase):
    def make_ranker(self, page):
        ranker = core.AmazonRanker.__new__(core.AmazonRanker)
        ranker.blocked = False
        ranker.consecutive_failures = 0
        ranker._recovery_attempted = False
        ranker._fetch_page = lambda _url: page
        ranker._is_blocked_page = lambda _html: False
        return ranker

    def test_rank_and_prime_delivery_are_extracted_from_one_search_page(self):
        page = '''
        <div data-component-type="s-search-result" data-asin="B000000001">Other product</div>
        <div data-component-type="s-search-result" data-asin="B0H5J2F9JL">
          Join Prime to get FREE delivery Tomorrow, Nov 18
          Or Non-members get FREE delivery Friday, Nov 20
        </div>
        '''
        result = self.make_ranker(page).find_ranks("screen protector", ["B0H5J2F9JL"], max_pages=1)

        self.assertEqual(result["B0H5J2F9JL"], "Page 1 · #2 | Prime: Tomorrow, Nov 18")
        self.assertEqual(core.parse_rank(result["B0H5J2F9JL"]), 2)

    def test_sponsored_card_can_supply_delivery_without_counting_as_natural_rank(self):
        page = '''
        <div data-component-type="s-search-result" data-asin="B0H5J2F9JL">
          Sponsored. Join Prime to get FREE delivery Tomorrow, Nov 18
        </div>
        '''
        result = self.make_ranker(page).find_ranks("screen protector", ["B0H5J2F9JL"], max_pages=1)

        self.assertEqual(result["B0H5J2F9JL"], "— | Prime: Tomorrow, Nov 18")
        self.assertIsNone(core.parse_rank(result["B0H5J2F9JL"]))
        self.assertTrue(core.has_prime_delivery_result(result["B0H5J2F9JL"]))

    def test_complete_scan_marks_missing_asin_without_claiming_a_rank(self):
        page = '<div data-component-type="s-search-result" data-asin="B000000001">Other product</div>'
        with patch("builtins.print") as printer:
            result = self.make_ranker(page).find_ranks("screen protector", ["B0H5J2F9JL"], max_pages=1)

        self.assertEqual(result["B0H5J2F9JL"], "— | Prime: 目标未出现在已扫描搜索页")
        self.assertIsNone(core.parse_rank(result["B0H5J2F9JL"]))
        self.assertIn("扫描 1/1 页（完成）", printer.call_args.args[0])

    def test_empty_search_page_is_marked_incomplete_not_missing(self):
        with patch("builtins.print") as printer:
            result = self.make_ranker("").find_ranks("screen protector", ["B0H5J2F9JL"], max_pages=1)

        self.assertEqual(result["B0H5J2F9JL"], "— | Prime: 扫描未完成")
        self.assertIn("扫描 1/1 页（未完成）", printer.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
