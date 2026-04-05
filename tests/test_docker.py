"""Tests for the unified Docker image.

These tests build the image once and verify each AGIFT_MODE behaves
correctly. They require Docker to be available and are skipped in
environments without it (e.g. standard CI matrix).

Run explicitly:
    pytest tests/test_docker.py -v --timeout=300
"""

import subprocess
import time
import uuid

import pytest
import urllib.request
import urllib.error

IMAGE_TAG = "agift-test:latest"
BUILD_TIMEOUT = 600  # 10 min for first build (torch download)
CONTAINER_PREFIX = "agift-test-"


def _run(cmd, **kwargs):
    """Run a shell command and return CompletedProcess."""
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _docker_available():
    """Check if Docker CLI is available and daemon is running."""
    try:
        result = _run(["docker", "info"], timeout=10)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(not _docker_available(), reason="Docker not available")


@pytest.fixture(scope="module")
def docker_image():
    """Build the unified Docker image once for the entire test module."""
    result = _run(
        ["docker", "build", "-t", IMAGE_TAG, "-f", "Dockerfile", "."],
        timeout=BUILD_TIMEOUT,
    )
    assert (
        result.returncode == 0
    ), f"Docker build failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    yield IMAGE_TAG
    # Cleanup image after all tests
    _run(["docker", "rmi", "-f", IMAGE_TAG], timeout=30)


def _container_name():
    """Generate a unique container name."""
    return f"{CONTAINER_PREFIX}{uuid.uuid4().hex[:8]}"


def _remove_container(name):
    """Force-remove a container by name."""
    _run(["docker", "rm", "-f", name], timeout=15)


class TestImageStructure:
    """Verify the built image has the expected files and packages."""

    def test_agift_package_importable(self, docker_image):
        name = _container_name()
        try:
            result = _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    name,
                    "-e",
                    "AGIFT_MODE=cli",
                    docker_image,
                    "python",
                    "-c",
                    "import agift; print(agift.__all__[:3])",
                ],
                timeout=60,
            )
            assert result.returncode == 0, result.stderr
            assert "AGIFT_TOP_TO_DCAT" in result.stdout or "[" in result.stdout
        finally:
            _remove_container(name)

    def test_gunicorn_installed(self, docker_image):
        name = _container_name()
        try:
            result = _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    name,
                    "--entrypoint",
                    "python",
                    docker_image,
                    "-c",
                    "import gunicorn; print(gunicorn.__version__)",
                ],
                timeout=30,
            )
            assert result.returncode == 0, result.stderr
        finally:
            _remove_container(name)

    def test_flask_installed(self, docker_image):
        name = _container_name()
        try:
            result = _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    name,
                    "--entrypoint",
                    "python",
                    docker_image,
                    "-c",
                    "import flask; print(flask.__version__)",
                ],
                timeout=30,
            )
            assert result.returncode == 0, result.stderr
        finally:
            _remove_container(name)

    def test_sentence_transformers_installed(self, docker_image):
        name = _container_name()
        try:
            result = _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    name,
                    "--entrypoint",
                    "python",
                    docker_image,
                    "-c",
                    "import sentence_transformers; print('ok')",
                ],
                timeout=30,
            )
            assert result.returncode == 0, result.stderr
            assert "ok" in result.stdout
        finally:
            _remove_container(name)

    def test_entrypoint_exists(self, docker_image):
        name = _container_name()
        try:
            result = _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    name,
                    "--entrypoint",
                    "test",
                    docker_image,
                    "-x",
                    "/entrypoint.sh",
                ],
                timeout=15,
            )
            assert result.returncode == 0, "entrypoint.sh not executable"
        finally:
            _remove_container(name)

    def test_dashboard_app_exists(self, docker_image):
        name = _container_name()
        try:
            result = _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    name,
                    "--entrypoint",
                    "test",
                    docker_image,
                    "-f",
                    "/app/dashboard/app.py",
                ],
                timeout=15,
            )
            assert result.returncode == 0, "dashboard/app.py not found in image"
        finally:
            _remove_container(name)


class TestCLIMode:
    """Test AGIFT_MODE=cli runs the pipeline entry point."""

    def test_cli_help(self, docker_image):
        """CLI mode with --help should print usage and exit 0."""
        name = _container_name()
        try:
            result = _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    name,
                    "-e",
                    "AGIFT_MODE=cli",
                    docker_image,
                    "--help",
                ],
                timeout=30,
            )
            assert result.returncode == 0, result.stderr
            assert "usage" in result.stdout.lower() or "--dry-run" in result.stdout
        finally:
            _remove_container(name)

    def test_cli_invalid_backend(self, docker_image):
        """CLI mode with bad backend should fail with a clear error."""
        name = _container_name()
        try:
            result = _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    name,
                    "-e",
                    "AGIFT_MODE=cli",
                    docker_image,
                    "--backend",
                    "invalid",
                ],
                timeout=30,
            )
            assert result.returncode != 0
            assert "invalid" in result.stderr.lower()
        finally:
            _remove_container(name)


