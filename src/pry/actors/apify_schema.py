"""Pry — Apify actor input/output schema builder.

Provides a fluent, typed API for constructing Apify actor input and output
schemas (JSON Schema compatible with Apify's `INPUT_SCHEMA.json` and
`OUTPUT_SCHEMA.json`).

Example:
    builder = ApifySchemaBuilder("Product Scraper")
    builder.add_string("url", "Start URL", required=True)
    builder.add_integer("maxResults", "Max Results", default=10, min=1, max=100)
    builder.add_enum("format", "Output Format", ["json", "csv", "markdown"], default="json")
    schema = builder.build_input_schema()
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT.
from __future__ import annotations

from typing import Any


class FieldSpec:
    """Base class for Apify schema field specifications."""

    def __init__(
        self,
        name: str,
        title: str,
        field_type: str,
        description: str = "",
        default: Any | None = None,
        nullable: bool = False,
    ) -> None:
        self.name = name
        self.title = title
        self.field_type = field_type
        self.description = description
        self.default = default
        self.nullable = nullable

    def to_dict(self) -> dict[str, Any]:
        spec: dict[str, Any] = {
            "title": self.title,
            "type": ([self.field_type, "null"] if self.nullable else self.field_type),
        }
        if self.description:
            spec["description"] = self.description
        if self.default is not None:
            spec["default"] = self.default
        return spec


class StringField(FieldSpec):
    """String field with optional pattern and editor hints."""

    def __init__(
        self,
        name: str,
        title: str,
        description: str = "",
        default: str | None = None,
        nullable: bool = False,
        min_length: int | None = None,
        max_length: int | None = None,
        pattern: str | None = None,
        editor: str | None = None,
    ) -> None:
        super().__init__(name, title, "string", description, default, nullable)
        self.min_length = min_length
        self.max_length = max_length
        self.pattern = pattern
        self.editor = editor

    def to_dict(self) -> dict[str, Any]:
        spec = super().to_dict()
        if self.min_length is not None:
            spec["minLength"] = self.min_length
        if self.max_length is not None:
            spec["maxLength"] = self.max_length
        if self.pattern is not None:
            spec["pattern"] = self.pattern
        if self.editor is not None:
            spec["editor"] = self.editor
        return spec


class IntegerField(FieldSpec):
    """Integer field with optional range."""

    def __init__(
        self,
        name: str,
        title: str,
        description: str = "",
        default: int | None = None,
        nullable: bool = False,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> None:
        super().__init__(name, title, "integer", description, default, nullable)
        self.minimum = minimum
        self.maximum = maximum

    def to_dict(self) -> dict[str, Any]:
        spec = super().to_dict()
        if self.minimum is not None:
            spec["minimum"] = self.minimum
        if self.maximum is not None:
            spec["maximum"] = self.maximum
        return spec


class NumberField(FieldSpec):
    """Number field with optional range."""

    def __init__(
        self,
        name: str,
        title: str,
        description: str = "",
        default: float | None = None,
        nullable: bool = False,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> None:
        super().__init__(name, title, "number", description, default, nullable)
        self.minimum = minimum
        self.maximum = maximum

    def to_dict(self) -> dict[str, Any]:
        spec = super().to_dict()
        if self.minimum is not None:
            spec["minimum"] = self.minimum
        if self.maximum is not None:
            spec["maximum"] = self.maximum
        return spec


class BooleanField(FieldSpec):
    """Boolean field with optional default."""

    def __init__(
        self,
        name: str,
        title: str,
        description: str = "",
        default: bool | None = None,
        nullable: bool = False,
    ) -> None:
        super().__init__(name, title, "boolean", description, default, nullable)


class EnumField(FieldSpec):
    """Enum field restricted to a set of allowed values."""

    def __init__(
        self,
        name: str,
        title: str,
        enum: list[str],
        description: str = "",
        default: str | None = None,
        nullable: bool = False,
    ) -> None:
        super().__init__(name, title, "string", description, default, nullable)
        self.enum = enum

    def to_dict(self) -> dict[str, Any]:
        spec = super().to_dict()
        spec["enum"] = self.enum
        return spec


class ArrayField(FieldSpec):
    """Array field with item schema."""

    def __init__(
        self,
        name: str,
        title: str,
        items: dict[str, Any],
        description: str = "",
        default: list[Any] | None = None,
        nullable: bool = False,
        min_items: int | None = None,
        max_items: int | None = None,
    ) -> None:
        super().__init__(name, title, "array", description, default, nullable)
        self.items = items
        self.min_items = min_items
        self.max_items = max_items

    def to_dict(self) -> dict[str, Any]:
        spec = super().to_dict()
        spec["items"] = self.items
        if self.min_items is not None:
            spec["minItems"] = self.min_items
        if self.max_items is not None:
            spec["maxItems"] = self.max_items
        return spec


class ObjectField(FieldSpec):
    """Object field with nested properties."""

    def __init__(
        self,
        name: str,
        title: str,
        properties: dict[str, Any],
        description: str = "",
        default: dict[str, Any] | None = None,
        nullable: bool = False,
        required: list[str] | None = None,
    ) -> None:
        super().__init__(name, title, "object", description, default, nullable)
        self.properties = properties
        self.required = required or []

    def to_dict(self) -> dict[str, Any]:
        spec = super().to_dict()
        spec["properties"] = self.properties
        if self.required:
            spec["required"] = self.required
        return spec


class ApifySchemaBuilder:
    """Fluent builder for Apify actor input/output schemas."""

    def __init__(
        self, title: str = "Actor Input", description: str = "", schema_version: int = 1
    ) -> None:
        self.title = title
        self.description = description
        self.schema_version = schema_version
        self._fields: dict[str, FieldSpec] = {}
        self._required: list[str] = []
        self._prefab: str | None = None

    def add_field(self, field: FieldSpec, required: bool = False) -> ApifySchemaBuilder:
        """Add a field specification to the schema."""
        self._fields[field.name] = field
        if required:
            self._required.append(field.name)
        return self

    def add_string(
        self,
        name: str,
        title: str,
        description: str = "",
        required: bool = False,
        default: str | None = None,
        nullable: bool = False,
        min_length: int | None = None,
        max_length: int | None = None,
        pattern: str | None = None,
        editor: str | None = None,
    ) -> ApifySchemaBuilder:
        field = StringField(
            name,
            title,
            description=description,
            default=default,
            nullable=nullable,
            min_length=min_length,
            max_length=max_length,
            pattern=pattern,
            editor=editor,
        )
        return self.add_field(field, required=required)

    def add_integer(
        self,
        name: str,
        title: str,
        description: str = "",
        required: bool = False,
        default: int | None = None,
        nullable: bool = False,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> ApifySchemaBuilder:
        field = IntegerField(
            name,
            title,
            description=description,
            default=default,
            nullable=nullable,
            minimum=minimum,
            maximum=maximum,
        )
        return self.add_field(field, required=required)

    def add_number(
        self,
        name: str,
        title: str,
        description: str = "",
        required: bool = False,
        default: float | None = None,
        nullable: bool = False,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> ApifySchemaBuilder:
        field = NumberField(
            name,
            title,
            description=description,
            default=default,
            nullable=nullable,
            minimum=minimum,
            maximum=maximum,
        )
        return self.add_field(field, required=required)

    def add_boolean(
        self,
        name: str,
        title: str,
        description: str = "",
        required: bool = False,
        default: bool | None = None,
        nullable: bool = False,
    ) -> ApifySchemaBuilder:
        field = BooleanField(
            name, title, description=description, default=default, nullable=nullable
        )
        return self.add_field(field, required=required)

    def add_enum(
        self,
        name: str,
        title: str,
        enum: list[str],
        description: str = "",
        required: bool = False,
        default: str | None = None,
        nullable: bool = False,
    ) -> ApifySchemaBuilder:
        field = EnumField(
            name, title, enum, description=description, default=default, nullable=nullable
        )
        return self.add_field(field, required=required)

    def add_array(
        self,
        name: str,
        title: str,
        items: dict[str, Any],
        description: str = "",
        required: bool = False,
        default: list[Any] | None = None,
        nullable: bool = False,
        min_items: int | None = None,
        max_items: int | None = None,
    ) -> ApifySchemaBuilder:
        field = ArrayField(
            name,
            title,
            items,
            description=description,
            default=default,
            nullable=nullable,
            min_items=min_items,
            max_items=max_items,
        )
        return self.add_field(field, required=required)

    def add_object(
        self,
        name: str,
        title: str,
        properties: dict[str, Any],
        description: str = "",
        required: bool = False,
        default: dict[str, Any] | None = None,
        nullable: bool = False,
        nested_required: list[str] | None = None,
    ) -> ApifySchemaBuilder:
        field = ObjectField(
            name,
            title,
            properties,
            description=description,
            default=default,
            nullable=nullable,
            required=nested_required,
        )
        return self.add_field(field, required=required)

    def set_prefab(self, prefab: str) -> ApifySchemaBuilder:
        """Set an Apify input schema prefab (e.g., 'START_URLS')."""
        self._prefab = prefab
        return self

    def build_input_schema(self) -> dict[str, Any]:
        """Build an Apify INPUT_SCHEMA.json-compatible dict."""
        schema: dict[str, Any] = {
            "title": self.title,
            "type": "object",
            "schemaVersion": self.schema_version,
            "properties": {name: field.to_dict() for name, field in self._fields.items()},
        }
        if self.description:
            schema["description"] = self.description
        if self._required:
            schema["required"] = self._required
        if self._prefab:
            schema["prefab"] = self._prefab
        return schema

    def build_output_schema(self) -> dict[str, Any]:
        """Build an Apify OUTPUT_SCHEMA.json-compatible dict."""
        schema: dict[str, Any] = {
            "title": self.title,
            "type": "object",
            "schemaVersion": self.schema_version,
            "properties": {name: field.to_dict() for name, field in self._fields.items()},
        }
        if self.description:
            schema["description"] = self.description
        if self._required:
            schema["required"] = self._required
        return schema
