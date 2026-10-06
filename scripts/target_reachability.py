"""Target reachability precheck — classify a target BEFORE blaming a tier.
The failure this prevents: an operator sees a browser tier fail, assumes Pry
is broken, and rebuilds a ladder that was never the problem. The usual cause is
an unreachable target presented as a scrape error. Unreachable is a fact about
the TARGET, not about us.
The TLS half exists because ``openssl s_client`` prints
``Verify return code: 0`` even when the handshake failed and NO peer
certificate was presented. That line alone is not evidence; only a subject
plus a SAN covering the hostname is.
Classification is pure — ``classify``/``classify_tls``/``blame_tier`` open no
socket, so the taxonomy is testable offline by injecting :class:`TargetProbe`.
"""

from __future__ import annotations

import logging
import socket
import ssl
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


class Failure(StrEnum):
    """Where the path to the target broke. Each is a distinct, actionable fact."""

    NONE = "none"
    DNS = "dns"
    TCP_REFUSED = "tcp_refused"
    TLS_HANDSHAKE = "tls_handshake"
    TLS_NO_PEER_CERT = "tls_no_peer_cert"
    TLS_HOSTNAME_MISMATCH = "tls_hostname_mismatch"
    UNREACHABLE = "unreachable"


class Reachability(StrEnum):
    """The verdict. Only REACHABLE and REFUSING are a usable site."""

    REACHABLE = "reachable"  # connected, valid cert, we are welcome
    REFUSING = "refusing"  # 403/401/429 — reachable, refusing US; use a proxy tier
    UNREACHABLE = "unreachable"  # broken before any HTTP status exists
    UNKNOWN = "unknown"  # no observation; never assert a fault on this


@dataclass(frozen=True)
class TargetProbe:
    """Facts observed for one target. Every field defaults to UNKNOWN.
    Absence of evidence is represented, never guessed: ``dns_ok=False`` with
    ``dns_error=None`` is still UNKNOWN — we cannot tell a lookup failure
    from a probe that never ran.
    """

    dns_ok: bool | None = None
    dns_error: str | None = None
    tcp_ok: bool | None = None
    tcp_error: str | None = None
    tls_completed: bool | None = None
    tls_error: str | None = None
    cert_subject: str | None = None
    cert_sans: tuple[str, ...] = ()
    cert_verified: bool | None = None
    http_status: int | None = None

    @property
    def observed(self) -> bool:
        keys = (self.dns_ok, self.tcp_ok, self.tls_completed, self.http_status)
        return any(v is not None for v in keys)


def classify_tls(probe: TargetProbe, hostname: str) -> Failure:
    """TLS-only verdict. Requires a verified cert with subject AND covering SAN.

    ``tls_completed`` alone is never sufficient — that is the exact trap.
    """
    if probe.tls_completed is None:
        return Failure.NONE if not probe.observed else Failure.UNREACHABLE
    if not probe.tls_completed:
        return Failure.TLS_HANDSHAKE
    if not probe.cert_subject:  # handshake "completed" but no cert presented
        return Failure.TLS_NO_PEER_CERT
    if not _san_covers(probe.cert_sans, hostname):
        return Failure.TLS_HOSTNAME_MISMATCH
    return Failure.TLS_HANDSHAKE if probe.cert_verified is False else Failure.NONE


def _san_covers(sans: tuple[str, ...], hostname: str) -> bool:
    """RFC 6125 name match: exact, single left-most wildcard, or a literal IP."""
    host = hostname.lower().strip(".")
    try:
        socket.inet_aton(host)
    except OSError as e:
        logger.warning(
            "suppressed %s in _san_covers (target_reachability.py:103): %s",
            "OSError",
            e,
        )
    else:
        return host in {s.lower().strip(".") for s in sans}
    for san in sans:
        name = san.lower().strip(".")
        if name == host:
            return True
        if name.startswith("*.") and host.split(".", 1)[-1] == name[2:] and name.count("*") == 1:
            return True
    return False


