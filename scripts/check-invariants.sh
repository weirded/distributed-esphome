#!/usr/bin/env bash
# Grep-based invariant linter for CLAUDE.md "Enforced invariants" (D.5).
#
# This is intentionally simple — every rule is a single grep call. If a rule
# cannot be expressed as a one-liner it belongs in ruff / mypy / the TS type
# checker, not here. Each failing rule prints the offending file and line
# and the script exits non-zero so CI fails loudly.
#
# Run locally:
#   bash scripts/check-invariants.sh
#
# Wired into the ``test`` job of .github/workflows/ci.yml.

set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Ensure Homebrew tools (rg, GNU grep) are visible when the script is invoked
# from a child shell that hasn't sourced the user's interactive rc file.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# Prefer ripgrep if available (faster, recursive by default, handles
# .gitignore). Fall back to GNU grep with extended regex. Both understand
# the same POSIX ERE patterns used below.
if command -v rg >/dev/null 2>&1; then
    SEARCH() { rg --no-heading --line-number --with-filename -e "$1" "${@:2}"; }
else
    SEARCH() { grep -RnHE -e "$1" "${@:2}"; }
fi

fail_count=0
rule_count=0

# Run SEARCH, capture output, apply optional allowlist filter, store in $hits.
# Exits non-zero if no matches found; we swallow that with ``|| true`` so the
# outer check can decide whether an empty result means pass or fail.
run_search() {
    local pattern="$1"; shift
    local allow="$1"; shift
    if [[ -n "$allow" ]]; then
        SEARCH "$pattern" "$@" 2>/dev/null | grep -Ev "$allow" || true
    else
        SEARCH "$pattern" "$@" 2>/dev/null || true
    fi
}

fail() {
    local rule_id="$1"; shift
    local message="$1"; shift
    echo ""
    echo "❌ ${rule_id}: ${message}"
    printf '%s\n' "$*"
    fail_count=$((fail_count + 1))
}

# check_absent <rule_id> <description> <pattern> <allowlist|""> <path...>
# Fails if <pattern> is found in any file under <path...>, except lines
# matching the optional <allowlist> regex.
check_absent() {
    local rule_id="$1"; shift
    local description="$1"; shift
    local pattern="$1"; shift
    local allow="$1"; shift
    rule_count=$((rule_count + 1))
    local hits
    hits=$(run_search "$pattern" "$allow" "$@")
    if [[ -n "$hits" ]]; then
        fail "$rule_id" "$description" "$hits"
    fi
}

echo "▶ Checking CLAUDE.md Enforced Invariants…"

# -----------------------------------------------------------------------------
# UI invariants
# -----------------------------------------------------------------------------

# (UI-1) No fetch() outside the api/ layer. Components must never call fetch
# directly — all server calls go through api/client.ts or a sibling module
# under api/. This is what stopped the EditorModal.tsx / schema.esphome.io
# violation from sneaking back in (C.5).
check_absent "UI-1" \
    "fetch() found outside ha-addon/ui/src/api/ — route all server calls through the api/ layer" \
    'fetch\(' \
    '/src/api/|/__tests__/|\.test\.|\.spec\.' \
    ha-addon/ui/src

# (UI-2) No Tailwind @apply directives. The project uses utility classes in
# JSX exclusively; @apply fragments the styling vocabulary across CSS files.
check_absent "UI-2" \
    "@apply directive found — use Tailwind utility classes in JSX, not @apply" \
    '@apply' \
    '' \
    ha-addon/ui/src

# (UI-3) No ``any`` type introduced in new UI code. Flags ``: any`` and
# ``as any`` (with POSIX-portable negative character classes as the
# word-boundary substitute since BSD grep lacks ``\b``). Existing sanctioned
# uses can be allow-listed with an inline ``// ALLOW_ANY`` comment.
check_absent "UI-3" \
    "explicit any type in TS — use unknown or a real type (use // ALLOW_ANY to opt out)" \
    ':[[:space:]]*any([^a-zA-Z_0-9]|$)|as[[:space:]]+any([^a-zA-Z_0-9]|$)' \
    'ALLOW_ANY|\.d\.ts:' \
    ha-addon/ui/src

