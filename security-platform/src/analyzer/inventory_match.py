"""Match vulnerabilities against the component inventory."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

INVENTORY_PATH = Path(__file__).parent.parent.parent / "config" / "inventory.yaml"


def _load_inventory() -> dict[str, Any]:
    """Load and return the inventory YAML data."""
    if not INVENTORY_PATH.exists():
        logger.warning("Inventory file not found: %s", INVENTORY_PATH)
        return {}
    with open(INVENTORY_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _normalize_package_name(name: str) -> str:
    """Normalize a package name for comparison (lowercase, strip scope prefix for npm)."""
    name = name.lower().strip()
    # Strip npm scope: @scope/package -> package
    if name.startswith("@"):
        parts = name.split("/", 1)
        if len(parts) == 2:
            return parts[1]
    return name


def _names_match(vuln_name: str, inventory_name: str) -> bool:
    """Check if a vulnerability's affected package name matches an inventory component.

    Handles:
    - Exact match
    - Case-insensitive match
    - npm scoped package comparison (@scope/name vs name)
    - Partial match (substring)
    """
    if not vuln_name or not inventory_name:
        return False

    v = vuln_name.lower().strip()
    i = inventory_name.lower().strip()

    # Exact match
    if v == i:
        return True

    # Normalized (strip scope)
    vn = _normalize_package_name(v)
    inv_n = _normalize_package_name(i)
    if vn == inv_n:
        return True

    # Substring match (e.g., "server-filesystem" matches "@modelcontextprotocol/server-filesystem")
    if vn in inv_n or inv_n in vn:
        return True

    # Hyphen/underscore normalization
    v_norm = re.sub(r"[-_]", "", vn)
    i_norm = re.sub(r"[-_]", "", inv_n)
    if v_norm == i_norm:
        return True

    return False


def match_vulnerability(vuln_dict: dict[str, Any]) -> list[str]:
    """Match a vulnerability against the component inventory.

    Returns a list of matching component names from the inventory.
    """
    inventory = _load_inventory()
    if not inventory:
        return []

    affected_name = vuln_dict.get("affected_component_name", "") or ""
    affected_ecosystem = (vuln_dict.get("affected_component_ecosystem", "") or "").lower()
    title = (vuln_dict.get("title", "") or "").lower()
    description = (vuln_dict.get("description", "") or "").lower()
    tags = [t.lower() for t in (vuln_dict.get("tags", []) or [])]

    matched: list[str] = []

    # All inventory components to check
    all_components: list[dict[str, Any]] = []
    all_components.extend(inventory.get("mcp_servers", []))
    all_components.extend(inventory.get("npm_packages", []))
    all_components.extend(inventory.get("python_packages", []))
    all_components.extend(inventory.get("skills", []))

    for component in all_components:
        comp_name = component.get("name", "")
        comp_ecosystem = (component.get("ecosystem", "") or "").lower()
        comp_tags = [t.lower() for t in component.get("tags", [])]

        # Direct name match
        if affected_name and _names_match(affected_name, comp_name):
            matched.append(comp_name)
            continue

        # Ecosystem-aware matching for ecosystem-generic vulnerabilities
        if affected_ecosystem:
            eco_map = {
                "npm": ["npm", "node"],
                "pypi": ["pip", "python", "pypi"],
                "go": ["go", "golang"],
            }
            for eco_key, eco_aliases in eco_map.items():
                if eco_key in affected_ecosystem or affected_ecosystem in eco_aliases:
                    if comp_ecosystem in eco_aliases or eco_key in comp_ecosystem:
                        # Check if component name appears in description/title
                        if comp_name.lower() in description or comp_name.lower() in title:
                            matched.append(comp_name)
                            break

        # Tag-based matching (e.g., both tagged "mcp-server")
        if comp_tags and tags:
            common_tags = set(comp_tags) & set(tags)
            if common_tags and comp_name.lower() in (title + " " + description):
                if comp_name not in matched:
                    matched.append(comp_name)

    return list(set(matched))
