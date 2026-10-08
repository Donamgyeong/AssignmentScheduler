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
        data = {'employees': [dict(name=n, salary=100, start='2026-10', end='2026-10') for n in ['A', 'B']],
                'projects': [dict(name='P1', cash=0, kind=100, expenses=0, start='2026-10', end='2026-10', participants='A,B'),
                             dict(name='P2', cash=0, kind=100, expenses=0, start='2026-10', end='2026-10', participants='A')]}
        self.assertEqual(sum(r['refund'] for r in allocate(data)['summary']), 0)

    def test_refund_reserves_cash(self):
        data = {'employees': [dict(name='A', salary=100, start='2026-10', end='2026-10')],
                'projects': [dict(name='P', cash=200, kind=150, expenses=80, start='2026-10', end='2026-10', participants='A')]}
        row = allocate(data)['summary'][0]
        self.assertEqual((row['kind'], row['refund'], row['cash'], row['balance']), (100, 50, 0, 70))
        data['projects'][0]['cash'] = 20
        self.assertEqual(allocate(data)['summary'][0]['balance'], -110)

    def test_ineligible_month_and_employee(self):
        data = sample()
        data['projects'][0]['participants'] = ''
        result = allocate(data)
        self.assertFalse(any(r['project'] == '과제 A' for r in result['allocations']))
        self.assertFalse(any(r['month'] == '2026-10' for r in result['allocations']))

    def test_invalid_input(self):
        data = sample()
        data['projects'][0]['participants'] = '없는 연구원'
        with self.assertRaises(ValueError):
            allocate(data)
        data = sample()
        data['employees'][0]['salary'] = -1
        with self.assertRaises(ValueError):
            allocate(data)


if __name__ == '__main__':
    unittest.main()
