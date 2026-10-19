const WEAK_TOKENS = new Set(["v1", "v2", "v3", "v4", "v5", "v1.0", "v1.5", "v2.0", "safetensors", "gguf", "ckpt", "pt", "bin", "onnx", "sft", "pth", "bf16", "fp16", "fp8", "f16", "f32", "int8", "q8", "q4", "8bit", "4bit", "2bit", "lora", "model", "new", "final", "comfyui", "comfy", "768p", "480p", "720p", "1080p", "512p", "x4", "x2", "hd"]);

function tokenMatch(wantName, xName) {
    const wantTokens = new Set(wantName.toLowerCase().split(/[-_.\s]+/).filter(t => t.length > 1));
    const wantExt = wantName.toLowerCase().split(".").pop();
    const xTokens = new Set(xName.toLowerCase().split(/[-_.\s]+/).filter(t => t.length > 1));
    const xExt = xName.toLowerCase().split(".").pop();
    if (xExt !== wantExt) return false;
    let common = 0, strong = 0;
    for (const t of xTokens) {
        if (wantTokens.has(t)) {
            common++;
            if (!WEAK_TOKENS.has(t)) strong++;
        }
    }
    return common >= 2 && strong >= 1;
}

const cases = [
    ["MysticXXX_MMH3-V1.safetensors", "minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors", false],
    ["MysticXXX_MMH3-V1.safetensors", "minimax_h3_fl2va_bf16.safetensors", false],
    ["mmproj-BF16.gguf", "mmproj-Qwen3.8-27B-BF16.gguf", true],
    ["minimax_h3_fl2va_bf16.safetensors", "minimax_h3_fl2va_bf16.safetensors", true],
    ["flux-vae-bf16.safetensors", "flux-vae-bf16.safetensors", true],
    ["sd_xl_base_1.0.safetensors", "sd_xl_refiner_1.0.safetensors", false],
    ["qwen3-8b-q4.gguf", "qwen3-14b-q4.gguf", true],
];

let pass = 0;
for (const [w, x, expect] of cases) {
    const got = tokenMatch(w, x);
    const ok = got === expect;
    if (ok) pass++;
    console.log(`${ok ? "PASS" : "FAIL"} tokenMatch(${w}, ${x}) = ${got} (期望 ${expect})`);
}
console.log(`${pass}/${cases.length} passed`);
process.exit(pass === cases.length ? 0 : 1);