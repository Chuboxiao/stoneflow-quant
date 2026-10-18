#!/bin/bash
# Open the portable reports in the default browser; no server is required.
set -eu
REPORT_ROOT="$(cd "$(dirname "$0")" && pwd)"
open "$REPORT_ROOT/report_site/index.html"
