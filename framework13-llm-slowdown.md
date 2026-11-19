# Framework 13 (7840U) local LLM slowdown: diagnosis

Nov 18, 2026 · Dustin · Shared doc: https://claude.ai/artifact/3L1nAkKQ3Y2y5XzUYnUbSr

## Summary

Local LLM generation slows from \~33 to \~20 tokens/s because the APU firmware's skin-temperature limit (STT, 43.5 °C) pulls the STAPM power limit down under sustained load. The skin temperature is an estimate from power history, so a laptop stand does not help. GPU clocks and memory were not the cause.

- **Cause:** about a minute into a sustained run, as the estimated skin temperature neared 43.5 °C, the STAPM limit began falling, and it reached 30 W two minutes later.
- **What didn't work:** the memory-fragmentation theory was wrong. Forcing `power_dpm_force_performance_level=high` hard-froze the machine and should stay on `auto`.
- **Fix:** a 50 °C skin limit only delayed a harder drop to 15 W. Cap package power at 22 W with RyzenAdj, by hand, before coding sessions, with Secure Boot still on. 27 W held 30.4–31.6 tok/s in benchmarks on both supplies, but real opencode use at 10–14k context still triggered the firmware's 15 W cut, so 22 W replaced it.
- **Separate win:** switching opencode to the non-reasoning Instruct model cut session-title time from 29–80 s to 1 s.
- **Model switch:** opencode now runs Qwen3.6-35B-A3B with thinking turned off. Prompt processing is about 2× faster than Qwen3 30B-A3B Instruct, and generation slightly slower.
- **Engine:** Vulkan beat ROCm. ROCm cost about 25% of generation speed on both models.
- **Runtime:** Ollama matches a standalone llama-server; no reason to switch.

## Current recommended setup

This is the best configuration found so far. The model has been on trial since 2026-11-18, with coding quality being judged on real work, and the 22 W cap has had only a few hours of real use.

| Part | Setting | Why |
| --- | --- | --- |
| Model | `qwen3.6:35b-a3b` as both `model` and `small_model`, with `"options": {"reasoning_effort": "none"}` in `opencode.json`; limit 24576 context / 4096 output | MoE, \~3B active; \~2× faster prompt processing. Thinking is on by default, so the option is required. Qwen3 30B-A3B Instruct stays in the picker as a fallback |
| Engine | Ollama on Vulkan, flash attention on, model 100% on the GPU, Ollama's own batch settings (`-ub 1024`) | ROCm was tested and rejected (see Engine: Vulkan vs ROCm); for Qwen3.6, `-ub 512` was \~10% slower on long prompts (see Ollama vs llama-server) |
| Keep-alive | `OLLAMA_KEEP_ALIVE=30m`, in `/etc/systemd/system/ollama.service.d/keepalive.conf` | The 5-minute default unloaded the model and lost its cache during pauses |
| Power cap | `llm_mode.sh`: `sudo modprobe ryzen_smu`, then `sudo ~/bin/ryzenadj --apu-skin-temp=43 --stapm-limit=22000 --fast-limit=22000 --slow-limit=22000` | Avoids the firmware's 15 W cut. Run by hand before coding; resets on charger unplug |
| GPU driver | `power_dpm_force_performance_level` left on `auto` | Forcing `high` froze the system |
| Monitoring | `llm_perflog.py` | Per-request speed logged against the power state and model |

Expected with Qwen3.6: \~24–26 tok/s generation on short contexts, \~19–23 tok/s at \~10k, and \~207–267 tok/s processing a 10k-token prompt.

## Setup

