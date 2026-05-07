"""
Idempotent demo seed for local testing and client demos.

Usage:
    python manage.py seed_demo_data

Safe to re-run: creates organizers/events/food only when missing.
Does not reset stock on existing food items.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from event_eats.models import CustomUser, Event, FoodItem

DEMO_PASSWORD = "DemoSeed2026!"


class Command(BaseCommand):
    help = "Seed demo organizers, published events, and food items (idempotent)."

    def handle(self, *args, **options):
        today = timezone.now().date()

        org_specs = [
            {
                "email": "org1@demo.test",
                "organization_name": "Hunger Heroes Co",
                "contact_person": "Alex Organizer",
                "phone": "0400000001",
            },
            {
                "email": "org2@demo.test",
                "organization_name": "Campus Bites Crew",
                "contact_person": "Jamie Organizer",
                "phone": "0400000002",
            },
        ]

        organizers = []
        for spec in org_specs:
            user, created = CustomUser.objects.get_or_create(
                username=spec["email"],
                defaults={
                    "email": spec["email"],
                    "organization_name": spec["organization_name"],
                    "contact_person": spec["contact_person"],
                    "phone": spec["phone"],
                    "role": CustomUser.ORGANIZER,
                },
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Created organizer {spec['email']} / password: {DEMO_PASSWORD}"
                    )
                )
            else:
                self.stdout.write(
                    f"Organizer already exists: {spec['email']} (password unchanged)"
                )
                if user.role != CustomUser.ORGANIZER:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Note: user has role '{user.role}', not organizer — "
                            "events may fail if you expected an organizer."
                        )
                    )
            organizers.append(user)

        org1, org2 = organizers[0], organizers[1]

        event_specs = [
            {
                "organizer": org1,
                "title": "Adelaide Food Fest",
                "description": "Outdoor festival with street food and live music. Demo event for testing bookings.",
                "venue": "Rundle Mall, Adelaide SA",
                "event_date": today + timedelta(days=7),
                "event_time": datetime.strptime("18:00", "%H:%M").time(),
                "foods": [
                    ("Beef Burger", "Classic beef patty with lettuce and tomato", Decimal("14.00"), 30),
                    ("Veggie Wrap", "Roasted veg and hummus wrap", Decimal("10.00"), 25),
                    ("Loaded Fries", "Cheese and jalapeño topping", Decimal("8.00"), 40),
                    ("Lemonade", "Fresh squeezed", Decimal("5.00"), 60),
                ],
            },
            {
                "organizer": org2,
                "title": "Campus Night Bazaar",
                "description": "Late-night bites on campus. Great for testing Stripe checkout.",
                "venue": "Uni Hub Lawn",
                "event_date": today + timedelta(days=14),
                "event_time": datetime.strptime("17:30", "%H:%M").time(),
                "foods": [
                    ("Margherita Pizza", "Wood-fired style", Decimal("16.00"), 20),
                    ("Chicken Tacos", "Two soft tacos with salsa", Decimal("12.00"), 25),
                    ("Pad Thai", "Mild spice, peanuts on the side", Decimal("15.00"), 20),
                    ("Mango Smoothie", "Cold blended mango", Decimal("7.00"), 30),
                    ("Brownie", "Chocolate fudge brownie", Decimal("6.00"), 40),
                ],
            },
            {
                "organizer": org1,
                "title": "Weekend Brunch Pop-Up",
                "description": "Morning brunch specials for weekend testers.",
                "venue": "Riverbank Community Hall",
                "event_date": today + timedelta(days=21),
                "event_time": datetime.strptime("10:00", "%H:%M").time(),
                "foods": [
                    ("Pancake Stack", "Maple syrup and berries", Decimal("13.00"), 20),
                    ("Avocado Toast", "Sourdough with feta", Decimal("11.00"), 25),
                    ("Eggs Benedict", "Hollandaise and ham", Decimal("17.00"), 18),
                    ("Cappuccino", "Double shot", Decimal("6.00"), 50),
                ],
            },
        ]

        for es in event_specs:
            event, ev_created = Event.objects.get_or_create(
                organizer=es["organizer"],
                title=es["title"],
                defaults={
                    "description": es["description"],
                    "venue": es["venue"],
                    "event_date": es["event_date"],
                    "event_time": es["event_time"],
                    "status": Event.PUBLISHED,
                },
            )
            if not ev_created and event.status != Event.PUBLISHED:
                event.status = Event.PUBLISHED
                event.save(update_fields=["status"])
                self.stdout.write(
                    self.style.WARNING(
                        f"Updated event '{event.title}' (id={event.pk}) to published."
                    )
                )

            action = "Created" if ev_created else "Found"
            self.stdout.write(
                f"{action} event id={event.pk} — {event.title} "
                f"({event.event_date} {event.event_time})"
            )

            for name, desc, price, qty in es["foods"]:
                fi, fi_created = FoodItem.objects.get_or_create(
                    event=event,
                    name=name,
                    defaults={
                        "description": desc,
                        "price": price,
                        "quantity_available": qty,
                        "is_available": True,
                    },
                )
                fi_action = "created" if fi_created else "exists"
                self.stdout.write(
                    f"  Food [{fi_action}] id={fi.pk} — {fi.name} @ {fi.price} AUD "
                    f"(stock {fi.quantity_available})"
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Done. Log in as your normal customer user, open Explore Events / home, "
                "choose an event, book food, and pay with Stripe test card 4242 4242 4242 4242."
            )
        )
        self.stdout.write(
            "Organizer logins (for dashboard): org1@demo.test / org2@demo.test "
            f"(password only set on first create: {DEMO_PASSWORD})"
        )
