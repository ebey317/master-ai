#!/bin/bash
# ============================================================
# master-ai — PYTHON LEARN MODE
# 10 lessons. Terminal → Python → Build real things.
# Run: bash ~/scripts/learn.sh
# ============================================================

source ~/scripts/brand.sh

PROGRESS_FILE="$HOME/.master_ai_progress.json"
CHAT_DIR="$HOME/.master_ai_chats"
OLLAMA_URL="http://localhost:11434"
MODEL="master-ai"

mkdir -p "$CHAT_DIR"

# ── PROGRESS ─────────────────────────────────────────────────
init_progress() {
    if [ ! -f "$PROGRESS_FILE" ]; then
        python3 -c "
import json
data = {'unlocked': 1, 'completed': [], 'streak': 0}
with open('$PROGRESS_FILE', 'w') as f:
    json.dump(data, f, indent=2)
"
    fi
}

get_unlocked() {
    python3 -c "
import json
try:
    d = json.load(open('$PROGRESS_FILE'))
    print(d.get('unlocked', 1))
except: print(1)
"
}

get_completed() {
    python3 -c "
import json
try:
    d = json.load(open('$PROGRESS_FILE'))
    print(' '.join(map(str, d.get('completed', []))))
except: print('')
"
}

mark_complete() {
    local lesson="$1"
    local next=$(( lesson + 1 ))
    python3 -c "
import json
try:
    d = json.load(open('$PROGRESS_FILE'))
except:
    d = {'unlocked': 1, 'completed': [], 'streak': 0}
if $lesson not in d['completed']:
    d['completed'].append($lesson)
d['streak'] = d.get('streak', 0) + 1
if $next > d.get('unlocked', 1):
    d['unlocked'] = $next
with open('$PROGRESS_FILE', 'w') as f:
    json.dump(d, f, indent=2)
print('saved')
"
}

save_chat() {
    local lesson="$1"
    local role="$2"
    local text="$3"
    python3 -c "
import json, os
f = '$CHAT_DIR/lesson_${lesson}.json'
try:
    chats = json.load(open(f))
except:
    chats = []
chats.append({'role': '$role', 'content': '''$text'''})
with open(f, 'w') as fp:
    json.dump(chats, fp, indent=2)
"
}

# ── AI GRADE ─────────────────────────────────────────────────
grade_answer() {
    local lesson_context="$1"
    local user_answer="$2"

    local payload
    payload=$(python3 -c "
import json, sys
system = '''You are a friendly coding teacher. A student is learning Python and terminal basics.
Grade their answer. Be encouraging. Reply with exactly:
PASS: <one sentence of praise and what they got right>
or
FAIL: <one sentence explaining what was wrong and a hint>
Keep it short. No lectures.'''
user = '''Lesson context: $lesson_context
Student answer: $user_answer
Grade this answer.'''
payload = {
    'model': '$MODEL',
    'messages': [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user}
    ],
    'stream': False
}
print(json.dumps(payload))
" 2>/dev/null)

    local response
    response=$(curl -s --max-time 30 -X POST "$OLLAMA_URL/api/chat" \
        -H "Content-Type: application/json" \
        -d "$payload" 2>/dev/null)

    python3 -c "
import json, sys
try:
    data = json.loads(sys.argv[1])
    print(data['message']['content'])
except:
    print('PASS: Good effort — moving on.')
" "$response"
}

# ── LIVE HELP FROM SYSTEM ────────────────────────────────────
show_live_help() {
    local cmds="$1"
    [ -z "$cmds" ] && return
    echo -e "${BC}  ── FROM YOUR SYSTEM ──────────────────────────────────${X}"
    for cmd in $cmds; do
        local desc
        desc=$(whatis "$cmd" 2>/dev/null | head -1)
        [ -n "$desc" ] && echo -e "${W}  whatis $cmd:${D}  $desc${X}"
        local hlp
        hlp=$("$cmd" --help 2>&1 | grep -v "^$" | head -1)
        [ -n "$hlp" ] && echo -e "${D}    $hlp${X}"
    done
    local found=0
    for cmd in $cmds; do
        local hits
        hits=$(grep -rn "\b${cmd}\b" ~/scripts/ --include="*.sh" --include="*.py" 2>/dev/null \
            | grep -v "^Binary" | head -3)
        if [ -n "$hits" ]; then
            [ "$found" -eq 0 ] && echo -e "${Y}  Real use in your scripts:${X}"
            found=1
            echo "$hits" | while IFS= read -r line; do
                echo -e "${D}    $line${X}"
            done
        fi
    done
    echo -e "${BC}  ─────────────────────────────────────────────────────${X}"
    echo ""
}

