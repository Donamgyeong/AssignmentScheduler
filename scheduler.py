"""Dependency-free monthly personnel budget allocator. Amounts are integer KRW."""
from collections import deque
from datetime import date


def months(start, end):
    def parse(value):
        d = date.fromisoformat(value + '-01')
        return d.year * 12 + d.month - 1
    first, last = parse(start), parse(end)
    if first > last:
        raise ValueError('시작월은 종료월보다 늦을 수 없습니다.')
    if last - first > 120:
        raise ValueError('계산 기간은 최대 121개월입니다.')
    return [f'{i // 12:04d}-{i % 12 + 1:02d}' for i in range(first, last + 1)]


def validate(data):
    for category in ('employees', 'projects'):
        seen = set()
        for row in data[category]:
            name = row['name'].strip()
            if not name or name in seen:
                raise ValueError('이름은 비어 있거나 중복될 수 없습니다.')
            seen.add(name)
            months(row['start'], row['end'])
            fields = ('salary',) if category == 'employees' else ('cash', 'kind', 'expenses')
            for field in fields:
                if type(row[field]) is not int or row[field] < 0:
                    raise ValueError('금액은 0 이상의 정수(원)여야 합니다.')


class Flow:
    def __init__(self):
        self.graph = {}

    def edge(self, source, target, capacity):
        self.graph.setdefault(source, [])
        self.graph.setdefault(target, [])
        forward = [target, capacity, len(self.graph[target]), capacity]
        reverse = [source, 0, len(self.graph[source]), 0]
        self.graph[source].append(forward)
        self.graph[target].append(reverse)
        return forward

    def solve(self, source, sink):
        while True:
            parents = {source: None}
            queue = deque([source])
            while queue and sink not in parents:
                node = queue.popleft()
                for i, edge in enumerate(self.graph[node]):
                    if edge[1] > 0 and edge[0] not in parents:
                        parents[edge[0]] = (node, i)
                        queue.append(edge[0])
            if sink not in parents:
                return
            amount = float('inf')
            node = sink
            while node != source:
                previous, index = parents[node]
                amount = min(amount, self.graph[previous][index][1])
                node = previous
            node = sink
            while node != source:
                previous, index = parents[node]
                edge = self.graph[previous][index]
                edge[1] -= amount
                self.graph[node][edge[2]][1] += amount
                node = previous


def allocate(data):
    validate(data)
    available = {(e['name'], month): e['salary'] for e in data['employees']
                 for month in months(e['start'], e['end'])}
    allocations = {}
    totals = {p['name']: {'kind': 0, 'cash': 0} for p in data['projects']}

    def phase(category):
        flow = Flow()
        source, sink = ('source',), ('sink',)
        edges = []
        for key, capacity in available.items():
            flow.edge(source, ('employee', *key), capacity)
        for p in data['projects']:
            name = p['name']
            deficit = max(0, p['kind'] - totals[name]['kind'])
            capacity = p['kind'] if category == 'kind' else max(0, p['cash'] - p['expenses'] - deficit)
            target = ('project', name)
            flow.edge(target, sink, capacity)
            active = set(months(p['start'], p['end']))
            for key, remaining in available.items():
                employee, month = key
                if month in active:
                    edge = flow.edge(('employee', *key), target, remaining)
                    edges.append((key, name, edge))
        flow.solve(source, sink)
        for key, project, edge in edges:
            amount = edge[3] - edge[1]
            if amount:
                available[key] -= amount
                totals[project][category] += amount
                allocations[(*key, project, category)] = amount

    phase('kind')
    phase('cash')
    summary = []
    diagnostics = []
    for p in data['projects']:
        total = totals[p['name']]
        refund = max(0, p['kind'] - total['kind'])
        balance = p['cash'] - p['expenses'] - total['cash'] - refund
        summary.append(dict(name=p['name'], kind=total['kind'], required=p['kind'],
                            cash=total['cash'], expenses=p['expenses'], refund=refund, balance=balance))
        active = set(months(p['start'], p['end']))
        eligible = [e for e in data['employees'] if active.intersection(months(e['start'], e['end']))]
        if not eligible:
            diagnostics.append(f"{p['name']}: 연구원의 재직기간과 과제 수행기간이 겹치지 않습니다.")
        elif not any(e['salary'] > 0 for e in eligible):
            diagnostics.append(f"{p['name']}: 해당 기간 참여 연구원의 월 임금이 모두 0원입니다.")
        elif refund:
            diagnostics.append(f"{p['name']}: 참여 가능한 인건비를 배분했으나 현물이 {refund:,}원 부족합니다. 다른 과제와의 배분 경쟁도 확인하세요.")
    rows = [dict(employee=k[0], month=k[1], project=k[2], category=k[3], amount=v)
            for k, v in sorted(allocations.items())]
    unused = [dict(employee=k[0], month=k[1], amount=v) for k, v in sorted(available.items()) if v]
    return dict(summary=summary, allocations=rows, unused=unused, diagnostics=diagnostics)


def sample():
    return {'employees': [
        dict(name='김연구', salary=4000000, start='2026-10', end='2026-12'),
        dict(name='이연구', salary=3500000, start='2026-10', end='2026-12'),
        dict(name='박연구', salary=3000000, start='2026-11', end='2026-12')],
        'projects': [
            dict(name='과제 A', cash=18000000, kind=12000000, expenses=4000000,
                 start='2026-10', end='2026-12'),
            dict(name='과제 B', cash=12000000, kind=10000000, expenses=3000000,
                 start='2026-11', end='2026-12')]}
