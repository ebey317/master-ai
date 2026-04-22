#!/bin/bash
# ============================================================
# CHUNKER-TEST — preset tasks you can fire with one word
# No quoting, no typing a full task string.
#
#   chunker-test water    → water purification field guide
#   chunker-test diesel   → diesel generator restart manual
#   chunker-test solar    → off-grid solar setup manual
#   chunker-test apothecary → common medicinal plants reference
#   chunker-test power    → power plant cold-start procedures
#   chunker-test short    → tiny 1000-word demo for speed testing
#
#   chunker-test           → lists all preset tasks
# ============================================================

declare -A TASKS=(
    [water]="write a 3000 word field guide to purifying water without electricity — for post-collapse scenarios. Cover: boiling, solar disinfection, filtration media (sand, charcoal, cloth), chemical treatment (bleach, iodine), and how to test for contamination."
    [diesel]="write a 5000 word manual for safely restarting a diesel generator that has been off for a week. Cover: pre-start inspection, fuel + oil check, battery state, glow plugs, cold-start procedure, load testing, troubleshooting no-start conditions, and safety rules."
    [solar]="write a 6000 word operating manual for a small off-grid solar setup. Cover: panels (series vs parallel), charge controller (PWM vs MPPT), battery bank care (flooded vs sealed vs lithium), inverter sizing, DC/AC wiring safety, daily maintenance, and winter preparation."
    [apothecary]="write a 5000 word reference guide to 20 common North American medicinal plants. For each: how to identify it, where it grows, what it treats, how to prepare it (tea/tincture/poultice), dosing, and toxicity warnings."
    [power]="write a 5000 word procedure for cold-starting a small coal or gas steam power plant after a complete shutdown. Cover: safety lockout/tagout, boiler inspection, steam pressure testing, turbine roll, generator sync to grid (if applicable), and emergency shutdown."
    [biodiesel]="write a 6000 word practical manual for producing biodiesel (LIQUID fuel) from waste vegetable oil in an off-grid setup. Cover: feedstock sourcing + filtering, titration to determine free fatty acid content, transesterification process (methanol + lye catalyst), washing + drying the finished fuel, storage, quality testing, engine compatibility, and safety hazards (methanol vapor, lye burns)."
    [biogas]="write a 6000 word practical manual for building and operating a small-scale biogas digester that produces methane (GAS/VAPOR fuel) from organic waste. Cover: anaerobic digester design (fixed-dome vs floating-drum), feedstock preparation (manure, food scraps, plant matter), C:N ratio + moisture balance, temperature control, slurry agitation, gas collection + storage (low pressure bags, scrubbers for H2S), safety (methane is explosive), cooking/lighting uses, and slurry residue as fertilizer."
    [short]="write a 1000 word quick-reference card for basic off-grid water filtration using household materials."
)

# Fuel ordering clusters the two bio-fuels together (liquid + vapor, Elijah's frame)
ORDER=(short water apothecary solar biodiesel biogas diesel power)

if [ $# -eq 0 ]; then
    echo ""
    echo "chunker-test — preset AI tasks you can run with one word:"
    echo ""
    for k in "${ORDER[@]}"; do
        printf "  %-12s %s\n" "$k" "${TASKS[$k]:0:80}..."
    done
    echo ""
    echo "usage: chunker-test <name>   e.g.  chunker-test short"
    echo ""
    exit 0
fi

KEY="$1"
TASK="${TASKS[$KEY]:-}"

if [ -z "$TASK" ]; then
    echo "no preset named '$KEY'. Try: ${ORDER[*]}"
    exit 1
fi

echo ""
echo "▸ preset: $KEY"
echo "▸ task:   $TASK"
echo ""
exec bash "$HOME/scripts/chunker.sh" "$TASK"
