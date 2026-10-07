# Plugins

Optional extension modules for OpenLabelServer.

## Planned capabilities

- Plugin interface and discovery
- Capability registration (render backends, barcode symbologies, output formats)
- Version compatibility checks
- Lifecycle management (load, configure, unload)

Plugins must not bypass RenderSpec or introduce undocumented public APIs. Any capability exposed through a plugin that affects observable behavior requires a published specification or RFC.

## Status

The plugin system is planned for post-v1.0. See [CHECKLIST.md](../CHECKLIST.md) and [ROADMAP.md](../ROADMAP.md).

## Ownership

Owned by the **Governance** and **Platform** subsystems. See [AGENTS.md](../AGENTS.md).