# ── LESSON RUNNER ────────────────────────────────────────────
run_lesson() {
    local NUM="$1"
    local TITLE="$2"
    local TEACH="$3"
    local TASK="$4"
    local CONTEXT="$5"
    local CMDS="$6"

    clear
    banner_master_ai
    echo ""
    echo -e "${C}  ── LESSON ${NUM}/10: ${W}${TITLE}${X}"
    echo -e "${D}  ──────────────────────────────────────────────────────${X}"
    echo ""
    echo -e "${W}${TEACH}${X}"
    echo ""
    show_live_help "$CMDS"
    echo -e "${D}  ──────────────────────────────────────────────────────${X}"
    echo -e "${Y}  YOUR TASK:${X}"
    echo -e "${W}  ${TASK}${X}"
    echo ""
    echo -e "${D}  Type your answer below. Type 'skip' to revisit later.${X}"
    echo -e "${D}  Type 'hint' for a clue.${X}"
    echo ""

    local ATTEMPTS=0
    while true; do
        echo -ne "${C}  Answer: ${X}"
        read -r ANSWER

        [ "$ANSWER" = "skip" ] && echo -e "${Y}  Skipped. Come back to this one.${X}" && return

        if [ "$ANSWER" = "hint" ]; then
            echo -e "${Y}  Hint: Think about what the task is asking for specifically.${X}"
            continue
        fi

        [ -z "$ANSWER" ] && continue

        ATTEMPTS=$(( ATTEMPTS + 1 ))
        save_chat "$NUM" "user" "$ANSWER"

        echo -e "${D}  Grading...${X}"
        local GRADE
        GRADE=$(grade_answer "Lesson $NUM: $TITLE. Teaching: $CONTEXT. Task given: $TASK" "$ANSWER")
        GRADE=$(echo "$GRADE" | sed 's/^[[:space:]]*//' | tr -d '\r')
        save_chat "$NUM" "assistant" "$GRADE"

        echo ""
        if echo "$GRADE" | grep -qi "^PASS"; then
            echo -e "${G}  ✅ ${GRADE#PASS: }${X}"
            echo ""
            mark_complete "$NUM" > /dev/null
            echo -e "${G}  ── Lesson ${NUM} complete! ──${X}"
            echo ""
            if [ "$NUM" -lt 10 ]; then
                local NEXT=$(( NUM + 1 ))
                echo -e "${C}  Loading lesson ${NEXT}...${X}"
                sleep 2
                case "$NEXT" in
                    2)  lesson_2 ;;
                    3)  lesson_3 ;;
                    4)  lesson_4 ;;
                    5)  lesson_5 ;;
                    6)  lesson_6 ;;
                    7)  lesson_7 ;;
                    8)  lesson_8 ;;
                    9)  lesson_9 ;;
                    10) lesson_10 ;;
                esac
            else
                echo -e "${G}  🎉 All 10 lessons complete! You built master-ai — you can build anything.${X}"
                sleep 3
                main
            fi
            return 0
        else
            CLEAN="${GRADE#FAIL: }"; CLEAN="${CLEAN#fail: }"
            echo -e "${Y}  ❌ ${CLEAN}${X}"
            echo ""
            if [ "$ATTEMPTS" -ge 3 ]; then
                echo -e "${D}  3 attempts made. Keep trying or type 'skip' to move on.${X}"
            fi
        fi
        echo ""
    done
}

# ── LESSONS ──────────────────────────────────────────────────

lesson_1() {
    run_lesson 1 "Terminal Basics" \
"The terminal is where you talk to your computer directly.
No clicking — just typing commands.

Key commands:
  ls              → list files in current folder
  cd folder       → move into a folder
  cd ..           → go back one folder
  pwd             → show where you are right now
  mkdir name      → make a new folder
  rm file         → delete a file
  rm -rf folder   → delete a folder and everything in it (careful!)
  cat file        → read a file
  nano file       → edit a file

You already use these in master.sh and your scripts." \
"What command would you type to see what files are in your Downloads folder?" \
"terminal navigation — listing files in a directory" \
"ls cd pwd mkdir rm cat"
}

