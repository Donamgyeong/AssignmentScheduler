import unittest
from scheduler import allocate, sample


class AllocationTests(unittest.TestCase):
    def test_salary_and_budget_conservation(self):
        data = sample()
        result = allocate(data)
        sums = {}
        for row in result['allocations'] + result['unused']:
            key = row['employee'], row['month']
            sums[key] = sums.get(key, 0) + row['amount']
        for (employee, month), total in sums.items():
            salary = next(e['salary'] for e in data['employees'] if e['name'] == employee)
            self.assertEqual(total, salary)
        for project, row in zip(data['projects'], result['summary']):
            self.assertEqual(row['refund'], max(0, project['kind'] - row['kind']))
            self.assertEqual(row['balance'], project['cash'] - row['cash'] - row['expenses'] - row['refund'])
            self.assertGreaterEqual(row['balance'], 0)

    def test_reassigns_to_avoid_greedy_shortfall(self):
        data = {'employees': [dict(name='A', salary=100, start='2026-10', end='2026-11')],
                'projects': [dict(name='P1', cash=0, kind=100, expenses=0, start='2026-10', end='2026-11'),
                             dict(name='P2', cash=0, kind=100, expenses=0, start='2026-10', end='2026-10')]}
        self.assertEqual(sum(r['refund'] for r in allocate(data)['summary']), 0)

    def test_refund_reserves_cash(self):
        data = {'employees': [dict(name='A', salary=100, start='2026-10', end='2026-10')],
                'projects': [dict(name='P', cash=200, kind=150, expenses=80, start='2026-10', end='2026-10', participants='A')]}
        row = allocate(data)['summary'][0]
        self.assertEqual((row['kind'], row['refund'], row['cash'], row['balance']), (100, 50, 0, 70))
        data['projects'][0]['cash'] = 20
        self.assertEqual(allocate(data)['summary'][0]['balance'], -110)

    def test_automatic_participants_ignore_legacy_lists(self):
        data = sample()
        for project in data['projects']:
            project['participants'] = ''
        result = allocate(data)
        self.assertEqual(sum(r['refund'] for r in result['summary']), 0)
        self.assertTrue(result['allocations'])
        data['projects'][0]['participants'] = '없는 연구원'
        self.assertEqual(result['allocations'], allocate(data)['allocations'])
        for row in result['allocations']:
            if row['project'] == '과제 B':
                self.assertNotEqual(row['month'], '2026-10')
            if row['employee'] == '박연구':
                self.assertNotEqual(row['month'], '2026-10')

    def test_nonoverlapping_period_diagnostic(self):
        data = sample()
        data['projects'][0]['start'] = '2027-01'
        data['projects'][0]['end'] = '2027-02'
        self.assertTrue(any('재직기간과 과제 수행기간' in reason for reason in allocate(data)['diagnostics']))

    def test_invalid_input(self):
        data = sample()
        data['employees'][0]['salary'] = -1
        with self.assertRaises(ValueError):
            allocate(data)


if __name__ == '__main__':
    unittest.main()