class TestInvalidMode:
    """Test that an unknown AGIFT_MODE fails cleanly."""

    def test_unknown_mode_exits_nonzero(self, docker_image):
        name = _container_name()
        try:
            result = _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    name,
                    "-e",
                    "AGIFT_MODE=bogus",
                    docker_image,
                ],
                timeout=15,
            )
            assert result.returncode != 0
            assert "Unknown AGIFT_MODE" in result.stdout
        finally:
            _remove_container(name)


class TestDashboardMode:
    """Test AGIFT_MODE=dashboard starts gunicorn and serves HTTP."""

    def test_dashboard_serves_http(self, docker_image):
        """Dashboard mode should respond to HTTP on port 5050."""
        name = _container_name()
        try:
            # Start container in background with CogDB (no Neo4j needed)
            _run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    name,
                    "-e",
                    "AGIFT_MODE=dashboard",
                    "-e",
                    "AGIFT_CRON_ENABLED=0",
                    "-e",
                    "BACKEND_TYPE=cogdb",
                    "-p",
                    "15050:5050",
                    docker_image,
                ],
                timeout=30,
            )

            # Wait for gunicorn to start
            url = "http://127.0.0.1:15050/"
            healthy = False
            for _ in range(20):
                time.sleep(2)
                try:
                    req = urllib.request.urlopen(url, timeout=5)
                    if req.status == 200:
                        body = req.read().decode()
                        assert "AGIFT Dashboard" in body
                        healthy = True
                        break
                except (urllib.error.URLError, ConnectionError, OSError):
                    continue

            # Grab logs for debugging if unhealthy
            if not healthy:
                logs = _run(["docker", "logs", name], timeout=10)
                pytest.fail(
                    f"Dashboard did not become healthy.\n"
                    f"STDOUT:\n{logs.stdout}\nSTDERR:\n{logs.stderr}"
                )
        finally:
            _remove_container(name)

    def test_dashboard_run_status_endpoint(self, docker_image):
        """The /run/status JSON endpoint should respond."""
        name = _container_name()
        try:
            _run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    name,
                    "-e",
                    "AGIFT_MODE=dashboard",
                    "-e",
                    "AGIFT_CRON_ENABLED=0",
                    "-e",
                    "BACKEND_TYPE=cogdb",
                    "-p",
                    "15051:5050",
                    docker_image,
                ],
                timeout=30,
            )

            url = "http://127.0.0.1:15051/run/status"
            healthy = False
            for _ in range(20):
                time.sleep(2)
                try:
                    req = urllib.request.urlopen(url, timeout=5)
                    if req.status == 200:
                        import json

                        data = json.loads(req.read())
                        assert "running" in data
                        assert data["running"] is False
                        healthy = True
                        break
                except (urllib.error.URLError, ConnectionError, OSError):
                    continue

            if not healthy:
                logs = _run(["docker", "logs", name], timeout=10)
                pytest.fail(
                    f"/run/status not reachable.\n"
                    f"STDOUT:\n{logs.stdout}\nSTDERR:\n{logs.stderr}"
                )
        finally:
            _remove_container(name)


class TestWorkerMode:
    """Test AGIFT_MODE=worker sets up cron and stays alive."""

    def test_worker_installs_cron(self, docker_image):
        """Worker mode should install the cron schedule and stay running."""
        name = _container_name()
        try:
            _run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    name,
                    "-e",
                    "AGIFT_MODE=worker",
                    "-e",
                    "BACKEND_TYPE=cogdb",
                    docker_image,
                ],
                timeout=30,
            )

            # Give it a moment to start
            time.sleep(3)

            # Check container is still running
            inspect = _run(
                ["docker", "inspect", "-f", "{{.State.Running}}", name],
                timeout=10,
            )
            assert "true" in inspect.stdout.lower(), (
                f"Worker container not running. Logs:\n"
                + _run(["docker", "logs", name], timeout=10).stdout
            )

            # Verify cron file was created
            result = _run(
                ["docker", "exec", name, "cat", "/etc/cron.d/weekly-agift"],
                timeout=10,
            )
            assert result.returncode == 0
            assert "run_agift_refresh.sh" in result.stdout

            # Verify refresh script is executable
            result = _run(
                ["docker", "exec", name, "test", "-x", "/app/run_agift_refresh.sh"],
                timeout=10,
            )
            assert result.returncode == 0
        finally:
            _remove_container(name)
