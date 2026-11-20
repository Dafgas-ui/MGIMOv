import unittest
from tests.brs_calculator_fixture import real_forecasts, CATEGORIES, EVENTS


class CalculatorContractTests(unittest.TestCase):
    def test_authoritative_contract_and_read_only_generation(self):
        samples = real_forecasts()
        for name, response in samples.items():
            for row in response['items']:
                events = {event['code']:event for event in row['events']}
                categories = {category['code']:category for category in row['categories']}
                self.assertEqual(set(events),set(EVENTS))
                for index, code in enumerate(EVENTS):
                    self.assertEqual(events[code]['category_code'],CATEGORIES[index])
                    self.assertEqual(events[code]['required'],index==1)
                    self.assertEqual(events[code]['admission_min'],10 if index==1 else 0)
                self.assertEqual(categories['EXAM']['admission_min'],10)
                self.assertIn('required_shortfalls', row)
                self.assertIn('category_shortfalls', row)
                self.assertIn('predicted_result', row)
        exams = {name:next(row for row in data['items'] if row['control']=='exam')
                 for name,data in samples.items()}
        self.assertIsNone(exams['empty']['published_points'])
        self.assertEqual(exams['zero']['published_points'], 0)
        self.assertEqual([exams[str(n)]['admission'] for n in (49,50,51)], [False,True,True])
        self.assertFalse(exams['required_missing']['admission'])
        self.assertFalse(exams['category_missing']['admission'])