lesson_2() {
    run_lesson 2 "Reading a Bash Script" \
"Every script in ~/scripts/ is just a text file with instructions.
Here's what the parts mean:

  #!/bin/bash          → tells the system this is a bash script
  MYVAR=\"hello\"      → creates a variable called MYVAR
  echo \$MYVAR         → prints the variable (the \$ reads it)
  echo \"hi there\"    → prints text
  bash script.sh       → runs a script

In master.sh you see things like:
  LOG_FILE=\"\$HOME/scripts/master.log\"
  That's just a variable storing a file path.

Functions look like this:
  my_function() {
      echo \"I do something\"
  }
  my_function    ← calling it" \
"In master.sh, what does the line LOG_FILE=\"\$HOME/scripts/master.log\" do?" \
"bash variables and script structure" \
"bash echo source"
}

lesson_3() {
    run_lesson 3 "Python Basics" \
"Python is like bash but more powerful and easier to read.
Run python3 in your terminal to try it live.

  name = \"Elijah\"          → variable (no \$ needed)
  age = 30                   → number variable
  print(name)                → prints it
  print(\"Hello \" + name)   → joins text
  print(f\"Hi {name}\")      → cleaner way (f-string)

Python files end in .py and run like this:
  python3 myscript.py

master_ai.py is a Python file. Every line you see like:
  KEYS_FILE = Path.home() / \".master_ai_keys\"
...is just Python setting a variable." \
"Write one line of Python that prints your name using an f-string." \
"Python variables and print with f-strings" \
"python3"
}

lesson_4() {
    run_lesson 4 "Making Decisions (if/else)" \
"Programs make decisions. In Python:

  if something_is_true:
      do this
  else:
      do that

Real example from master_ai.py:
  if has_image:
      route = 'vision'
  else:
      route = 'local'

In bash you see the same idea:
  if command -v ollama &>/dev/null; then
      echo 'ollama found'
  else
      echo 'not found'
  fi

The pattern is always: IF condition THEN action ELSE other action." \
"Write a Python if/else that prints 'big' if a number is over 100, otherwise prints 'small'. Use the number 150." \
"if/else logic in Python" \
""
}

lesson_5() {
    run_lesson 5 "Loops — Do It Multiple Times" \
"Loops repeat actions. Two main types:

  FOR loop — do something for each item:
    files = ['master.sh', 'brand.sh', 'learn.sh']
    for f in files:
        print(f)

  WHILE loop — keep going until something changes:
    while True:
        answer = input('Type x to stop: ')
        if answer == 'x':
            break

The main loop in master_ai.py is a while True loop —
it keeps waiting for your input forever until you type x.

In bash you see:
  for model in llama mistral qwen; do
      echo \$model
  done" \
"Write a Python for loop that prints the numbers 1 through 5." \
"for loops in Python" \
""
}

lesson_6() {
    run_lesson 6 "Functions — Reusable Blocks" \
"Functions are named blocks of code you can run anytime.

  def greet(name):
      print(f'Hello {name}!')

  greet('Elijah')    → prints: Hello Elijah!
  greet('customer')  → prints: Hello customer!

Functions can return values:
  def add(a, b):
      return a + b

  result = add(3, 5)
  print(result)      → 8

In master_ai.py every section is a function:
  def detect_route(text, has_image):  → decides which AI to use
  def ask_local(messages, model):     → talks to Ollama
  def speak(text):                    → plays audio

In master.sh every option is a function:
  startup()
  check_ollama()
  launch_master_ai()" \
"Write a Python function called 'double' that takes a number and returns it multiplied by 2. Then call it with the number 7 and print the result." \
"Python functions with parameters and return values" \
""
}

lesson_7() {
    run_lesson 7 "Files and JSON" \
"Your app stores settings in files. Two main types:

Plain text file:
  # Write
  with open('notes.txt', 'w') as f:
      f.write('hello')

  # Read
  with open('notes.txt', 'r') as f:
      content = f.read()
  print(content)

JSON file (structured data — like ~/.master_ai_keys):
  import json

  # Read keys
  with open('keys.json', 'r') as f:
      keys = json.load(f)
  print(keys['groq'])

  # Write keys
  keys['groq'] = 'new_key'
  with open('keys.json', 'w') as f:
      json.dump(keys, f, indent=2)

~/.master_ai_keys is exactly this — a JSON file with your API keys.
update_keys.sh reads it and writes to it." \
"What Python module do you need to import to read a JSON file, and what function reads it?" \
"Python file operations and JSON" \
"python3 cat"
}

lesson_8() {
    run_lesson 8 "Running Commands from Python" \
"Python can run any terminal command using subprocess.
This is how master_ai.py runs piper TTS and aplay.

  import subprocess

  # Run a command
  result = subprocess.run('ls', shell=True, capture_output=True, text=True)
  print(result.stdout)    → shows the output

  # Run in background (non-blocking)
  subprocess.Popen('firefox &', shell=True)

In master_ai.py:
  subprocess.run(['arecord', '-f', 'cd', '-t', 'wav', '-d', '5', filename])
  → records 5 seconds of audio

  subprocess.run(['aplay', filename])
  → plays a wav file

pc_control.sh does the same thing in bash:
  bash -c \"\$cmd\"
  → runs any command the AI suggests" \
"What Python module runs terminal commands, and what attribute gives you the output?" \
"subprocess module — running commands from Python" \
"aplay arecord curl"
}

lesson_9() {
    run_lesson 9 "Talking to AI (APIs)" \
"Your app talks to Ollama using HTTP requests — like a web browser loading a page.

In Python with requests:
  import requests

  response = requests.post(
      'http://localhost:11434/api/chat',
      json={
          'model': 'master-ai',
          'messages': [{'role': 'user', 'content': 'hello'}],
          'stream': False
      }
  )
  reply = response.json()['message']['content']
  print(reply)

This is exactly what master_ai.py does in ask_local().
The only difference is master_ai.py uses urllib instead of requests
(same thing, built into Python).

For cloud APIs (Groq, OpenAI) it's the same pattern
but with an Authorization header:
  headers = {'Authorization': 'Bearer YOUR_KEY'}" \
"In the Ollama API call above, what key in the JSON response contains the AI's reply?" \
"HTTP requests to AI APIs — Ollama and cloud providers" \
"curl python3"
}

lesson_10() {
    run_lesson 10 "Make a Real Change" \
"You now understand every part of master-ai.
Let's prove it with a real task.

Look at ~/scripts/master.sh — it has a menu with numbered options.
Each option calls a function at the top of the file.

For example option 2 calls check_ollama() which runs a curl command
and prints whether Ollama is running or not.

You can add your own option by:
1. Writing a new function above main_menu()
2. Adding an echo line to the menu
3. Adding a case line to handle the new number

The whole app is yours to edit. Nothing is locked.
Every script in ~/scripts/ is a plain text file." \
"Tell me: what file would you edit to add a new option to the master.sh menu, and what are the two things you need to add inside that file?" \
"master-ai architecture — adding features to master.sh" \
"nano cat grep bash"
}

# ── LINUX COMMANDS TRACK ─────────────────────────────────────
cmd_lesson() {
    local CMD="$1"
    local DESC="$2"
    local EXAMPLE="$3"
    local TASK="$4"

    clear
    banner_master_ai
    echo ""
    echo -e "${C}  ── LINUX COMMAND: ${W}${CMD}${X}"
    echo -e "${D}  ──────────────────────────────────────────────────────${X}"
    echo ""
    echo -e "${W}  ${DESC}${X}"
    echo ""
    show_live_help "$CMD"
    echo -e "${Y}  EXAMPLE:${X}"
    echo -e "${W}  ${EXAMPLE}${X}"
    echo ""
    echo -e "${D}  ──────────────────────────────────────────────────────${X}"
    echo -e "${Y}  YOUR TASK:${X}"
    echo -e "${W}  ${TASK}${X}"
    echo ""
    echo -ne "${C}  Answer: ${X}"
    read -r ANS
    if [ -n "$ANS" ]; then
        echo -e "${D}  Grading...${X}"
        local GRADE
        GRADE=$(grade_answer "Linux command: $CMD. Description: $DESC. Task: $TASK" "$ANS")
        GRADE=$(echo "$GRADE" | sed 's/^[[:space:]]*//' | tr -d '\r')
        if echo "$GRADE" | grep -qi "^PASS"; then
            echo -e "${G}  ✅ ${GRADE#PASS: }${X}"
        else
            CLEAN="${GRADE#FAIL: }"; CLEAN="${CLEAN#fail: }"
            echo -e "${Y}  ❌ ${CLEAN}${X}"
        fi
    fi
    echo ""
    echo -ne "${C}  Back to commands menu? (y/n): ${X}"
    read -r BACK
    [[ "$BACK" == "y" || "$BACK" == "Y" ]] && linux_menu
}

dojo_bash_tutor() {
    # Interactive 5-step lesson: learn the bash moves behind the dojo gate
    # by copy-pasting them. Lives in Learn Python, not in Sensei's gate.
    clear
    banner_master_ai
    echo ""
    echo -e "${BC}  ╔═════════════════════════════════════════════╗${X}"
    echo -e "${BC}  ║${X}  ${BW}🥷  DOJO BASH TUTOR — 5 moves${X}               ${BC}║${X}"
    echo -e "${BC}  ╚═════════════════════════════════════════════╝${X}"
    echo ""
    echo -e "  ${BW}Goal:${X} get comfortable with copy-paste, identifying bash,"
    echo -e "        and finding a project — the exact moves the Sensei gate does."
    echo ""
    echo -e "  Each step: ${BW}I show a command → you copy it → paste here → Enter.${X}"
    echo ""
    read -rp "  press Enter to start (or x to cancel) " go
    [[ "$go" =~ ^[xX]$ ]] && return

    # ── Step 1: identify bash ──
    clear
    echo ""
    echo -e "  ${BW}Move 1/5 — Identify bash${X}"
    echo ""
    echo -e "  Bash commands look like this:  ${G}ls ~/scripts${X}"
    echo -e "  A comment looks like this:     ${Y}# this is a note, not a command${X}"
    echo -e "  A shebang at the top of a file: ${C}#!/bin/bash${X}  (tells the OS to use bash)"
    echo ""
    echo -e "  ${BW}The prompt${X} — text your terminal shows before you type —"
    echo -e "  usually ends in ${C}\$${X} or ${C}#${X}. Everything AFTER the prompt is what you type."
    echo -e "  Everything NOT after a prompt is output."
    echo ""
    read -rp "  press Enter when ready " _

    # ── Step 2: copy-paste ──
    clear
    echo ""
    echo -e "  ${BW}Move 2/5 — Copy & paste safely${X}"
    echo ""
    echo -e "  ${BW}Copy this command:${X}"
    echo ""
    echo -e "      ${G}echo \"hello dojo\"${X}"
    echo ""
    echo -e "  Highlight it with your mouse/finger → right-click → Copy."
    echo -e "  Then right-click in this terminal → Paste → press Enter."
    echo ""
    echo -e "  ${Y}Safety rule:${X} never paste commands you don't recognize."
    echo -e "  Red flags: ${R}curl ... | bash${X}, ${R}sudo${X}, ${R}rm -rf${X} from strangers."
    echo ""
    while true; do
        read -rp "  paste here: " typed
        case "$typed" in
            *"hello dojo"*)
                echo -e "  ${G}✅ paste worked.${X} The shell ran your pasted text as a command."
                break ;;
            "") echo -e "  ${Y}nothing pasted — try again (right-click → Paste)${X}" ;;
            *)
                echo -e "  ${Y}got:${X} $typed"
                echo -e "  ${Y}expected something containing 'hello dojo' — try copying again${X}" ;;
        esac
    done
    sleep 1

    # ── Step 3: open a project folder ──
    clear
    echo ""
    echo -e "  ${BW}Move 3/5 — Open a project folder${X}"
    echo ""
    echo -e "  ${BW}~${X} means your home folder (${C}$HOME${X})."
    echo -e "  ${BW}/${X} separates folders — like ${C}~/scripts/PROJECTS.md${X}"
    echo ""
    echo -e "  ${BW}Copy + paste:${X}"
    echo ""
    echo -e "      ${G}ls ~/scripts${X}"
    echo ""
    echo -e "  It lists every file in your scripts folder."
    echo ""
    while true; do
        read -rp "  paste here: " typed
        if [[ "$typed" =~ ^ls[[:space:]]+~?/?scripts ]] || [[ "$typed" =~ ^ls[[:space:]]+\$HOME/scripts ]]; then
            echo -e "  ${G}✅ correct.${X} Running it for you:"
            echo ""
            ls ~/scripts | head -20 | sed 's/^/    /'
            echo -e "  ${D}(truncated to 20 lines)${X}"
            break
        elif [ -z "$typed" ]; then
            echo -e "  ${Y}paste the line above${X}"
        else
            echo -e "  ${Y}close — expected:${X} ${G}ls ~/scripts${X}"
        fi
    done
    read -rp "  press Enter to continue " _

    # ── Step 4: find a project ──
    clear
    echo ""
    echo -e "  ${BW}Move 4/5 — Find a project${X}"
    echo ""
    echo -e "  Project names live in ${C}~/scripts/PROJECTS.md${X} under headings"
    echo -e "  that start with ${C}### ${X}(three hashes + space)."
    echo ""
    echo -e "  ${BW}The pipe (|) chains two commands:${X}"
    echo -e "      ${G}cat${X}  = show file contents"
    echo -e "      ${G}grep '^### '${X} = keep only lines starting with ### (^ = start)"
    echo ""
    echo -e "  ${BW}Copy + paste:${X}"
    echo ""
    echo -e "      ${G}cat ~/scripts/PROJECTS.md | grep '^### '${X}"
    echo ""
    while true; do
        read -rp "  paste here: " typed
        if [[ "$typed" == *"PROJECTS.md"* ]] && [[ "$typed" == *"### "* ]]; then
            echo -e "  ${G}✅ correct.${X} Output:"
            echo ""
            cat ~/scripts/PROJECTS.md | grep '^### ' | sed 's/^/    /'
            break
        elif [ -z "$typed" ]; then
            echo -e "  ${Y}paste the line above${X}"
        else
            echo -e "  ${Y}expected a line referencing PROJECTS.md and '### '${X}"
        fi
    done
    read -rp "  press Enter to continue " _

    # ── Step 5: pick one ──
    clear
    echo ""
    echo -e "  ${BW}Move 5/5 — Paste a project name${X}"
    echo ""
    echo -e "  Pick one from the list above and type its exact name."
    echo -e "  (e.g. ${C}Sensei${X}, ${C}Pupil${X}, ${C}Master AI${X})"
    echo ""
    local -a valid_names
    mapfile -t valid_names < <(awk '
        /^## Project Boards/ { in_b = 1; next }
        /^## / && in_b  { in_b = 0 }
        /^### / && in_b { sub(/^### /, ""); print }
    ' "$HOME/scripts/PROJECTS.md")
    while true; do
        read -rp "  project name: " pick
        local hit=0
        for n in "${valid_names[@]}"; do
            if [ "$n" = "$pick" ]; then
                hit=1
                echo -e "  ${G}✅ matched:${X} ${BW}$n${X}"
                echo ""
                echo -e "  ${BW}🥷 Tutor complete.${X} You can now:"
                echo -e "    • tell bash apart from comments + output"
                echo -e "    • copy/paste safely"
                echo -e "    • list folders (${G}ls${X})"
                echo -e "    • read + filter files (${G}cat | grep${X})"
                echo -e "    • select a project by name"
                echo ""
                echo -e "  Next: try the Sensei gate (${C}master.sh → 4${X}) and do it live."
                echo ""
                read -rp "  press Enter to return to learn menu " _
                return 0
            fi
        done
        if [ "$hit" -eq 0 ]; then
            if [ -z "$pick" ]; then
                echo -e "  ${Y}enter a project name exactly as shown${X}"
            else
                echo -e "  ${Y}no match. valid: ${valid_names[*]}${X}"
            fi
        fi
    done
}

