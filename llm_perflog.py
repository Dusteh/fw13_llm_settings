#!/usr/bin/env python3
"""Track local LLM speed against the laptop's power/thermal state over days.

Passive: reads Ollama's per-request timings from the journal (so it measures real
opencode work without loading a second model), and samples the APU's firmware
limits, temperatures, clocks and power source.

  llm_perflog.py start          run in the background (systemd user unit)
  llm_perflog.py stop | status
  llm_perflog.py run            run in the foreground
  llm_perflog.py report [DAYS]  summarise the last DAYS days (default 3)

Logs: perflog/requests-YYYY-MM-DD.csv (one row per request) and
      perflog/samples-YYYY-MM-DD.csv (one row every SAMPLE_SECS).
"""
import csv, glob, json, os, re, statistics, struct, subprocess, sys, threading, time, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "perflog")
UNIT = "llm-perflog"
SAMPLE_SECS = 10
DEV = "/sys/class/drm/card1/device"
PM_TABLE = "/sys/kernel/ryzen_smu_drv/pm_table"
# pm_table offsets for Phoenix table version 0x4C0009, from RyzenAdj lib/api.c
PM_FIELDS = {"stapm": 0x4, "stapm_lim": 0x0, "fast_lim": 0x8, "slow": 0x14, "slow_lim": 0x10,
             "skin": 0x5C, "skin_lim": 0x58}
CAPPED_BELOW_W = 30  # stock limits are 53 fast / 35 slow; the coding cap sets both to 27 W

SAMPLE_COLS = ["time", "capped", "stapm_w", "stapm_lim_w", "fast_lim_w", "slow_w", "slow_lim_w",
               "skin_c", "skin_lim_c", "gpu_c", "gpu_busy", "sclk", "mclk", "fclk",
               "source", "battery", "model"]
REQUEST_COLS = ["time", "model", "ctx_tokens", "prompt_tokens", "prompt_tps", "gen_tokens", "gen_tps",
                "capped", "slow_lim_w", "stapm_lim_w", "skin_c", "gpu_c", "sclk", "source"]

latest = {}  # most recent sample, attached to each request row
lock = threading.Lock()


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def active_level(name):
    for line in read(f"{DEV}/{name}").splitlines():
        if "*" in line:
            return line.split(":")[1].strip(" *").replace("Mhz", "")
    return ""


def power_source():
    for p in glob.glob("/sys/class/power_supply/ucsi-source-psy-*"):
        if read(f"{p}/online") == "1":
            watts = int(read(f"{p}/voltage_max", "0")) * int(read(f"{p}/current_max", "0")) / 1e12
            return f"{watts:.0f}W"
    return "battery"


def loaded_model():
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=2) as r:
            models = json.load(r).get("models", [])
        return "+".join(m["name"] for m in models)
    except Exception:
        return ""


def cap_state(pm):
    # The coding cap lowers fast and slow together. The firmware's own skin cut drops
    # only slow (to ~15 W) and puts fast back to stock, so tell the two apart.
    if pm["fast_lim"] < CAPPED_BELOW_W:
        return "yes"
    if pm["slow_lim"] < CAPPED_BELOW_W:
        return "fw_cut"
    return "no"


def sample():
    s = {"time": datetime.now().isoformat(timespec="seconds")}
    try:
        with open(PM_TABLE, "rb") as f:
            raw = f.read(0x60)
        pm = {k: struct.unpack_from("<f", raw, o)[0] for k, o in PM_FIELDS.items()}
        s.update(stapm_w=f"{pm['stapm']:.1f}", stapm_lim_w=f"{pm['stapm_lim']:.0f}",
                 fast_lim_w=f"{pm['fast_lim']:.0f}", slow_w=f"{pm['slow']:.1f}",
                 slow_lim_w=f"{pm['slow_lim']:.0f}", skin_c=f"{pm['skin']:.1f}",
                 skin_lim_c=f"{pm['skin_lim']:.1f}",
                 capped=cap_state(pm))
    except OSError:
        s["capped"] = "unknown"  # ryzen_smu not loaded (sudo modprobe ryzen_smu)
    hw = glob.glob(f"{DEV}/hwmon/hwmon*")
    if hw:
        s["gpu_c"] = f"{int(read(hw[0] + '/temp1_input', '0')) / 1000:.0f}"
    s.update(gpu_busy=read(f"{DEV}/gpu_busy_percent"), sclk=active_level("pp_dpm_sclk"),
             mclk=active_level("pp_dpm_mclk"), fclk=active_level("pp_dpm_fclk"),
             source=power_source(), model=loaded_model())
    bats = glob.glob("/sys/class/power_supply/BAT*")
    s["battery"] = f"{read(bats[0] + '/status')} {read(bats[0] + '/capacity')}%" if bats else ""
    return s


def append(kind, cols, row):
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"{kind}-{row['time'][:10]}.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


def sampler():
    while True:
        s = sample()
        with lock:
            latest.clear()
            latest.update(s)
        append("samples", SAMPLE_COLS, s)
        time.sleep(SAMPLE_SECS)


