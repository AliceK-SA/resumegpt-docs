#!/usr/bin/env bash
# Stable DOCX/PDF layout with matching page count and TOC in LibreOffice.
set -euo pipefail
cd "$(dirname "$0")/.."
SOFFICE="${SOFFICE:-soffice}"
mkdir -p report/build
python3 scripts/render_diagrams.py
python3 report/extract.py
previous=''
for round in 1 2 3 4 5 6; do
  node report/report.js "$(cat report/build/n 2>/dev/null || echo 20)"
  (cd report/build && "$SOFFICE" -env:UserInstallation="file:///tmp/resumegpt-lo-$PPID" --headless --convert-to pdf --outdir . report.docx >/dev/null)
  python3 report/pages.py
  state="$(sha256sum report/build/pages.json report/build/n | sha256sum | cut -c 1-64)"
  if [[ "$previous" = "$state" ]]; then
    echo "Report pagination stable after pass $round: $(cat report/build/n) leaves"
    exit 0
  fi
  previous="$state"
done
echo 'ERROR: pagination did not converge; check Word/LibreOffice layout' >&2
exit 1
