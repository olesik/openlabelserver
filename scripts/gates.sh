#!/usr/bin/env bash
# Shared status handling for the scripts/ gates.
#
# A gate whose tool is missing reports it and exits with GATE_SKIPPED instead of
# succeeding, so no caller can mistake "nothing was checked" for a pass. A caller
# that runs several gates collects that status and names the gates that never ran.

# Exit status meaning "the tool this gate needs is not installed".
GATE_SKIPPED=77

# gate_skip <tool> <subject>: report a missing tool and exit GATE_SKIPPED.
gate_skip() {
  local tool="$1"
  local subject="$2"
  echo "SKIPPED gate: ${tool} is not installed; ${subject} not checked." >&2
  exit "${GATE_SKIPPED}"
}

# gate_require <tool> <subject>: return when the tool is on PATH, else gate_skip.
gate_require() {
  command -v "$1" >/dev/null 2>&1 || gate_skip "$1" "$2"
}
