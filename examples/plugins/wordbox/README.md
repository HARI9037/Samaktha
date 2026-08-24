# WordBox Example Tool

A Samaktha example **tool-only plugin**: a single `Tool` that counts words
and characters in supplied text. It shows how a plugin contributes tools
without any lifecycle logic of its own.

See [docs/PLUGINS.md](../../../docs/PLUGINS.md) for the full plugin author guide.

## Layout

- `manifest.json` — canonical plugin declaration
- `wordbox.py` — entry module exposing `create_plugin()`
- `tests/` — pytest suite using `PluginHarness`

## Development

```bash
samaktha-plugin validate .
samaktha-plugin test .
```
