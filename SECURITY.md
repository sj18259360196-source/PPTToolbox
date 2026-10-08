# Reporting security issues

Do not put API keys, project files, local databases, or private logs in public
issues. Use GitHub's private vulnerability reporting when the repository offers
it. For an ordinary bug, share a small synthetic reproduction and redacted logs.

The desktop manager binds only to loopback and requires its session token for
API requests. Agent tools retain project authorization checks. The updater is
exposed only through the owner's authenticated UI, not through MCP or PPTAgent.

Updates come from the repository pinned in `distribution/release_config.json`.
An Ed25519 signature authenticates the update manifest. The manifest binds the
version, repository, platform, installer URL, byte size and SHA-256 digest.
An invalid signature, changed file, unsupported database schema or lower observed
version prevents installation. TLS checks must not be disabled.

The first installation is a trust bootstrap. Download it from the official
repository's Releases page. The initial release has no Microsoft Authenticode
certificate; Windows may display an unknown-publisher warning. A release manifest
signature is distinct from Windows code signing.

The updater never kills an active Agent or Office process. It reuses the
installer's task audit, cooperative shutdown, maintenance fence and file backup.
Disk/download failures do not replace the current program. After power loss,
preserve `UPDATE_PENDING.json` and the referenced backup for recovery.

Do not replace a live database with an older backup. Software rollback requires
compatible data schema and a stopped installation. Imported extensions and
direct local shell use remain outside the updater's trust model.
