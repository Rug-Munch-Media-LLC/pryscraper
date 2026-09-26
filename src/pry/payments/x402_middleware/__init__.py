"""x402 ASGI payment middleware — package facade (audit E41 split).

The former 1,000+ line monolith is now:
    config.py          — PAID_ENDPOINTS + pricing tier tables
    classification.py  — fail-closed free/paid route classification
    enforcement.py     — X402Middleware ASGI enforcement + header budget

The public import surface is UNCHANGED: every name previously importable
from ``pry.payments.x402_middleware`` still resolves here.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from pry.payments.x402 import X402_PRICING
from pry.payments.x402_middleware.classification import (
    DEFAULT_FREE_PATHS,
    DEFAULT_FREE_PREFIXES,
    _admin_prefix,
    _caller_key_from_scope,
    audit_route_classification,
    classify_path,
    iter_app_route_paths,
    resolve_operation,
)
from pry.payments.x402_middleware.config import (
    PAID_ENDPOINTS,
    X402_GATE_MISCONFIGURED,
)
from pry.payments.x402_middleware.enforcement import (
    X402_PAYMENT_HEADER_MAX_BYTES,
    X402Middleware,
    _compact_payment_required_header,
)
from pry.payments.x402_middleware.internal import (
    INTERNAL_SCOPE_KEY,
    INTERNAL_SIG_HEADER,
    INTERNAL_TOKEN_HEADER,
    internal_enabled,
    internal_request,
    internal_signature,
    internal_token,
    mark_internal_verified,
)

__all__ = [
    "DEFAULT_FREE_PATHS",
    "DEFAULT_FREE_PREFIXES",
    "INTERNAL_SCOPE_KEY",
    "INTERNAL_SIG_HEADER",
    "INTERNAL_TOKEN_HEADER",
    "PAID_ENDPOINTS",
    "X402_GATE_MISCONFIGURED",
    "X402_PAYMENT_HEADER_MAX_BYTES",
    "X402_PRICING",
    "X402Middleware",
    "_admin_prefix",
    "_caller_key_from_scope",
    "_compact_payment_required_header",
    "audit_route_classification",
    "classify_path",
    "internal_enabled",
    "internal_request",
    "internal_signature",
    "internal_token",
    "iter_app_route_paths",
    "mark_internal_verified",
    "resolve_operation",
]
