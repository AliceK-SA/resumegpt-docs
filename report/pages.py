#!/usr/bin/env python3
"""Read actual rendered page numbers from final PDF for generator convergence."""
from __future__ import annotations
import json,re,subprocess,sys
from pathlib import Path
B=Path(__file__).resolve().parent/'build'; pdf=B/'report.pdf'
toc=json.loads((B/'toc.json').read_text(encoding='utf-8'))
pages_raw=subprocess.check_output(['pdfinfo',str(pdf)],text=True)
page_count=int(re.search(r'^Pages:\s+(\d+)',pages_raw,re.M).group(1))
def normalized(x):return re.sub(r'\s+',' ',x).strip().upper()
extracted={}
for page in range(3,page_count+1):
    output=subprocess.check_output(['pdftotext','-layout','-f',str(page),'-l',str(page),str(pdf),'-'],text=True)
    lines=[normalized(x) for x in output.splitlines() if x.strip()]
    extracted[page]=lines
found={}; missing=[]
for title,_ in toc:
    label=normalized(title)
    # Exact heading, not references in running text or TOC.
    matching=[page for page,lines in extracted.items() if page>=5 and any(line==label for line in lines)]
    if not matching:
        # A very long section title can wrap to the next line in PDF.
        matching=[page for page,lines in extracted.items() if page>=5 and len(label)>48 and any(line.startswith(label[:46]) for line in lines)]
    if matching:found[title]=matching[0]-1
    else:missing.append(title)
old=json.loads((B/'pages.json').read_text(encoding='utf-8')) if (B/'pages.json').exists() else {}
old_n=(B/'n').read_text().strip() if (B/'n').exists() else ''
(B/'pages.json').write_text(json.dumps(found,ensure_ascii=False,indent=2),encoding='utf-8')
(B/'n').write_text(str(page_count-1))
print('leaves',page_count-1,'toc',len(found),'missing',missing)
if missing:sys.exit('Cannot locate headings. Render/TOC mismatch: '+', '.join(missing))
if old==found and old_n==str(page_count-1):print('STABLE')
