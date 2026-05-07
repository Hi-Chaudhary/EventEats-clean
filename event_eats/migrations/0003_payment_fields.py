# Generated manually for Stripe payment integration

from decimal import Decimal

from django.db import migrations, models


def backfill_payment_statuses(apps, schema_editor):
    EventRegistration = apps.get_model("event_eats", "EventRegistration")
    FoodBooking = apps.get_model("event_eats", "FoodBooking")

    FoodBooking.objects.all().update(payment_status="paid")

    for reg in EventRegistration.objects.all():
        bookings = FoodBooking.objects.filter(registration=reg)
        if not bookings.exists():
            continue
        total = Decimal("0")
        for b in bookings:
            total += b.total_price
        reg.payment_status = "paid"
        reg.total_amount = total
        reg.save(update_fields=["payment_status", "total_amount"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("event_eats", "0002_event_image_fooditem_image"),
    ]

    operations = [
        migrations.AddField(
            model_name="eventregistration",
            name="payment_status",
            field=models.CharField(
                choices=[
                    ("none", "None"),
                    ("pending", "Pending"),
                    ("paid", "Paid"),
                    ("cancelled", "Cancelled"),
                    ("expired", "Expired"),
                ],
                default="none",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="eventregistration",
            name="stripe_session_id",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="eventregistration",
            name="stripe_payment_intent_id",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="eventregistration",
            name="total_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name="foodbooking",
            name="payment_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("paid", "Paid"),
                    ("cancelled", "Cancelled"),
                    ("expired", "Expired"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="foodbooking",
            name="stripe_checkout_session_id",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.RunPython(backfill_payment_statuses, noop_reverse),
    ]