# (UI-4) No CSS flex on <td>. Table cells must not be flex containers — it
# breaks the table layout model. Came from a real bug.
check_absent "UI-4" \
    "flex/inline-flex on <td> — tables layout, not flex" \
    '<td[^>]*(className|class)="[^"]*(^|[[:space:]])(inline-)?flex([[:space:]]|")' \
    '' \
    ha-addon/ui/src

# -----------------------------------------------------------------------------
# Python invariants
# -----------------------------------------------------------------------------

# (PY-1) YAML parsing must go through yaml.safe_load — never regex. Hand-rolled
# regex YAML parsers broke device-name detection (#160). The known
# ``_ota_network_diagnostics`` fallback path is allow-listed: it explicitly
# tries safe_load first and only falls back to regex after catching an
# exception, which is the correct pattern.
check_absent "PY-1" \
    "YAML parsed with regex instead of yaml.safe_load" \
    '_re\.(search|match|findall)\(.*(esphome|ssid|password|wifi):' \
    '_ota_network_diagnostics|# ALLOW_REGEX_YAML' \
    ha-addon/server ha-addon/client

# (PY-2) Subprocess invocations must log. Every file that contains a
# ``subprocess.run(`` or ``subprocess.Popen(`` call must also have a
# module-level ``logger = logging.getLogger(…)``. Real subprocess logging
# of the command line is enforced by code review, but this at least catches
# a file that forgot to wire up logging entirely — which is how #176/#177/#180
# became untriageable.
rule_count=$((rule_count + 1))
subproc_files=$(SEARCH 'subprocess\.(run|Popen)\(' ha-addon/client ha-addon/server 2>/dev/null | cut -d: -f1 | sort -u || true)
missing_logger=""
for f in $subproc_files; do
    [[ -f "$f" ]] || continue
    if ! grep -q 'logger = logging.getLogger' "$f" 2>/dev/null; then
        missing_logger="${missing_logger}${f}: subprocess without module-level logger"$'\n'
    fi
done
if [[ -n "$missing_logger" ]]; then
    fail "PY-2" \
        "subprocess.run/Popen in a file without a module-level logger — command lines must be logged" \
        "$missing_logger"
fi

# (PY-3) ``esphome run`` vs ``esphome upload`` argument confusion (#177). The
# retry path in client.py MUST NOT pass --no-logs to ``esphome upload``. The
# test_run_job_ota_retry_uses_upload_without_no_logs unit test already guards
# this at runtime, but we also grep-check here so a refactor that moves the
# command construction still trips an alarm.
check_absent "PY-3" \
    "'esphome upload' invocation passes --no-logs — that flag is run-only (#177)" \
    '"upload",.*--no-logs|--no-logs.*"upload"' \
    '' \
    ha-addon/client

# (PY-4) IMAGE_VERSION bump reminder: warn (not fail) if the client Dockerfile
# or requirements.txt is newer than IMAGE_VERSION. See the dev.2 incident in
# WORKITEMS-1.3.1 — the pydantic add broke every deployed worker because
# IMAGE_VERSION wasn't bumped. This check is soft (warn-only) because file
# mtimes aren't reliable across git checkouts.
rule_count=$((rule_count + 1))
reqs_file="ha-addon/client/requirements.txt"
docker_file="ha-addon/client/Dockerfile"
image_ver_file="ha-addon/client/IMAGE_VERSION"
if [[ -f "$reqs_file" && -f "$image_ver_file" ]]; then
    if [[ "$reqs_file" -nt "$image_ver_file" || "$docker_file" -nt "$image_ver_file" ]]; then
        echo ""
        echo "⚠ PY-4 (warning, not blocking): ha-addon/client/{requirements.txt,Dockerfile} modified more recently than IMAGE_VERSION."
        echo "   Did you forget to bump ha-addon/client/IMAGE_VERSION and constants.MIN_IMAGE_VERSION?"
        echo "   See the dev.2 incident in dev-plans/WORKITEMS-1.3.1.md."
    fi
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

echo ""
if [[ $fail_count -eq 0 ]]; then
    echo "✅ All $rule_count enforced invariants pass."
    exit 0
else
    echo "💥 $fail_count of $rule_count enforced invariants failed."
    echo "   See CLAUDE.md → Enforced Invariants for the rationale behind each rule."
    exit 1
fi
