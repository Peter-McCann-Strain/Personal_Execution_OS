#!/bin/sh
set -eu

docs_mermaid_tmp=$(mktemp -d "${TMPDIR:-/tmp}/peos-mermaid.XXXXXX")

cleanup() {
  case "$docs_mermaid_tmp" in
    */peos-mermaid.*) rm -r -- "$docs_mermaid_tmp" ;;
    *) echo "Refusing to remove unexpected path: $docs_mermaid_tmp" >&2 ;;
  esac
}
trap cleanup EXIT HUP INT TERM

find_chromium() {
  for executable in \
    google-chrome-stable \
    google-chrome \
    chromium \
    chromium-browser; do
    if command -v "$executable" >/dev/null 2>&1; then
      command -v "$executable"
      return 0
    fi
  done

  for executable in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Chromium.app/Contents/MacOS/Chromium"; do
    if [ -x "$executable" ]; then
      printf '%s\n' "$executable"
      return 0
    fi
  done

  for cache_root in \
    "${PLAYWRIGHT_BROWSERS_PATH:-}" \
    "${HOME:-}/Library/Caches/ms-playwright" \
    "${HOME:-}/.cache/ms-playwright"; do
    if [ -z "$cache_root" ] || [ ! -d "$cache_root" ]; then
      continue
    fi

    executable=$(
      find "$cache_root" -type f \
        \( -name chrome-headless-shell -o -name chrome -o -name Chromium \) \
        2>/dev/null |
        sort |
        tail -n 1
    )
    if [ -n "$executable" ] && [ -x "$executable" ]; then
      printf '%s\n' "$executable"
      return 0
    fi
  done

  return 1
}

if [ -z "${PUPPETEER_EXECUTABLE_PATH:-}" ]; then
  if docs_chromium=$(find_chromium); then
    PUPPETEER_EXECUTABLE_PATH=$docs_chromium
    export PUPPETEER_EXECUTABLE_PATH
  fi
fi

docs_mermaid_files=$(
  git ls-files --cached --others --exclude-standard -- '*.md' |
    while IFS= read -r source; do
      if grep -q '^```mermaid[[:space:]]*$' "$source"; then
        printf '%s\n' "$source"
      fi
    done
)

if [ -z "$docs_mermaid_files" ]; then
  echo "No Mermaid diagrams found." >&2
  exit 1
fi

printf '%s\n' "$docs_mermaid_files" |
  while IFS= read -r source; do
    output_name=$(printf '%s' "$source" | tr '/ ' '__')
    if ! npx --yes @mermaid-js/mermaid-cli@11.16.0 \
      -i "$source" -o "$docs_mermaid_tmp/$output_name"; then
      echo "Mermaid rendering needs Chrome or Chromium." >&2
      echo "Install it with: npx playwright install chromium" >&2
      exit 1
    fi
  done

echo "Mermaid render check passed."
