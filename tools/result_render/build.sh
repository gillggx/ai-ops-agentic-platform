#!/usr/bin/env bash
# 打包 headless chart bundle（改 charts/ 或 headless.ts 後重跑，bundle.js 進 repo）
set -euo pipefail
cd "$(dirname "$0")"
npx --yes esbuild@0.21.5 entry.ts --bundle --format=iife --minify \
  --outfile=bundle.js --loader:.tsx=tsx \
  --alias:@=../../aiops-app/src
echo "bundle.js: $(wc -c < bundle.js) bytes"
