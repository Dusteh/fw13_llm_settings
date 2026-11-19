# To evaluate later

- **Memory budget for loading both models at once** (Instruct + Thinking, so switching in opencode doesn't reload).
  More memory or GTT won't raise tok/s (memory-bandwidth bound: ~90 GB/s, ~45 tok/s ceiling, ~32 seen); it only buys capacity.
  Now: 2×32 GB DDR5-5600, 8 GiB BIOS VRAM + 26.7 GiB GTT cap (`ttm.pages_limit`, default half of RAM). Model is 21 GB at 100% GPU.
  To work out: 2 × ~21 GB + KV cache vs the GTT cap and RAM left for the OS; raise `ttm.pages_limit` on the kernel command line if worth it; `OLLAMA_MAX_LOADED_MODELS=2`.
- After a few days of logging: `./llm_perflog.py report 7` to compare the 22 W cap, firmware cuts and compaction (prompt) speed.

# Done

- **Batch-size test (2026-11-18, 22 W cap, 8k prompt):** ub 512 = 122.3 tok/s, 1024 = 112.4, 2048 = 111.0, 512 again = 121.6. That was the older Qwen3 model under llama-bench. Ollama actually launches with `-ub 1024`, and for Qwen3.6 that beats 512 by ~10% (see "Ollama vs llama-server"), so leave Ollama's setting alone.
- **Qwen3.6-35B-A3B trial (default since 2026-11-18 22:05):** thinking off via `"options": {"reasoning_effort": "none"}` in opencode.json. Benchmarks vs Qwen3 30B-A3B Instruct: prompt at 10k 207 vs 114 tok/s, gen at 10k 19.3 vs 20.4, gen short 24.2 vs 29.5. Judge coding quality on real work; compare with `./llm_perflog.py report 7` (now grouped by model). To revert: set `model` and `small_model` back to `ollama/qwen3:30b-a3b-instruct-2507-q4_K_M`.
- **ROCm vs Vulkan (2026-11-18 22:12, 22 W cap, `HSA_OVERRIDE_GFX_VERSION=11.0.0`):** Qwen3.6: generation 26.4→20.6 (short) and 22.9→16.9 (10k), 10k prompt 267→267. Qwen3 Instruct: generation 30.8→21.9 and 19.9→15.0, 10k prompt 115.5→285.6. ROCm costs ~25% generation; Vulkan stays. ROCm only helps the old model's prompt processing.
- **Ollama vs llama-server (2026-11-18 22:30, Vulkan, 22 W):** Qwen3.6, Ollama 26.2 / 262.5 / 23.2 tok/s (gen short / 10k prompt / gen at 10k) vs its bundled llama-server standalone 24.6 / 258.2 / 22.9 (ub 1024) and 25.1 / 235.5 / 22.3 (ub 512). Instruct: Ollama 29.6 / 110.2 / 19.5 vs system llama-server b8681 27.4 / 103.4 / 18.6. Stay on Ollama. The system b8681 can't load Ollama's Qwen3.6 file. Run by hand, the bundled server needs `GGML_BACKEND_PATH=/usr/local/lib/ollama/vulkan/libggml-vulkan.so`, or it silently uses the CPU.
