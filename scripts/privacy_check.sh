#!/usr/bin/env bash
# Blocks a commit or push if anything that could identify a defendant is about to leave this machine.
# Run by hand (bash scripts/privacy_check.sh) or install as a git hook (bash scripts/install_hooks.sh).
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"
fail=0
files=$(git ls-files --cached --others --exclude-standard)

say() { echo "BLOCKED: $1"; fail=1; }

echo "$files" | grep -E '^(work|tests/_work)/' >/dev/null && say "files under work/ or tests/_work/ are tracked"
echo "$files" | grep -E '(^|/)\.env' >/dev/null && say ".env file is tracked"
echo "$files" | grep -Ei 'Public EN\.csv|ovd.*\.csv$' | grep -v '^tests/fixtures/' >/dev/null && say "an OVD-Info export is tracked"
echo "$files" | grep -E 'targets\.simple\.csv$' | grep -v '^tests/fixtures/' >/dev/null && say "an OpenSanctions dump is tracked"
echo "$files" | grep -E '\.xlsx$|courtlink_report.*\.html$' >/dev/null && say "a workbook or report file is tracked"

# Case-page links and real-looking case identifiers outside the synthetic test fixtures
scan=$(echo "$files" | grep -vE '^tests/|^courts_info/' | grep -E '\.(py|md|rq|ttl|yaml|yml|html|txt|csv|json)$')
if [ -n "$scan" ]; then
  echo "$scan" | xargs grep -nE 'case_uid=[0-9a-f]{8}-' 2>/dev/null && say "a real court case-page link (case_uid=...) appears above"
  echo "$scan" | xargs grep -nE '\b[0-9]{2}(RS|OS|OV|GV)[0-9]{4}-[0-9]{2}-20[0-9]{2}-[0-9]{6}-[0-9]{2}\b' 2>/dev/null \
      | grep -v '66RS0001-01-2024-001234-56' && say "a case identifier (UID) appears above; use the synthetic example instead"
  echo "$scan" | xargs grep -nE '/Users/[A-Za-z]+/' 2>/dev/null && say "a personal file path appears above"
fi

if [ "$fail" -ne 0 ]; then echo "Privacy check failed: nothing was committed or pushed."; exit 1; fi
echo "Privacy check passed."
