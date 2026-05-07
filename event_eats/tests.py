from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import CustomUser, Event, EventRegistration, FoodBooking, FoodItem

User = get_user_model()


@override_settings(
    STRIPE_SECRET_KEY="sk_test_dummy",
    STRIPE_PUBLISHABLE_KEY="pk_test_dummy",
    STRIPE_WEBHOOK_SECRET="whsec_test_dummy",
    STRIPE_CURRENCY="aud",
    SITE_URL="http://testserver",
)
class StripeIntegrationTests(TestCase):
    def setUp(self):
        self.organizer = User.objects.create_user(
            username="org@test.com",
            email="org@test.com",
            password="pass12345",
        )
        self.organizer.role = CustomUser.ORGANIZER
        self.organizer.save()

        self.customer = User.objects.create_user(
            username="cust@test.com",
            email="cust@test.com",
            password="pass12345",
        )
        self.customer.role = CustomUser.USER
        self.customer.save()

        self.event = Event.objects.create(
            organizer=self.organizer,
            title="Test Fest",
            description="Desc",
            venue="Hall",
            event_date="2030-01-15",
            event_time="12:00:00",
            status=Event.PUBLISHED,
        )
        self.food = FoodItem.objects.create(
            event=self.event,
            name="Burger",
            description="Tasty",
            price=Decimal("10.00"),
            quantity_available=5,
            is_available=True,
        )

        self.client = Client()
        self.client.login(username="cust@test.com", password="pass12345")

    def test_free_registration_no_stripe_call(self):
        with patch("event_eats.payment_helpers.stripe.checkout.Session.create") as mock_create:
            self.client.post(
                reverse("register_and_book_food", args=[self.event.id]),
                {f"quantity_{self.food.id}": "0"},
            )
            mock_create.assert_not_called()

        reg = EventRegistration.objects.get(user=self.customer, event=self.event)
        self.assertFalse(reg.has_pending_food_payment())
        self.assertEqual(reg.payment_status, EventRegistration.NONE)
        self.assertEqual(reg.food_bookings.count(), 0)

    @patch("event_eats.payment_helpers.stripe.checkout.Session.create")
    def test_checkout_reserves_stock_and_redirects(self, mock_create):
        mock_session = MagicMock()
        mock_session.id = "cs_test_123"
        mock_session.url = "https://checkout.stripe.com/test"
        mock_create.return_value = mock_session

        resp = self.client.post(
            reverse("register_and_book_food", args=[self.event.id]),
            {f"quantity_{self.food.id}": "2"},
        )

        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp["Location"], "https://checkout.stripe.com/test")

        self.food.refresh_from_db()
        self.assertEqual(self.food.quantity_available, 3)

        reg = EventRegistration.objects.get(user=self.customer, event=self.event)
        self.assertTrue(reg.has_pending_food_payment())
        self.assertEqual(reg.stripe_session_id, "cs_test_123")
        fb = reg.food_bookings.get()
        self.assertEqual(fb.payment_status, FoodBooking.PENDING)
        self.assertEqual(fb.stripe_checkout_session_id, "cs_test_123")

    @patch("event_eats.views.stripe.Webhook.construct_event")
    def test_webhook_completed_marks_paid(self, mock_construct):
        reg = EventRegistration.objects.create(
            user=self.customer,
            event=self.event,
            payment_status=EventRegistration.PENDING,
            stripe_session_id="cs_wh_1",
            total_amount=Decimal("20.00"),
        )
        self.food.quantity_available = 3
        self.food.save()
        FoodBooking.objects.create(
            registration=reg,
            food_item=self.food,
            quantity=2,
            total_price=Decimal("20.00"),
            payment_status=FoodBooking.PENDING,
            stripe_checkout_session_id="cs_wh_1",
        )

        mock_construct.return_value = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_wh_1",
                    "payment_intent": "pi_test_999",
                    "metadata": {"registration_id": str(reg.id)},
                }
            },
        }

        resp = self.client.post(
            reverse("stripe_webhook"),
            data=b'{"dummy":true}',
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig_header",
        )
        self.assertEqual(resp.status_code, 200)

        reg.refresh_from_db()
        fb = reg.food_bookings.get()
        self.assertEqual(fb.payment_status, FoodBooking.PAID)
        self.assertEqual(reg.payment_status, EventRegistration.PAID)
        self.assertEqual(reg.stripe_payment_intent_id, "pi_test_999")

    @patch("event_eats.views.stripe.Webhook.construct_event")
    def test_webhook_completed_idempotent(self, mock_construct):
        reg = EventRegistration.objects.create(
            user=self.customer,
            event=self.event,
            payment_status=EventRegistration.PAID,
            stripe_session_id=None,
            total_amount=Decimal("20.00"),
        )
        FoodBooking.objects.create(
            registration=reg,
            food_item=self.food,
            quantity=2,
            total_price=Decimal("20.00"),
            payment_status=FoodBooking.PAID,
            stripe_checkout_session_id="cs_wh_2",
        )

        mock_construct.return_value = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_wh_2",
                    "payment_intent": "pi_x",
                    "metadata": {"registration_id": str(reg.id)},
                }
            },
        }

        resp = self.client.post(
            reverse("stripe_webhook"),
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig",
        )
        self.assertEqual(resp.status_code, 200)

    @patch("event_eats.views.stripe.Webhook.construct_event")
    def test_webhook_expired_releases_stock(self, mock_construct):
        reg = EventRegistration.objects.create(
            user=self.customer,
            event=self.event,
            payment_status=EventRegistration.PENDING,
            stripe_session_id="cs_ex",
            total_amount=Decimal("10.00"),
        )
        self.food.quantity_available = 4
        self.food.save()
        FoodBooking.objects.create(
            registration=reg,
            food_item=self.food,
            quantity=1,
            total_price=Decimal("10.00"),
            payment_status=FoodBooking.PENDING,
            stripe_checkout_session_id="cs_ex",
        )

        mock_construct.return_value = {
            "type": "checkout.session.expired",
            "data": {"object": {"id": "cs_ex", "metadata": {"registration_id": str(reg.id)}}},
        }

        resp = self.client.post(
            reverse("stripe_webhook"),
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig",
        )
        self.assertEqual(resp.status_code, 200)

        self.food.refresh_from_db()
        self.assertEqual(self.food.quantity_available, 5)

        fb = FoodBooking.objects.get(registration=reg)
        self.assertEqual(fb.payment_status, FoodBooking.EXPIRED)

    @patch("event_eats.views.stripe.checkout.Session.retrieve")
    def test_cancel_view_releases_stock(self, mock_retrieve):
        reg = EventRegistration.objects.create(
            user=self.customer,
            event=self.event,
            payment_status=EventRegistration.PENDING,
            stripe_session_id="cs_can",
            total_amount=Decimal("10.00"),
        )
        self.food.quantity_available = 4
        self.food.save()
        FoodBooking.objects.create(
            registration=reg,
            food_item=self.food,
            quantity=1,
            total_price=Decimal("10.00"),
            payment_status=FoodBooking.PENDING,
            stripe_checkout_session_id="cs_can",
        )

        mock_retrieve.return_value = MagicMock(
            metadata={"registration_id": str(reg.id)},
        )

        resp = self.client.get(
            reverse("stripe_cancel"),
            {"session_id": "cs_can"},
        )
        self.assertEqual(resp.status_code, 200)

        self.food.refresh_from_db()
        self.assertEqual(self.food.quantity_available, 5)

        fb = FoodBooking.objects.get(registration=reg)
        self.assertEqual(fb.payment_status, FoodBooking.CANCELLED)
