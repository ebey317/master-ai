#!/bin/bash
# endurance_day.sh — the rainy-day / snowy-day run.
#
# Chains benchmark_sensei.sh and competitor_benchmark.sh in endurance mode
# so the whole thing fills 8-11 hours — the "I'd do this all day before I
# put on a movie" pace. Each tool writes to its own output dir; a top-level
# day.log captures both.
#
# Usage:
#   bash ~/scripts/endurance_day.sh               # default reps (sensei 5, competitor 4)
#   bash ~/scripts/endurance_day.sh 6 5           # (sensei_reps) (competitor_reps)

set -u
SENSEI_REPS="${1:-5}"
COMP_REPS="${2:-4}"
DAY_OUT="$HOME/Desktop/master_ai_endurance_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$DAY_OUT"
DAY_LOG="$DAY_OUT/day.log"
: > "$DAY_LOG"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$DAY_LOG"; }

log "════════════════════════════════════════════════════════"
log "  MASTER AI — ENDURANCE DAY"
log "  sensei reps: $SENSEI_REPS · competitor reps: $COMP_REPS"
log "  day log:     $DAY_LOG"
log "════════════════════════════════════════════════════════"
log ""
day_start=$(date +%s)

# --- Phase 1: full benchmark_sensei.sh in endurance mode ---
log "Phase 1: benchmark_sensei.sh --reps $SENSEI_REPS --short"
phase1_start=$(date +%s)
bash "$HOME/scripts/benchmark_sensei.sh" --reps "$SENSEI_REPS" --short 2>&1 | tee -a "$DAY_LOG"
phase1_end=$(date +%s)
phase1_min=$(( (phase1_end - phase1_start) / 60 ))
log ""
log "Phase 1 complete: ${phase1_min} min"
log ""

# Brief cooldown so Ollama can shed the last model loaded into RAM before
# the competitor phase starts with fresh state.
log "Cooldown: 60s to let Ollama drop cached models..."
sleep 60

# --- Phase 2: competitor_benchmark.sh in endurance mode ---
log "Phase 2: competitor_benchmark.sh --reps $COMP_REPS"
phase2_start=$(date +%s)
bash "$HOME/scripts/competitor_benchmark.sh" --reps "$COMP_REPS" 2>&1 | tee -a "$DAY_LOG"
phase2_end=$(date +%s)
phase2_min=$(( (phase2_end - phase2_start) / 60 ))
log ""
log "Phase 2 complete: ${phase2_min} min"
log ""

day_end=$(date +%s)
day_total_min=$(( (day_end - day_start) / 60 ))
day_total_hr=$(awk -v m="$day_total_min" 'BEGIN {printf "%.1f", m/60}')

log "════════════════════════════════════════════════════════"
log "  ENDURANCE DAY COMPLETE"
log "  Total wall-clock: ${day_total_min} min (${day_total_hr} hrs)"
log "  Phase 1 (benchmark_sensei):  ${phase1_min} min"
log "  Phase 2 (competitor):        ${phase2_min} min"
log ""
log "  Outputs:"
log "    ~/Desktop/master_ai_benchmark/summary.md   (sensei endurance)"
log "    ~/Desktop/master_ai_competitor/standard.md (competitor standard)"
log "    $DAY_LOG                                    (full day log)"
log "════════════════════════════════════════════════════════"

# Voice the final verdict if TTS is up
verdict_text="Endurance day complete. Ran for ${day_total_hr} hours. Go put on a movie."
curl -sf -m 10 -X POST http://localhost:5050/speak \
    -H 'Content-Type: application/json' \
    -d "$(python3 -c "import json,sys;print(json.dumps({'text':sys.argv[1]}))" "$verdict_text")" \
    -o /dev/null 2>/dev/null && log "  (tts spoke the wrap)"
