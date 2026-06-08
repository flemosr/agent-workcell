#!/bin/sh
# Shared Agent Workcell context/skill setup helpers.

set -e

WORKCELL_CONTEXT_REPO_ROOT="/opt/workcell-context"
WORKCELL_DEFAULT_CONTEXT="/opt/agent-context.md"
WORKCELL_DEFAULT_SKILLS="/opt/agent-default-skills"

wc_error() {
  echo "Error: $*" >&2
  exit 1
}

wc_is_context_repo_mounted() {
  [ -d "$WORKCELL_CONTEXT_REPO_ROOT" ]
}

wc_repo_context_path() {
  printf '%s/GLOBAL_AGENTS.md\n' "$WORKCELL_CONTEXT_REPO_ROOT"
}

wc_repo_skills_path() {
  printf '%s/skills\n' "$WORKCELL_CONTEXT_REPO_ROOT"
}

wc_require_vars() {
  for name in "$@"; do
    eval "value=\${$name:-}"
    [ -n "$value" ] || wc_error "internal error: missing $name"
  done
}

wc_prepare_context() {
  wc_require_vars WORKCELL_CONTEXT_NATIVE WORKCELL_CONTEXT_SOURCE
  repo_context="$(wc_repo_context_path)"
  mkdir -p "$(dirname "$WORKCELL_CONTEXT_NATIVE")"
  if [ -e "$WORKCELL_CONTEXT_NATIVE" ] && [ ! -L "$WORKCELL_CONTEXT_NATIVE" ]; then
    wc_error "$WORKCELL_CONTEXT_NATIVE exists and is not the expected Workcell symlink. Run the documented manual migration first."
  fi
  mkdir -p "$(dirname "$WORKCELL_CONTEXT_SOURCE")"

  if [ -e "$repo_context" ] || [ -L "$repo_context" ]; then
    [ -f "$repo_context" ] || wc_error "$repo_context exists but is not a regular file or symlink to a regular file"
    WORKCELL_EFFECTIVE_CONTEXT="$repo_context"
    WORKCELL_EFFECTIVE_CONTEXT_LOCATION="mounted repo"
  else
    if [ ! -e "$WORKCELL_CONTEXT_SOURCE" ] && [ ! -L "$WORKCELL_CONTEXT_SOURCE" ]; then
      cp "$WORKCELL_DEFAULT_CONTEXT" "$WORKCELL_CONTEXT_SOURCE"
    fi
    WORKCELL_EFFECTIVE_CONTEXT="$WORKCELL_CONTEXT_SOURCE"
    WORKCELL_EFFECTIVE_CONTEXT_LOCATION="sandbox volume"
  fi

  ln -sfnT "$WORKCELL_EFFECTIVE_CONTEXT" "$WORKCELL_CONTEXT_NATIVE"
  export WORKCELL_EFFECTIVE_CONTEXT WORKCELL_EFFECTIVE_CONTEXT_LOCATION
}

wc_chown_persisted_context() {
  [ -n "${WORKCELL_CONTEXT_SOURCE:-}" ] || return 0
  chown agent:agent "$(dirname "$WORKCELL_CONTEXT_SOURCE")" 2>/dev/null || true
  if [ -L "$WORKCELL_CONTEXT_SOURCE" ]; then
    chown -h agent:agent "$WORKCELL_CONTEXT_SOURCE" 2>/dev/null || true
  elif [ -e "$WORKCELL_CONTEXT_SOURCE" ]; then
    chown agent:agent "$WORKCELL_CONTEXT_SOURCE" 2>/dev/null || true
  fi
  if [ -L "${WORKCELL_CONTEXT_NATIVE:-}" ]; then
    chown -h agent:agent "$WORKCELL_CONTEXT_NATIVE" 2>/dev/null || true
  fi
}

