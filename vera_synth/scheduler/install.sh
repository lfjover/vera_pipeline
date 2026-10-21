#!/usr/bin/env bash
# Install the posting schedule on this Linux machine (Raspberry Pi) as systemd user timers.
#
#   vera_synth/scheduler/install.sh              every account that has a .env
#   vera_synth/scheduler/install.sh art photo    only these accounts
#   vera_synth/scheduler/install.sh --remove     stop and delete all the timers
#
# Each account gets verasynth-<name>-post.service and .timer. The timer fires every
# interval_hours (from account.json) and publishes at most one due post from the
# account's queue/. Output goes to the account's logs/post.log.
set -euo pipefail

SYNTH_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_DIR="$(dirname "$SYNTH_DIR")"
POSTER_DIR="$REPO_DIR/instagram_poster"
VENV="$POSTER_DIR/.venv"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

if [[ "${1:-}" == "--remove" ]]; then
    for timer in "$UNIT_DIR"/verasynth-*-post.timer; do
        [[ -e "$timer" ]] || continue
        unit="$(basename "$timer")"
        systemctl --user disable --now "$unit" || true
        rm -f "$timer" "${timer%.timer}.service"
        echo "removed ${unit%.timer}"
    done
    systemctl --user daemon-reload
    exit 0
fi

if [[ $# -gt 0 ]]; then
    accounts=()
    for name in "$@"; do accounts+=("$SYNTH_DIR/vera_synth_${name#vera_synth_}"); done
else
    accounts=("$SYNTH_DIR"/vera_synth_*/)
fi

if [[ ! -x "$VENV/bin/python" ]]; then
    echo "creating $VENV"
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet -r "$POSTER_DIR/requirements.txt"

mkdir -p "$UNIT_DIR"
installed=0
for dir in "${accounts[@]}"; do
    dir="${dir%/}"
    account="$(basename "$dir")"
    short="${account#vera_synth_}"
    if [[ ! -f "$dir/account.json" ]]; then
        echo "skip $account: no account.json" >&2
        continue
    fi
    if [[ ! -f "$dir/.env" ]]; then
        echo "skip $account: no .env (copy it from the Mac, it is not in git)" >&2
        continue
    fi
    hours="$(python3 -c 'import json,sys; print(int(json.load(open(sys.argv[1])).get("interval_hours", 1)))' "$dir/account.json")"
    mkdir -p "$dir/logs"

    cat > "$UNIT_DIR/verasynth-$short-post.service" <<EOF
[Unit]
Description=Publish the next due $account post
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$POSTER_DIR
ExecStart=$VENV/bin/python -m igpost --env-file $dir/.env run-queue --queue-dir $dir/queue --max 1
StandardOutput=append:$dir/logs/post.log
StandardError=append:$dir/logs/post.log
EOF

    cat > "$UNIT_DIR/verasynth-$short-post.timer" <<EOF
[Unit]
Description=Publish one $account post every $hours hour(s)

[Timer]
OnCalendar=*-*-* 00/$hours:00:00
Persistent=true
RandomizedDelaySec=2min

[Install]
WantedBy=timers.target
EOF

    echo "installed verasynth-$short-post (every $hours h)"
    installed=$((installed + 1))
done

systemctl --user daemon-reload
for timer in "$UNIT_DIR"/verasynth-*-post.timer; do
    if [[ -e "$timer" ]]; then systemctl --user enable --now "$(basename "$timer")"; fi
done

# Keep the user's timers running after logout and across reboots.
if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]]; then
    loginctl enable-linger "$USER" || echo "run: sudo loginctl enable-linger $USER" >&2
fi

if [[ $installed -gt 0 ]]; then systemctl --user list-timers 'verasynth-*'; fi
