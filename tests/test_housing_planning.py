import copy
import csv
import datetime as dt
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from housing_moveins import parse_csv, district_key
from housing_pipeline import parse_rows
from market_overview import supply_metrics
from data_revisions import changes
from trade_regions import PROVINCES, districts


def csv_body(rows):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['입주예정월','지역','사업유형','주소','아파트명','세대수'])
    writer.writerows(rows)
    return out.getvalue().encode('utf-8-sig')


class MoveinsTests(unittest.TestCase):
    def rows(self):
        return [['2026-10','서울','분양','서울특별시 강남구 역삼동','A',100],
                ['2027-00','서울','분양','서울특별시 강남구 역삼동','B',200],
                ['2027-04','서울','임대','서울특별시 강남구 역삼동','C',300]]

    def test_unknown_month_separates_from_monthly_and_window_totals(self):
        data = parse_csv(csv_body(self.rows()),'2026-06-30',3)
        self.assertEqual(data['total_units'],600)
        self.assertEqual(sum(data['values']['전국']['scheduled']),400)
        self.assertEqual(data['values']['전국']['unscheduled'],{'2027':200})
        metrics,_,_ = supply_metrics('서울|강남구',moveins=data,today=dt.date(2026,10,8))
        self.assertEqual(metrics['moveins6']['value'],100)
        self.assertEqual(metrics['moveins12']['value'],400)
        self.assertEqual(metrics['moveins_unknown']['value'],200)
        self.assertEqual(metrics['moveins12']['scope'],'서울|강남구')
        self.assertNotIn('A',str(data))

    def test_incomplete_horizon_is_not_a_shortened_total(self):
        data = parse_csv(csv_body(self.rows()),'2026-06-30')
        metrics,_,_ = supply_metrics('전국',moveins=data,today=dt.date(2028,3,1))
        self.assertIsNone(metrics['moveins6']['value'])
        self.assertEqual(metrics['moveins6']['period'],'2028-03~2028-08')

    def test_ambiguous_old_incheon_boundary_uses_parent_scope(self):
        rows = [['2026-10','인천','분양','인천광역시 서구 검단동','A',500]]
        data = parse_csv(csv_body(rows),'2026-06-30')
        self.assertIsNone(data['values']['인천|서구']['scheduled'][3])
        metrics,_,scope = supply_metrics('인천|검단구',moveins=data,today=dt.date(2026,10,8))
        self.assertEqual(scope,'인천')
        self.assertEqual(metrics['moveins6']['value'],500)
        self.assertIn('상위 지역 자료',metrics['moveins6']['note'])

    def test_validation_rejects_wrong_file_row_count_dates_and_units(self):
        with self.assertRaises(ValueError):parse_csv(b'other,data\n1,2','2026-06-30')
        with self.assertRaises(ValueError):parse_csv(csv_body(self.rows()),'2026-06-30',4)
        for value in ('2027-13','2029-01'):
            rows=self.rows();rows[0][0]=value
            with self.assertRaises(ValueError):parse_csv(csv_body(rows),'2026-06-30')
        rows=self.rows();rows[0][5]=-1
        with self.assertRaises(ValueError):parse_csv(csv_body(rows),'2026-06-30')

    def test_district_address_matches_city_and_ward_and_single_sejong(self):
        scope=districts()
        self.assertEqual(district_key('경기','경기도 수원시 영통구 영통동',scope),'경기|수원시 영통구')
        self.assertEqual(district_key('세종','세종특별자치시 나성동',scope),'세종|')

    def test_unknown_year_revision_is_retained_without_assigning_a_month(self):
        data=parse_csv(csv_body(self.rows()),'2026-06-30')
        updated=copy.deepcopy(data);updated['values']['서울']['unscheduled']['2027']=250
        records=changes('moveins',data,updated)
        self.assertEqual(len(records),1)
        self.assertEqual((records[0]['month'],records[0]['delta']),('2027-00',50))


class PipelineTests(unittest.TestCase):
    def rows(self,combined=False):
        provinces=[p for p in PROVINCES if not combined or p not in ('광주','전남')]
        if combined:provinces+=['전남광주']
        rows=[['아파트 인허가 실적'],[],['<누계>'],['<월계>','2026년 08월말 현재'],['구분','','','','','','','','아파트']]
        rows += [[p,0,0,0,0,0,0,0,1] for p in provinces]
        rows += [['전국',0,0,0,0,0,0,0,len(provinces)]]
        return rows

    def test_reads_monthly_apartment_column_and_checks_national_sum(self):
        values=parse_rows(self.rows(),'2026-08','인허가')
        self.assertEqual(values['전국'],17)
        self.assertEqual(values['전남광주'],2)
        rows=self.rows();rows[-1][8]=18
        with self.assertRaises(ValueError):parse_rows(rows,'2026-08','인허가')
        with self.assertRaises(ValueError):parse_rows(self.rows(),'2026-07','인허가')
        with self.assertRaises(ValueError):parse_rows(self.rows(),'2026-08','착공')

    def test_combined_authority_is_not_split_into_old_provinces(self):
        values=parse_rows(self.rows(True),'2026-08','인허가')
        self.assertEqual(values['전국'],16)
        self.assertNotIn('광주',values)
        pipeline={'months':['2026-08'],'values':{'광주':{k:[None] for k in ('permit','start','completion')},
                  '전남광주':{k:[10] for k in ('permit','start','completion')}}}
        metrics,scope,_=supply_metrics('광주|북구',pipeline=pipeline)
        self.assertEqual(scope,'전남광주')
        self.assertEqual(metrics['permit']['value'],10)
        self.assertIn('통합 공표값',metrics['permit']['note'])


if __name__ == '__main__':
    unittest.main()
