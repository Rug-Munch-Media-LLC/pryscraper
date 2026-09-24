"""Hosted-Pry API facade preserving the historical import path.

Signup, instance management, checkout, and portal routes are split into
focused modules while ``pry.api.routers.commerce.hosting.router`` and the
request models remain available from this package.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from pry.api.routers.commerce.hosting import (
    checkout as checkout,
    instances as instances,
    signup as signup,
)
from pry.api.routers.commerce.hosting.checkout import (
    hosting_checkout_page,
    hosting_portal,
    hosting_portal_request,
)
from pry.api.routers.commerce.hosting.instances import (
    hosting_instance_cancel,
    hosting_instance_detail,
    hosting_instance_renew,
    hosting_instances,
)
from pry.api.routers.commerce.hosting.models import (
    HostingConfirmRequest,
    HostingPortalRequest,
    HostingSignupRequest,
    HostingVerifyRequest,
)
from pry.api.routers.commerce.hosting.router import router
from pry.api.routers.commerce.hosting.signup import (
    hosting_plans,
    hosting_signup,
    hosting_signup_confirm,
    hosting_signup_verify,
    hosting_verify_link,
)

__all__ = [
    "HostingConfirmRequest",
    "HostingPortalRequest",
    "HostingSignupRequest",
    "HostingVerifyRequest",
    "hosting_checkout_page",
    "hosting_instance_cancel",
    "hosting_instance_detail",
    "hosting_instance_renew",
    "hosting_instances",
    "hosting_plans",
    "hosting_portal",
    "hosting_portal_request",
    "hosting_signup",
    "hosting_signup_confirm",
    "hosting_signup_verify",
    "hosting_verify_link",
    "router",
]
