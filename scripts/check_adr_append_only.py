#!/usr/bin/env python3
"""Checks accepted ADRs against Git base. BASE_SHA must be supplied in CI."""
from __future__ import annotations
import os,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
BASE_SHA=os.environ.get('BASE_SHA','').strip()
if not BASE_SHA or re.fullmatch(r'0+',BASE_SHA):
    print('ADR baseline unavailable: structural checks only (Git diff check requires BASE_SHA)')
new_files=sorted((ROOT/'docs/adr').glob('[0-9][0-9][0-9][0-9]-*.md'))
errors=[]
rx_status=re.compile(r'^- \*\*Статус:\*\* ')
rx_replaces=re.compile(r'^- \*\*Заменяет:\*\* ')
def normalized(text):
    return '\n'.join(line for line in text.splitlines() if not rx_status.match(line) and not rx_replaces.match(line))
for f in new_files:
    now=f.read_text(encoding='utf-8')
    path=f.relative_to(ROOT).as_posix()
    if '**Статус:**' not in now or '**Дата:**' not in now: errors.append(f'{path}: missing status/date')
    if not BASE_SHA or re.fullmatch(r'0+',BASE_SHA):continue
    old=subprocess.run(['git','show',f'{BASE_SHA}:{path}'],cwd=ROOT,text=True,capture_output=True)
    if old.returncode!=0:
        if '**Участники:**' not in now:errors.append(f'{path}: new ADR missing participants')
        continue
    if ('**Статус:** Принято' in old.stdout or '**Статус:** Заменено' in old.stdout) and normalized(old.stdout)!=normalized(now):
        errors.append(f'{path}: accepted ADR changed outside Status/Replaces')
for e in errors:print('ERROR:',e)
print('ADR append-only check:',len(errors),'problem(s)',('against '+BASE_SHA[:12]) if BASE_SHA else '(local structural-only)')
sys.exit(bool(errors))
