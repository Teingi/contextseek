# contextseek v0.1.3

This release focuses on a stronger and more reliable Dream pipeline.

## Highlights

- Added **dream graduation**: reinforced dream items can mature into durable knowledge (`knowledge` + `stable` + `graduated`).
- Added **no-LLM quality gates** for consolidation/divergence to suppress noisy fallback outputs.
- Added **persistent per-scope dream cooldown** via `dream_state.json` for scheduler/daemon paths.
- Expanded Dream configuration surface (`DREAM_*`) and aligned docs in both English and Chinese.
- Updated Dream API and CLI reporting to include graduation-aware fields.

## Notes

- `DREAM_LLM_ENABLED` now defaults to `true`.
- Manual `ctx.dream()` calls default to `force=True` (bypasses cooldown by design).
