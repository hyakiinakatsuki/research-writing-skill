#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: bash paper_snapshot.sh <create|list|restore> <paper_dir> [snapshot_name]"
}

cmd="${1:-}"
paper_dir="${2:-}"
snapshot_name="${3:-}"

if [[ -z "$cmd" || -z "$paper_dir" ]]; then
  usage
  exit 1
fi
if [[ ! -d "$paper_dir" ]]; then
  echo "Paper directory not found: $paper_dir" >&2
  exit 1
fi
paper_dir="$(cd "$paper_dir" && pwd)"

case "$snapshot_name" in
  *..*|*/*|*" "*)
    echo "Invalid snapshot name: $snapshot_name" >&2
    exit 1
    ;;
esac

paper_base="$(basename "$paper_dir")"
snap_root="$(cd "$paper_dir/.." && pwd)/.paper-snapshots/$paper_base"
mkdir -p "$snap_root"

case "$cmd" in
  create)
    if [[ -z "$snapshot_name" ]]; then
      snapshot_name="$(date +%Y%m%d-%H%M%S)"
    fi
    dest="$snap_root/$snapshot_name"
    if [[ -e "$dest" ]]; then
      echo "Snapshot already exists: $dest" >&2
      exit 1
    fi
    mkdir -p "$dest"
    for item in full-paper.md main.tex main.pdf references.bib chapters plan tables figures; do
      if [[ -e "$paper_dir/$item" ]]; then
        cp -R "$paper_dir/$item" "$dest/"
      fi
    done
    find "$dest" -type f ! -name SNAPSHOT.sha256 -print0 | sort -z | xargs -0 shasum -a 256 > "$dest/SNAPSHOT.sha256"
    echo "$snapshot_name"
    ;;
  list)
    find "$snap_root" -mindepth 1 -maxdepth 1 -type d -print | sort
    ;;
  restore)
    if [[ -z "$snapshot_name" ]]; then
      echo "snapshot_name is required for restore" >&2
      usage
      exit 1
    fi
    src="$snap_root/$snapshot_name"
    if [[ ! -d "$src" ]]; then
      echo "Snapshot not found: $src" >&2
      exit 1
    fi
    if [[ ! -f "$src/SNAPSHOT.sha256" ]]; then
      echo "Snapshot hash manifest missing: $src/SNAPSHOT.sha256" >&2
      exit 1
    fi
    (cd "$src" && shasum -a 256 -c SNAPSHOT.sha256 >/dev/null)
    for item in full-paper.md main.tex main.pdf references.bib chapters plan tables figures; do
      rm -rf "$paper_dir/$item"
      if [[ -e "$src/$item" ]]; then
        cp -R "$src/$item" "$paper_dir/"
      fi
    done
    echo "restored $snapshot_name"
    ;;
  *)
    usage
    exit 1
    ;;
esac
