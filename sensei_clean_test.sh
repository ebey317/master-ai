#!/usr/bin/env bash
# Sensei Clean — interactive standalone test runner.
# Launched by ~/Desktop/SenseiClean.desktop (and runnable directly).
#
# Walks the user through scan -> review -> apply -> exit. Undo is shown
# as a separate command they can run later. Never moves files unless the
# user types y at the apply prompt.

set -uo pipefail

cd "$HOME"

cyan="\e[36m"
yellow="\e[33m"
green="\e[32m"
dim="\e[2m"
reset="\e[0m"

banner() {
  printf "${cyan}Sensei Clean — review-first local cleanup${reset}\n"
  printf "${dim}standalone test runner${reset}\n\n"
}

banner

printf "Step 1: SCAN — inventory + duplicate detection.\n"
printf "  Reads: ~/Desktop ~/Downloads ~/Documents ~/Pictures ~/Videos\n"
printf "  Writes only to: ~/sensei_runs/<timestamp>/\n"
printf "  Hashing is on, so first run may take a minute.\n\n"
read -rp "  Enter to scan, Ctrl-C to abort: " _

# Try the PATH version first; fall back to the script if not installed.
if command -v sensei-clean >/dev/null 2>&1; then
  SC=sensei-clean
else
  SC="python3 $HOME/scripts/sensei_clean.py"
fi

OUT=/tmp/sensei_clean_scan.out
$SC scan --sha256 | tee "$OUT"
echo

RUN_DIR=$(grep -m1 "^  run:" "$OUT" | awk '{print $2}')
if [[ -z "${RUN_DIR}" || ! -d "${RUN_DIR}" ]]; then
  printf "${yellow}could not parse run dir from scan output. Bail.${reset}\n"
  read -rp "  Enter to close: " _
  exit 1
fi

printf "\n${cyan}Step 2: REVIEW${reset}\n"
printf "  Report: ${RUN_DIR}/reports/summary.md\n\n"
read -rp "  Open the report? [y/N]: " ans
case "${ans,,}" in
  y|yes)
    xdg-open "${RUN_DIR}/reports/summary.md" >/dev/null 2>&1 \
      || cat "${RUN_DIR}/reports/summary.md"
    echo
    ;;
esac

printf "\n${cyan}Step 3: APPLY${reset}\n"
printf "  Moves duplicates to ~/Sensei-Quarantine/duplicates/\n"
printf "  Monitored-lane (sensitive) items are skipped by default.\n\n"
read -rp "  Apply unattended-lane actions? [y/N]: " ans
case "${ans,,}" in
  y|yes)
    read -rp "  Also include monitored (sensitive) items? [y/N]: " mon
    if [[ "${mon,,}" == "y" || "${mon,,}" == "yes" ]]; then
      $SC apply "${RUN_DIR}" --yes --approve-monitored
    else
      $SC apply "${RUN_DIR}" --yes
    fi
    echo
    printf "${green}Apply complete. Journal: ${RUN_DIR}/undo.jsonl${reset}\n"
    ;;
  *)
    printf "${dim}skipped apply — nothing moved.${reset}\n"
    ;;
esac

printf "\n${cyan}Step 4: UNDO${reset}\n"
printf "  Reverse what apply did at any time with:\n"
printf "    sensei-clean undo ${RUN_DIR}\n\n"
read -rp "  Enter to close: " _
