# Changelog

All notable changes to this project will be documented in this file.

Format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2025-04-04

### Added
- Tag-based publish workflow for PyPI and Docker Hub
- Docker Hub image publishing (`deepcivic/agift-dashboard`, `deepcivic/agift-worker`)
- CHANGELOG.md for version-bound release notes
- `release.sh` helper script for version bumps and tagging
- GitHub Release auto-created from changelog entries

### Changed
- Publish workflow triggers on version tags instead of GitHub releases
- Release notes sourced from changelog (commit history not exposed)

## [0.1.0] - 2025-04-03

### Added
- Initial public release
- AGIFT vocabulary ingestion from TemaTres REST API
- Neo4j and CogDB backend support
- Sentence-transformer and Isaacus embedding providers
- Cosine similarity semantic edge builder
- CLI (`agift` command) and programmatic `run_pipeline()` API
- Flask dashboard for config, run control, and monitoring
- Docker Compose stack (Neo4j + dashboard + worker)
