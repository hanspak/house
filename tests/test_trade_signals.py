import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import trade_signals as signals
import molit_trades
from data_archive import save_rows

MONTHS = [f'2025-{m:02d}' for m in range(1, 13)] + [f'2026-{m:02d}' for m in range(1, 13)]
SCOPE = {'서울': ['서울|강남구', '서울|서초구']}


def row(month, price, name='A', area=84.9, dealing='중개거래', buyer='개인', seller='개인', day=15):
    return [f'{month}-{day:02d}', '역삼동', name, area, 5, price, 2000, '', '1', dealing, buyer, seller, '11680-1']


class ParticipantTests(unittest.TestCase):
    def test_counts_roll_up_and_old_rows_are_not_known(self):
        rows = {'서울|강남구': [row('2026-01', 100, dealing='직거래', buyer='법인'), row('2026-01', 100)[:9]],
                '서울|서초구': [row('2026-01', 100, seller='법인')]}
        out = signals.participants(rows, MONTHS, SCOPE, {})
        i = MONTHS.index('2026-01')
        self.assertEqual([out['서울|강남구'][k][i] for k in ('n', 'known', 'direct', 'buyer_corp', 'seller_corp')], [2, 1, 1, 1, 0])
        self.assertEqual([out['서울'][k][i] for k in ('n', 'known', 'direct', 'seller_corp')], [3, 2, 1, 1])
        self.assertEqual(out['전국']['n'][i], 3)

    def test_missing_month_blanks_district_and_parents(self):
        out = signals.participants({'서울|강남구': [], '서울|서초구': []}, MONTHS, SCOPE, {'서울|서초구': ['2026-02']})
        i = MONTHS.index('2026-02')
        self.assertIsNone(out['서울|서초구']['n'][i])
        self.assertIsNone(out['서울']['n'][i])
        self.assertIsNone(out['전국']['known'][i])
        self.assertEqual(out['서울|강남구']['n'][i], 0)


class RepeatIndexTests(unittest.TestCase):
    def test_recovers_known_monthly_growth(self):
        # 매달 1%씩 오르는 시장에서 여러 단지가 서로 다른 간격으로 다시 거래된다.
        level = [100 * 1.01 ** i for i in range(len(MONTHS))]
        pairs = [(s, t, math.log(level[t] / level[s])) for s in range(len(MONTHS)) for t in range(s + 1, min(s + 4, len(MONTHS))) for _ in range(10)]
        result = signals.repeat_index(pairs, len(MONTHS))
        self.assertEqual(result['index'][0], 100.0)
        for i, value in enumerate(result['index']):
            self.assertAlmostEqual(value, round(level[i], 2), places=1)

    def test_months_with_few_pairs_are_blank(self):
        pairs = [(0, 1, 0.0)] * signals.MIN_PAIRS + [(1, 2, 0.1)] * 3
        result = signals.repeat_index(pairs, 4)
        self.assertEqual(result['index'][:2], [100.0, 100.0])
        self.assertIsNone(result['index'][2])
        self.assertIsNone(result['index'][3])
        self.assertEqual(result['pairs'], [20, 23, 3, 0])

    def test_pairs_skip_same_month_and_extreme_ratios(self):
        rows = {'서울|강남구': [row('2025-01', 100), row('2025-01', 110, day=20), row('2025-03', 120),
                                row('2025-05', 400), row('2025-01', 50, name='B'), row('2025-02', 55, name='B', area=59.9)]}
        out = signals.price_signals(rows, MONTHS, SCOPE, {})
        # A: 1월(100)→1월(110) 같은 달 제외, 1월(110)→3월(120) 포함, 3월(120)→5월(400) 3배라 제외. B는 면적이 달라 다른 집.
        self.assertEqual(out['서울|강남구']['pairs'][:5], [1, 0, 1, 0, 0])


class NewHighTests(unittest.TestCase):
    def test_new_high_uses_previous_twelve_months_only(self):
        rows = {'서울|강남구': [row('2025-01', 200), row('2025-06', 120), row('2026-02', 150),
                                row('2026-03', 140), row('2026-04', 100, name='B')]}
        out = signals.price_signals(rows, MONTHS, SCOPE, {})['서울|강남구']
        feb, mar, apr = (MONTHS.index(m) for m in ('2026-02', '2026-03', '2026-04'))
        # 2026-02: 직전 12개월(2025-02~2026-01)에는 2025-06의 120만 있어 150은 경신. 2025-01의 200은 기간 밖.
        self.assertEqual((out['eligible'][feb], out['new_high'][feb]), (1, 1))
        # 2026-03: 직전 최고가 150보다 낮아 경신 아님. 2026-04 B는 이전 거래가 없어 비교 대상이 아님.
        self.assertEqual((out['eligible'][mar], out['new_high'][mar]), (1, 0))
        self.assertEqual((out['eligible'][apr], out['new_high'][apr]), (0, 0))
        self.assertIsNone(out['eligible'][11])


class SchemaTests(unittest.TestCase):
    def test_archive_accepts_old_and_new_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_rows(Path(tmp), 'trades', 'apt', '11680', '202601', [row('2026-01', 100), row('2026-01', 100)[:9]])
            with self.assertRaises(ValueError):
                save_rows(Path(tmp), 'trades', 'apt', '11680', '202601', [row('2026-01', 100)[:10]])

    def test_outdated_cache_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, rows in [('old', [row('2026-01', 1)[:9]]), ('new', [row('2026-01', 1)]), ('empty', [])]:
                Path(tmp, name).write_text(json.dumps(rows))
            self.assertEqual([molit_trades.outdated(Path(tmp, n)) for n in ('old', 'new', 'empty')], [True, False, False])

    def test_upgrade_refetches_newest_outdated_months_within_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp, 'molit')
            months = molit_trades.months_back(6)
            for kind in molit_trades.TYPES:
                (cache / kind).mkdir(parents=True)
                for ym in months:
                    rows = [row(f'{ym[:4]}-{ym[4:]}', 100)[:9]]
                    (cache / kind / f'11680_{ym}.json').write_text(json.dumps(rows))
            fetched = []

            def fetch(key, kind, lawd, ym):
                fetched.append((kind, ym))
                return [row(f'{ym[:4]}-{ym[4:]}', 100)]
            with patch.object(molit_trades, 'CACHE', str(cache)), patch.object(molit_trades, 'ROOT', tmp), \
                    patch.object(molit_trades, 'REGIONS', ['11680']), patch.object(molit_trades, 'fetch', fetch), \
                    patch.object(molit_trades, 'api_key', return_value='k'), \
                    patch.object(molit_trades, 'save_rows'), patch.object(molit_trades, 'save_cached_rows'):
                data = molit_trades.collect(6, workers=1, upgrade_limit=2)
            refresh = set(months[-molit_trades.REFRESH_MONTHS:])
            upgraded = sorted(f for f in fetched if f[1] not in refresh)
            # 새로 받는 3개월을 뺀 이전 형식 중 가장 최근 달부터 2건만 다시 받는다.
            self.assertEqual(len(upgraded), 2)
            self.assertTrue(all(ym == months[-molit_trades.REFRESH_MONTHS - 1] for _, ym in upgraded))
            # 이전 형식과 새 형식이 섞여도 같은 지역의 거래는 한 번만 센다.
            rid = list(data['trades']['apt'])[0]
            self.assertEqual(len(data['trades']['apt'][rid]), 6)


if __name__ == '__main__':
    unittest.main()
