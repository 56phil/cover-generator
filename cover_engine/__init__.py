"""Cover generation engine for print and front-cover exports."""

from .legacy import (
    BINDING_OPTIONS,
    DEFAULT_METADATA,
    CoverError,
    CoverGenerator,
    Geometry,
    calculate_geometry,
    normalize_loaded_data,
    read_frontmatter,
    repo_name,
    resolve_path,
    set_project_context,
    write_metadata,
)
from .metadata import load_metadata, save_metadata
from .validation import ValidationIssue, validate_cover