NEW_PROMPT = re.compile(r"task (\d+) \| new prompt.*task\.n_tokens = (\d+)")
PROMPT_EVAL = re.compile(r"task (\d+) \| prompt eval time = +[\d.]+ ms / +(\d+) tokens .* ([\d.]+) tokens per second")
GEN_EVAL = re.compile(r"task (\d+) \| +eval time = +[\d.]+ ms / +(\d+) tokens .* ([\d.]+) tokens per second")


def follow_ollama():
    tasks = defaultdict(dict)
    proc = subprocess.Popen(["journalctl", "-u", "ollama", "-f", "-n", "0", "-o", "cat"],
                            stdout=subprocess.PIPE, text=True, bufsize=1)
    for line in proc.stdout:
        if m := NEW_PROMPT.search(line):
            tasks[m[1]] = {"ctx_tokens": m[2]}
        elif m := PROMPT_EVAL.search(line):
            tasks[m[1]].update(prompt_tokens=m[2], prompt_tps=m[3])
        elif m := GEN_EVAL.search(line):
            t = tasks.pop(m[1], {})
            with lock:
                snap = dict(latest)
            row = {**{k: snap.get(k, "") for k in REQUEST_COLS}, **t,
                   "time": datetime.now().isoformat(timespec="seconds"),
                   "gen_tokens": m[2], "gen_tps": m[3]}
            append("requests", REQUEST_COLS, row)


def run():
    threading.Thread(target=sampler, daemon=True).start()
    follow_ollama()


def load(kind, days):
    since = (datetime.now() - timedelta(days=days)).isoformat()
    rows = []
    for path in sorted(glob.glob(os.path.join(LOG_DIR, f"{kind}-*.csv"))):
        with open(path) as f:
            rows += [r for r in csv.DictReader(f) if r["time"] >= since]
    return rows


def med(vals):
    vals = [float(v) for v in vals if v]
    return f"{statistics.median(vals):6.1f}" if vals else "     -"


def report(days):
    reqs = load("requests", days)
    # Ignore tiny generations (titles, single tool calls): their tok/s is noisy.
    reqs = [r for r in reqs if r["gen_tokens"] and int(r["gen_tokens"]) >= 20]
    if not reqs:
        print(f"No requests with 20+ generated tokens in the last {days} day(s).")
        return
    print(f"Requests (20+ generated tokens), last {days} day(s): {len(reqs)}\n")
    print("Median speed by model, cap state and context size (tok/s):")
    print(f"  {'model':36} {'capped':8} {'context':>8} {'n':>5} {'gen':>6} {'prompt':>6}")
    def bucket(r):
        c = int(r["ctx_tokens"] or 0)
        return "<4k" if c < 4000 else "4k-12k" if c < 12000 else "12k+"
    groups = defaultdict(list)
    for r in reqs:
        groups[(r["model"] or "unknown", r["capped"] or "unknown", bucket(r))].append(r)
    for (model, capped, b), rs in sorted(groups.items()):
        print(f"  {model[:36]:36} {capped:8} {b:>8} {len(rs):5} {med(r['gen_tps'] for r in rs)} "
              f"{med(r['prompt_tps'] for r in rs)}")

    print("\nBy day (median gen tok/s, skin estimate, GPU temp at request time):")
    by_day = defaultdict(list)
    for r in reqs:
        by_day[r["time"][:10]].append(r)
    for day, rs in sorted(by_day.items()):
        capped = sum(r["capped"] == "yes" for r in rs)
        print(f"  {day}  n={len(rs):4}  capped={capped:4}  gen {med(r['gen_tps'] for r in rs)}  "
              f"skin {med(r['skin_c'] for r in rs)}C  gpu {med(r['gpu_c'] for r in rs)}C")

    slow = [r for r in reqs if float(r["gen_tps"]) < 18]
    if slow:
        print(f"\nSlowest requests (< 18 tok/s): {len(slow)}")
        for r in slow[-10:]:
            print(f"  {r['time']}  {float(r['gen_tps']):5.1f} tok/s  ctx {r['ctx_tokens']:>6}  "
                  f"capped={r['capped']}  slow_lim={r['slow_lim_w']}W  stapm_lim={r['stapm_lim_w']}W  "
                  f"skin={r['skin_c']}C  gpu={r['gpu_c']}C  sclk={r['sclk']}  {r['source']}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "run":
        run()
    elif cmd == "start":
        subprocess.run(["systemd-run", "--user", f"--unit={UNIT}", "--collect",
                        sys.executable, "-I", os.path.abspath(__file__), "run"], check=True)
        print(f"Logging to {LOG_DIR}. Stop with: {sys.argv[0]} stop")
    elif cmd == "stop":
        subprocess.run(["systemctl", "--user", "stop", UNIT])
    elif cmd == "status":
        subprocess.run(["systemctl", "--user", "status", UNIT, "--no-pager", "-n", "5"])
    elif cmd == "report":
        report(int(sys.argv[2]) if len(sys.argv) > 2 else 3)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
