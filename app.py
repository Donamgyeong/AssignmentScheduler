import csv
import json
import os
import sqlite3
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
from scheduler import allocate, sample, validate

EMPLOYEE = [('name', '연구원 이름'), ('salary', '월 임금 (원)'), ('start', '시작월 YYYY-MM'), ('end', '종료월 YYYY-MM')]
PROJECT = [('name', '과제 이름'), ('cash', '현금 예산 (원)'), ('kind', '현물 의무액 (원)'),
           ('expenses', '기타 현금 지출 (원)'), ('start', '시작월 YYYY-MM'), ('end', '종료월 YYYY-MM'),
           ('participants', '참여 연구원 (쉼표 구분)')]
MONEY = {'salary', 'cash', 'kind', 'expenses', 'amount', 'required', 'refund', 'balance', 'delta', 'previous'}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('과제 인건비 배분 — 프로토타입')
        self.geometry('1200x780')
        self.minsize(950, 650)
        self.folder = Path(os.getenv('LOCALAPPDATA', str(Path.home()))) / 'AssignmentScheduler'
        self.folder.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.folder / 'scheduler.db')
        self.db.execute('CREATE TABLE IF NOT EXISTS snapshots (id INTEGER PRIMARY KEY, created TEXT, body TEXT)')
        record = self.db.execute('SELECT body FROM snapshots ORDER BY id DESC LIMIT 1').fetchone()
        state = json.loads(record[0]) if record else {}
        self.data = state.get('data', {'employees': [], 'projects': []})
        self.baseline = state.get('baseline', [])
        self.result = None
        self.dirty = False
        self.protocol('WM_DELETE_WINDOW', self.close)
        ttk.Label(self, text='과제 예산 · 월별 인건비 배분', font=('맑은 고딕', 18, 'bold')).pack(anchor='w', padx=18, pady=(14, 6))
        ttk.Label(self, text='전체 입력 기간을 재계산합니다. 현물 우선 배분 → 예상 반납액 확보 → 현금 배분. 금액 단위: 원').pack(anchor='w', padx=18)
        bar = ttk.Frame(self)
        bar.pack(fill='x', padx=18, pady=12)
        for label, command in [('샘플 불러오기', self.load_sample), ('저장', self.save), ('자동 배분', self.calculate),
                               ('현재 안 확정', self.confirm), ('기존안 가져오기', self.import_baseline), ('결과 CSV 내보내기', self.export),
                               ('백업', self.backup), ('복원', self.restore)]:
            ttk.Button(bar, text=label, command=command).pack(side='left', padx=(0, 6))
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill='both', expand=True, padx=18)
        self.trees = {}
        for category, label, fields in [('employees', '연구원', EMPLOYEE), ('projects', '과제', PROJECT)]:
            frame = ttk.Frame(self.tabs)
            self.tabs.add(frame, text=label)
            actions = ttk.Frame(frame)
            actions.pack(fill='x', pady=10)
            for text, command in [('추가', lambda c=category: self.edit(c)), ('수정', lambda c=category: self.edit(c, True)),
                                  ('삭제', lambda c=category: self.delete(c)),
                                  ('CSV 가져오기', lambda c=category: self.import_csv(c)),
                                  ('CSV 양식 저장', lambda c=category: self.template(c))]:
                ttk.Button(actions, text=text, command=command).pack(side='left', padx=4)
            if category == 'projects':
                ttk.Label(frame, text='참여 연구원을 반드시 지정하세요. 예산은 입력한 수행기간 전체 금액이며 기타 지출에는 예정 지출도 포함하세요.').pack(anchor='w', pady=5)
            self.trees[category] = self.tree(frame, fields)
            self.trees[category].bind('<Double-1>', lambda event, c=category: self.edit(c, True))
        self.result_frame = ttk.Frame(self.tabs)
        self.tabs.add(self.result_frame, text='과제별 결과')
        self.summary_label = ttk.Label(self.result_frame, text='연구원과 과제를 입력한 뒤 자동 배분을 실행하세요.')
        self.summary_label.pack(anchor='w', pady=12)
        self.trees['summary'] = self.tree(self.result_frame, [('name', '과제'), ('kind', '배분 현물'), ('required', '현물 의무액'),
            ('cash', '현금 인건비'), ('expenses', '기타 지출'), ('refund', '예상 반납액'), ('balance', '반납 후 현금 잔액')])
        self.trees['allocations'] = self.result_tab('월별 배분·비교', [('month', '월'), ('employee', '연구원'), ('project', '과제'),
            ('category', '구분'), ('amount', '추천 금액'), ('previous', '이전 확정 금액'), ('delta', '증감')])
        self.trees['unused'] = self.result_tab('미배분 임금', [('month', '월'), ('employee', '연구원'), ('amount', '회사 부담 잔액')])
        self.status = ttk.Label(self, text=f'저장 위치: {self.folder} | 계산 전', wraplength=1150)
        self.status.pack(fill='x', padx=18, pady=10)
        self.refresh()

    def tree(self, frame, fields):
        holder = ttk.Frame(frame)
        holder.pack(fill='both', expand=True)
        tree = ttk.Treeview(holder, columns=[k for k, _ in fields], show='headings', selectmode='browse')
        for key, title in fields:
            tree.heading(key, text=title)
            tree.column(key, width=145, minwidth=100, anchor='e' if key in MONEY else 'w')
        vertical = ttk.Scrollbar(holder, orient='vertical', command=tree.yview)
        horizontal = ttk.Scrollbar(holder, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        return tree

    def result_tab(self, label, fields):
        frame = ttk.Frame(self.tabs)
        self.tabs.add(frame, text=label)
        return self.tree(frame, fields)

    def fill(self, name, rows):
        tree = self.trees[name]
        tree.delete(*tree.get_children())
        for i, row in enumerate(rows):
            values = []
            for key in tree['columns']:
                value = row.get(key, '')
                if key in MONEY and isinstance(value, int):
                    value = f'{value:,}'
                if key == 'category':
                    value = {'kind': '현물', 'cash': '현금'}.get(value, value)
                values.append(value)
            tree.insert('', 'end', iid=str(i), values=values)

    def refresh(self):
        for key in ('employees', 'projects'):
            self.fill(key, self.data[key])

    def changed(self):
        self.dirty = True
        self.result = None
        for name in ('summary', 'allocations', 'unused'):
            self.fill(name, [])
        self.summary_label.config(text='입력이 변경되었습니다. 자동 배분을 다시 실행하세요.')
        self.status.config(text=f'미저장 변경 있음 | 저장 위치: {self.folder}')
        self.refresh()

    def edit(self, category, existing=False):
        selection = self.trees[category].selection()
        if existing and not selection:
            return
        index = int(selection[0]) if existing else None
        row = self.data[category][index] if existing else {}
        fields = EMPLOYEE if category == 'employees' else PROJECT
        dialog = tk.Toplevel(self)
        dialog.title('항목 수정' if existing else '항목 추가')
        dialog.transient(self)
        dialog.grab_set()
        entries = {}
        for i, (key, label) in enumerate(fields):
            ttk.Label(dialog, text=label).grid(row=i, column=0, padx=12, pady=8, sticky='w')
            entry = ttk.Entry(dialog, width=45)
            entry.insert(0, str(row.get(key, '2026-10' if key in ('start', 'end') else '')))
            entry.grid(row=i, column=1, padx=12, pady=8)
            entries[key] = entry
        def submit():
            try:
                item = {key: int(entry.get().replace(',', '')) if key in MONEY else entry.get().strip() for key, entry in entries.items()}
                candidate = json.loads(json.dumps(self.data))
                if existing:
                    candidate[category][index] = item
                    if category == 'employees' and item['name'] != row['name']:
                        for project in candidate['projects']:
                            project['participants'] = ','.join(item['name'] if n.strip() == row['name'] else n.strip() for n in project['participants'].split(','))
                else:
                    candidate[category].append(item)
                validate(candidate)
                self.data = candidate
                self.changed()
                dialog.destroy()
            except (ValueError, KeyError, TypeError) as error:
                messagebox.showerror('입력 오류', str(error), parent=dialog)
        ttk.Button(dialog, text='적용', command=submit).grid(row=len(fields), column=1, pady=14, sticky='e', padx=12)

    def delete(self, category):
        selection = self.trees[category].selection()
        if not selection:
            return
        index = int(selection[0])
        name = self.data[category][index]['name']
        if messagebox.askyesno('삭제', f'{name} 항목을 삭제할까요? 연구원 삭제 시 참여 목록에서도 제외됩니다.'):
            self.data[category].pop(index)
            if category == 'employees':
                for p in self.data['projects']:
                    p['participants'] = ','.join(n.strip() for n in p['participants'].split(',') if n.strip() != name)
            self.changed()

    def load_sample(self):
        if (self.data['employees'] or self.data['projects']) and not messagebox.askyesno('샘플', '현재 입력과 확정 기준안을 샘플로 교체할까요?'):
            return
        self.data, self.baseline = sample(), []
        self.changed()
        self.calculate()

    def save(self):
        self.backup(automatic=True)
        body = json.dumps(dict(data=self.data, baseline=self.baseline), ensure_ascii=False)
        self.db.execute('INSERT INTO snapshots(created, body) VALUES (?, ?)', (datetime.now().isoformat(), body))
        self.db.commit()
        self.dirty = False
        self.status.config(text=f'저장 완료 | {self.folder}')

    def backup(self, automatic=False):
        if automatic:
            path = self.folder / 'before_save.db'
        else:
            self.save()  # include current edits in manual backup
            path = filedialog.asksaveasfilename(defaultextension='.db', initialfile='scheduler-backup.db', filetypes=[('데이터 백업', '*.db')])
            if not path:
                return
        if Path(path).resolve() == (self.folder / 'scheduler.db').resolve():
            messagebox.showerror('백업 오류', '현재 데이터 파일은 덮어쓸 수 없습니다.')
            return
        with sqlite3.connect(path) as destination:
            self.db.backup(destination)
        if not automatic:
            self.status.config(text=f'백업 완료: {path}')

    def restore(self):
        path = filedialog.askopenfilename(filetypes=[('데이터 백업', '*.db')])
        if not path:
            return
        try:
            with sqlite3.connect(f'file:{Path(path).as_posix()}?mode=ro', uri=True) as source:
                record = source.execute('SELECT body FROM snapshots ORDER BY id DESC LIMIT 1').fetchone()
            if not record:
                raise ValueError('저장된 내역이 없는 백업입니다.')
            state = json.loads(record[0])
            validate(state['data'])
            baseline = state.get('baseline', [])
            if not isinstance(baseline, list):
                raise ValueError('잘못된 확정 기준안입니다.')
            for row in baseline:
                if not isinstance(row, dict) or not all(k in row for k in ('employee', 'month', 'project', 'category', 'amount')) or type(row['amount']) is not int:
                    raise ValueError('잘못된 확정 기준안입니다.')
            if messagebox.askyesno('복원', '현재 내용을 백업 파일의 내용으로 교체하고 저장할까요?'):
                self.data, self.baseline = state['data'], baseline
                self.changed()
                self.save()
        except (sqlite3.Error, ValueError, KeyError, TypeError) as error:
            messagebox.showerror('복원 오류', str(error))

    def calculate(self):
        try:
            if not self.data['employees'] or not self.data['projects']:
                raise ValueError('연구원과 과제를 각각 하나 이상 입력하세요.')
            self.result = allocate(self.data)
            for name in ('summary', 'unused'):
                self.fill(name, self.result[name])
            self.fill('allocations', self.comparison())
            refund = sum(r['refund'] for r in self.result['summary'])
            overspend = sum(max(0, -r['balance']) for r in self.result['summary'])
            self.summary_label.config(text=f'예상 반납액 합계: {refund:,}원 | 현금 부족 합계: {overspend:,}원 | 추천안이며 실제 집행·현물 인정 결과가 아닙니다.')
            self.tabs.select(self.result_frame)
            self.status.config(text='계산 완료. 확정은 비교 기준안 저장이며 집행기간 고정 기능은 아직 지원하지 않습니다.')
        except (ValueError, KeyError, TypeError) as error:
            messagebox.showerror('계산 오류', str(error))

    def comparison(self):
        def key(row):
            return tuple(row[k] for k in ('employee', 'month', 'project', 'category'))
        old = {key(row): row['amount'] for row in self.baseline}
        new = {key(row): row['amount'] for row in self.result['allocations']}
        return [dict(zip(('employee', 'month', 'project', 'category'), k), amount=new.get(k, 0),
                     previous=old.get(k, 0), delta=new.get(k, 0) - old.get(k, 0)) for k in sorted(old.keys() | new.keys())]

    def confirm(self):
        if self.result is None:
            messagebox.showinfo('확정', '먼저 자동 배분을 실행하세요.')
            return
        if any(row['balance'] < 0 for row in self.result['summary']):
            messagebox.showerror('확정 불가', '현금 부족이 있는 과제가 있습니다. 예산 또는 지출을 수정하세요.')
            return
        if messagebox.askyesno('기준안 확정', '현재 추천안을 다음 계산의 비교 기준으로 저장할까요? 이전 집행액을 고정하는 기능은 아닙니다.'):
            self.baseline = self.result['allocations'].copy()
            self.save()
            self.fill('allocations', self.comparison())

    def import_baseline(self):
        path = filedialog.askopenfilename(title='기존 월별 배분 CSV 선택', filetypes=[('CSV', '*.csv')])
        if not path:
            return
        try:
            rows, seen = [], set()
            with open(path, encoding='utf-8-sig', newline='') as source:
                reader = csv.DictReader(source)
                fields = ('employee', 'month', 'project', 'category', 'amount')
                if not set(fields).issubset(reader.fieldnames or []):
                    raise ValueError('필수 열: employee, month, project, category, amount. category는 kind(현물) 또는 cash(현금)입니다.')
                for raw in reader:
                    row = {k: raw[k].strip() for k in fields}
                    row['amount'] = int(row['amount'].replace(',', ''))
                    from scheduler import months
                    months(row['month'], row['month'])
                    key = tuple(row[k] for k in fields[:-1])
                    if not row['employee'] or not row['project'] or row['category'] not in ('kind', 'cash') or row['amount'] < 0 or key in seen:
                        raise ValueError('기존안의 이름·구분·금액 또는 중복 행을 확인하세요.')
                    seen.add(key)
                    rows.append(row)
            if messagebox.askyesno('기존안 가져오기', f'{len(rows)}행으로 비교 기준안을 교체할까요?'):
                self.baseline = rows
                self.dirty = True
                if self.result is not None:
                    self.fill('allocations', self.comparison())
                self.status.config(text='기존 비교 기준안 가져오기 완료. 저장을 눌러 보관하세요.')
        except (OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
            messagebox.showerror('기존안 오류', str(error))

    def write_csv(self, path, fields, rows):
        with open(path, 'w', encoding='utf-8-sig', newline='') as output:
            writer = csv.DictWriter(output, fieldnames=[key for key, _ in fields])
            writer.writeheader()
            writer.writerows(rows)

    def template(self, category):
        path = filedialog.asksaveasfilename(defaultextension='.csv', initialfile=category + '.csv', filetypes=[('CSV', '*.csv')])
        if path:
            fields = EMPLOYEE if category == 'employees' else PROJECT
            self.write_csv(path, fields, self.data[category] or sample()[category])

    def import_csv(self, category):
        path = filedialog.askopenfilename(filetypes=[('CSV', '*.csv')])
        if not path:
            return
        try:
            fields = EMPLOYEE if category == 'employees' else PROJECT
            with open(path, encoding='utf-8-sig', newline='') as source:
                reader = csv.DictReader(source)
                if not set(k for k, _ in fields).issubset(reader.fieldnames or []):
                    raise ValueError('열 이름이 양식과 다릅니다. CSV 양식 저장 버튼으로 양식을 받으세요.')
                rows = [{k: int(row[k].replace(',', '')) if k in MONEY else row[k].strip() for k, _ in fields} for row in reader]
            candidate = json.loads(json.dumps(self.data))
            candidate[category] = rows
            validate(candidate)
            if messagebox.askyesno('가져오기', f'{len(rows)}개 항목으로 {category} 목록을 교체할까요?'):
                self.data = candidate
                self.changed()
        except (OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
            messagebox.showerror('가져오기 오류', str(error))

    def export(self):
        if self.result is None:
            messagebox.showinfo('내보내기', '먼저 자동 배분을 실행하세요.')
            return
        folder = filedialog.askdirectory(title='결과 파일을 저장할 폴더')
        if folder:
            target = Path(folder) / ('배분결과_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
            target.mkdir()
            for name, rows in [('summary', self.result['summary']), ('allocations', self.comparison()), ('unused', self.result['unused'])]:
                fields = [(key, key) for key in self.trees[name]['columns']]
                self.write_csv(target / (name + '.csv'), fields, rows)
            self.status.config(text=f'CSV 3개 저장 완료: {target}')

    def close(self):
        if self.dirty:
            answer = messagebox.askyesnocancel('종료', '변경사항을 저장할까요?')
            if answer is None:
                return
            if answer:
                self.save()
        self.db.close()
        self.destroy()


if __name__ == '__main__':
    App().mainloop()
