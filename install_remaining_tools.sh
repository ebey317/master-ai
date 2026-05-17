#!/usr/bin/env bash
# One-shot installer for the last 6 tools the detector still flags.
# Sensei-side helper. Authored by Claude; user runs in own terminal.
# Run as: bash ~/scripts/install_remaining_tools.sh   (NOT under sudo)

set -uo pipefail

if [[ $EUID -eq 0 ]]; then
  echo "Run as your own user, not sudo. The script calls sudo only where needed."
  exit 1
fi

log()  { printf "\n=== %s ===\n" "$*"; }
ok()   { printf "  ok  %s\n" "$*"; }
warn() { printf "  !!  %s\n" "$*" >&2; }

# 1. bat -> batcat symlink (debian rename)
log "bat -> batcat symlink"
if command -v bat >/dev/null; then
  ok "bat already on PATH"
elif command -v batcat >/dev/null; then
  sudo ln -sf "$(command -v batcat)" /usr/local/bin/bat && ok "symlinked"
else
  warn "batcat not found; sudo apt install -y bat"
fi

# 2. VS Code (Microsoft apt repo)
log "VS Code"
if command -v code >/dev/null; then
  ok "code already present"
else
  sudo apt install -y wget gpg apt-transport-https
  wget -qO- https://packages.microsoft.com/keys/microsoft.asc \
    | gpg --dearmor \
    | sudo tee /etc/apt/keyrings/packages.microsoft.gpg >/dev/null
  echo "deb [arch=amd64,arm64,armhf signed-by=/etc/apt/keyrings/packages.microsoft.gpg] https://packages.microsoft.com/repos/code stable main" \
    | sudo tee /etc/apt/sources.list.d/vscode.list >/dev/null
  sudo apt update -qq && sudo apt install -y code && ok "code installed"
fi

# 3. glab (GitLab CLI, official installer)
log "glab"
if command -v glab >/dev/null; then
  ok "glab already present"
else
  curl -sL https://gitlab.com/gitlab-org/cli/-/raw/main/scripts/install.sh \
    | sudo bash && ok "glab installed"
fi

# 4. deno (installs to ~/.deno/bin)
log "deno"
if command -v deno >/dev/null; then
  ok "deno already present"
else
  curl -fsSL https://deno.land/install.sh | sh -s -- -y && ok "deno installed (~/.deno/bin)"
fi

# 5. bun (installs to ~/.bun/bin)
log "bun"
if command -v bun >/dev/null; then
  ok "bun already present"
else
  curl -fsSL https://bun.sh/install | bash && ok "bun installed (~/.bun/bin)"
fi

# 6. eza (modern ls — cargo install, compiles from source, slow first time)
log "eza (cargo install — compiles from source, ~5 min first time)"
if command -v eza >/dev/null; then
  ok "eza already present"
elif command -v cargo >/dev/null; then
  cargo install eza && ok "eza installed (~/.cargo/bin)"
else
  warn "cargo missing; install rust first or skip eza"
fi

# 7. mongosh — interactive ask; default NO if no TTY
log "mongosh (MongoDB shell)"
if command -v mongosh >/dev/null; then
  ok "mongosh already present"
else
  ans="N"
  if [[ -t 0 ]]; then
    read -rp "Install mongosh? You only need it if you use MongoDB. [y/N] " ans
  fi
  if [[ "$ans" =~ ^[Yy]$ ]]; then
    curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc \
      | sudo gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg
    echo "deb [signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg arch=amd64,arm64] https://repo.mongodb.org/apt/ubuntu $(lsb_release -cs)/mongodb-org/7.0 multiverse" \
      | sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list >/dev/null
    sudo apt update -qq && sudo apt install -y mongodb-mongosh && ok "mongosh installed"
  else
    ok "mongosh skipped"
  fi
fi

log "Done. Tools landed in user dirs — add to PATH in ~/.bashrc if not already:"
echo '  export PATH="$HOME/.deno/bin:$HOME/.bun/bin:$HOME/.cargo/bin:$PATH"'
echo
echo "Then run:  python3 ~/scripts/sensei_tool_detector.py"