def classify(probe: TargetProbe, hostname: str) -> Reachability:
    """Single entry point: transport first, then HTTP, then fall back to UNKNOWN.

    Transport precedes HTTP because a status cannot exist without a transport.
    A 403 is REFUSING, never UNREACHABLE — refusing us is what a proxy tier is
    FOR, and conflating the two sends the operator to rebuild the ladder for a
    reachable site. ``TLS_NO_PEER_CERT`` maps to UNKNOWN, not UNREACHABLE: the
    handshake finished, so we have no evidence of a fault at the target, only
    no certificate to judge by. A hard failure (incomplete handshake, no
    covering SAN) accuses the target.
    """
    if probe.dns_ok is False:
        return Reachability.UNREACHABLE
    if probe.tcp_ok is False:
        return Reachability.UNREACHABLE
    tls = classify_tls(probe, hostname)
    if tls in (Failure.TLS_HANDSHAKE, Failure.TLS_HOSTNAME_MISMATCH):
        return Reachability.UNREACHABLE
    if tls is Failure.TLS_NO_PEER_CERT or probe.http_status is None:
        return Reachability.UNKNOWN
    if 200 <= probe.http_status < 300:
        return Reachability.REACHABLE
    if probe.http_status in (401, 403, 407, 429, 451):
        return Reachability.REFUSING
    if probe.http_status >= 500:
        return Reachability.UNREACHABLE
    return Reachability.REACHABLE


def blame_tier(reachability: Reachability) -> bool:
    """May this target's state be reported as a SCRAPE failure?
    No for UNREACHABLE and UNKNOWN — those are facts about the target or our
    probe, not about the tier. Yes for REACHABLE and REFUSING: the tier engaged
    with the site, so a failure there is ours.
    """
    return reachability in (Reachability.REACHABLE, Reachability.REFUSING)


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().strip(".")


def precheck_dns_and_tcp(hostname: str, port: int = 443, timeout: float = 5.0) -> TargetProbe:
    try:
        socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        logger.warning(
            "suppressed %s in precheck_dns_and_tcp (target_reachability.py:163): %s",
            "OSError",
            exc,
        )
        return TargetProbe(dns_ok=False, dns_error=str(exc))
    try:
        with socket.create_connection((hostname, port), timeout=timeout):
            return TargetProbe(dns_ok=True, tcp_ok=True)
    except OSError as exc:
        logger.warning(
            "suppressed %s in precheck_dns_and_tcp (target_reachability.py:168): %s",
            "OSError",
            exc,
        )
        return TargetProbe(dns_ok=True, tcp_ok=False, tcp_error=str(exc))


def _cert_to_probe(cert: dict) -> tuple[str | None, tuple[str, ...]]:
    """Subject and SAN list out of a ``getpeercert()`` dict."""
    subject = ",".join(str(v) for _, v in cert.get("subject", ()) if v) or None
    sans = tuple(str(v) for kind, v in cert.get("subjectAltName", ()) if kind == "DNS")
    return subject, sans


def precheck_tls(hostname: str, port: int = 443, timeout: float = 5.0) -> TargetProbe:
    """Live TLS probe reporting what was actually PRESENTED.
    ``CERT_OPTIONAL`` is load-bearing: it verifies without aborting on an
    untrusted chain, so ``getpeercert()`` returns a populated dict and the SAN
    is readable for a cert we would not trust. ``CERT_NONE`` returns an EMPTY
    dict; ``CERT_REQUIRED`` kills the handshake first.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_OPTIONAL
    try:
        with (
            socket.create_connection((hostname, port), timeout=timeout) as raw,
            ctx.wrap_socket(raw, server_hostname=hostname) as tls,
        ):
            subject, sans = _cert_to_probe(tls.getpeercert() or {})
            return TargetProbe(
                tls_completed=True,
                cert_subject=subject,
                cert_sans=sans,
                cert_verified=None,
                tls_error=None if subject else "no peer certificate",
            )
    except (ssl.SSLError, OSError) as exc:
        logger.warning(
            "suppressed %s in precheck_tls (target_reachability.py:203): %s",
            "(ssl.SSLError, OSError)",
            exc,
        )
        return TargetProbe(tls_completed=False, tls_error=str(exc))
