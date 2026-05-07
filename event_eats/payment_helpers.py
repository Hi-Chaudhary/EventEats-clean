"""Helpers for Stripe checkout + booking payment state."""

from __future__ import annotations

from decimal import Decimal

import stripe
from django.conf import settings


def configure_stripe() -> None:
    stripe.api_key = settings.STRIPE_SECRET_KEY


def registration_has_pending_unpaid_bookings(registration) -> bool:
    from .models import FoodBooking

    return registration.food_bookings.filter(payment_status=FoodBooking.PENDING).exists()


def sync_registration_payment_status(registration) -> None:
    """Derive EventRegistration.payment_status from FoodBooking rows."""
    from .models import EventRegistration, FoodBooking

    has_paid = registration.food_bookings.filter(payment_status=FoodBooking.PAID).exists()
    has_pending = registration.food_bookings.filter(payment_status=FoodBooking.PENDING).exists()

    if has_pending:
        registration.payment_status = EventRegistration.PENDING
    elif has_paid:
        registration.payment_status = EventRegistration.PAID
    else:
        registration.payment_status = EventRegistration.NONE

    registration.save(update_fields=["payment_status"])


def release_checkout_session_bookings(session_id: str, terminal_status: str) -> None:
    """
    Return stock and mark PENDING food bookings for this Checkout Session as cancelled/expired.
    terminal_status: FoodBooking.CANCELLED or FoodBooking.EXPIRED
    """
    from .models import FoodBooking

    bookings = FoodBooking.objects.select_related("food_item", "registration").filter(
        stripe_checkout_session_id=session_id,
        payment_status=FoodBooking.PENDING,
    )
    registrations_to_sync = set()
    for fb in bookings:
        fi = fb.food_item
        fi.quantity_available += fb.quantity
        fi.save(update_fields=["quantity_available"])
        fb.payment_status = terminal_status
        fb.save(update_fields=["payment_status"])
        registrations_to_sync.add(fb.registration_id)

    from .models import EventRegistration

    for reg_id in registrations_to_sync:
        reg = EventRegistration.objects.get(pk=reg_id)
        reg.stripe_session_id = None
        reg.save(update_fields=["stripe_session_id"])
        sync_registration_payment_status(reg)


def mark_checkout_session_paid(session_id: str, payment_intent_id: str | None) -> None:
    """Mark PENDING bookings for session as PAID (idempotent)."""
    from .models import FoodBooking

    bookings = FoodBooking.objects.filter(
        stripe_checkout_session_id=session_id,
        payment_status=FoodBooking.PENDING,
    )
    if not bookings.exists():
        return

    reg = bookings.first().registration
    bookings.update(payment_status=FoodBooking.PAID)

    if payment_intent_id:
        pid = payment_intent_id
        if isinstance(pid, dict):
            pid = pid.get("id") or ""
        reg.stripe_payment_intent_id = str(pid)
        reg.save(update_fields=["stripe_payment_intent_id"])

    sync_registration_payment_status(reg)


def build_line_items_for_bookings(bookings) -> list[dict]:
    """Build Stripe Checkout line_items from FoodBooking query (same currency)."""
    line_items = []
    for fb in bookings:
        unit_cents = int((fb.food_item.price * Decimal("100")).quantize(Decimal("1")))
        line_items.append(
            {
                "price_data": {
                    "currency": settings.STRIPE_CURRENCY,
                    "product_data": {"name": fb.food_item.name},
                    "unit_amount": unit_cents,
                },
                "quantity": fb.quantity,
            }
        )
    return line_items


def create_checkout_session(
    registration: EventRegistration,
    line_items: list[dict],
    success_path: str,
    cancel_path: str,
) -> stripe.checkout.Session:
    configure_stripe()
    base = settings.SITE_URL.rstrip("/")
    return stripe.checkout.Session.create(
        mode="payment",
        line_items=line_items,
        success_url=f"{base}{success_path}?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base}{cancel_path}?session_id={{CHECKOUT_SESSION_ID}}",
        metadata={"registration_id": str(registration.id)},
    )