| Part | Detail |
| --- | --- |
| Laptop | Framework Laptop 13, Ryzen 7 7840U (Phoenix), Radeon 780M iGPU, 53 GiB RAM visible |
| OS | Ubuntu 26.04.1 LTS, kernel 7.0.0-43-generic, Secure Boot on (lockdown = integrity) |
| Power and display | 100 W USB-C dock (20 V × 5 A) driving an external monitor; laptop on a stand |
| Runtime | Ollama (llama.cpp, Vulkan backend), model fully on the GPU |
| Client | opencode, pointed at Ollama's OpenAI-compatible API |
| Models | Qwen3 30B-A3B, Q4\_K\_M: a mixture-of-experts model, 30.5B parameters, \~3B active per token, \~18 GB on disk |

## Symptom

The same model ran at \~33 tokens/s right after the laptop had been idle, and \~20 tokens/s after sustained use. opencode felt slower still, \~13 tokens/s, because its prompts carry \~9,000 tokens of context.

| Benchmark (Instruct model, warm) | Prompt speed | Generation speed |
| --- | --- | --- |
| Short prompt (23 tokens) | \~596 tok/s | 21.8–22.3 tok/s |
| \~6,300-token prompt | \~151 tok/s | \~16 tok/s |
| \~9,100-token prompt (opencode-sized) | \~107–110 tok/s | 13.4–14.0 tok/s |

The fast runs only ever happened after idle time, which was the clue that pointed to a power or thermal limit rather than software.

## Model choice

The Ollama tag `qwen3:30b-a3b` is the reasoning-only "Qwen3 30B A3B Thinking 2507" build, and none of `think:false`, `reasoning_effort:none` or `/no_think` turns its reasoning off. Every opencode request, including background session titles, wrote hundreds of reasoning tokens first.

| Request | Thinking build | Instruct build (`qwen3:30b-a3b-instruct-2507-q4_K_M`) |
| --- | --- | --- |
| Session title | 29–80 s, 544–1,500 tokens, sometimes no answer | 1.0 s, 6 tokens |
| One tool call | 11.6 s, 186 tokens | 2.4 s, 22 tokens |

opencode now uses the Instruct build as both `model` and `small_model`; the Thinking build stays in the picker for hard problems. Both have the same architecture and speed per token.

## Wrong turns

Two earlier theories were wrong, and one of the tests crashed the machine.

**Memory fragmentation (disproved).** One fast run followed a memory compaction, so fragmentation looked like the cause. It wasn't: with 40.2 GiB free in large blocks after dropping caches and compacting, the model still generated only 21.8 tok/s. The fast runs had simply followed idle time.

**Forcing the GPU to `high` (hard freeze).** Logging under load showed the GPU at 96% busy but held at its 800 MHz minimum clock, at 12–16 W. Setting `/sys/class/drm/card1/device/power_dpm_force_performance_level` to `high` and starting a benchmark froze the whole system about 12 s later. The journal simply stops, with no amdgpu reset, timeout or panic logged. About a minute earlier the dock's monitor had been re-detected over DisplayPort MST.

