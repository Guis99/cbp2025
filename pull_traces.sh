#!/usr/bin/env bash
# Download and extract the CBP2025 traces (needed on a fresh workstation).
set -euo pipefail

uv venv
# shellcheck disable=SC1091
source .venv/bin/activate                 # set up venv using uv
uv pip install gdown                       # to pull from the Google Drive folder

# NOTE: `gdown --folder` writes into a directory named after the *Drive folder*,
# created in the CWD. This script assumes those archives land in ./traces/. If
# gdown reports a different output dir, move the *.tar.xz there (or set DL_DIR).
gdown --folder https://drive.google.com/drive/folders/10CL13RGDW3zn-Dx7L0ineRvl7EpRsZDW

# Extract each archive into its OWN dir. (The previous version extracted
# fp.tar.xz into all four dirs -- classic copy-paste bug.)
# compress.tar.xz and media.tar.xz are also downloaded but not needed here;
# add them to the list if you want them.
for tr_type in fp infra int web; do
    archive="./traces/${tr_type}.tar.xz"
    if [ ! -f "$archive" ]; then
        echo "WARN: $archive not found (check gdown output location)" >&2
        continue
    fi
    mkdir -p "./traces/${tr_type}"
    # Archives are flat (int_0_trace.gz at root), so -C lands them directly.
    # If yours are nested (int/int_0_trace.gz), verify with: tar -tf "$archive" | head
    tar -xf "$archive" -C "./traces/${tr_type}" &
done
wait                                       # don't exit while extractions run

echo "extraction complete:"
for tr_type in fp infra int web; do
    printf "  %-6s %s file(s)\n" "$tr_type" "$(ls "./traces/${tr_type}" 2>/dev/null | wc -l | tr -d ' ')"
done
