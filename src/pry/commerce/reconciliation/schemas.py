"""Pry — reconciliation vertical schemas."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from typing import Any, Literal, NotRequired, TypedDict

FieldType = Literal["str", "float", "int", "bool"]


class FieldConfig(TypedDict):
    type: FieldType
    required: bool
    description: NotRequired[str]
    default: NotRequired[Any]


class Schema(TypedDict):
    name: str
    fields: dict[str, FieldConfig]
    identity_fields: list[str]


# ── Vertical Schemas ──

VERTICAL_SCHEMAS: dict[str, Schema] = {
    "product": {
        "name": "Product",
        "fields": {
            "name": {"type": "str", "required": True, "description": "Product name"},
            "price": {"type": "float", "required": True, "description": "Current price"},
            "original_price": {
                "type": "float",
                "required": False,
                "description": "Original/MSRP price",
            },
            "currency": {
                "type": "str",
                "required": False,
                "default": "USD",
                "description": "Currency code",
            },
            "availability": {
                "type": "str",
                "required": False,
                "description": "in_stock, out_of_stock, pre_order",
            },
            "brand": {"type": "str", "required": False, "description": "Brand/manufacturer"},
            "sku": {"type": "str", "required": False, "description": "Product SKU or ID"},
            "url": {"type": "str", "required": True, "description": "Product URL"},
            "image_url": {"type": "str", "required": False, "description": "Product image URL"},
            "description": {"type": "str", "required": False, "description": "Product description"},
            "rating": {"type": "float", "required": False, "description": "Average rating (0-5)"},
            "review_count": {"type": "int", "required": False, "description": "Number of reviews"},
            "category": {"type": "str", "required": False, "description": "Product category"},
        },
        "identity_fields": ["name", "sku", "url"],
    },
    "job": {
        "name": "Job Posting",
        "fields": {
            "title": {"type": "str", "required": True, "description": "Job title"},
            "company": {"type": "str", "required": True, "description": "Company name"},
            "location": {"type": "str", "required": False, "description": "Job location"},
            "salary_min": {"type": "float", "required": False, "description": "Minimum salary"},
            "salary_max": {"type": "float", "required": False, "description": "Maximum salary"},
            "salary_currency": {"type": "str", "required": False, "default": "USD"},
            "description": {"type": "str", "required": False, "description": "Job description"},
            "url": {"type": "str", "required": True, "description": "Job posting URL"},
            "posted_date": {"type": "str", "required": False, "description": "Posted date"},
            "job_type": {
                "type": "str",
                "required": False,
                "description": "Full-time, part-time, contract",
            },
        },
        "identity_fields": ["title", "company"],
    },
    "real_estate": {
        "name": "Real Estate Listing",
        "fields": {
            "address": {"type": "str", "required": True, "description": "Property address"},
            "price": {"type": "float", "required": True, "description": "Listing price"},
            "bedrooms": {"type": "int", "required": False, "description": "Number of bedrooms"},
            "bathrooms": {"type": "float", "required": False, "description": "Number of bathrooms"},
            "sqft": {"type": "int", "required": False, "description": "Square footage"},
            "property_type": {
                "type": "str",
                "required": False,
                "description": "House, condo, apartment",
            },
            "url": {"type": "str", "required": True, "description": "Listing URL"},
            "description": {"type": "str", "required": False, "description": "Listing description"},
        },
        "identity_fields": ["address"],
    },
    "review": {
        "name": "Review",
        "fields": {
            "product_name": {
                "type": "str",
                "required": True,
                "description": "Product being reviewed",
            },
            "rating": {"type": "int", "required": True, "description": "Rating (1-5)"},
            "title": {"type": "str", "required": False, "description": "Review title"},
            "body": {"type": "str", "required": False, "description": "Review text"},
            "author": {"type": "str", "required": False, "description": "Review author"},
            "date": {"type": "str", "required": False, "description": "Review date"},
            "url": {"type": "str", "required": True, "description": "Review URL"},
        },
        "identity_fields": ["product_name", "author", "title"],
    },
}


__all__ = ["VERTICAL_SCHEMAS", "FieldConfig", "FieldType", "Schema"]
