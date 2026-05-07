from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    USER = 'user'
    ORGANIZER = 'organizer'
    ADMIN = 'admin'

    ROLE_CHOICES = [
        (USER, 'User'),
        (ORGANIZER, 'Organizer'),
        (ADMIN, 'Admin'),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=USER)

    organization_name = models.CharField(max_length=150, blank=True, null=True)
    contact_person = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=15, blank=True, null=True)

    def __str__(self):
        return self.email


class Event(models.Model):
    PENDING = 'pending'
    PUBLISHED = 'published'
    REJECTED = 'rejected'

    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (PUBLISHED, 'Published'),
        (REJECTED, 'Rejected'),
    ]

    organizer = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='events')
    title = models.CharField(max_length=200)
    description = models.TextField()
    venue = models.CharField(max_length=250)
    event_date = models.DateField()
    event_time = models.TimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    image = models.ImageField(upload_to='events/', blank=True, null=True)

    def __str__(self):
        return self.title


class FoodItem(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='food_items')
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    quantity_available = models.PositiveIntegerField()
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    image = models.ImageField(upload_to='food_items/', blank=True, null=True)

    def __str__(self):
        return f"{self.name} - {self.event.title}"


class EventRegistration(models.Model):
    NONE = 'none'
    PENDING = 'pending'
    PAID = 'paid'
    CANCELLED = 'cancelled'
    EXPIRED = 'expired'

    PAYMENT_STATUS_CHOICES = [
        (NONE, 'None'),
        (PENDING, 'Pending'),
        (PAID, 'Paid'),
        (CANCELLED, 'Cancelled'),
        (EXPIRED, 'Expired'),
    ]

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='registrations')
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='registrations')
    registered_at = models.DateTimeField(auto_now_add=True)
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default=NONE,
    )
    stripe_session_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True, null=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        unique_together = ('user', 'event')

    def has_pending_food_payment(self) -> bool:
        """True if any food lines are still awaiting Stripe confirmation."""
        return self.food_bookings.filter(payment_status='pending').exists()

    def __str__(self):
        return f"{self.user.email} registered for {self.event.title}"


class FoodBooking(models.Model):
    PENDING = 'pending'
    PAID = 'paid'
    CANCELLED = 'cancelled'
    EXPIRED = 'expired'

    PAYMENT_STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (PAID, 'Paid'),
        (CANCELLED, 'Cancelled'),
        (EXPIRED, 'Expired'),
    ]

    registration = models.ForeignKey(EventRegistration, on_delete=models.CASCADE, related_name='food_bookings')
    food_item = models.ForeignKey(FoodItem, on_delete=models.CASCADE, related_name='bookings')
    quantity = models.PositiveIntegerField()
    total_price = models.DecimalField(max_digits=8, decimal_places=2)
    booked_at = models.DateTimeField(auto_now_add=True)
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default=PENDING,
    )
    stripe_checkout_session_id = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.food_item.name} x {self.quantity}"