wc_seed_default_skills() {
  wc_require_vars WORKCELL_SKILLS_SOURCE
  mkdir -p "$WORKCELL_SKILLS_SOURCE"
  [ -d "$WORKCELL_DEFAULT_SKILLS" ] || return 0
  for default_dir in "$WORKCELL_DEFAULT_SKILLS"/*; do
    [ -d "$default_dir" ] || continue
    [ -f "$default_dir/SKILL.md" ] || continue
    skill_name=$(basename "$default_dir")
    dest_dir="$WORKCELL_SKILLS_SOURCE/$skill_name"
    if [ ! -e "$dest_dir" ] && [ ! -L "$dest_dir" ]; then
      cp -a "$default_dir" "$dest_dir"
    fi
  done
}

wc_skill_dir_valid() {
  [ -d "$1" ] && [ -f "$1/SKILL.md" ]
}

wc_link_skills_from_source() {
  src_root="$1"
  [ -d "$src_root" ] || return 0
  for skill_dir in "$src_root"/*; do
    [ -e "$skill_dir" ] || [ -L "$skill_dir" ] || continue
    wc_skill_dir_valid "$skill_dir" || continue
    skill_name=$(basename "$skill_dir")
    [ -e "$WORKCELL_MERGED_SKILLS/$skill_name" ] || [ -L "$WORKCELL_MERGED_SKILLS/$skill_name" ] || \
      ln -s "$skill_dir" "$WORKCELL_MERGED_SKILLS/$skill_name"
  done
}

wc_prepare_skills() {
  wc_require_vars WORKCELL_SKILLS_NATIVE WORKCELL_SKILLS_SOURCE WORKCELL_MERGED_SKILLS
  mkdir -p "$(dirname "$WORKCELL_SKILLS_NATIVE")"
  if [ -e "$WORKCELL_SKILLS_NATIVE" ] && [ ! -L "$WORKCELL_SKILLS_NATIVE" ]; then
    wc_error "$WORKCELL_SKILLS_NATIVE exists and is not the expected Workcell symlink. Run the documented manual migration first."
  fi
  mkdir -p "$WORKCELL_SKILLS_SOURCE"
  wc_seed_default_skills

  rm -rf "$WORKCELL_MERGED_SKILLS"
  mkdir -p "$WORKCELL_MERGED_SKILLS"
  repo_skills="$(wc_repo_skills_path)"
  [ -d "$repo_skills" ] && wc_link_skills_from_source "$repo_skills"
  wc_link_skills_from_source "$WORKCELL_SKILLS_SOURCE"
  ln -sfnT "$WORKCELL_MERGED_SKILLS" "$WORKCELL_SKILLS_NATIVE"
}

wc_chown_persisted_skills() {
  [ -n "${WORKCELL_SKILLS_SOURCE:-}" ] || return 0
  chown -R agent:agent "$WORKCELL_SKILLS_SOURCE" 2>/dev/null || true
  chown agent:agent "$WORKCELL_MERGED_SKILLS" 2>/dev/null || true
  if [ -L "${WORKCELL_SKILLS_NATIVE:-}" ]; then
    chown -h agent:agent "$WORKCELL_SKILLS_NATIVE" 2>/dev/null || true
  fi
}

wc_prepare_all() {
  wc_prepare_context
  wc_prepare_skills
}

wc_validate_skill_name() {
  name="$1"
  [ -n "$name" ] || wc_error "skill name is required"
  case "$name" in
    */*|*..*) wc_error "invalid skill name: $name" ;;
  esac
}

wc_skill_source_dir() {
  name="$1"
  repo_skills="$(wc_repo_skills_path)"
  if [ -d "$repo_skills" ] && wc_skill_dir_valid "$repo_skills/$name"; then
    printf 'mounted repo\t%s\n' "$repo_skills/$name"
  elif wc_skill_dir_valid "$WORKCELL_SKILLS_SOURCE/$name"; then
    printf 'sandbox volume\t%s\n' "$WORKCELL_SKILLS_SOURCE/$name"
  fi
}

wc_skill_create_dir() {
  name="$1"
  if wc_is_context_repo_mounted; then
    dir="$(wc_repo_skills_path)/$name"
    location="mounted repo"
  else
    dir="$WORKCELL_SKILLS_SOURCE/$name"
    location="sandbox volume"
  fi
  mkdir -p "$dir"
  if [ ! -e "$dir/SKILL.md" ] && [ ! -L "$dir/SKILL.md" ]; then
    printf '# %s\n\n' "$name" > "$dir/SKILL.md"
  fi
  printf '%s\t%s\n' "$location" "$dir"
}

