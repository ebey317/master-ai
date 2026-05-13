#!/bin/bash
# jobseeker.sh — Personal job seeker wizard
# Built for Elijah W. Wilkins Sr. — Indianapolis, IN
#
# Usage:
#   bash jobseeker.sh                # Wizard mode (new application)
#   bash jobseeker.sh --profile      # Edit yearly profile
#   bash jobseeker.sh --help         # Show usage
#
# The wizard knows who you are (from profile.yaml) and only asks the
# 4-5 things that change per application. It produces:
#   1. A tailored portfolio PDF (~/jobseeker/packets/)
#   2. A filled application answer sheet for copy-paste into online forms
#      (~/jobseeker/apps/)

# ============================================================
# Configuration
# ============================================================
JOBSEEKER_DIR="$HOME/jobseeker"
PROFILE_FILE="$JOBSEEKER_DIR/profile.yaml"
POSTINGS_DIR="$JOBSEEKER_DIR/postings"
PACKETS_DIR="$JOBSEEKER_DIR/packets"
APPS_DIR="$JOBSEEKER_DIR/apps"
PORTFOLIO_SCRIPT="$HOME/scripts/portfolio.sh"
OLLAMA_MODEL="master-ai"
OLLAMA_URL="http://localhost:11434/api/generate"

# Light-terminal colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
NC='\033[0m'

green_check() { printf "${GREEN}\xe2\x9c\x93${NC} %s\n" "$1"; }
red_x()       { printf "${RED}\xe2\x9c\x97${NC} %s\n" "$1"; }
yellow_warn() { printf "${YELLOW}!${NC} %s\n" "$1"; }
blue_info()   { printf "${BLUE}\xc2\xbb${NC} %s\n" "$1"; }
header()      { printf "${BOLD}%s${NC}\n" "$1"; }

