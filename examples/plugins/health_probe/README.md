# Health Probe Example Provider

A Samaktha example **provider plugin**: a deterministic
`CommunicationProvider` that is always healthy, never touches the network,
and records every request it would deliver. It shows how a plugin
contributes providers into the `CommunicationRegistry`.

See [docs/PLUGINS.md](../../docs/PLUGINS.md) for the full plugin author guide.

## Layout

- `manifest.json` — canonical plugin declaration
- `health_probe.py` — entry module exposing `create_plugin()`
- `tests/` — pytest suite using `PluginHarness`

## Development

```bash
samaktha-plugin validate .
samaktha-plugin test .
```