linux_menu() {
    clear
    banner_master_ai
    echo ""
    echo -e "${C}  ── LINUX COMMANDS ──────────────────────────────────────${X}"
    echo -e "${D}  Each command shows live system help + real use in your scripts${X}"
    echo ""
    echo -e "  ${Y}1)${W}  ls        ${D}— list files and folders${X}"
    echo -e "  ${Y}2)${W}  cd        ${D}— change directory${X}"
    echo -e "  ${Y}3)${W}  cat       ${D}— read a file${X}"
    echo -e "  ${Y}4)${W}  grep      ${D}— search inside files${X}"
    echo -e "  ${Y}5)${W}  curl      ${D}— fetch URLs / talk to APIs${X}"
    echo -e "  ${Y}6)${W}  chmod     ${D}— change file permissions${X}"
    echo -e "  ${Y}7)${W}  ps        ${D}— list running processes${X}"
    echo -e "  ${Y}8)${W}  kill      ${D}— stop a process${X}"
    echo -e "  ${Y}9)${W}  systemctl ${D}— manage system services${X}"
    echo -e "  ${Y}10)${W} man       ${D}— read the manual for any command${X}"
    echo ""
    echo -e "  ${Y}L)${W}  Look up any command  ${D}(type the name)${X}"
    echo -e "  ${Y}x)${W}  Back to main menu${X}"
    echo ""
    echo -ne "${C}  Choose (1-10, L, x): ${X}"
    read -r C

    case "$C" in
        1) cmd_lesson "ls" \
            "Lists files and folders in the current directory." \
            "ls ~/scripts/   → shows all files in your scripts folder" \
            "What flag would you add to ls to show hidden files?" ;;
        2) cmd_lesson "cd" \
            "Changes your current directory." \
            "cd ~/scripts/   → moves into your scripts folder" \
            "How would you go back one folder from wherever you are?" ;;
        3) cmd_lesson "cat" \
            "Prints the contents of a file to the terminal." \
            "cat ~/.master_ai_memory   → shows your AI memory file" \
            "What command reads the file ~/.master_ai_active_task?" ;;
        4) cmd_lesson "grep" \
            "Searches inside files for text matching a pattern." \
            "grep 'MODEL' ~/scripts/pc_control.sh   → finds MODEL lines" \
            "How would you search all .sh files in ~/scripts/ for the word 'ollama'?" ;;
        5) cmd_lesson "curl" \
            "Transfers data from URLs — used to call APIs like Ollama." \
            "curl http://localhost:11434/api/tags   → checks Ollama models" \
            "What curl command checks if Ollama is running on port 11434?" ;;
        6) cmd_lesson "chmod" \
            "Changes who can read, write, or execute a file." \
            "chmod +x script.sh   → makes a script runnable" \
            "What chmod command makes master.sh executable?" ;;
        7) cmd_lesson "ps" \
            "Shows processes currently running on the system." \
            "ps aux | grep ollama   → checks if ollama is running" \
            "What command + grep would check if python3 is running?" ;;
        8) cmd_lesson "kill" \
            "Stops a running process by its process ID." \
            "kill 1234   → stops process with ID 1234" \
            "What command shows you a process ID so you know what to kill?" ;;
        9) cmd_lesson "systemctl" \
            "Controls system services — start, stop, check status." \
            "systemctl status ollama   → checks if Ollama service is running" \
            "What systemctl command would restart the ollama service?" ;;
        10) cmd_lesson "man" \
            "Opens the full manual page for any command." \
            "man ls   → full documentation for the ls command" \
            "What command gives a one-line description of curl without opening the full manual?" ;;
        l|L)
            echo -ne "${C}  Command name: ${X}"
            read -r LOOKUP
            LOOKUP=$(echo "$LOOKUP" | xargs)
            if [ -n "$LOOKUP" ]; then
                clear
                banner_master_ai
                echo ""
                echo -e "${C}  ── Looking up: ${W}${LOOKUP}${X}"
                echo ""
                show_live_help "$LOOKUP"
            fi
            echo -ne "${C}  Back to commands menu? (y/n): ${X}"
            read -r BACK
            [[ "$BACK" == "y" || "$BACK" == "Y" ]] && linux_menu
            ;;
        x|X) main; return ;;
        *) echo -e "${D}  Invalid option.${X}"; sleep 1; linux_menu ;;
    esac
}

