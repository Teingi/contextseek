# Icons

Tauri requires real icon binaries to build. They are intentionally not committed
as text. Generate them from a single source PNG (≥ 1024×1024) on the build
machine:

```bash
cargo tauri icon path/to/source-logo.png
```

This produces `32x32.png`, `128x128.png`, `128x128@2x.png`, `icon.icns`,
`icon.ico` (and platform variants) into this directory, matching the `bundle.icon`
list in `../tauri.conf.json`.
