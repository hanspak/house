from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import openpyxl
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import housing_supply
import molit_rents
from trade_regions import PROVINCES


class RentTests(unittest.TestCase):
    def test_xml_preserves_contract_type_and_omits_invalid_amount(self):
        xml = ET.fromstring('''<response><items>
          <item><dealYear>2026</dealYear><dealMonth>8</dealMonth><dealDay>1</dealDay>
          <deposit>20,000</deposit><monthlyRent>0</monthlyRent><excluUseAr>59</excluUseAr><contractType>갱신</contractType></item>
          <item><deposit>미확인</deposit><monthlyRent>0</monthlyRent></item>
          </items></response>''')
        rows = molit_rents.parse_items(xml)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][:5], ['2026-08-01',20000,0,59,'갱신'])

    def test_jeonse_monthly_samples_and_missing_region_are_separate(self):
        rows = [['2026-08-01', 20000, 0, 59, '신규']] * 10 + [['2026-08-01', 1000, 70, 59, '']] * 9
        scope = {'서울': ['서울|종로구'], '부산': ['부산|중구']}
        with patch.object(molit_rents, 'districts', return_value=scope):
            data = molit_rents.aggregate(['2026-08'], {'서울|종로구': rows}, {})
        self.assertEqual(data['서울']['deposit'], [20000])
        self.assertEqual(data['서울']['monthly_n'], [9])
        self.assertEqual(data['서울']['rent'], [None])
        self.assertEqual(data['서울']['unknown_n'], [9])
        self.assertEqual(data['전국']['n'], [None])


class SupplyTests(unittest.TestCase):
    def workbook(self, path, missing=False, total=340):
        book = openpyxl.Workbook()
        sheet = book.active;sheet.title = '시군구별★'
        for row in [['제목'],[None],['구분','시군구','26.8']]:sheet.append(row)
        for province in PROVINCES:
            if not missing or province != '제주':sheet.append([province,'계',100])
        sheet = book.create_sheet('공사완료후★')
        for row in [['제목'],[None],['구분','시군구','계'],[None],['전국','합계',total]]:sheet.append(row)
        for province in PROVINCES:sheet.append([province,'계',20])
        book.save(path);book.close()

    def test_totals_and_completed_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'supply.xlsx';self.workbook(path)
            result = housing_supply.parse_workbook(path,'2026-08')
            self.assertEqual(result['total']['전국'],1700)
            self.assertEqual(result['completed']['전국'],340)
            with self.assertRaises(ValueError):housing_supply.parse_workbook(path,'2026-07')
            self.workbook(path,missing=True)
            with self.assertRaises(ValueError):housing_supply.parse_workbook(path,'2026-08')
            self.workbook(path,total=341)
            with self.assertRaises(ValueError):housing_supply.parse_workbook(path,'2026-08')

    def test_merged_region_maps_districts_without_duplicate_total(self):
        self.assertEqual(housing_supply.region_key('전남광주','동 구'),'광주|동구')
        self.assertEqual(housing_supply.region_key('전남광주','목포시'),'전남|목포시')
        self.assertIsNone(housing_supply.region_key('전남광주','계'))


if __name__ == '__main__':
    unittest.main()
