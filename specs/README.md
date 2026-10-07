# Specifications

Published specifications define all public behavior for OpenLabelServer.

> **The specification is the product; the code is an implementation of the specification.**

If implementation and specification disagree, **the specification wins** until an accepted RFC changes the specification.

## Layout

| Directory | Specification | Schema |
|-----------|---------------|--------|
| [renderspec/](renderspec/) | [specification.md](renderspec/specification.md) | [schema.json](renderspec/schema.json) |
| [stockspec/](stockspec/) | [specification.md](stockspec/specification.md) | [schema.json](stockspec/schema.json) |
| [calibrationspec/](calibrationspec/) | [specification.md](calibrationspec/specification.md) | [schema.json](calibrationspec/schema.json) |
| [api/](api/) | [specification.md](api/specification.md) | [openapi.yaml](api/openapi.yaml) |
| [conformance/](conformance/) | Conformance requirements (in progress) | — |

Each specification directory includes an `examples/` folder with valid sample documents.

## Changing a specification

1. Open a [Specification Change](../../.github/ISSUE_TEMPLATE/specification_change.yml) issue or submit an RFC under [rfcs/](../rfcs/).
2. Update the specification document.
3. Update the JSON Schema or OpenAPI contract.
4. Add or update example documents.
5. Update conformance tests when behavior is observable.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full workflow.

## Ownership

Specifications are owned by the **Governance** subsystem. See [AGENTS.md](../AGENTS.md).