Others have reported a [Thunderbolt-dock MST crash on a 7840U Framework 13](https://lists.linaro.org/archives/list/linux-stable-mirror@lists.linaro.org/thread/FLZC6HZ4FQLB5ABRY4VMB3TGNQ757UZY), [`high` hanging an AMD GPU](https://gitlab.freedesktop.org/drm/amd/-/issues/1839), and [`high` leaving clocks stuck low anyway](https://gitlab.freedesktop.org/drm/amd/-/issues/2842). The setting doesn't touch the real limit (below) and resets on reboot. **Leave it on `auto`.**

## Root cause: the skin-temperature power limit

The firmware's STAPM power limit, not the GPU driver, throttles sustained load. In a 5-minute test it began falling at 19:14:27, with the estimated skin temperature at 40.3 °C, and kept falling about 1 W every 5 s after the estimate passed 43.5 °C.

ryzen\_smu pm\_table, sampled every 5 s · 18 Nov 2026, 19:13:27–19:16:52 (10 × 512-token llama-bench runs):

| Time | Skin estimate (limit 43.5 °C) | STAPM limit | GPU temp | Speed |
| --- | --- | --- | --- | --- |
| 19:13:27 | 35.7 °C | 53 W | 47 °C | 32.7 tok/s |
| 19:14:27 | 40.3 °C | 52 W | 95 °C | 32.1 |
| 19:15:02 | 43.8 °C | 48 W | 97 °C | 32.1 |
| 19:15:42 | 46.1 °C | 40 W | 100 °C | 31.7 |
| 19:16:27 | 47.9 °C | 30 W | 96 °C | 30.8–31.1 |

STAPM (Skin Temperature-Aware Power Management) and STT (skin temperature tracking) don't measure the case. They estimate it from recent power draw, so a stand's airflow barely changes the result. Generation held 32.7 tok/s at the start and 31.1 tok/s at the end, because the limit had only just reached the \~30–35 W the chip draws. In longer sessions the limit keeps falling, and earlier logging caught the chip at 12–16 W and \~20 tok/s.

The GPU also reached its 100 °C core limit during the run. Its clock stayed at 1.6–2.7 GHz under load with the driver on `auto`.

**Limits at idle**, read with `ryzenadj -i`:

| Limit | Value |
| --- | --- |
| STAPM | 53 W |
| PPT fast | 53 W |
| PPT slow | 35 W |
| PPT APU | 41 W |
| APU skin temperature (STT) | 43.5 °C (36.0 °C at idle) |
| Core temperature (tctl) | 100 °C |

Reading these limits under Secure Boot needed the amkillam fork of the `ryzen_smu` kernel module, because lockdown blocks RyzenAdj's default `/dev/mem` route (see Commands).

## Tried: raising the skin limit to 50 °C

The APU skin limit was raised from 43.5 °C to 50 °C with `ryzenadj --apu-skin-temp=50`, which reported "Successfully set apu\_skin\_temp\_limit to 50". It held full speed for about 4 minutes. Then the GPU hit its 100 °C limit and the firmware cut power to a hard 15 W (see the retest below). It is not recommended as a permanent setting.

- **Hotter case.** 43.5 °C is the firmware's comfort limit for a laptop resting on a lap. 50 °C is meant for desk or stand use only.
- **It may not persist.** Forum users report the firmware resets RyzenAdj limits after the chassis cools or the charger is unplugged. The chosen cap is applied by hand instead (see the current recommended setup above); the forum's automatic approach is [AlxHnr's amd-ryzen-ignore-stapm](https://github.com/AlxHnr/amd-ryzen-ignore-stapm).
- **It delays the drop rather than removing it.** One user in the [Framework thread](https://community.frame.work/t/radeon-780m-thermal-throttling-stays-on-until-i-reboot/58576) saw no change from raising only the skin limit. Here it held as set, but other limits took over, so the next step lowers `--stapm-limit` and `--slow-limit`.
- **The ceiling is low anyway.** The GPU already sits at its 100 °C limit, and in the retest it throttled there before the skin limit was reached.

## Retest with skin limit 50 °C

Raising the skin limit worked as set but only delayed the drop and made it sharper: speed held \~32 tok/s for 6 runs, slid to \~27 tok/s, then fell to 16.5 tok/s at a hard 15 W.

15 × llama-bench tg512 runs, 18 Nov 2026 19:20–19:25, starting with the skin estimate already at \~39–43 °C:

| Runs | Speed (tok/s) | What was limiting |
| --- | --- | --- |
| 1–6 | 32.46, 32.01, 31.91, 31.83, 31.76, 31.55 | Nothing — full speed at 53 W |
| 7–14 | 29.60, 28.30, 26.93, 26.85, 27.78, 28.05, 28.10, 25.72 | GPU at 100 °C, clock down to \~1.0–1.4 GHz |
| 15 | 16.54 | Slow PPT cut to 15 W |

- **The skin limit held.** STAPM stayed at 53 W until the skin estimate reached 50 °C at 19:24:01, about 4 minutes in versus about 1 minute at 43.5 °C.
- **The GPU's own heat limit came first.** By 19:23:16 the GPU sat at 99–100 °C and its clock had fallen from 2.5 GHz to \~1.0–1.4 GHz, with the STAPM limit still at 53 W. Speed slid to \~27–28 tok/s.
- **Then a hard cut instead of a ramp.** After the estimate crossed 50 °C, the STAPM limit eased 52→49 W, then at 19:25:16 the slow PPT limit dropped straight from 35 to 15 W. By 19:25:31 everything was pinned at 15.0 W, the GPU at 800 MHz and memory/fabric clocks at 1000/500 MHz.

That 15 W floor matches the original \~20 tok/s slow state and the Framework forum's report of locking at ≤15 W until the chassis cools. The real ceiling is cooling, about 30–33 W sustained. The first test showed a 30 W limit still gives \~31 tok/s, because token generation is limited by memory bandwidth, not GPU power.

## Next: cap package power instead

Rather than raising thermal limits, cap STAPM, fast and slow PPT at \~25–28 W so the chip never reaches 100 °C or the skin limit. The expected cost is \~1–2 tok/s, in exchange for steady speed instead of a drop to 15 W.

### Result: the 27 W cap holds steady speed

`ryzenadj --apu-skin-temp=43 --stapm-limit=27000 --fast-limit=27000 --slow-limit=27000`, then 25 × llama-bench tg512 runs, 19:31–19:39 on the 100 W dock. The skin estimate started at 38.4 °C, warmer than the first test's 35.7 °C.

| Runs | Speed (tok/s) | Package power | GPU temp |
| --- | --- | --- | --- |
| 1–5 | 31.63, 31.36, 31.25, 31.07, 31.04 | 25–27 W | 67–78 °C |
| 6–15 | 31.10 → 30.79 | 25–27 W | 79–83 °C |
| 16–25 | 30.42–30.76 | 26–27 W | 83–90 °C |

- **No drop.** Speed stayed within 1 tok/s of the start for 8 minutes. That's \~1–2 tok/s below a cool-start peak (32.6), instead of falling to 16–20.
- **The GPU stayed under its limit.** It peaked at 90 °C, against 100 °C uncapped.
- **The skin estimate still passed its limit, but no cut followed.** It crossed 43 °C at \~19:33 and reached 49.5 °C by the end, still rising about 0.3 °C/min. The firmware didn't cut power; the reported STAPM limit even rose from 28 to 30 W. Why the cut didn't fire here isn't known, so a 30+ minute run is needed to confirm it never does.

### Switching to the 60 W supply

Logged every second while moving from the 100 W dock to a 60 W USB-C supply (20 V × 3 A):

| Time | Event | STAPM / fast / slow | Skin limit |
| --- | --- | --- | --- |
| 19:44:28 | On the dock, cap applied | 27 / 27 / 27 W | 43 °C |
| 19:44:49 | Dock unplugged: the cap is gone | 30 / 46 / 35 → 28 / 28 / 28 W | 42 °C |
| 19:44:52–19:45:22 | On battery | 39–41 / 41 / 33 W | 42 °C |
| 19:45:23 | 60 W plugged in | 46 → 53 / 53 / 35 W | 43.5 °C |

- **Unplugging resets RyzenAdj's limits,** as the forum reported.
- **The firmware gives the 60 W supply the same stock limits as the 100 W dock,** so the cap is needed on both.
- **Unplugging the dock logged an amdgpu display warning** (`REG_WAIT timeout` in `dcn31_program_compbuf_size`, a kernel WARNING from kwin) as the MST link was torn down. The system recovered. It's more evidence that the display driver is fragile around this dock, consistent with the earlier freeze following an MST re-detect.

With the cap re-applied, 15 runs (19:49–19:54) on the 60 W supply went 32.02 → 30.50 tok/s, the same as on the dock. Package power held at 23–27 W and the GPU peaked at 92 °C. The battery's status flickered to "Discharging", but it read only 1–4 mA at 17.6 V (under 0.1 W) and the charge didn't move from 3714 mAh. **The 60 W supply is enough with the cap.**

**Superseded by 22 W.** 27 W passed these benchmarks and the 60 W test, but real opencode use still triggered the firmware's 15 W cut (see the next section). The cap is applied by hand only for coding sessions, resets when the charger is unplugged, and needs `sudo modprobe ryzen_smu` after each boot.

## Real opencode use: 27 W wasn't enough

In real coding the 27 W cap hit the firmware's 15 W cut within two minutes, and generation fell from \~20.3 to 10.8 tok/s.

| Time | Skin estimate | GPU | Limits | Generation |
| --- | --- | --- | --- | --- |
| 20:27 | 50.7 °C | 99–100 °C | 27 W cap | \~20.3 tok/s |
| 20:28:41 | 52.3 °C | 90 °C | slow PPT cut to 15 W, fast back to the stock 53 W | 16.4, then 10.8 tok/s |

- **Benchmarks understated the heat.** opencode sends 10–14k-token contexts, and processing long prompts is compute-heavy, unlike generation.
- **Re-running the cap lifts the cut at once.** It cleared at a 46.5 °C skin estimate, so rerun `llm_mode.sh` if the cut recurs.

## 22 W cap

The cap was lowered to 22 W at 20:45. In a 7-minute 8k-prompt benchmark it held exactly 22 W with no firmware cut, even at a 55.2 °C skin estimate.

- **The cut isn't a fixed \~50–52 °C threshold.** It fired at 50.6 and 52.3 °C before but not at 55.2 °C here; the trigger is unknown.
- **The GPU still reaches 95–99 °C** during long prompts, with clocks of 1.1–2.0 GHz. It holds steady rather than falling off.
- **Only about an hour of real use so far.** The `llm_perflog.py` report after a few days will show whether 20 W or 25 W fits better.

## Batch size

Ollama's default batch of 512 was fastest for an 8k-token prompt under the 22 W cap, so no Modelfile change.

| Batch (`-ub`) | 8k prompt speed |
| --- | --- |
| 512 (default) | 122.3 tok/s |
| 1024 | 112.4 tok/s |
| 2048 | 111.0 tok/s |
| 512, repeated last | 121.6 tok/s |

The repeated run matched the first, so heat didn't skew the later ones. This was the older Qwen3 model under llama-bench; for Qwen3.6, Ollama's `-ub 1024` is faster (see Ollama vs llama-server).

## opencode compaction

Compaction is slow because opencode resends the whole conversation with a new system prompt, so Ollama reprocesses it from scratch at \~45–130 tok/s.

- **Keep-alive 30 minutes.** The 5-minute default unloaded the model during pauses and lost its cache.
- **Smaller window.** The limit went from 32768 / 8192 to 24576 / 4096 (for Qwen3.6 too), so opencode compacts at \~20k tokens and each compaction is smaller.
- **Caveat: long multi-file tasks can loop.** Summarising many repos looped seven times: one read of a 2.7 MB `.jsonl` transcript filled the window, and one compaction returned an empty summary. Telling it to write the output as it goes and to skip `.jsonl` files fixed it.
- **Skipped `OLLAMA_KV_CACHE_TYPE=q8_0`.** It saves memory but can slow prompt processing on Vulkan.
- **Cached prefixes are nearly free.** A repeated 10k prompt with an unchanged prefix was served from cache at \~20,000–27,000 tok/s equivalent. That's why keep-alive (no unloads) and a stable prompt prefix matter.

## Monitoring

`llm_perflog.py` logs real per-request speed against the power state, passively, without loading a second model.

- **Per request:** it parses Ollama's journal `print_timing` lines for context size, prompt tokens and speed, and generated tokens and speed.
- **Every 10 s:** `pm_table` limits and draw, the skin estimate, GPU temperature and clocks, the power source and the battery.
- **Output:** daily CSVs in `perflog/`. The `capped` column is `yes` (the coding cap), `fw_cut` (the firmware's 15 W cut) or `no` (stock).
- **Commands:** `start`, `stop`, `status`, `report [DAYS]`. It runs as a transient systemd user unit, so start it again after a reboot, after `sudo modprobe ryzen_smu`.

## Model comparison: Qwen3.6-35B-A3B vs Qwen3 30B-A3B Instruct

With thinking turned off, Qwen3.6 processes prompts about 1.8× faster and generates slightly slower. Tests ran under the 22 W cap on Vulkan, through Ollama's OpenAI-compatible API (the path opencode uses).

| Test | Qwen3 Instruct | Qwen3.6 |
| --- | --- | --- |
| Session title, as opencode sends it | 0.6 s | 51.9 s, 1,375 tokens of reasoning |
| Title with `reasoning_effort: "none"` | 0.2 s | 1.2 s, no reasoning |
| Tool call (`read_file`) | correct, 1.6 s | correct, 5.5 s (thinking on) |
| Generation, short context | 29.5 tok/s | 24.2 tok/s |
| Generation at \~10k | 20.4 tok/s | 19.3 tok/s |
| Prompt processing at \~10k | 114 tok/s | 207 tok/s |
| Loaded size | 21 GB, 100% GPU | 22 GB, 100% GPU |

- **About the model:** `qwen35moe`, 35.5B parameters, \~3B active, 262k native context, a vision projector, and thinking levels false/true with true the default. `opencode run` confirmed `reasoning_effort` passes through: a 2-token reply with no reasoning.
- **Prompt speed matters most.** opencode's own system prompt is \~9,100 tokens, which is why contexts start near 10k.
- **Keep `model` and `small_model` the same.** Both models don't fit in GPU memory together, and a mismatched `small_model` makes Ollama swap models on every title (seen at 22:03).
- **Considered but not chosen:** [Qwen3-Coder-30B-A3B](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct) (same speed as now, XML tool-call format); dense Qwen3.8-27B and Devstral 24B (\~4–8 tok/s on this bandwidth); gpt-oss-20b (a reasoning model).

## Engine: Vulkan vs ROCm

Vulkan stays: ROCm cost about 25% of generation speed on both models, and its one win is something Qwen3.6 already gets on Vulkan.

Ollama drops ROCm on this GPU ("dropping ROCm device — no rocblas support for gfx target gfx1103"). It was tested with `HSA_OVERRIDE_GFX_VERSION=11.0.0` and `OLLAMA_VULKAN=0` in a drop-in. ROCm then ran as gfx1100 in `rocm_v7_2` and reported 26.7 GiB of GPU memory, against \~35 GiB on Vulkan; both models still loaded 100% on the GPU. The tests ran back to back under the 22 W cap, with the skin estimate at 46–47 °C at the start of each.

| Test | Vulkan | ROCm | Change |
| --- | --- | --- | --- |
| Qwen3.6 generation, short | 26.4 tok/s | 20.6 tok/s | −22% |
| Qwen3.6 10k prompt | 267 tok/s | 267 tok/s | same |
| Qwen3.6 generation at 10k | 22.9 tok/s | 16.9 tok/s | −26% |
| Qwen3 Instruct generation, short | 30.8 tok/s | 21.9 tok/s | −29% |
| Qwen3 Instruct 10k prompt | 115.5 tok/s | 285.6 tok/s | +147% |
| Qwen3 Instruct generation at 10k | 19.9 tok/s | 15.0 tok/s | −25% |

There were no hangs during the test. The change was reverted; a leftover `rocm-test.conf` now only sets `OLLAMA_VULKAN=1`, which is harmless.

## Ollama vs llama-server

Ollama's wrapper costs nothing measurable against a standalone llama-server, so Ollama stays.

Ollama 0.40.3 runs models through its own bundled llama.cpp `llama-server` (build 0.5.0-dev, commit 631109b), launched with `-c 32768 -np 1 --flash-attn on -b 1024 -ub 1024 --context-shift --keep 4 --load-mode dio`. The system llama.cpp is the Debian package, build 8681. All runs were on Vulkan under the 22 W cap, with the same prompts as earlier and thinking off (`think:false` for Ollama, `chat_template_kwargs.enable_thinking=false` for llama-server).

**Qwen3.6 35B-A3B** (tok/s):

| Test | Ollama | Bundled server, `-ub 1024` | Bundled server, `-ub 512` |
| --- | --- | --- | --- |
| Generation, short | 26.2 | 24.6 | 25.1 |
| 10k prompt | 262.5 | 258.2 | 235.5 |
| Generation at 10k | 23.2 | 22.9 | 22.3 |
| Tool call (`read_file`) | — | correct, 3.6 s | correct, 3.8 s |

**Qwen3 30B-A3B Instruct** (tok/s):

| Test | Ollama | System llama-server b8681 (`-ub 1024`) |
| --- | --- | --- |
| Generation, short | 29.6 | 27.4 |
| 10k prompt | 110.2 | 103.4 |
| Generation at 10k | 19.5 | 18.6 |
| Tool call | — | correct, 2.5 s |

- **No wrapper cost.** The gaps are within run-to-run noise. Stay on Ollama.
- **Keep Ollama's `-ub 1024` for Qwen3.6.** 512 was \~10% slower on long prompts, the opposite of the older model's llama-bench result, so don't override it.
- **The system build can't load Ollama's Qwen3.6 file** ("missing tensor 'blk.40.ssm\_conv1d.weight'"). Layer 40 is the MTP/nextn prediction layer, which Ollama's build loads and ignores. On the Instruct model the system build was slightly slower.
- **Gotcha: the bundled server run by hand silently uses the CPU.** It finds no GPU ("no usable GPU found") unless started with `GGML_BACKEND_PATH=/usr/local/lib/ollama/vulkan/libggml-vulkan.so` and `LD_LIBRARY_PATH=/usr/local/lib/ollama:/usr/local/lib/ollama/vulkan`. Its log doesn't name the device, so check GPU memory: `mem_info_gtt_used` + `mem_info_vram_used` rose \~21 GiB.
- **The accidental CPU run shows what the GPU buys.** Qwen3.6 on 8 threads generated 20.2 tok/s on a short prompt, close to the GPU, since both are limited by the same \~90 GB/s memory bandwidth. But it managed 74 tok/s on the 10k prompt and 12.2 tok/s generation at 10k, against 262 and 23 on the GPU. The GPU matters most for long contexts.

## Commands

These worked on this machine with Secure Boot left on. Ubuntu's DKMS signing key (`/var/lib/shim-signed/mok/MOK.der`) was already enrolled, so no MOK enrollment reboot was needed.

1. Remove the original `ryzen_smu` 0.1.5 if it's installed. It supports Zen 1–3 only, so on Phoenix it loads but never binds to the root complex, and `/sys/kernel/ryzen_smu_drv` never appears:

   ```
   sudo rmmod ryzen_smu
   sudo dkms remove ryzen_smu/0.1.5 --all && sudo rm -rf /usr/src/ryzen_smu-0.1.5
   ```
2. Install the [amkillam fork](https://github.com/amkillam/ryzen_smu) (0.1.7), which knows Phoenix (`1022:14e8`, CPU model `0x74`):

   ```
   git clone https://github.com/amkillam/ryzen_smu && cd ryzen_smu
   sudo make dkms-install
   sudo modprobe ryzen_smu
   cat /sys/kernel/ryzen_smu_drv/drv_version   # 0.1.7
   ```
3. Build [RyzenAdj](https://github.com/FlyGoat/RyzenAdj) and read or set the limits. The build here is main at 44438e1, one commit past v0.19.0, which only adds Dragon Range / Fire Range support. It needs `libpci-dev` and `cmake`, and root even for `-i`. `--apu-skin-temp` only takes whole degrees; power limits are in mW. The last line is the 22 W coding cap, the same command as `llm_mode.sh`:

   ```
   git clone https://github.com/FlyGoat/RyzenAdj && cd RyzenAdj
   mkdir build && cd build && cmake -DCMAKE_BUILD_TYPE=Release .. && make
   cp ryzenadj ~/bin/ryzenadj
   sudo ~/bin/ryzenadj -i
   sudo ~/bin/ryzenadj --apu-skin-temp=43 --stapm-limit=22000 --fast-limit=22000 --slow-limit=22000
   ```
4. Log the limits without root. `/sys/kernel/ryzen_smu_drv/pm_table` is world-readable. For PM table version `0x4C0009`, each field is a little-endian float32 at these offsets (from RyzenAdj's `lib/api.c`):

| Field | Limit offset | Value offset |
| --- | --- | --- |
| STAPM | 0x0 | 0x4 |
| PPT fast | 0x8 | 0xC |
| PPT slow | 0x10 | 0x14 |
| APU skin temperature (STT) | 0x58 | 0x5C |

The GPU clocks come from `pp_dpm_sclk`, `pp_dpm_mclk` and `pp_dpm_fclk` under `/sys/class/drm/card1/device`, where the active level is marked `*`.

## Open questions

- **Memory budget for loading both models at once.** More RAM or GTT won't raise tok/s: generation is bound by \~90 GB/s of memory bandwidth, a \~45 tok/s ceiling. It would only avoid reloads when switching between Instruct and Thinking.
- **Model choice for coding.** Qwen3.6 on trial; judge coding quality on real work and compare speeds with `./llm_perflog.py report 7` (now grouped by model).

## Sources

- [Radeon 780M: thermal throttling to 800 MHz until the chassis cools](https://community.frame.work/t/radeon-780m-thermal-throttling-stays-on-until-i-reboot/58576) — Framework forum, the same STAPM pattern on a 7840U
- [RyzenAdj](https://github.com/FlyGoat/RyzenAdj) — reads and sets SMU power and thermal limits
- [amkillam/ryzen\_smu](https://github.com/amkillam/ryzen_smu) — kernel module RyzenAdj uses under Secure Boot; adds Phoenix support
- [AlxHnr's amd-ryzen-ignore-stapm](https://github.com/AlxHnr/amd-ryzen-ignore-stapm) — systemd approach to firmware resets
- [amdgpu MST payload crash with a Thunderbolt dock on a Framework 13 7840U](https://lists.linaro.org/archives/list/linux-stable-mirror@lists.linaro.org/thread/FLZC6HZ4FQLB5ABRY4VMB3TGNQ757UZY) — linux-stable mailing list
- [7640U can't drive 4K60 over a USB-C dock (DSC)](https://community.frame.work/t/resolved-7640u-linux-cant-drive-4k60-over-usb-c-dock-because-dsc-is-not-working/40803) — Framework forum; DPM changes broke boot with the dock attached
- [drm/amd #1839: GPU hangs on high performance level](https://gitlab.freedesktop.org/drm/amd/-/issues/1839)
- [drm/amd #2842: GPU clock stuck low when forcing high](https://gitlab.freedesktop.org/drm/amd/-/issues/2842)
- [llama.cpp #13565: 780M HIP vs Vulkan performance](https://github.com/ggml-org/llama.cpp/issues/13565)
- [llama.cpp #15012](https://github.com/ggml-org/llama.cpp/issues/15012) — model research
- [Best MoE models for local coding](https://www.promptquorum.com/prompt-bites/best-moe-models-local-coding) — PromptQuorum
- [Best Ollama models](https://www.morphllm.com/best-ollama-models) — Morph
- [Best local LLM for coding](https://localairun.com/best-local-llm-for-coding/) — LocalAIRun
- [Qwen3-Coder-30B-A3B-Instruct](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct) — model card
