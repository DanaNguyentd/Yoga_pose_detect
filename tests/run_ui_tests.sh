#!/bin/sh
# Runs the interface tests. They load the real web/index.html and web/app.js in
# a headless DOM and drive the controls, with Python replaced by stubs.
#
#   npm install jsdom      (once)
#   sh tests/run_ui_tests.sh

set -e
cd "$(dirname "$0")/.."

if ! node -e "require('jsdom')" 2>/dev/null; then
  echo "jsdom is not installed. Run: npm install jsdom"
  exit 1
fi

failed=0
for suite in tests/test_ui.js tests/test_log.js tests/test_range.js tests/test_position.js; do
  printf '%-24s' "$(basename "$suite")"
  if node "$suite" > /tmp/ui_test_out 2>&1; then
    echo "$(tail -1 /tmp/ui_test_out)"
  else
    echo "FAILED"
    cat /tmp/ui_test_out
    failed=1
  fi
done
exit $failed