# ============================================================
# Dependency check
# ============================================================
check_deps() {
    local missing=()
    command -v python3 >/dev/null 2>&1 || missing+=("python3")
    command -v jq      >/dev/null 2>&1 || missing+=("jq")
    command -v curl    >/dev/null 2>&1 || missing+=("curl")
    if ! python3 -c "import yaml" 2>/dev/null; then
        missing+=("python3-yaml")
    fi
    if [ ${#missing[@]} -gt 0 ]; then
        red_x "Missing: ${missing[*]}"
        echo "Install with: sudo apt install ${missing[*]}"
        exit 1
    fi
}

# ============================================================
# YAML helpers (Python inline)
# ============================================================
yaml_get() {
    # Usage: yaml_get <yaml_file> <dotted.path>
    python3 - "$1" "$2" <<'PY'
import sys, yaml
path = sys.argv[2].split(".")
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f) or {}
for key in path:
    if isinstance(data, list):
        try:
            data = data[int(key)]
        except (ValueError, IndexError):
            print(""); sys.exit(0)
    elif isinstance(data, dict):
        data = data.get(key, "")
    else:
        print(""); sys.exit(0)
if isinstance(data, (list, dict)):
    print(yaml.safe_dump(data, default_flow_style=False).strip())
elif data is None:
    print("")
elif isinstance(data, bool):
    print("yes" if data else "no")
else:
    print(data)
PY
}

profile_loaded() {
    [ -f "$PROFILE_FILE" ]
}

# ============================================================
# Profile YAML syntax validator (friendly errors, no traceback)
# ============================================================
validate_profile_syntax() {
    local err
    if ! err=$(python3 - "$PROFILE_FILE" 2>&1 <<'PY'
import sys, yaml
try:
    yaml.safe_load(open(sys.argv[1]))
except yaml.YAMLError as e:
    m = getattr(e, "problem_mark", None)
    if m:
        print(f"line {m.line+1}, column {m.column+1}: {e.problem}")
    else:
        print(str(e))
    sys.exit(1)
PY
    ); then
        red_x "Profile YAML is broken:"
        echo "    $err"
        echo
        echo "Most common cause: pasting a value next to existing quotes."
        echo "    WRONG:  phone: \"\"317-555-0100"
        echo "    RIGHT:  phone: \"317-555-0100\""
        echo
        echo "Fix it with:  bash $0 --profile"
        echo "Then save and re-run the wizard."
        exit 1
    fi
}

# ============================================================
# Profile sanity check (warn on FILL gaps)
# ============================================================
profile_health() {
    local critical=("identity.phone" "address.street" "address.zip"
                    "salary.hourly_target")
    local field val gaps=()
    for field in "${critical[@]}"; do
        val=$(yaml_get "$PROFILE_FILE" "$field")
        [ -z "$val" ] && gaps+=("$field")
    done

    if [ ${#gaps[@]} -gt 0 ]; then
        yellow_warn "Profile has ${#gaps[@]} blank field(s): ${gaps[*]}"
        echo "    These will appear blank in your application answer sheet."
        echo "    Fill them now? (y/N)"
        read -r ans
        if [[ "$ans" =~ ^[Yy] ]]; then
            edit_profile
            return
        fi
        echo "    Continuing — fill them later with: bash $0 --profile"
        echo
    fi
}

# ============================================================
# Profile editor
# ============================================================
edit_profile() {
    if [ ! -f "$PROFILE_FILE" ]; then
        red_x "No profile at $PROFILE_FILE"
        exit 1
    fi
    local editor="${EDITOR:-nano}"
    blue_info "Opening profile in $editor..."
    "$editor" "$PROFILE_FILE"
    green_check "Profile saved"
}

# ============================================================
# Lane picker (match job title against profile.lane_keywords)
# ============================================================
pick_lane() {
    local title_lower
    title_lower=$(printf "%s" "$1" | tr '[:upper:]' '[:lower:]')
    python3 - "$PROFILE_FILE" "$title_lower" <<'PY'
import sys, yaml
profile = yaml.safe_load(open(sys.argv[1])) or {}
title = sys.argv[2]
lanes = profile.get("lane_keywords", {}) or {}
best, best_hits = "general_pivot", 0
for lane, keywords in lanes.items():
    if not keywords: continue
    hits = sum(1 for k in keywords if k.lower() in title)
    if hits > best_hits:
        best, best_hits = lane, hits
print(best)
PY
}

# ============================================================
# Resume picker for lane (read from portfolio.sh lane configs)
# ============================================================
resume_for_lane() {
    local lane="$1"
    local conf="$HOME/portfolio/lanes/${lane}.conf"
    if [ -f "$conf" ]; then
        # shellcheck disable=SC1090
        ( source "$conf" >/dev/null 2>&1; printf "%s\n" "$RESUME" )
    else
        echo "resume_general.pdf"
    fi
}

# ============================================================
# Cover paragraph generator (master-ai via ollama API)
# ============================================================
generate_cover() {
    local employer="$1"
    local title="$2"
    local posting="$3"
    local profile_summary
    profile_summary=$(python3 - "$PROFILE_FILE" <<'PY'
import yaml
p = yaml.safe_load(open(__import__("sys").argv[1])) or {}
ident = p.get("identity", {})
trades = p.get("trades", {})
certs = [c.get("name") for c in (p.get("certifications") or []) if c.get("name")]
edu = p.get("education") or []
years = trades.get("years_experience", "")
print(f"Name: {ident.get('full_name','')}")
print(f"Location: {p.get('address',{}).get('city','')}, {p.get('address',{}).get('state','')}")
print(f"Primary trade: {trades.get('primary','')} ({years} years)")
print(f"Secondary trades: {', '.join(trades.get('secondary', []) or [])}")
print(f"Certifications: {', '.join(certs)}")
if edu:
    e = edu[0]
    print(f"Education: {e.get('hours','')} hours {e.get('program','')} at {e.get('school','')}")
PY
)

    local prompt
    prompt=$(cat <<EOF
You are writing a 3-4 sentence cover-letter paragraph for a working-tradesman applying to a job. Plain, direct, no fluff. No "I am writing to apply for..." openers. Speak in first person. Do NOT invent skills or experience not in the profile below.

APPLICANT PROFILE:
${profile_summary}

EMPLOYER: ${employer}
JOB TITLE: ${title}

JOB POSTING (may be empty):
${posting:-[no posting provided]}

Write the cover paragraph. Reference the employer by name. Tie 1-2 specific things from the applicant profile to what the posting (or job title) is asking for. Stop after 4 sentences. No sign-off, no "sincerely". Output only the paragraph.
EOF
)

    local response
    response=$(curl -s "$OLLAMA_URL" -d "$(jq -n --arg m "$OLLAMA_MODEL" --arg p "$prompt" \
        '{model:$m, prompt:$p, stream:false}')" 2>/dev/null)

    if [ -z "$response" ]; then
        echo ""
        return 1
    fi

    printf "%s" "$response" | jq -r '.response // empty' 2>/dev/null | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

# ============================================================
# Wizard
# ============================================================
ask() {
    local prompt="$1"
    local default="$2"
    local var
    # Prompt goes to stderr so $(ask ...) captures only the answer
    if [ -n "$default" ]; then
        printf "%s [%s]: " "$prompt" "$default" >&2
    else
        printf "%s: " "$prompt" >&2
    fi
    read -r var </dev/tty 2>/dev/null || read -r var
    [ -z "$var" ] && var="$default"
    printf "%s" "$var"
}

wizard() {
    header "=== Job Seeker — New Application ==="
    echo

    local applicant_name
    applicant_name=$(yaml_get "$PROFILE_FILE" "identity.full_name")
    blue_info "Applicant: $applicant_name (from profile)"
    echo

    profile_health

    # Job-specific intake
    local employer title city_state distance posting_input start_date
    employer=$(ask "Company or agency name (employer / staffing co / job source)" "")
    [ -z "$employer" ] && { red_x "Company or agency name required"; exit 1; }

    title=$(ask "Job title (as posted)" "")
    [ -z "$title" ] && { red_x "Job title required"; exit 1; }

    city_state=$(ask "Job city, ST (or full address)" "Indianapolis, IN")
    distance=$(ask "Distance from home in miles (blank to skip)" "")
    start_date=$(ask "Preferred start date" "immediate")

    echo
    echo "Job posting source — choose one:"
    echo "  1) Paste posting text now (end with a single line 'EOF')"
    echo "  2) Path to a .txt file"
    echo "  3) Skip (cover will use job title only)"
    local posting=""
    posting_input=$(ask "Choice" "3")
    case "$posting_input" in
        1)
            blue_info "Paste posting. End with a line containing only: EOF"
            local line
            while IFS= read -r line; do
                [ "$line" = "EOF" ] && break
                posting+="$line"$'\n'
            done
            ;;
        2)
            local pathin
            pathin=$(ask "File path" "")
            pathin="${pathin/#\~/$HOME}"
            if [ -f "$pathin" ]; then
                posting=$(cat "$pathin")
            else
                yellow_warn "File not found — skipping posting"
            fi
            ;;
        *) ;;
    esac

    # Save posting if any
    local date_stamp employer_safe posting_path=""
    date_stamp=$(date +%Y-%m-%d)
    employer_safe=$(printf "%s" "$employer" | tr '[:upper:]' '[:lower:]' \
        | tr ' ' '_' | tr -cd 'a-z0-9_')
    if [ -n "$posting" ]; then
        posting_path="$POSTINGS_DIR/${date_stamp}_${employer_safe}.txt"
        printf "%s" "$posting" > "$posting_path"
        green_check "Posting saved: $posting_path"
    fi

    # Derive lane + resume
    echo
    blue_info "Deriving lane from job title..."
    local lane resume
    lane=$(pick_lane "$title")
    resume=$(resume_for_lane "$lane")
    green_check "Lane: $lane (resume: $resume)"

    # Confirm or override lane
    echo
    echo "Lane override? Available: hvac_service, hvac_refrig, hvac_install,"
    echo "  facility_maintenance, industrial_maintenance, general_pivot"
    local lane_override
    lane_override=$(ask "Lane (Enter to keep $lane)" "$lane")
    if [ "$lane_override" != "$lane" ]; then
        lane="$lane_override"
        resume=$(resume_for_lane "$lane")
        green_check "Switched to lane: $lane"
    fi

    # Generate cover paragraph
    echo
    blue_info "Generating tailored cover paragraph (master-ai)..."
    local cover
    cover=$(generate_cover "$employer" "$title" "$posting")
    if [ -z "$cover" ]; then
        yellow_warn "master-ai unreachable or returned empty — using lane default"
        cover=$(yaml_get "$HOME/portfolio/lanes/${lane}.conf" "" 2>/dev/null)
        cover=""
    else
        green_check "Cover paragraph drafted"
    fi

    # Show review
    echo
    header "=== Review ==="
    echo "Company:     $employer"
    echo "Job title:   $title"
    echo "Location:    $city_state"
    [ -n "$distance" ] && echo "Distance:    $distance miles"
    echo "Start date:  $start_date"
    echo "Lane:        $lane"
    echo "Resume:      $resume"
    echo
    echo "Cover paragraph:"
    if [ -n "$cover" ]; then
        printf "  %s\n" "$cover" | fold -s -w 76 | sed 's/^/  /'
    else
        echo "  (using lane default — no master-ai response)"
    fi
    echo
    echo "Choices:"
    echo "  1) Build packet + answer sheet"
    echo "  2) Edit cover paragraph in \$EDITOR"
    echo "  3) Cancel"
    local choice
    choice=$(ask "Choice" "1")
    case "$choice" in
        2)
            local tmpf
            tmpf=$(mktemp -t cover.XXXXXX.txt)
            printf "%s" "$cover" > "$tmpf"
            "${EDITOR:-nano}" "$tmpf"
            cover=$(cat "$tmpf")
            rm -f "$tmpf"
            green_check "Cover updated"
            ;;
        3) echo "Cancelled."; exit 0 ;;
    esac

    # Build packet via portfolio.sh with cover override
    echo
    blue_info "Building portfolio packet..."
    local packet_output
    if [ -n "$cover" ]; then
        packet_output=$(JOBSEEKER_COVER_OVERRIDE="$cover" \
            bash "$PORTFOLIO_SCRIPT" "$employer" "$lane" 2>&1)
    else
        packet_output=$(bash "$PORTFOLIO_SCRIPT" "$employer" "$lane" 2>&1)
    fi
    echo "$packet_output" | grep -E "^(\[|\xe2|\xc2|✓|✗|»|!|Output)" || echo "$packet_output"

    # Move packet from ~/portfolio/output/ to ~/jobseeker/packets/
    local src_packet="$HOME/portfolio/output/${date_stamp}_${employer_safe}_${lane}.pdf"
    local dst_packet="$PACKETS_DIR/${date_stamp}_${employer_safe}_${lane}.pdf"
    if [ -f "$src_packet" ]; then
        mv "$src_packet" "$dst_packet"
        green_check "Packet: $dst_packet"
    fi

    # Generate application answer sheet
    local apps_path="$APPS_DIR/${date_stamp}_${employer_safe}.md"
    write_answer_sheet "$apps_path" "$employer" "$title" "$city_state" \
        "$distance" "$start_date" "$lane" "$cover" "$posting_path"
    green_check "Answer sheet: $apps_path"

    echo
    header "=== Done ==="
    echo "Packet:       $dst_packet"
    echo "Answer sheet: $apps_path"
    [ -n "$posting_path" ] && echo "Posting:      $posting_path"
    echo
    echo "The answer sheet is for copy-paste into online application forms."
    echo "Open it with:  xdg-open '$apps_path'"

    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$dst_packet" >/dev/null 2>&1 &
    fi
}

