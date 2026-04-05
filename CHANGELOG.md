# Changelog

All notable changes to this project will be documented in this file.

Format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2025-04-05

### Fixed
- Worker container exiting immediately due to cron PID lock conflict.

## [0.2.0] - 2025-04-05

### Added
- Public `get_term_properties(term_id)` method on `GraphBackend` interface,
  implemented in both CogDB and Neo4j backends. Consumers no longer need to
  reach into the private `_get_props()` helper to access `dcat_theme` and
  other term attributes.
- Unified Docker image (`deepcivic/agift`) replacing separate dashboard and
  worker images. Single container runs dashboard + cron by default, with
  `AGIFT_MODE` env var to select mode (`dashboard`, `worker`, `cli`).
- Docker test suite (`tests/test_docker.py`) covering image structure, all
  three container modes, and HTTP health checks.
- Concurrent alt-label fetching via `ThreadPoolExecutor` (10 workers),
  reducing fetch time for ~589 terms from sequential to ~59 batches.

### Changed
- Dashboard now runs pipeline in-process via `run_pipeline()` instead of
  `docker exec` to the worker container. No more Docker-in-Docker.
- Dashboard served by gunicorn (production WSGI server) instead of Flask
  dev server.
- TemaTres API courtesy pause reduced from `sleep(2)` to `sleep(0.2)`.
- Retry logic upgraded to exponential backoff with jitter (up to 5 attempts).
- Publish workflow builds single `deepcivic/agift` image instead of two.
- Docker Hub description update removed from CI (manual for now).

### Removed
- Separate `dashboard/Dockerfile` and `worker/Dockerfile` (replaced by
  unified `Dockerfile` at repo root).

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
