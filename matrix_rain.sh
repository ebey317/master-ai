#!/usr/bin/env bash
# Matrix rain spelling MASTER AI. Ctrl-C to exit.
exec python3 - <<'PYEOF'
import os, sys, random, time, signal, shutil

if not sys.stdout.isatty():
    sys.stderr.write("matrix_rain.sh needs a real terminal.\n"
                     "Open a shell window and run: ~/scripts/matrix_rain.sh\n")
    sys.exit(2)

GREEN  = '\033[32m'
BGREEN = '\033[1;32m'
WHITE  = '\033[1;97m'
RESET  = '\033[0m'
HIDE   = '\033[?25l'
SHOW   = '\033[?25h'
CLEAR  = '\033[2J\033[H'
BG_ON  = '\033[40m'
BG_OFF = '\033[49m'

LETTERS = {
    'M': ["##     ##","###   ###","#### ####","## ### ##","##     ##","##     ##","##     ##"],
    'A': ["   ###   ","  ## ##  "," ##   ## ","##     ##","#########","##     ##","##     ##"],
    'S': [" ######  ","##    ## ","##       "," ######  ","      ## ","##    ## "," ######  "],
    'T': ["#########","    #    ","    #    ","    #    ","    #    ","    #    ","    #    "],
    'E': ["#########","##       ","##       ","#######  ","##       ","##       ","#########"],
    'R': ["######## ","##     ##","##     ##","######## ","##   ##  ","##    ## ","##     ##"],
    'I': ["####"," ## "," ## "," ## "," ## "," ## ","####"],
    ' ': ["   ","   ","   ","   ","   ","   ","   "],
}
WORD = "MASTER AI"
BANNER = [" ".join(LETTERS[c][r] for c in WORD) for r in range(7)]
BH = len(BANNER)
BW = len(BANNER[0])

def cleanup(*_):
    sys.stdout.write(SHOW + RESET + BG_OFF + CLEAR)
    sys.stdout.flush()
    sys.exit(0)

signal.signal(signal.SIGINT,  cleanup)
signal.signal(signal.SIGTERM, cleanup)

cols, rows = shutil.get_terminal_size((80, 24))
b_top  = max(0, (rows - BH) // 2)
b_left = max(0, (cols - BW) // 2)

banner_mask = [[False]*cols for _ in range(rows)]
for i, line in enumerate(BANNER):
    rr = b_top + i
    if rr >= rows: break
    for j, ch in enumerate(line):
        cc = b_left + j
        if cc >= cols: break
        if ch != ' ':
            banner_mask[rr][cc] = True

heads  = [random.randint(-rows, 0) for _ in range(cols)]
speeds = [random.choice([1, 1, 1, 2]) for _ in range(cols)]
chars  = "abcdefghijklmnopqrstuvwxyz0123456789@#$%&*+=<>?/\\|"

sys.stdout.write(BG_ON + HIDE + CLEAR)

def draw_banner():
    for i, line in enumerate(BANNER):
        sys.stdout.write(f'\033[{b_top+i+1};{b_left+1}H{WHITE}{line}{RESET}{BG_ON}')

try:
    while True:
        out = []
        for c in range(cols):
            head = heads[c]
            tail = head - 12
            if 0 <= tail < rows and not banner_mask[tail][c]:
                out.append(f'\033[{tail+1};{c+1}H ')
            body = head - 3
            if 0 <= body < rows and not banner_mask[body][c]:
                out.append(f'\033[{body+1};{c+1}H{GREEN}{random.choice(chars)}')
            if 0 <= head < rows and not banner_mask[head][c]:
                out.append(f'\033[{head+1};{c+1}H{BGREEN}{random.choice(chars)}')
            heads[c] = head + speeds[c]
            if heads[c] - 14 > rows:
                heads[c] = random.randint(-8, 0)
        sys.stdout.write(''.join(out))
        draw_banner()
        sys.stdout.flush()
        time.sleep(0.06)
except KeyboardInterrupt:
    cleanup()
finally:
    cleanup()
PYEOF
