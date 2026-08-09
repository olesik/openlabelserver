# Security Policy

## Supported Versions

OpenLabelServer is in early development. Security fixes are applied to the latest release on `main` and, when applicable, to the most recent tagged release.

| Version | Supported |
|---------|-----------|
| `main` (pre-release) | Yes |
| Tagged releases | Yes, when published |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

**Preferred:** Use [GitHub Security Advisories](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) to report a vulnerability privately on this repository.

**Alternative:** Contact repository maintainers through a private channel listed in repository metadata or maintainer profiles.

If you do not receive a response within five business days, please follow up through the same channel.

Include as much detail as possible:

- Description of the vulnerability and potential impact
- Steps to reproduce
- Affected component (API, renderer, printing, frontend, infrastructure)
- Proof of concept, if available
- Your contact information for follow-up

## What to Report

Examples of issues we want to hear about:

- Authentication or authorization bypass
- Remote code execution in the server, renderer, or print pipeline
- Path traversal or arbitrary file read/write through asset or job APIs
- Injection vulnerabilities in API inputs that reach shell, CUPS, or file operations
- Secrets or credentials committed to the repository
- Dependency vulnerabilities with demonstrable exploit paths in this project

## Out of Scope

The following are generally **not** treated as security vulnerabilities for this project:

- Denial of service through extremely large but valid RenderSpec documents, unless trivially triggered without authentication on a default deployment
- Physical printer misalignment or calibration inaccuracy (see CalibrationSpec and conformance tests)
- Issues requiring compromise of the host operating system outside OpenLabelServer
- Vulnerabilities in third-party dependencies without a practical impact on OpenLabelServer after configuration review

## Response Process

1. **Acknowledgment** — We aim to acknowledge reports within five business days.
2. **Triage** — We assess severity, reproducibility, and affected versions.
3. **Fix** — We develop and test a fix on a private branch when warranted.
4. **Disclosure** — We coordinate disclosure timing with the reporter. We prefer coordinated disclosure after a fix is available.
5. **Release** — Security fixes are documented in [CHANGELOG.md](CHANGELOG.md) with credit to reporters when permitted.

## Safe Deployment Practices

Until v1.0, treat all deployments as **pre-production**:

- Do not expose the API to untrusted networks without authentication and TLS
- Run containers with least-privilege users and read-only filesystems where practical
- Restrict CUPS and printer access to trusted networks
- Keep Docker images and dependencies updated
- Do not commit secrets, API tokens, or printer credentials to the repository

## Security Design Principles

OpenLabelServer follows these security-oriented architectural choices:

- **Specification-first APIs** — Public contracts are documented in OpenAPI; undocumented behavior is not supported
- **Separation of concerns** — Layout (RenderSpec), stock geometry (StockSpec), and printer calibration (CalibrationSpec) are distinct; clients should not mix trust boundaries
- **No hidden configuration** — Operational settings should be explicit and documented
- **Platform independence** — Avoid vendor SDKs and opaque binary dependencies that hinder auditability

As the reference implementation matures, we will publish hardening guides for production deployments.

## Recognition

We appreciate responsible disclosure. Reporters who allow public acknowledgment will be credited in the changelog unless they prefer to remain anonymous.
