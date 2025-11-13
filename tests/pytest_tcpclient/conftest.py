import tomllib
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def setup_pytester_config(pytester: pytest.Pytester) -> None:
    """Automatically configure pytester with pytest-asyncio settings to avoid deprecation warnings.

    This fixture reads the pytest configuration from the main pyproject.toml file
    and applies any pytest.ini_options to the pytester instance used in tests.
    """
    # Read the pytest configuration from the main pyproject.toml
    project_root = Path(__file__).parent.parent.parent
    pyproject_path = project_root / "pyproject.toml"

    with open(pyproject_path, "rb") as f:
        config = tomllib.load(f)

    # Extract pytest configuration if it exists
    pytest_config = config.get("tool", {}).get("pytest", {}).get("ini_options", {})

    if pytest_config:
        # Create a minimal pyproject.toml with just the pytest configuration
        pyproject_content = "[tool.pytest.ini_options]\n"
        for key, value in pytest_config.items():
            # only if key begins with "asyncio_"
            if not key.startswith("asyncio_"):
                continue
            if isinstance(value, bool):
                pyproject_content += f"{key} = {str(value).lower()}\n"
            elif isinstance(value, str):
                pyproject_content += f'{key} = "{value}"\n'
            else:
                pyproject_content += f"{key} = {value}\n"

        pytester.makepyprojecttoml(pyproject_content.strip())
