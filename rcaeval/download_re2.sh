#!/usr/bin/env bash
# Download RCAEval RE2 systems from the official Zenodo record (14590730),
# the same URLs RCAEval.utility.download_re2{ob,ss,tt}_dataset() uses
# (checked against github.com/phamquiluan/RCAEval, RCAEval/utility/__init__.py).
# No RCAEval install needed. The whole RE2 archive is ~4.2 GB per the README.
#   rcaeval/download_re2.sh            # RE2-OB only (development set)
#   rcaeval/download_re2.sh OB TT SS   # all three
# Output: data/RE2/RE2-<SYS>/  (+ data/RE2/SHA256SUMS of the zips)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/data/RE2"; mkdir -p "$DEST"
SYSTEMS=("$@"); [ ${#SYSTEMS[@]} -eq 0 ] && SYSTEMS=(OB)
for s in "${SYSTEMS[@]}"; do
  case "$s" in OB|SS|TT) ;; *) echo "unknown system $s (OB|SS|TT)" >&2; exit 1 ;; esac
  name="RE2-$s"
  if [ -d "$DEST/$name" ]; then echo "$name already extracted"; continue; fi
  zip="$DEST/$name.zip"
  curl -fL --retry 5 -C - -o "$zip" "https://zenodo.org/records/14590730/files/$name.zip?download=1"
  (cd "$DEST" && sha256sum "$name.zip" >> SHA256SUMS)
  python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$zip" "$DEST"
  rm -f "$zip"
  echo "extracted $name -> $DEST"
done
echo "Next: python3 rcaeval/inventory_re2.py data/RE2"
