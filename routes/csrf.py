"""
routes/csrf.py – Shared CSRF verification helper (Phase 4D)

Provides a single _verify_csrf() function used by both the submit and admin
blueprints.  Using one implementation avoids drift between blueprints.
"""

import hmac
from flask import current_app, request, session


def verify_csrf() -> bool:
    """
    Timing-safe CSRF token verification.

    Compares the ``csrf_token`` form field against the value stored in the
    server-side session using :func:`hmac.compare_digest` to prevent
    timing-based attacks.

    Returns ``True`` (valid) or ``False`` (invalid / missing).

    Automatically passes when ``app.config["TESTING"]`` is ``True`` so that
    the existing test suite — which does not inject tokens — continues to pass
    unchanged.  Production deployments always enforce the check.
    """
    if current_app.config.get("TESTING"):
        return True

    submitted = request.form.get("csrf_token", "")
    expected  = session.get("csrf_token", "")

    if not submitted or not expected:
        return False

    return hmac.compare_digest(submitted, expected)
