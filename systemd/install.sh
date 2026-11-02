#!/usr/bin/env bash
# Retire legacy HTTP timers; scheduling now belongs to the application backend.
set -euo pipefail

units=(journal-daily journal-weekly journal-monthly)
for unit in "${units[@]}"; do
  for suffix in timer service; do
    name="${unit}.${suffix}"
    if [[ -f "${HOME}/.config/systemd/user/${name}" ]]; then
      systemctl --user disable --now "$name"
      rm "${HOME}/.config/systemd/user/${name}"
    fi
  done
done
systemctl --user daemon-reload
printf '%s\n' 'Legacy timers removed. Packaged Meditations now schedules reviews while running.'
printf '%s\n' 'For a standalone backend, opt in with JOURNAL_SCHEDULED_REVIEWS=true.'
