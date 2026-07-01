"""Validate all scraper templates — verify JSON schema, required fields, and selector structure.
This ensures every template is structurally correct before we claim it works."""

import json
import sys
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent
REQUIRED_KEYS = ["name", "description", "site", "category", "icon", "schema"]
REQUIRED_SCHEMA_KEYS = ["name", "base_selector", "fields"]
REQUIRED_FIELD_KEYS = ["name", "selector", "type"]
VALID_TYPES = {"text", "attribute", "html", "nested", "count", "exists", "regex"}
VALID_TRANSFORMS = {"strip_currency", "lower", "upper", "strip", "int", "float", ""}


def validate_template(path: Path) -> list[str]:
    errors = []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f"Invalid JSON: {e}"]

    for key in REQUIRED_KEYS:
        if key not in data:
            errors.append(f"Missing required key: {key}")

    schema = data.get("schema", {})
    for key in REQUIRED_SCHEMA_KEYS:
        if key not in schema:
            errors.append(f"Schema missing required key: {key}")

    fields = schema.get("fields", [])
    if not fields:
        errors.append("Schema has no fields")

    for i, field in enumerate(fields):
        for key in REQUIRED_FIELD_KEYS:
            if key not in field:
                errors.append(f"Field {i} missing required key: {key}")
        ftype = field.get("type", "")
        if ftype and ftype not in VALID_TYPES:
            errors.append(f"Field {i} invalid type: {ftype}")
        transform = field.get("transform", "")
        if transform and transform not in VALID_TRANSFORMS:
            errors.append(f"Field {i} invalid transform: {transform}")

    return errors


def main() -> int:
    all_errors = {}
    total = 0
    valid = 0

    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        if path.name == "validate_templates.py":
            continue
        total += 1
        errors = validate_template(path)
        if errors:
            all_errors[path.name] = errors
        else:
            valid += 1

    if all_errors:
        for name, errors in all_errors.items():
            print(f"❌ {name}:")
            for e in errors:
                print(f"   - {e}")
        print(f"\n{valid}/{total} templates valid, {len(all_errors)} failed")
        return 1
    else:
        print(f"✅ All {total} templates valid!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