wc_skill_list() {
  wc_require_vars WORKCELL_SKILLS_SOURCE
  repo_skills="$(wc_repo_skills_path)"
  tmp_seen="/tmp/workcell-skill-seen.$$"
  : > "$tmp_seen"
  printf '%-28s  %-14s  %s\n' "NAME" "LOCATION" "PATH"
  if [ -d "$repo_skills" ]; then
    for skill_dir in "$repo_skills"/*; do
      [ -e "$skill_dir" ] || [ -L "$skill_dir" ] || continue
      wc_skill_dir_valid "$skill_dir" || continue
      name=$(basename "$skill_dir")
      printf '%-28s  %-14s  %s\n' "$name" "mounted repo" "$skill_dir"
      printf '%s\n' "$name" >> "$tmp_seen"
    done
  fi
  for skill_dir in "$WORKCELL_SKILLS_SOURCE"/*; do
    [ -e "$skill_dir" ] || [ -L "$skill_dir" ] || continue
    wc_skill_dir_valid "$skill_dir" || continue
    name=$(basename "$skill_dir")
    if grep -qxF "$name" "$tmp_seen"; then
      continue
    fi
    printf '%-28s  %-14s  %s\n' "$name" "sandbox volume" "$skill_dir"
    printf '%s\n' "$name" >> "$tmp_seen"
  done

  shadowed="/tmp/workcell-skill-shadowed.$$"
  : > "$shadowed"
  if [ -d "$repo_skills" ]; then
    for skill_dir in "$WORKCELL_SKILLS_SOURCE"/*; do
      [ -e "$skill_dir" ] || [ -L "$skill_dir" ] || continue
      wc_skill_dir_valid "$skill_dir" || continue
      name=$(basename "$skill_dir")
      if wc_skill_dir_valid "$repo_skills/$name"; then
        printf '%-28s  %-14s  %s\n' "$name" "sandbox volume" "$skill_dir" >> "$shadowed"
      fi
    done
  fi
  if [ -s "$shadowed" ]; then
    printf '\nShadowed:\n'
    printf '%-28s  %-14s  %s\n' "NAME" "LOCATION" "PATH"
    cat "$shadowed"
  fi
  rm -f "$tmp_seen" "$shadowed"
}

wc_confirm_overwrite() {
  prompt="$1"
  printf '%s [y/N] ' "$prompt"
  read ans
  case "$ans" in y|Y) return 0 ;; *) echo "Aborted."; return 1 ;; esac
}

wc_context_open() {
  wc_prepare_context
  wc_chown_persisted_context
  echo "Opening in-effect context ($WORKCELL_EFFECTIVE_CONTEXT_LOCATION): $WORKCELL_EFFECTIVE_CONTEXT"
  exec runuser -u agent -- vi "$WORKCELL_EFFECTIVE_CONTEXT"
}

wc_context_restore() {
  wc_prepare_context
  target="$WORKCELL_EFFECTIVE_CONTEXT"
  [ -L "$target" ] && wc_error "in-effect context source is a symlink: $target. Restore symlinked context files manually."
  echo "About to restore context from image default."
  echo "  Target ($WORKCELL_EFFECTIVE_CONTEXT_LOCATION): $target"
  echo "  Source: $WORKCELL_DEFAULT_CONTEXT"
  if [ "$WORKCELL_EFFECTIVE_CONTEXT_LOCATION" = "mounted repo" ]; then
    echo "Warning: this overwrites the shared mounted context repo and may affect all workspaces/harnesses using it."
  fi
  wc_confirm_overwrite "Continue?" || exit 0
  cp "$WORKCELL_DEFAULT_CONTEXT" "$target"
  wc_chown_persisted_context
  echo "Restored context: $target"
}

wc_skill_open() {
  wc_validate_skill_name "$1"
  wc_prepare_skills
  result="$(wc_skill_source_dir "$1" || true)"
  if [ -z "$result" ]; then
    result="$(wc_skill_create_dir "$1")"
  fi
  location=$(printf '%s' "$result" | cut -f1)
  dir=$(printf '%s' "$result" | cut -f2-)
  if [ "$location" = "sandbox volume" ]; then
    chown -R agent:agent "$dir" 2>/dev/null || true
  fi
  echo "Opening in-effect skill ($location): $dir/SKILL.md"
  exec runuser -u agent -- vi "$dir/SKILL.md"
}

wc_skill_restore() {
  wc_validate_skill_name "$1"
  default_dir="$WORKCELL_DEFAULT_SKILLS/$1"
  [ -d "$default_dir" ] && [ -f "$default_dir/SKILL.md" ] || wc_error "not a default skill: $1. Custom skills cannot be restored by Workcell; recover them via Git or manual edits."
  wc_prepare_skills
  result="$(wc_skill_source_dir "$1" || true)"
  if [ -z "$result" ]; then
    echo "Skill '$1' is already using the image default."
    exit 0
  fi
  location=$(printf '%s' "$result" | cut -f1)
  target_dir=$(printf '%s' "$result" | cut -f2-)
  [ -L "$target_dir" ] && wc_error "in-effect skill source is a symlink: $target_dir. Restore symlinked skills manually."
  echo "About to restore skill '$1' from image default."
  echo "  Target ($location): $target_dir"
  echo "  Source: $default_dir"
  echo "Warning: this replaces the entire target skill directory and may delete extra files."
  if [ "$location" = "mounted repo" ]; then
    echo "Warning: this overwrites the shared mounted context repo and may affect all workspaces/harnesses using it."
  fi
  wc_confirm_overwrite "Continue?" || exit 0
  rm -rf "$target_dir"
  cp -a "$default_dir" "$target_dir"
  [ "$location" = "sandbox volume" ] && chown -R agent:agent "$target_dir" 2>/dev/null || true
  echo "Restored skill: $target_dir"
}