# ── MAIN MENU ────────────────────────────────────────────────
main() {
    init_progress
    local UNLOCKED
    UNLOCKED=$(get_unlocked)
    local COMPLETED
    COMPLETED=$(get_completed)

    clear
    banner_master_ai
    echo ""
    echo -e "${C}  ── LEARN MODE ──────────────────────────────────────────${X}"
    echo -e "${D}  Terminal + Linux commands + Python + how to build AI apps${X}"
    echo ""
    echo -e "${BC}  ── TRACK 1: LINUX COMMANDS ────────────────────────────${X}"
    echo -e "  ${Y}c)${W}  Linux Commands  ${D}— learn commands used by PC Control${X}"
    echo -e "  ${Y}b)${W}  Dojo Bash Tutor ${D}— 5 moves to talk to Sensei (copy-paste, find a project)${X}"
    echo ""
    echo -e "${BC}  ── TRACK 2: PYTHON + BUILD AI APPS ────────────────────${X}"

    local lessons=(
        "1:Terminal Basics"
        "2:Reading a Bash Script"
        "3:Python Basics"
        "4:Making Decisions"
        "5:Loops"
        "6:Functions"
        "7:Files and JSON"
        "8:Running Commands"
        "9:Talking to AI"
        "10:Make a Real Change"
    )

    for entry in "${lessons[@]}"; do
        local num="${entry%%:*}"
        local title="${entry##*:}"
        if echo "$COMPLETED" | grep -qw "$num"; then
            echo -e "  ${Y}${num})${X} ${W}${title}${D}  ✅ complete${X}"
        elif [ "$num" -le "$UNLOCKED" ]; then
            echo -e "  ${Y}${num})${X} ${G}${title}${D}  ← start here${X}"
        else
            echo -e "  ${D}${num}) ${title}  🔒 locked${X}"
        fi
    done

    echo ""
    echo -e "  ${Y}r)${W} Review a completed lesson chat${X}"
    echo -e "  ${Y}x)${W} Exit${X}"
    echo ""
    echo -ne "${C}  Choose (c for commands, 1-10 for Python, r, x): ${X}"
    read -r CHOICE

    case "$CHOICE" in
        c|C) linux_menu ;;
        b|B) dojo_bash_tutor ;;
        1)  [ "$UNLOCKED" -ge 1 ] && lesson_1  || echo -e "${R}  🔒 Locked.${X}" ;;
        2)  [ "$UNLOCKED" -ge 2 ] && lesson_2  || echo -e "${R}  🔒 Complete lesson 1 first.${X}" ;;
        3)  [ "$UNLOCKED" -ge 3 ] && lesson_3  || echo -e "${R}  🔒 Complete lesson 2 first.${X}" ;;
        4)  [ "$UNLOCKED" -ge 4 ] && lesson_4  || echo -e "${R}  🔒 Complete lesson 3 first.${X}" ;;
        5)  [ "$UNLOCKED" -ge 5 ] && lesson_5  || echo -e "${R}  🔒 Complete lesson 4 first.${X}" ;;
        6)  [ "$UNLOCKED" -ge 6 ] && lesson_6  || echo -e "${R}  🔒 Complete lesson 5 first.${X}" ;;
        7)  [ "$UNLOCKED" -ge 7 ] && lesson_7  || echo -e "${R}  🔒 Complete lesson 6 first.${X}" ;;
        8)  [ "$UNLOCKED" -ge 8 ] && lesson_8  || echo -e "${R}  🔒 Complete lesson 7 first.${X}" ;;
        9)  [ "$UNLOCKED" -ge 9 ] && lesson_9  || echo -e "${R}  🔒 Complete lesson 8 first.${X}" ;;
        10) [ "$UNLOCKED" -ge 10 ] && lesson_10 || echo -e "${R}  🔒 Complete lesson 9 first.${X}" ;;
        r|R)
            echo -ne "${C}  Which lesson to review (1-10): ${X}"
            read -r REV
            CHAT="$CHAT_DIR/lesson_${REV}.json"
            if [ -f "$CHAT" ]; then
                echo ""
                python3 -c "
import json
chats = json.load(open('$CHAT'))
for c in chats:
    role = c['role'].upper()
    print(f'  [{role}]: {c[\"content\"]}')
    print()
"
            else
                echo -e "${Y}  No chat saved for lesson ${REV} yet.${X}"
            fi
            ;;
        x|X) echo -e "${G}  Keep learning!${X}"; exit 0 ;;
        *) echo -e "${D}  Invalid option.${X}" ;;
    esac

    echo ""
    echo -ne "${C}  Back to lessons menu? (y/n): ${X}"
    read -r AGAIN
    [[ "$AGAIN" == "y" || "$AGAIN" == "Y" ]] && main
}

main