# ============================================================
# Application answer sheet generator
# ============================================================
write_answer_sheet() {
    local path="$1" employer="$2" title="$3" city_state="$4"
    local distance="$5" start_date="$6" lane="$7" cover="$8" posting_path="$9"
    local today
    today=$(date "+%B %d, %Y")

    # Pull profile values
    local p_name p_email p_phone p_street p_city p_state p_zip
    local p_transp p_dl p_commute p_citizen p_felony p_drug p_bg p_refs
    local p_salary p_hours_ot p_w2 p_1099 p_certs p_edu

    p_name=$(yaml_get   "$PROFILE_FILE" "identity.full_name")
    p_email=$(yaml_get  "$PROFILE_FILE" "identity.email")
    p_phone=$(yaml_get  "$PROFILE_FILE" "identity.phone")
    p_street=$(yaml_get "$PROFILE_FILE" "address.street")
    p_city=$(yaml_get   "$PROFILE_FILE" "address.city")
    p_state=$(yaml_get  "$PROFILE_FILE" "address.state")
    p_zip=$(yaml_get    "$PROFILE_FILE" "address.zip")
    p_transp=$(yaml_get "$PROFILE_FILE" "logistics.transportation")
    p_dl=$(yaml_get     "$PROFILE_FILE" "logistics.driver_license")
    p_commute=$(yaml_get "$PROFILE_FILE" "logistics.willing_to_commute_miles")
    p_citizen=$(yaml_get "$PROFILE_FILE" "work_authorization.us_citizen")
    p_felony=$(yaml_get  "$PROFILE_FILE" "work_authorization.felony_record")
    p_drug=$(yaml_get    "$PROFILE_FILE" "work_authorization.drug_screen_ok")
    p_bg=$(yaml_get      "$PROFILE_FILE" "work_authorization.background_check_ok")
    p_refs=$(yaml_get    "$PROFILE_FILE" "work_authorization.references_available")
    p_salary=$(yaml_get  "$PROFILE_FILE" "salary.hourly_target")
    p_w2=$(yaml_get      "$PROFILE_FILE" "salary.open_to_w2")
    p_1099=$(yaml_get    "$PROFILE_FILE" "salary.open_to_1099")
    p_hours_ot=$(yaml_get "$PROFILE_FILE" "salary.open_to_overtime")

    # Certs as one line
    p_certs=$(python3 - "$PROFILE_FILE" <<'PY'
import sys, yaml
p = yaml.safe_load(open(sys.argv[1])) or {}
parts = []
for c in (p.get("certifications") or []):
    nm = c.get("name","")
    yr = c.get("earned_year","")
    parts.append(f"{nm} ({yr})" if yr else nm)
print("; ".join(parts))
PY
)

    p_edu=$(python3 - "$PROFILE_FILE" <<'PY'
import sys, yaml
p = yaml.safe_load(open(sys.argv[1])) or {}
out = []
for e in (p.get("education") or []):
    s = e.get("school","")
    pr = e.get("program","")
    h = e.get("hours","")
    y = e.get("completion_year","")
    out.append(f"{s} — {pr}, {h} hours" + (f" ({y})" if y else ""))
print("; ".join(out))
PY
)

    cat > "$path" <<EOF
# Application — $employer

**Job:** $title
**Date:** $today
**Lane:** $lane
**Posting saved:** ${posting_path:-not provided}

---

## Personal

| Field | Answer |
|---|---|
| Full name | $p_name |
| Email | $p_email |
| Phone | ${p_phone:-_(blank — fill in profile)_} |
| Street | ${p_street:-_(blank — fill in profile)_} |
| City | $p_city |
| State | $p_state |
| ZIP | ${p_zip:-_(blank — fill in profile)_} |

## Job-specific

| Field | Answer |
|---|---|
| Company / agency | $employer |
| Position | $title |
| Job location | $city_state |
| Distance from home | ${distance:-_(not entered)_} miles |
| Start date / availability | $start_date |
| Lane | $lane |

## Work authorization

| Question | Answer |
|---|---|
| US citizen? | $p_citizen |
| Authorized to work in US? | yes |
| Felony record? | $p_felony |
| Pass drug screen? | $p_drug |
| Pass background check? | $p_bg |
| References available? | $p_refs |

## Logistics

| Question | Answer |
|---|---|
| Reliable transportation? | $p_transp |
| Driver's license? | $p_dl |
| Willing to commute (miles) | $p_commute |
| Open to overtime? | $p_hours_ot |
| W-2 OK? | $p_w2 |
| 1099 OK? | $p_1099 |
| Hourly rate target | ${p_salary:-_(blank — fill in profile)_} |

## Credentials

**Certifications:** ${p_certs:-_(none listed in profile)_}

**Education:** ${p_edu:-_(none listed in profile)_}

---

## Cover paragraph (use as cover-letter body or "Why this company?")

${cover:-_(no cover generated — see lane default)_}

---

## Tips for filling the online form

- **Copy-paste from the tables above** for standard fields.
- **Use the cover paragraph** for "tell us why you want to work here" boxes.
- **Attach the packet PDF** from \`~/jobseeker/packets/\` if the form takes a single resume upload (the packet has the cover, resume, certs, all fused).
- **If they ask "how did you hear about us?"** — answer however you actually heard.
- **Salary question** — if forced to pick a number, use your profile's hourly_target.
EOF
}

# ============================================================
# Help
# ============================================================
show_help() {
    cat <<EOF
jobseeker.sh — Personal job seeker wizard

USAGE
    bash $0                 Run the wizard for a new application
    bash $0 --profile       Edit the yearly profile (~/jobseeker/profile.yaml)
    bash $0 --help          Show this help

FILES
    ~/jobseeker/profile.yaml      Your yearly profile (who you are)
    ~/jobseeker/postings/         Saved job postings (per application)
    ~/jobseeker/packets/          Generated portfolio PDFs
    ~/jobseeker/apps/             Filled application answer sheets

CADENCE
    Profile = updated yearly or when something changes (cert renewed,
    moved, salary target shifted).
    Wizard  = run heavily during job search, dormant during a job.

SYNC
    Move ~/jobseeker/ inside your Google Drive Desktop or OneDrive folder
    (or symlink it) to auto-sync your profile + packets across devices.
EOF
}

# ============================================================
# Main
# ============================================================
main() {
    check_deps

    if [ ! -f "$PROFILE_FILE" ]; then
        red_x "No profile at $PROFILE_FILE"
        echo "    Profile should have been created during setup."
        echo "    Reinstall: copy ~/jobseeker/profile.yaml from defaults."
        exit 1
    fi
    [ ! -x "$PORTFOLIO_SCRIPT" ] && chmod +x "$PORTFOLIO_SCRIPT" 2>/dev/null

    case "${1:-}" in
        --profile) edit_profile ;;
        --help|-h) show_help ;;
        "")        validate_profile_syntax; wizard ;;
        *)         show_help; exit 1 ;;
    esac
}

main "$@"
