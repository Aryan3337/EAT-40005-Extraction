#!/usr/bin/env bash
#
# Add one person's PUBLIC ssh key to this server, safely.
#
#   ./add_ssh_key.sh 'ssh-ed25519 AAAAC3Nz... alice@laptop'
#
# Written for the handover session, where keys get added live and in a hurry.
# Everything here exists because of a way that goes wrong under time pressure:
#
#   - `>` instead of `>>` wipes the only key on the box. This only appends,
#     and takes a timestamped backup first.
#   - A malformed key line is SILENTLY IGNORED by sshd -- no error, the key
#     just never works. So the key is validated by ssh-keygen BEFORE it is
#     written, not after.
#   - Someone pastes a PRIVATE key by mistake, on a shared screen. That is
#     refused loudly, and they are told to rotate it.
#   - The file is ignored entirely if it is group- or world-readable, so the
#     mode is reset every time.
#
# This script NEVER removes a key. To revoke one, delete its line by hand and
# re-run with no argument to see the remaining fingerprints.
#
# See the "Access" section of deploy/nectar/README.md for the wider picture --
# in particular, verifying the new key from a SECOND terminal before closing
# the one you are in.

set -euo pipefail

# Overridable so the script can be tested against a scratch file.
KEYFILE="${AUTHORIZED_KEYS:-$HOME/.ssh/authorized_keys}"

say() { printf '%s\n' "$*"; }
die() { printf 'REFUSED: %s\n' "$*" >&2; exit 1; }

fingerprints() {
    if [ -s "$KEYFILE" ]; then
        ssh-keygen -l -f "$KEYFILE" 2>/dev/null || true
    fi
}

# No argument: just report who currently has access.
if [ $# -eq 0 ]; then
    say "Keys currently authorised in $KEYFILE:"
    say ""
    fingerprints | sed 's/^/  /'
    say ""
    say "Count: $(fingerprints | wc -l)"
    say ""
    say "To add one:  $0 'ssh-ed25519 AAAA... name@host'"
    exit 0
fi

[ $# -eq 1 ] || die "expected exactly one argument -- quote the whole key in single quotes."

KEY="$1"

# A private key on a shared screen is the worst outcome here, so check first.
case "$KEY" in
    *"PRIVATE KEY"*|-----BEGIN*)
        die "that is a PRIVATE key, not a public one.

Nothing has been written. Tell them to treat that key as compromised and
generate a new pair:

    ssh-keygen -t ed25519 -C \"name@swin\"

then send you the contents of the .pub file only."
        ;;
esac

# One line, no embedded newline.
case "$KEY" in
    *$'\n'*) die "the key spans multiple lines. A public key is ONE line; the paste was wrapped." ;;
esac

# Recognised key type up front, so the ssh-keygen failure below is about
# corruption rather than someone pasting a sentence.
case "$KEY" in
    ssh-ed25519\ *|ssh-rsa\ *|ecdsa-sha2-*\ *|sk-ssh-ed25519@openssh.com\ *|sk-ecdsa-sha2-*\ *) ;;
    *) die "does not start with a known key type (ssh-ed25519, ssh-rsa, ecdsa-sha2-*, or a sk-* security-key type).

What was passed began: $(printf '%.40s' "$KEY")..." ;;
esac

# The real check: ssh-keygen parses it or it is not a usable key.
SCRATCH="$(mktemp)"
trap 'rm -f "$SCRATCH"' EXIT
printf '%s\n' "$KEY" > "$SCRATCH"
if ! PARSED="$(ssh-keygen -l -f "$SCRATCH" 2>&1)"; then
    die "ssh-keygen could not read that key, so sshd would silently ignore it.

ssh-keygen said: $PARSED"
fi

KEYDIR="$(dirname "$KEYFILE")"
mkdir -p "$KEYDIR"
# Best-effort: sshd wants 700 on ~/.ssh, but a directory we cannot chmod is a
# warning, not a reason to abandon the key. (`set -e` would otherwise abort
# the whole add here.)
chmod 700 "$KEYDIR" 2>/dev/null || say "warning: could not chmod 700 $KEYDIR -- check it yourself."
touch "$KEYFILE"

# Already present? Compare by fingerprint, not by text: the same key can carry
# a different trailing comment.
NEW_FP="$(printf '%s' "$PARSED" | awk '{print $2}')"
if fingerprints | awk '{print $2}' | grep -qxF "$NEW_FP"; then
    say "Already authorised -- nothing to do."
    say "  $PARSED"
    exit 0
fi

BEFORE="$(fingerprints | wc -l)"
BACKUP="${KEYFILE}.bak-$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "$KEYFILE" "$BACKUP" 2>/dev/null || true

# Append. Leading newline guards against a file with no trailing newline,
# which would otherwise glue two keys into one unusable line.
printf '\n%s\n' "$KEY" >> "$KEYFILE"

# sshd ignores the file outright if it is group- or world-readable.
chmod 600 "$KEYFILE"
sed -i '/^$/d' "$KEYFILE"

AFTER="$(fingerprints | wc -l)"

say ""
say "Added:   $PARSED"
say "Keys:    $BEFORE -> $AFTER"
say "Backup:  $BACKUP"
say ""
say "NOW VERIFY IT, FROM THEIR MACHINE, BEFORE YOU CLOSE THIS SESSION:"
say ""
say "    ssh -i <their private key> ubuntu@136.186.108.232 'echo OK; whoami'"
say ""
say "Expect: OK / ubuntu. If it fails, this session is still open -- restore with:"
say ""
say "    cp $BACKUP $KEYFILE"
say ""
