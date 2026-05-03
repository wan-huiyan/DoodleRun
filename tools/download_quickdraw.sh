#!/bin/bash
# Download Quick Draw simplified .ndjson for the 5 DoodleRun animals.
# Note: chicken and dinosaur are not in Quick Draw's 345 categories.
# We use 'duck' and 'dragon' as substitutes.
set -e
mkdir -p data/quickdraw
cd data/quickdraw
for word in pig cat dog dragon duck; do
  echo "downloading $word..."
  curl -sS -o "${word}.ndjson" \
    "https://storage.googleapis.com/quickdraw_dataset/full/simplified/${word}.ndjson"
done
ls -lh
