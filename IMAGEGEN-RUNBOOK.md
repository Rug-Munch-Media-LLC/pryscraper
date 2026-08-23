# Local Image Generation Runbook (CPU-only, quantized)

Hardware baseline (Talos, measured 2026-08-23): **16 vCPU** AMD EPYC 9645,
**62 GB RAM** (~17 GB free alongside production services), **575 GB disk**,
no GPU/KVM. Docker available.

## Honest capability rundown

| Model | Quant | RAM | Time/image (512px) | Verdict on this box |
|---|---|---|---|---|
| SD-Turbo | Q8 GGUF | ~2 GB | ~10–20 s (1 step) | ✅ comfortable |
| SD 1.5 | Q8_0 GGUF | ~2.1 GB | ~60–120 s (20 steps) | ✅ fine for batches |
| BK-SDM (distilled) | int8 ONNX | ~1.2 GB | ~30–60 s | ✅ fastest quality tradeoff |
| SDXL | Q4_K_M GGUF | ~5–6 GB | ~3–6 min | ⚠️ ok off-peak |
| Flux.1-schnell | Q4 GGUF | ~7–9 GB | ~5–10 min (4 steps) | ⚠️ risky next to prod services |

Rules of thumb: CPU image gen scales with cores × memory bandwidth; expect
roughly linear time with steps; always run `nice -n 19` / taskset-limited
next to production services; never load >6 GB models while the platform is
under traffic.

## Recommended stack: stable-diffusion.cpp

Fits our existing llama.cpp-style ops (single binary, GGUF quantized weights,
no Python env):

```bash
git clone --recursive https://github.com/leejet/stable-diffusion.cpp
cd stable-diffusion.cpp
cmake -B build -DSD_CUBLAS=OFF -DSD_METAL=OFF
cmake --build build --config Release -j 8

# SD-Turbo for fast drafts (Q8)
./build/bin/sd -m sd-turbo-Q8_0.gguf -p "flat minimal icon background,
soft lime gradient, abstract geometric shapes, no text" \
  --steps 2 --sampling-method euler -W 512 -H 512 -o bg.png
```

Model sources: HuggingFace `GGUF` conversions (search "sd-turbo gguf",
"sd15 gguf", "flux1-schnell gguf"). Store under `/srv/models/imagegen/`.

## What we use it for (and what we don't)

**Good fits:**
- OG/social preview card backgrounds per actor (1200×630 crop from 512→upscale)
- Store-listing hero art variants
- Blog/docs header illustrations

**Bad fits (keep programmatic):**
- Icon glyphs — diffusion cannot do crisp geometry/text/transparency;
  our SVG generator is deterministic, 2 KB, and scales losslessly
- Anything requiring brand consistency across 52 actors

## Pipeline sketch (og-images)

1. `sd -m sd-turbo-Q8_0.gguf --steps 2 -W 512 -H 320` → textured backdrop
2. Composite actor icon.svg + title text via Pillow/SVG layer
3. Export 1200×630 PNG into pry-web/landing/public/og/

Run inside `nice -n 19 systemd-run --scope -p MemoryMax=4G` to protect prod.
