"""Nox configuration."""

import nox

nox.options.sessions = ["formatter", "lint", "mypy", "test"]
nox.options.default_venv_backend = "uv|virtualenv"
nox.options.reuse_existing_virtualenvs = True


@nox.session(python=["3.14"])
def formatter(session: nox.Session) -> None:
    """Run code formatter."""
    session.install("ruff", "black")
    session.install("-e", ".[dev]")
    session.run("ruff", "check", "--fix-only", ".")
    session.run("ruff", "format", ".")
    session.run("black", ".")


@nox.session(python=["3.14"])
def lint(session: nox.Session) -> None:
    """Lint with ruff."""
    session.install("ruff")
    session.install("-e", ".[dev]")
    session.run("ruff", "check", ".")


@nox.session(python=["3.14"])
def mypy(session: nox.Session) -> None:
    """Typecheck with mypy."""
    session.install("mypy")
    session.install("-e", ".[dev]")
    session.run("python3", "-m", "mypy", "src")


@nox.session(
    python=["3.14", "3.13", "3.12", "3.11"],
)
def test(session: nox.Session) -> None:
    """Run unittests."""
    session.install("-e", ".[dev]")
    session.run("coverage", "erase")
    session.run(
        "python",
        "-m",
        "pytest",
        "tests/",
        "-v",  # verbose output
        #"-x",  # stop after first failure
        # "--timeout=3",  # noqa: ERA001
        # "--session-timeout=15",  # noqa: ERA001
    )
    session.notify("coverage")


@nox.session(python=["3.14"])
def coverage(session: nox.Session) -> None:
    """Generate coverage report."""
    session.install("-e", ".[dev]")
    session.run("coverage", "html", "-d", "coverage.html")
    session.run("coverage", "xml", "-o", "coverage.xml")
    session.run("coverage", "lcov", "-o", "lcov.info")
    session.run("coverage", "report", "-m")
