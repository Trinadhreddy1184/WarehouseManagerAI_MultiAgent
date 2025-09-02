"""Utility functions for loading configuration files with environment variable
substitution.

Configuration in this project is stored in YAML files under ``src/config``.
Values can include shell‑style variables such as ``${DB_HOST}`` which will be
replaced with the corresponding environment variable at load time.  The
loader functions return plain Python dictionaries.
"""
import os
from typing import Any, Dict
import yaml

def _load_yaml_with_env(path: str) -> Dict[str, Any]:
    """Load a YAML file and expand any environment variables in its contents.

    Parameters
    ----------
    path : str
        Relative or absolute path to the YAML file.

    Returns
    -------
    Dict[str, Any]
        The parsed YAML structure with environment variables substituted.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    # Expand environment variables like ${VAR_NAME}
    expanded = os.path.expandvars(raw)
    return yaml.safe_load(expanded) or {}


def load_llm_config(path: str) -> Dict[str, Any]:
    """Load the large language model configuration from YAML.

    The returned dictionary will include keys ``llm`` and ``bedrock``.  See
    ``src/config/llm_config.yaml`` for an example.
    """
    return _load_yaml_with_env(path)


def load_database_config(path: str) -> Dict[str, Any]:
    """Load the database configuration from YAML.

    The returned dictionary will contain a ``database`` section describing
    connection parameters.  See ``src/config/database_config.yaml`` for
    details.
    """
    return _load_yaml_with_env(path)
