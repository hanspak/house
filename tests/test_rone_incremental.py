from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import market_extra as extra


def feed(months, **values):
    return {'months': months, 'values': values, 'source': 's'}


class RoneIncrementalTests(unittest.TestCase):
    def test_refresh_start_goes_back_24_months_or_full_range(self):
        self.assertEqual(extra.refresh_start(feed(['2026-08'], a=[1]), '200012'), '202409')
        self.assertEqual(extra.refresh_start(feed(['2001-03'], a=[1]), '200012'), '200012')
        self.assertEqual(extra.refresh_start(None, '200601'), '200601')
        self.assertEqual(extra.refresh_start({'months': []}, '200601'), '200601')

    def test_merge_keeps_old_months_and_overwrites_window(self):
        old = feed(['2026-06', '2026-07'], a=[1, 2], gone=[5, 6])
        new = feed(['2026-07', '2026-08'], a=[20, 30], added=[7, 8])
        merged = extra.merge_feed(old, new)
        self.assertEqual(merged['months'], ['2026-06', '2026-07', '2026-08'])
        self.assertEqual(merged['values']['a'], [1, 20, 30])
        self.assertEqual(merged['values']['gone'], [5, None, None])
        self.assertEqual(merged['values']['added'], [None, 7, 8])
        self.assertTrue(extra.valid_feed(merged))
        self.assertIs(extra.merge_feed(None, new), new)

    def test_apt_trades_asks_once_for_all_regions_from_window_start(self):
        rows = [{'ITM_ID': extra.RONE_COUNT_ITEM, 'CLS_ID': 1, 'CLS_FULLNM': '서울', 'WRTTIME_IDTFR_ID': m, 'DTA_VAL': v}
                for m, v in [('202607', 10), ('202608', 11)]]
        rows.append({'ITM_ID': extra.RONE_COUNT_ITEM, 'CLS_ID': 1, 'CLS_FULLNM': None, 'WRTTIME_IDTFR_ID': '202606', 'DTA_VAL': 9})
        with patch.object(extra, 'rone_rows', return_value=rows) as call:
            data = extra.rone_apt_trades('key', previous=feed(['2024-01', '2026-06'], 서울=[1, 2]))
        call.assert_called_once()
        self.assertEqual(call.call_args.kwargs['START_WRTTIME'], '202407')
        self.assertNotIn('CLS_ID', call.call_args.kwargs)
        self.assertEqual(data['months'][-3:], ['2026-06', '2026-07', '2026-08'])
        self.assertEqual(data['values']['서울'][:1] + data['values']['서울'][-3:], [1, 9, 10, 11])

    def test_unsold_window_does_not_zero_fill_missing_leading_months(self):
        rows = [{'CLS_FULLNM': p + '>계', 'WRTTIME_IDTFR_ID': '202608', 'DTA_VAL': 1} for p in extra.PROV17 if p != '세종']
        rows += [{'CLS_FULLNM': '세종>계', 'WRTTIME_IDTFR_ID': m, 'DTA_VAL': 2} for m in ('202607', '202608')]
        with patch.object(extra, 'rone_rows', return_value=rows):
            data = extra.rone_unsold('key', previous=feed(['2026-06'], 세종=[3]))
        self.assertEqual(data['values']['서울'], [None, None, 1])
        self.assertEqual(data['values']['세종'], [3, 2, 2])
        self.assertEqual(data['values']['전국'][-1], 18)
        with patch.object(extra, 'rone_rows', return_value=rows):
            full = extra.rone_unsold('key')
        self.assertEqual(full['values']['서울'], [0, 1])


if __name__ == '__main__':
    unittest.main()
