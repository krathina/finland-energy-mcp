"""The project's identity (name, version, home page), read from the installed package metadata.

The values live in pyproject.toml only; installing the project copies them into the package
metadata, which is what this module reads (like reading a jar's MANIFEST.MF in Java).
"""

from importlib import metadata

_DISTRIBUTION = "finland-energy-mcp"  # the name in pyproject.toml; the key to look the rest up


def name() -> str:
    """Project name, e.g. "finland-energy-mcp"."""
    return metadata.metadata(_DISTRIBUTION)["Name"]


def version() -> str:
    """Installed version, e.g. "0.1.0"."""
    return metadata.version(_DISTRIBUTION)


def home_page() -> str:
    """The Homepage entry of [project.urls] in pyproject.toml."""
    # Stored as "Project-URL: Homepage, https://..." lines in the metadata.
    for entry in metadata.metadata(_DISTRIBUTION).get_all("Project-URL") or []:
        label, _, url = str(entry).partition(",")
        if label.strip().lower() == "homepage":
            return url.strip()
    raise LookupError("no Homepage in [project.urls] of pyproject.toml")


def user_agent() -> str:
    """How we introduce ourselves to APIs: project, version and home page (no personal data)."""
    return f"{name()}/{version()} (+{home_page()})"
