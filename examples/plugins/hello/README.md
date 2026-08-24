# Hello Example Plugin

A Samaktha example **tool plugin** that greets the caller. It demonstrates
the complete plugin surface: a manifest, an entry module exposing
`create_plugin()`, a contributed `Tool`, lifecycle hooks (`start`/`stop`),
and a pytest suite built on the SDK testing utilities.

See [docs/PLUGINS.md](../../../docs/PLUGINS.md) for the full plugin author guide.

## Layout

- `manifest.json` — canonical plugin declaration
- `hello.py` — entry module exposing `create_plugin()`
- `tests/` — pytest suite using `PluginHarness`

## Development

```bash
samaktha-plugin validate .
samaktha-plugin test .
```
