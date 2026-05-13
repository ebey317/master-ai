#!/bin/bash
# portfolio.sh — Tailored job application portfolio assembler
# Built for Elijah W. Wilkins Sr. — Indianapolis, IN
#
# Usage:
#   bash portfolio.sh                                    # Setup mode (first run)
#   bash portfolio.sh "Employer Name" lane_name          # Build mode
#
# Example:
#   bash portfolio.sh "Tradesmen International" facility_maintenance

# ============================================================
# Configuration
# ============================================================
PORTFOLIO_DIR="$HOME/portfolio"
MASTER_DIR="$PORTFOLIO_DIR/master"
LANES_DIR="$PORTFOLIO_DIR/lanes"
OUTPUT_DIR="$PORTFOLIO_DIR/output"

# Standard filenames in master/
STD_RESUME_DETAILED="resume_detailed.pdf"
STD_RESUME_5YEAR="resume_5year.pdf"
STD_RESUME_GENERAL="resume_general.pdf"
STD_CERTS="certs_combined.pdf"
STD_OSHA_IMG="osha_fall_protection.jpg"
STD_EPA608="epa608_type2.pdf"
STD_REFERENCES="references.pdf"
STD_TOOLS="tools_owned.pdf"

# Light-terminal colors (no bright cyan/green/white)
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
NC='\033[0m'

