# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from typing import Any

CATEGORIES: dict[str, list[dict[str, Any]]] = {
    "hosting": [
        {
            "name": "Hetzner",
            "url": "https://hetzner.com/?ref=pry",
            "commission": "\u20ac25/signup + 10% recurring",
            "cookie_days": 90,
            "tag": "hetzner",
        },
        {
            "name": "DigitalOcean",
            "url": "https://m.do.co/c/pry",
            "commission": "$25/paid referral",
            "cookie_days": 60,
            "tag": "do",
        },
        {
            "name": "Linode (Akamai)",
            "url": "https://www.linode.com/?ref=pry",
            "commission": "$20/paid referral",
            "cookie_days": 60,
            "tag": "linode",
        },
        {
            "name": "Vultr",
            "url": "https://www.vultr.com/?ref=pry",
            "commission": "$10-$50/signup",
            "cookie_days": 30,
            "tag": "vultr",
        },
        {
            "name": "OVHcloud",
            "url": "https://www.ovhcloud.com/?ref=pry",
            "commission": "Partner program",
            "cookie_days": 30,
            "tag": "ovh",
        },
        {
            "name": "UpCloud",
            "url": "https://upcloud.com/?ref=pry",
            "commission": "Usage share",
            "cookie_days": 30,
            "tag": "upcloud",
        },
        {
            "name": "Netcup",
            "url": "https://netcup.com/?ref=pry",
            "commission": "\u20ac5/signup",
            "cookie_days": 90,
            "tag": "netcup",
        },
    ],
    "domains": [
        {
            "name": "Namecheap",
            "url": "https://namecheap.com/?affiliateid=pry",
            "commission": "Up to $50/domain",
            "cookie_days": 365,
            "tag": "namecheap",
        },
        {
            "name": "Cloudflare Registrar",
            "url": "https://cloudflare.com/?ref=pry",
            "commission": "At-cost pricing",
            "cookie_days": 0,
            "tag": "cloudflare",
        },
        {
            "name": "Porkbun",
            "url": "https://porkbun.com/?affiliate=pry",
            "commission": "$0.50-$2/domain",
            "cookie_days": 365,
            "tag": "porkbun",
        },
        {
            "name": "Spaceship",
            "url": "https://spaceship.com/?affiliate=pry",
            "commission": "Usage share",
            "cookie_days": 30,
            "tag": "spaceship",
        },
    ],
    "cdn": [
        {
            "name": "Cloudflare",
            "url": "https://cloudflare.com/?ref=pry",
            "commission": "Partner program",
            "cookie_days": 30,
            "tag": "cloudflare",
        },
        {
            "name": "Bunny CDN",
            "url": "https://bunny.net?affiliate=pry",
            "commission": "10% recurring lifetime",
            "cookie_days": 60,
            "tag": "bunny",
        },
        {
            "name": "Fastly",
            "url": "https://fastly.com/?ref=pry",
            "commission": "Partner program",
            "cookie_days": 30,
            "tag": "fastly",
        },
    ],
    "email": [
        {
            "name": "SendGrid",
            "url": "https://sendgrid.com/?ref=pry",
            "commission": "$30/referral",
            "cookie_days": 30,
            "tag": "sendgrid",
        },
        {
            "name": "Mailgun",
            "url": "https://mailgun.com/?ref=pry",
            "commission": "Usage share",
            "cookie_days": 30,
            "tag": "mailgun",
        },
        {
            "name": "Resend",
            "url": "https://resend.com/?ref=pry",
            "commission": "$20/signup",
            "cookie_days": 30,
            "tag": "resend",
        },
        {
            "name": "Postmark",
            "url": "https://postmarkapp.com/?ref=pry",
            "commission": "Usage share",
            "cookie_days": 30,
            "tag": "postmark",
        },
        {
            "name": "Brevo (Sendinblue)",
            "url": "https://www.brevo.com/?ref=pry",
            "commission": "Paid plan share",
            "cookie_days": 30,
            "tag": "brevo",
        },
    ],
    "monitoring": [
        {
            "name": "Sentry",
            "url": "https://sentry.io/?ref=pry",
            "commission": "$100-$1,000 (tiered)",
            "cookie_days": 60,
            "tag": "sentry",
        },
        {
            "name": "Datadog",
            "url": "https://datadoghq.com/?ref=pry",
            "commission": "Partner program",
            "cookie_days": 30,
            "tag": "datadog",
        },
        {
            "name": "Better Stack",
            "url": "https://betterstack.com/?ref=pry",
            "commission": "$50/paid signup",
            "cookie_days": 30,
            "tag": "betterstack",
        },
        {
            "name": "Highlight.io",
            "url": "https://highlight.io/?ref=pry",
            "commission": "Usage share",
            "cookie_days": 30,
            "tag": "highlight",
        },
        {
            "name": "PostHog",
            "url": "https://posthog.com/?ref=pry",
            "commission": "20% recurring for 2 years",
            "cookie_days": 60,
            "tag": "posthog",
        },
    ],
}
