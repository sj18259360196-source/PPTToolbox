# Development and releases

Use a project-local Python environment. Install `requirements-dev.txt` for the
core tests, and the optional graphics dependencies for graphics tests. Windows
desktop and Office behavior require separate Windows acceptance checks.

`release.json` is the product version source. Run
`python -B scripts/release_info.py sync` after changing it.

Public builds use an audited source export and a fresh pinned embedded runtime.
See `distribution/PUBLIC_RELEASE.md` for the exact commands. Never publish
personal project folders, management databases, credentials, feedback, original
experience notes or local build evidence. Changes under the private development
checkout are not automatically part of the public repository.

CI runs focused deterministic tests and builds draft releases from version tags.
A draft is not available to in-app updates. The maintainer verifies the installer,
signs its metadata with a locally protected private key, uploads the signed
manifest and publishes the tested draft. Do not put the private signing key in
the repository, Actions logs or issue attachments.