# ============================================================
# Output helpers
# ============================================================
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
    command -v pdfunite >/dev/null 2>&1 || missing+=("poppler-utils")
    command -v ps2pdf   >/dev/null 2>&1 || missing+=("ghostscript")
    command -v groff    >/dev/null 2>&1 || missing+=("groff")

    if [ ${#missing[@]} -gt 0 ]; then
        red_x "Missing required tools: ${missing[*]}"
        echo
        echo "Install with this one command (you run sudo, not me):"
        echo
        echo "    sudo apt install ${missing[*]}"
        echo
        exit 1
    fi
}

# ============================================================
# Lane config templates
# ============================================================
write_lane() {
    local name="$1"
    local title="$2"
    local cover_line="$3"
    local resume="$4"
    local cert_order="$5"
    local conf_path="$LANES_DIR/$name.conf"

    cat > "$conf_path" <<EOF
# Lane: $name
LANE_TITLE="$title"
COVER_LINE="$cover_line"
RESUME="$resume"
CERT_ORDER="$cert_order"
EOF
    green_check "$name.conf"
}

create_lane_configs() {
    write_lane "hvac_service" \
        "HVAC Commercial Service" \
        "Commercial HVAC service tech with EPA 608 Type II, OSHA 10, and Fall Protection. Available for service routes and commercial installs." \
        "resume_detailed.pdf" \
        "epa608_type2.pdf osha_fall_protection.jpg certs_combined.pdf"

    write_lane "hvac_refrig" \
        "HVAC Commercial Refrigeration" \
        "Commercial refrigeration tech with EPA 608 Type II. Cold storage, supermarket, and food service capable." \
        "resume_5year.pdf" \
        "epa608_type2.pdf osha_fall_protection.jpg certs_combined.pdf"

    write_lane "hvac_install" \
        "HVAC New Construction Install" \
        "Commercial HVAC install crew. OSHA 10 and Fall Protection Competent. Sheet metal, equipment set, mechanical room build-out." \
        "resume_5year.pdf" \
        "osha_fall_protection.jpg epa608_type2.pdf certs_combined.pdf"

    write_lane "facility_maintenance" \
        "Facility Maintenance" \
        "Multi-trade maintenance tech with HVAC, electrical (261.5 hours Robeson coursework), and carpentry. OSHA 10, Fall Protection." \
        "resume_general.pdf" \
        "osha_fall_protection.jpg certs_combined.pdf epa608_type2.pdf"

    write_lane "industrial_maintenance" \
        "Industrial Maintenance" \
        "Industrial maintenance tech with electrical and HVAC stack. EPA 608 Type II, OSHA 10. Manufacturing-plant capable." \
        "resume_general.pdf" \
        "certs_combined.pdf epa608_type2.pdf osha_fall_protection.jpg"

    write_lane "general_pivot" \
        "General Pivot" \
        "Multi-trade technician with safety, electrical, mechanical, and carpentry credentials. Hands-on capable across industries." \
        "resume_general.pdf" \
        "certs_combined.pdf osha_fall_protection.jpg epa608_type2.pdf"
}

# ============================================================
# Setup mode
# ============================================================
find_and_copy() {
    local std_name="$1"
    local pattern="$2"
    local dest="$MASTER_DIR/$std_name"

    if [ -f "$dest" ]; then
        return 0
    fi

    local dir found
    for dir in "${SEARCH_PATHS[@]}"; do
        [ -d "$dir" ] || continue
        found=$(find "$dir" -maxdepth 2 -type f -iname "$pattern" 2>/dev/null | head -1)
        if [ -n "$found" ] && [ -f "$found" ]; then
            cp "$found" "$dest"
            return 0
        fi
    done
    return 1
}

setup_mode() {
    header "Portfolio Setup"
    echo

    blue_info "Creating $PORTFOLIO_DIR/{master,lanes,output}"
    mkdir -p "$MASTER_DIR" "$LANES_DIR" "$OUTPUT_DIR"
    green_check "Directories ready"
    echo

    # Search paths (global so find_and_copy can see)
    SEARCH_PATHS=(
        "$HOME/Downloads"
        "$HOME/Documents"
        "$HOME/Desktop"
        "$HOME"
    )
    while IFS= read -r dir; do
        SEARCH_PATHS+=("$dir")
    done < <(find "$HOME" -maxdepth 3 -type d -iname "*resume*" 2>/dev/null)

    blue_info "Searching for source files in:"
    local p
    for p in "${SEARCH_PATHS[@]}"; do
        [ -d "$p" ] && echo "    $p"
    done
    echo

    blue_info "Source file scan:"

    # Detailed resume
    find_and_copy "$STD_RESUME_DETAILED" "*detail*.pdf" \
        || find_and_copy "$STD_RESUME_DETAILED" "*wilkins*.pdf"

    # 5-year resume
    find_and_copy "$STD_RESUME_5YEAR" "*5year*.pdf" \
        || find_and_copy "$STD_RESUME_5YEAR" "*5_year*.pdf" \
        || find_and_copy "$STD_RESUME_5YEAR" "*5yr*.pdf"

    # General resume (likely missing — built in deepening session)
    find_and_copy "$STD_RESUME_GENERAL" "*general*.pdf"

    # Combined certificates PDF
    find_and_copy "$STD_CERTS" "*ertificate*.pdf" \
        || find_and_copy "$STD_CERTS" "*earned*.pdf" \
        || find_and_copy "$STD_CERTS" "*educational*.pdf"

    # OSHA 10 / Fall Protection image
    find_and_copy "$STD_OSHA_IMG" "img_2021062*.jpg" \
        || find_and_copy "$STD_OSHA_IMG" "*osha*.jpg" \
        || find_and_copy "$STD_OSHA_IMG" "*fall*.jpg"

    # EPA 608 (typically missing until requested)
    find_and_copy "$STD_EPA608" "*epa*608*.pdf" \
        || find_and_copy "$STD_EPA608" "*epa*type*.pdf"

    # References & tools (typically missing for now)
    find_and_copy "$STD_REFERENCES" "references.pdf"
    find_and_copy "$STD_TOOLS" "tools*.pdf"

    echo

    blue_info "Lane configs:"
    create_lane_configs
    echo

    # Final status
    header "Setup Complete"
    echo
    header "Master folder status ($MASTER_DIR):"
    local f
    for f in "$STD_RESUME_DETAILED" "$STD_RESUME_5YEAR" "$STD_RESUME_GENERAL" \
             "$STD_CERTS" "$STD_OSHA_IMG" "$STD_EPA608" \
             "$STD_REFERENCES" "$STD_TOOLS"; do
        if [ -f "$MASTER_DIR/$f" ]; then
            green_check "$f"
        else
            red_x "$f  (drop in $MASTER_DIR/ to enable)"
        fi
    done
    echo
    header "Available lanes:"
    ls -1 "$LANES_DIR" 2>/dev/null | sed 's/\.conf$//' | sed 's/^/    /'
    echo
    header "Build a packet with:"
    echo "    bash $0 \"Employer Name\" lane_name"
    echo
    echo "Example:"
    echo "    bash $0 \"Tradesmen International\" facility_maintenance"
    echo
}

# ============================================================
# Cover page generation (groff -> PostScript -> PDF)
# ============================================================
generate_cover() {
    local out="$1"
    local employer="$2"
    local lane_title="$3"
    local cover_line="$4"
    local today
    today=$(date "+%B %d, %Y")

    # Escape backslashes for groff safety
    local emp_e ttl_e cov_e
    emp_e=$(printf "%s" "$employer"    | sed 's/\\/\\\\/g')
    ttl_e=$(printf "%s" "$lane_title"  | sed 's/\\/\\\\/g')
    cov_e=$(printf "%s" "$cover_line"  | sed 's/\\/\\\\/g')

    local roff_file
    roff_file=$(mktemp -t cover.roff.XXXXXX)

    cat > "$roff_file" <<EOF
.po 1.25i
.ll 6i
.sp 1.5i
.ft HB
.ps 26
.ce 1
${emp_e}
.ft HI
.ps 14
.sp 0.4i
.ce 1
${ttl_e}
.ft H
.ps 12
.vs 16p
.sp 0.8i
.fi
${cov_e}
.sp |8.5i
.ft H
.ps 10
.ce 3
Elijah W. Wilkins Sr.
HVAC Technician  -  Indianapolis, IN
${today}
EOF

    if groff -K utf8 -T ps "$roff_file" 2>/dev/null | ps2pdf - "$out" 2>/dev/null; then
        rm -f "$roff_file"
        green_check "Cover page"
        return 0
    else
        rm -f "$roff_file"
        red_x "Cover page generation failed"
        return 1
    fi
}

# ============================================================
# Image to PDF
# ============================================================
convert_image_to_pdf() {
    local in="$1"
    local out="$2"

    if command -v img2pdf >/dev/null 2>&1; then
        img2pdf "$in" -o "$out" 2>/dev/null
        return $?
    elif command -v convert >/dev/null 2>&1; then
        convert "$in" "$out" 2>/dev/null
        return $?
    else
        return 1
    fi
}

# ============================================================
# Build mode
# ============================================================
build_mode() {
    local employer="$1"
    local lane="$2"

    header "Portfolio Build"
    blue_info "Employer: $employer"
    blue_info "Lane:     $lane"
    echo

    local lane_conf="$LANES_DIR/$lane.conf"
    if [ ! -f "$lane_conf" ]; then
        red_x "Lane '$lane' not found at $lane_conf"
        echo
        echo "Available lanes:"
        ls -1 "$LANES_DIR" 2>/dev/null | sed 's/\.conf$//' | sed 's/^/    /'
        exit 1
    fi

    # Source the lane config
    LANE_TITLE=""
    COVER_LINE=""
    RESUME=""
    CERT_ORDER=""
    # shellcheck disable=SC1090
    source "$lane_conf"

    if [ -z "$RESUME" ]; then
        red_x "Lane config missing RESUME field"
        exit 1
    fi

    # Output naming
    local date_stamp employer_safe output_name output_path
    date_stamp=$(date +%Y-%m-%d)
    employer_safe=$(printf "%s" "$employer" | tr '[:upper:]' '[:lower:]' | tr ' ' '_' | tr -cd 'a-z0-9_')
    output_name="${date_stamp}_${employer_safe}_${lane}.pdf"
    output_path="$OUTPUT_DIR/$output_name"

    # Working dir
    local tmpdir
    tmpdir=$(mktemp -d -t portfolio.XXXXXX)
    trap 'rm -rf "$tmpdir"' EXIT

    # Step 1: cover (honor JOBSEEKER_COVER_OVERRIDE from jobseeker.sh)
    local cover_text="${JOBSEEKER_COVER_OVERRIDE:-$COVER_LINE}"
    blue_info "Generating cover page..."
    if ! generate_cover "$tmpdir/00_cover.pdf" "$employer" "$LANE_TITLE" "$cover_text"; then
        exit 1
    fi

    # Step 2: resume (required)
    local resume_src="$MASTER_DIR/$RESUME"
    if [ -f "$resume_src" ]; then
        cp "$resume_src" "$tmpdir/01_resume.pdf"
        green_check "Resume: $RESUME"
    else
        red_x "Resume missing: $RESUME"
        echo "    Drop $RESUME into $MASTER_DIR/ and rerun."
        exit 1
    fi

    # Step 3: certs in lane order
    local cert_idx=2
    local cert pad pdf_target cert_src
    for cert in $CERT_ORDER; do
        cert_src="$MASTER_DIR/$cert"
        pad=$(printf "%02d" $cert_idx)

        if [ ! -f "$cert_src" ]; then
            yellow_warn "Skipping (missing): $cert"
            continue
        fi

        case "$cert" in
            *.jpg|*.jpeg|*.JPG|*.JPEG|*.png|*.PNG)
                pdf_target="$tmpdir/${pad}_$(basename "$cert" | sed 's/\.[^.]*$//').pdf"
                if convert_image_to_pdf "$cert_src" "$pdf_target"; then
                    green_check "Cert (image to PDF): $cert"
                    cert_idx=$((cert_idx + 1))
                else
                    yellow_warn "Cannot convert image $cert — install with: sudo apt install img2pdf"
                fi
                ;;
            *.pdf|*.PDF)
                cp "$cert_src" "$tmpdir/${pad}_${cert}"
                green_check "Cert: $cert"
                cert_idx=$((cert_idx + 1))
                ;;
            *)
                yellow_warn "Unsupported file type: $cert"
                ;;
        esac
    done

    # Step 4: references + tools (if present)
    if [ -f "$MASTER_DIR/$STD_REFERENCES" ]; then
        pad=$(printf "%02d" $cert_idx)
        cp "$MASTER_DIR/$STD_REFERENCES" "$tmpdir/${pad}_references.pdf"
        green_check "References sheet"
        cert_idx=$((cert_idx + 1))
    fi
    if [ -f "$MASTER_DIR/$STD_TOOLS" ]; then
        pad=$(printf "%02d" $cert_idx)
        cp "$MASTER_DIR/$STD_TOOLS" "$tmpdir/${pad}_tools.pdf"
        green_check "Tools-owned list"
    fi

    echo

    # Step 5: combine
    blue_info "Fusing into final packet..."

    local files_to_combine=()
    local pdf
    for pdf in "$tmpdir"/*.pdf; do
        [ -f "$pdf" ] && files_to_combine+=("$pdf")
    done

    if [ ${#files_to_combine[@]} -lt 2 ]; then
        red_x "Need at least cover + resume to build (have ${#files_to_combine[@]})"
        exit 1
    fi

    if ! pdfunite "${files_to_combine[@]}" "$output_path" 2>/dev/null; then
        red_x "pdfunite failed"
        exit 1
    fi

    echo
    header "Build Complete"
    green_check "Output: $output_path"
    echo

    # Open in default PDF viewer
    if command -v xdg-open >/dev/null 2>&1; then
        blue_info "Opening for review..."
        xdg-open "$output_path" >/dev/null 2>&1 &
    fi
}

# ============================================================
# Main
# ============================================================
main() {
    check_deps

    case $# in
        0)
            setup_mode
            ;;
        2)
            if [ ! -d "$MASTER_DIR" ]; then
                red_x "Portfolio not set up yet."
                echo
                echo "Run setup first:"
                echo "    bash $0"
                exit 1
            fi
            build_mode "$1" "$2"
            ;;
        *)
            cat <<EOF
portfolio.sh — Tailored job application portfolio assembler

Usage:
    bash $0                                    # Setup mode
    bash $0 "Employer Name" lane_name          # Build mode

Example:
    bash $0 "Tradesmen International" facility_maintenance

Lanes (after setup):
    hvac_service, hvac_refrig, hvac_install,
    facility_maintenance, industrial_maintenance, general_pivot
EOF
            exit 1
            ;;
    esac
}

main "$@"
