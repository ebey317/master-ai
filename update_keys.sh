#!/bin/bash
source ~/scripts/brand.sh

KEYS_FILE="$HOME/.master_ai_keys"

[ ! -f "$KEYS_FILE" ] && echo '{}' > "$KEYS_FILE" && chmod 600 "$KEYS_FILE"

load_key() {
    python3 -c "
import json, sys
try:
    d = json.load(open('$KEYS_FILE'))
    print(d.get(sys.argv[1], ''))
except: print('')
" "$1" 2>/dev/null
}

save_key() {
    python3 -c "
import json, sys, os
field = sys.argv[1]; value = sys.argv[2]
try:
    with open('$KEYS_FILE') as f: keys = json.load(f)
except: keys = {}
keys[field] = value
with open('$KEYS_FILE', 'w') as f: json.dump(keys, f, indent=2)
os.chmod('$KEYS_FILE', 0o600)
" "$1" "$2" 2>/dev/null
}

detect_expiry() {
    # Try to extract expiry date from the key itself (JWT decode)
    python3 -c "
import sys, base64, json, datetime

key = sys.argv[1]
parts = key.split('.')
if len(parts) == 3:
    try:
        payload = parts[1]
        payload += '=' * (4 - len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        exp = data.get('exp')
        if exp:
            d = datetime.datetime.utcfromtimestamp(int(exp)).date()
            print(d.isoformat())
            sys.exit(0)
    except:
        pass
print('')
" "$1" 2>/dev/null
}

detect_service() {
    local key="$1"
    local len=${#key}

    [[ "$key" == gsk_* ]]                          && { echo "groq|Groq|groq.com"; return; }
    [[ "$key" == sk-ant-* ]]                        && { echo "anthropic|Anthropic / Claude|console.anthropic.com"; return; }
    [[ "$key" == sk-or-v1-* ]]                      && { echo "openrouter|OpenRouter|openrouter.ai"; return; }
    [[ "$key" == sk-proj-* ]]                       && { echo "openai|OpenAI|platform.openai.com"; return; }
    [[ "$key" == sk-* ]]                            && { echo "deepseek|DeepSeek|platform.deepseek.com"; return; }
    [[ "$key" == hf_* ]]                            && { echo "huggingface|HuggingFace|huggingface.co"; return; }
    [[ "$key" == ya29.* || "$key" == 1//* ]]        && { echo "google|Google Cloud|console.cloud.google.com"; return; }
    [[ "$key" == xai-* ]]                           && { echo "xai|xAI / Grok|x.ai"; return; }
    [[ "$key" == AIzaSy* ]]                         && { echo "gemini|Google Gemini|aistudio.google.com/app/apikey"; return; }
    [[ "$key" == Bearer\ * ]]                       && { echo "bearer|Bearer token|unknown"; return; }
    [[ $len -ge 30 && $len -le 50 && "$key" =~ ^[a-zA-Z0-9_-]+$ ]] && { echo "gumroad|Gumroad|app.gumroad.com/settings/advanced"; return; }

    echo "unknown||"
}

show_all_keys() {
    echo ""
    echo -e "${D}  ┌──────────────────────────────────────────────────────────────────┐${X}"
    echo -e "${D}  │${X}  ${C}API Key Reference — Master AI${X}"
    echo -e "${D}  │${X}  ${D}This replaces your notes. Everything in one place.${X}"
    echo -e "${D}  └──────────────────────────────────────────────────────────────────┘${X}"
    python3 -c "
import json, datetime

KNOWN = [
    ('groq',        'Groq',              'console.groq.com/keys',                    'Fast free cloud AI — recommended'),
    ('openai',      'OpenAI',            'platform.openai.com/api-keys',             'GPT-4o — most capable'),
    ('openrouter',  'OpenRouter',        'openrouter.ai/keys',                       'Free llama fallback'),
    ('deepseek',    'DeepSeek R1',       'platform.deepseek.com/api-keys',           'Reasoning model — best for complex tasks'),
    ('gumroad',     'Gumroad',           'app.gumroad.com/settings/advanced',        'Sell Master AI — Access Token'),
    ('huggingface', 'HuggingFace',       'huggingface.co/settings/tokens',           'Model downloads'),
    ('xai',         'xAI / Grok',        'console.x.ai',                             'Grok API'),
]

# Default daily token limits for known free tiers (user can override with {field}_tokens_limit)
FREE_LIMITS = {
    'groq':       500_000,
    'openrouter': 200_000,
}

G = '\033[92m'; R = '\033[91m'; C = '\033[96m'; W = '\033[97m'
Y = '\033[33m'; D = '\033[90m'; B = '\033[1m'; X = '\033[0m'

try:
    saved = json.load(open('$KEYS_FILE'))
except:
    saved = {}

today = datetime.date.today()

def expiry_display(field):
    exp_str = saved.get(field + '_expires', '')
    if not exp_str:
        return f'{D}—{X}', ''
    try:
        exp = datetime.date.fromisoformat(exp_str)
        days = (exp - today).days
        if days < 0:
            return f'{R}{B}{exp_str} (expired!){X}', '⛔'
        elif days == 0:
            return f'{R}{B}{exp_str} (today!){X}', '🚨'
        elif days <= 3:
            return f'{R}{exp_str} ({days}d){X}', '⚠'
        elif days <= 7:
            return f'{Y}{exp_str} ({days}d){X}', ''
        else:
            return f'{G}{exp_str} ({days}d){X}', ''
    except:
        return f'{D}{exp_str}{X}', ''

def token_bar(field):
    tok_date = saved.get(f'{field}_tokens_date', '')
    tok_used = saved.get(f'{field}_tokens_today', 0)
    if tok_date != today.isoformat() or not tok_used:
        return ''
    limit = saved.get(f'{field}_tokens_limit') or FREE_LIMITS.get(field)
    used_fmt = f'{tok_used:,}'
    if limit:
        pct = tok_used / limit
        filled = int(pct * 10)
        bar = '█' * filled + '░' * (10 - filled)
        limit_fmt = f'{limit:,}'
        if pct >= 0.9:
            col = R
        elif pct >= 0.7:
            col = Y
        else:
            col = G
        return f'       {D}tokens today: {col}{bar} {used_fmt} / {limit_fmt}{D} ({pct*100:.1f}%){X}'
    else:
        return f'       {D}tokens today: {W}{used_fmt}{X}'

# meta fields to hide from extras
META_SUFFIXES = ('_expires', '_tokens_today', '_tokens_date', '_tokens_limit')
known_fields = {f for f,_,_,_ in KNOWN}
for f,_,_,_ in KNOWN:
    for s in META_SUFFIXES:
        known_fields.add(f + s)

print()
print(f'  {D}{\"─\"*82}{X}')
print(f'  {C}{\"SERVICE\":<18}{W}{\"KEY STATUS\":<22}{C}{\"EXPIRY\":<26}{D}{\"GET KEY AT\"}{X}')
print(f'  {D}{\"─\"*82}{X}')

for field, label, url, note in KNOWN:
    val = saved.get(field, '')
    exp_col, exp_icon = expiry_display(field)
    if val:
        masked = val[:6] + '...' + val[-4:] if len(val) > 10 else '(set)'
        icon = exp_icon if exp_icon else '✅'
        print(f'  {G}{icon}{X}  {W}{label:<18}{X}{G}{masked:<22}{X}{exp_col:<26}  {D}{url}{X}')
        bar = token_bar(field)
        if bar:
            print(bar)
    else:
        print(f'  {R}○{X}   {D}{label:<18}{X}{Y}{\"(not saved)\":<22}{X}{D}—{\" \"*24}{url}{X}')
        print(f'       {D}↳ {note}{X}')

extras = {k: v for k, v in saved.items()
          if k not in known_fields and not any(k.endswith(s) for s in META_SUFFIXES)}
if extras:
    print(f'  {D}{\"─\"*82}{X}')
    print(f'  {D}Other saved keys:{X}')
    for k, v in extras.items():
        masked = v[:6] + '...' + v[-4:] if len(v) > 10 else '(set)'
        exp_col, _ = expiry_display(k)
        print(f'  {G}✅{X}  {W}{k:<18}{X}{G}{masked:<22}{X}{exp_col}')
        bar = token_bar(k)
        if bar:
            print(bar)

print(f'  {D}{\"─\"*82}{X}')
saved_count = sum(1 for f,_,_,_ in KNOWN if saved.get(f))
missing_count = sum(1 for f,_,_,_ in KNOWN if not saved.get(f))
print(f'  {D}Saved: {G}{saved_count}{D}  |  Missing: {Y}{missing_count}{D}  |  File: ~/.master_ai_keys{X}')
print()
" 2>/dev/null
}

verify_key() {
    local field="$1"
    local key="$2"
    echo ""
    echo -e "  ${D}  Testing key from Master AI...${X}"
    python3 -c "
import json, sys, urllib.request

field = sys.argv[1]
key   = sys.argv[2]

G = '\033[92m'; R = '\033[91m'; W = '\033[97m'; D = '\033[90m'; Y = '\033[33m'; X = '\033[0m'

def test_groq(k):
    p = json.dumps({'model':'llama-3.3-70b-versatile','messages':[{'role':'user','content':'Reply with exactly two words: key working'}],'max_tokens':10,'stream':False}).encode()
    req = urllib.request.Request('https://api.groq.com/openai/v1/chat/completions',data=p,
        headers={'Content-Type':'application/json','Authorization':f'Bearer {k}','User-Agent':'python-requests/2.31.0'})
    with urllib.request.urlopen(req,timeout=15) as r:
        return json.loads(r.read())['choices'][0]['message']['content'].strip()

def test_gemini(k):
    p = json.dumps({'contents':[{'parts':[{'text':'Reply with exactly two words: key working'}]}]}).encode()
    url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={k}'
    req = urllib.request.Request(url,data=p,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=15) as r:
        return json.loads(r.read())['candidates'][0]['content']['parts'][0]['text'].strip()

def test_anthropic(k):
    p = json.dumps({'model':'claude-sonnet-4-6','max_tokens':10,'system':'','messages':[{'role':'user','content':'Reply with exactly two words: key working'}]}).encode()
    req = urllib.request.Request('https://api.anthropic.com/v1/messages',data=p,
        headers={'Content-Type':'application/json','x-api-key':k,'anthropic-version':'2023-06-01'})
    with urllib.request.urlopen(req,timeout=15) as r:
        return json.loads(r.read())['content'][0]['text'].strip()

def test_openai(k):
    p = json.dumps({'model':'gpt-4o','messages':[{'role':'user','content':'Reply with exactly two words: key working'}],'max_tokens':10}).encode()
    req = urllib.request.Request('https://api.openai.com/v1/chat/completions',data=p,
        headers={'Content-Type':'application/json','Authorization':f'Bearer {k}'})
    with urllib.request.urlopen(req,timeout=15) as r:
        return json.loads(r.read())['choices'][0]['message']['content'].strip()

def test_openrouter(k):
    p = json.dumps({'model':'meta-llama/llama-3.3-70b-instruct:free','messages':[{'role':'user','content':'Reply with exactly two words: key working'}],'max_tokens':10}).encode()
    req = urllib.request.Request('https://openrouter.ai/api/v1/chat/completions',data=p,
        headers={'Content-Type':'application/json','Authorization':f'Bearer {k}'})
    with urllib.request.urlopen(req,timeout=15) as r:
        return json.loads(r.read())['choices'][0]['message']['content'].strip()

def test_deepseek(k):
    p = json.dumps({'model':'deepseek-reasoner','messages':[{'role':'user','content':'Reply with exactly two words: key working'}],'max_tokens':10,'stream':False}).encode()
    req = urllib.request.Request('https://api.deepseek.com/v1/chat/completions',data=p,
        headers={'Content-Type':'application/json','Authorization':f'Bearer {k}'})
    with urllib.request.urlopen(req,timeout=60) as r:
        return json.loads(r.read())['choices'][0]['message']['content'].strip()

tests = {'groq':test_groq,'gemini':test_gemini,'anthropic':test_anthropic,'openai':test_openai,'openrouter':test_openrouter,'deepseek':test_deepseek}
# Alternate-slot support: 'groq_routing' / 'openrouter_backup' / etc. →
# strip the suffix and test against the parent service.
base_field = field
if field not in tests:
    for svc in tests:
        if field.startswith(svc + '_'):
            base_field = svc
            break
fn = tests.get(base_field)
if not fn:
    print(f'  {Y}⚠  No test available for {field} — key saved but not verified.{X}')
    sys.exit(0)
if base_field != field:
    print(f'  {D}   Testing {field} as a {base_field} key...{X}')

try:
    reply = fn(key)
    print(f'  {G}✅ Verified — key works against {base_field.upper()}{X}')
    print(f'  {D}   Saved as: {field}{X}')
    print(f'  {D}   Response: \"{reply}\"{X}')
except Exception as e:
    err = str(e)
    if '401' in err or '403' in err:
        print(f'  {R}❌ Key rejected by {base_field.upper()} — invalid or expired.{X}')
    elif '429' in err:
        print(f'  {Y}⚠  Rate limited — key is valid but usage limit hit. Try again later.{X}')
    elif '400' in err:
        print(f'  {R}❌ Bad request — key format may be wrong for {base_field.upper()}.{X}')
    else:
        print(f'  {R}❌ Could not connect to {base_field.upper()}: {err[:80]}{X}')
    sys.exit(1)
" "$field" "$key" 2>/dev/null
}

main() {
    clear
    banner_master_ai
    echo ""
    echo -e "${D}  ────────────────────────────────────────────────────────────${X}"
    echo -e "  ${C}API Key Manager${X}   ${D}paste any key — Master AI detects the service${X}"
    echo -e "${D}  ────────────────────────────────────────────────────────────${X}"

    show_all_keys

    while true; do
        echo -e "${D}  ────────────────────────────────────────────────────────────${X}"
        echo -e "  ${Y}1)${W} Paste a new key"
        echo -e "  ${Y}2)${W} Remove a key"
        echo -e "  ${Y}3)${W} View all keys"
        echo -e "  ${Y}4)${W} Set / update expiry date for a key"
        echo -e "  ${Y}5)${W} Set daily token limit for a key"
        echo -e "  ${Y}x)${W} Done"
        echo ""
        echo -ne "  \e[5m${C}Choose: ${X}\e[0m"
        read -r OPT

        case "$OPT" in

            1)
                clear
                banner_master_ai
                echo ""
                echo -e "${D}  ────────────────────────────────────────────────────────────${X}"
                echo -e "  ${C}Paste Your Key${X}"
                echo -e "${D}  ────────────────────────────────────────────────────────────${X}"
                echo ""
                echo -e "  ${D}Input is hidden. Paste and press ENTER.${X}"
                echo ""
                echo -ne "  \e[5m${C}Key: ${X}\e[0m"
                read -rs RAW_KEY; echo ""

                [ -z "$RAW_KEY" ] && echo -e "${Y}  Nothing entered.${X}" && continue

                IFS='|' read -r FIELD LABEL SITE <<< "$(detect_service "$RAW_KEY")"

                echo ""

                if [[ "$FIELD" == "unknown" ]]; then
                    echo -e "  ${Y}⚠  Could not auto-detect this key.${X}"
                    echo ""
                    echo -e "  ${D}Which service is this for?${X}"
                    echo -e "  ${Y}1)${W} Groq           ${D}groq.com${X}"
                    echo -e "  ${Y}2)${W} OpenAI         ${D}platform.openai.com${X}"
                    echo -e "  ${Y}3)${W} OpenRouter     ${D}openrouter.ai${X}"
                    echo -e "  ${Y}4)${W} Anthropic      ${D}console.anthropic.com${X}"
                    echo -e "  ${Y}5)${W} Gemini (free)  ${D}aistudio.google.com/app/apikey${X}"
                    echo -e "  ${Y}6)${W} DeepSeek R1    ${D}platform.deepseek.com${X}"
                    echo -e "  ${Y}6)${W} Gumroad        ${D}app.gumroad.com${X}"
                    echo -e "  ${Y}7)${W} HuggingFace    ${D}huggingface.co${X}"
                    echo -e "  ${Y}8)${W} Other (custom name)${X}"
                    echo ""
                    echo -ne "  ${C}Choose (1-8): ${X}"
                    read -r SVC_CHOICE
                    case "$SVC_CHOICE" in
                        1) FIELD="groq";         LABEL="Groq" ;;
                        2) FIELD="openai";       LABEL="OpenAI" ;;
                        3) FIELD="openrouter";   LABEL="OpenRouter" ;;
                        4) FIELD="anthropic";    LABEL="Anthropic" ;;
                        5) FIELD="gemini";       LABEL="Gemini" ;;
                        6) FIELD="deepseek";     LABEL="DeepSeek" ;;
                        7) FIELD="gumroad";      LABEL="Gumroad" ;;
                        8) FIELD="huggingface";  LABEL="HuggingFace" ;;
                        9)
                            echo -ne "  ${C}Service name (lowercase, no spaces): ${X}"
                            read -r FIELD
                            LABEL="$FIELD"
                            ;;
                        *) echo -e "${Y}  Cancelled.${X}"; continue ;;
                    esac
                else
                    echo -e "  ${G}✅ Detected: ${W}${LABEL}${X}"
                    [ -n "$SITE" ] && echo -e "  ${D}   Source:   ${SITE}${X}"
                    echo ""
                    local existing
                    existing=$(load_key "$FIELD")
                    if [ -n "$existing" ]; then
                        local masked="${existing:0:6}...${existing: -4}"
                        echo -e "  ${Y}  ${LABEL} already has a key saved: ${W}${masked}${X}"
                        echo ""
                        echo -e "  ${W}How do you want to save this new one?${X}"
                        echo -e "    ${Y}r)${W} Replace ${X}${D}— overwrite the existing ${LABEL} key${X}"
                        echo -e "    ${Y}a)${W} Add as alternate slot ${X}${D}— keep both, save under a named suffix${X}"
                        echo -e "    ${Y}n)${W} Cancel${X}"
                        echo ""
                        echo -ne "  ${C}Choose (r/a/n): ${X}"
                        read -r MULTI_CHOICE
                        case "$MULTI_CHOICE" in
                            r|R) ;; # fall through, keep FIELD as-is
                            a|A)
                                echo ""
                                echo -e "  ${D}Name the alternate slot — e.g. 'remote', 'backup', '2'.${X}"
                                echo -e "  ${D}Will be saved as: ${LABEL,,}_<slot>${X}"
                                echo -ne "  ${C}Slot name: ${X}"
                                read -r SLOT
                                [ -z "$SLOT" ] && echo -e "${Y}  Cancelled.${X}" && continue
                                # sanitize: lowercase, letters/digits/underscore only
                                SLOT=$(echo "$SLOT" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_' '_' | sed 's/__*/_/g; s/^_//; s/_$//')
                                [ -z "$SLOT" ] && echo -e "${Y}  Invalid slot name.${X}" && continue
                                FIELD="${FIELD}_${SLOT}"
                                LABEL="${LABEL} (${SLOT})"
                                echo -e "  ${G}  → Saving as alternate: ${FIELD}${X}"
                                ;;
                            *) echo -e "${Y}  Cancelled.${X}"; continue ;;
                        esac
                    else
                        echo -ne "  \e[5m${C}Save as ${LABEL} key? (y/n): ${X}\e[0m"
                        read -r CONFIRM
                        [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]] && echo -e "${Y}  Skipped.${X}" && continue
                    fi
                fi

                save_key "$FIELD" "$RAW_KEY"
                echo ""
                echo -e "  ${G}✅ ${LABEL} key saved.${X}"
                echo -e "  ${D}   Field: ~/.master_ai_keys → \"${FIELD}\"${X}"
                verify_key "$FIELD" "$RAW_KEY"
                echo ""

                local AUTO_EXP
                AUTO_EXP=$(detect_expiry "$RAW_KEY")
                if [ -n "$AUTO_EXP" ]; then
                    save_key "${FIELD}_expires" "$AUTO_EXP"
                    echo -e "  ${G}🔍 Expiry auto-detected: ${W}${AUTO_EXP}${X}"
                    echo ""
                else
                    echo -e "  ${D}Expiry date? (YYYY-MM-DD or ENTER to skip):${X}"
                    echo -ne "  ${C}Expiry: ${X}"
                    read -r EXPIRY_DATE
                    if [[ "$EXPIRY_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
                        save_key "${FIELD}_expires" "$EXPIRY_DATE"
                        echo -e "  ${G}✅ Expiry saved: ${EXPIRY_DATE}${X}"
                    elif [ -n "$EXPIRY_DATE" ]; then
                        echo -e "  ${Y}  Invalid format — skipped. Use YYYY-MM-DD.${X}"
                    fi
                    echo ""
                fi
                sleep 1
                ;;

            2)
                show_all_keys
                echo -ne "  ${C}Field name to remove: ${X}"
                read -r DEL_FIELD
                [ -z "$DEL_FIELD" ] && continue
                python3 -c "
import json, os
try:
    with open('$KEYS_FILE') as f: keys = json.load(f)
    if '$DEL_FIELD' in keys:
        del keys['$DEL_FIELD']
        with open('$KEYS_FILE', 'w') as f: json.dump(keys, f, indent=2)
        os.chmod('$KEYS_FILE', 0o600)
        print('  \033[92m✅ Removed: $DEL_FIELD\033[0m')
    else:
        print('  \033[33m⚠  Key not found: $DEL_FIELD\033[0m')
except Exception as e:
    print(f'  \033[31m❌ Error: {e}\033[0m')
" 2>/dev/null
                echo ""
                ;;

            3)
                show_all_keys
                ;;

            4)
                show_all_keys
                echo -ne "  ${C}Field name to set expiry (e.g. groq): ${X}"
                read -r EXP_FIELD
                [ -z "$EXP_FIELD" ] && continue
                echo -ne "  ${C}Expiry date (YYYY-MM-DD): ${X}"
                read -r EXP_DATE
                if [[ "$EXP_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
                    save_key "${EXP_FIELD}_expires" "$EXP_DATE"
                    echo -e "  ${G}✅ Expiry saved for ${EXP_FIELD}: ${EXP_DATE}${X}"
                else
                    echo -e "  ${Y}  Invalid format. Use YYYY-MM-DD (e.g. 2026-05-01)${X}"
                fi
                echo ""
                ;;

            5)
                show_all_keys
                echo -e "  ${D}Set a daily token limit for a service (e.g. groq, openai).${X}"
                echo -e "  ${D}Master AI will show a usage bar counting down from this limit.${X}"
                echo ""
                echo -ne "  ${C}Field name (e.g. groq): ${X}"
                read -r LIM_FIELD
                [ -z "$LIM_FIELD" ] && continue
                echo -ne "  ${C}Daily token limit (e.g. 500000): ${X}"
                read -r LIM_VAL
                if [[ "$LIM_VAL" =~ ^[0-9]+$ ]]; then
                    save_key "${LIM_FIELD}_tokens_limit" "$LIM_VAL"
                    echo -e "  ${G}✅ Token limit set for ${LIM_FIELD}: ${LIM_VAL} tokens/day${X}"
                else
                    echo -e "  ${Y}  Invalid — enter a number (e.g. 500000)${X}"
                fi
                echo ""
                ;;

            x|X|exit|quit)
                echo -e "${G}\n  Keys saved. Goodbye.\n${X}"
                exit 0
                ;;
        esac
    done
}

main
