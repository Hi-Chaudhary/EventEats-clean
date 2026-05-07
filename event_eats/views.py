from decimal import Decimal

import stripe
from django.conf import settings
from django.contrib import messages
from django.forms import ValidationError
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .payment_helpers import (
    build_line_items_for_bookings,
    create_checkout_session,
    mark_checkout_session_paid,
    registration_has_pending_unpaid_bookings,
    release_checkout_session_bookings,
    sync_registration_payment_status,
)
from .forms import (
    UserRegisterForm,
    OrganizerRegisterForm,
    LoginForm,
    EventForm,
    FoodItemForm
)

from .models import CustomUser, Event, FoodItem, EventRegistration, FoodBooking


def get_auth_forms():
    return {
        'user_register_form': UserRegisterForm(),
        'organizer_register_form': OrganizerRegisterForm(),
        'login_form': LoginForm(),
    }


def home(request):
    user_register_form = UserRegisterForm()
    organizer_register_form = OrganizerRegisterForm()
    login_form = LoginForm()

    if request.method == "POST":

        if 'user_register' in request.POST:
            user_register_form = UserRegisterForm(request.POST)

            if user_register_form.is_valid():
                try:
                    user = user_register_form.save()
                except ValidationError as exc:
                    if getattr(exc, 'error_dict', None):
                        for field, errs in exc.error_dict.items():
                            for err in errs:
                                user_register_form.add_error(field, err)
                    else:
                        for msg in exc.messages:
                            user_register_form.add_error(None, msg)
                    messages.error(request, "Please correct the user registration form.")
                else:
                    login(request, user)
                    messages.success(request, "User account created successfully.")
                    return redirect('home')
            else:
                messages.error(request, "Please correct the user registration form.")

        elif 'organizer_register' in request.POST:
            organizer_register_form = OrganizerRegisterForm(request.POST)

            if organizer_register_form.is_valid():
                try:
                    user = organizer_register_form.save()
                except ValidationError as exc:
                    if getattr(exc, 'error_dict', None):
                        for field, errs in exc.error_dict.items():
                            for err in errs:
                                organizer_register_form.add_error(field, err)
                    else:
                        for msg in exc.messages:
                            organizer_register_form.add_error(None, msg)
                    messages.error(request, "Please correct the organizer registration form.")
                else:
                    login(request, user)
                    messages.success(request, "Organizer account created successfully.")
                    return redirect('home')
            else:
                messages.error(request, "Please correct the organizer registration form.")

        elif 'login_submit' in request.POST:
            login_form = LoginForm(request.POST)

            if login_form.is_valid():
                user = login_form.cleaned_data['user']
                login(request, user)
                messages.success(request, "Logged in successfully.")
                return redirect('home')
            else:
                messages.error(request, "Invalid login details.")

    published_events = Event.objects.filter(status=Event.PUBLISHED).order_by('event_date')

    return render(request, 'home.html', {
        'user_register_form': user_register_form,
        'organizer_register_form': organizer_register_form,
        'login_form': login_form,
        'published_events': published_events,
    })


def logout_view(request):
    logout(request)
    messages.success(request, "Logged out successfully.")
    return redirect('home')


@login_required
def organizer_dashboard(request):
    if request.user.role != CustomUser.ORGANIZER:
        messages.error(request, "Only organizers can access this page.")
        return redirect('home')

    events = Event.objects.filter(organizer=request.user).order_by('-created_at')

    context = get_auth_forms()
    context['events'] = events

    return render(request, 'organizer_dashboard.html', context)


@login_required
def create_event(request):
    if request.user.role != CustomUser.ORGANIZER:
        messages.error(request, "Only organizers can create events.")
        return redirect('home')

    form = EventForm()

    if request.method == "POST":
        form = EventForm(request.POST)

        if form.is_valid():
            event = form.save(commit=False)
            event.organizer = request.user
            event.status = Event.PENDING
            event.save()

            messages.success(request, "Event submitted successfully. Waiting for admin approval.")
            return redirect('organizer_dashboard')

    context = get_auth_forms()
    context['form'] = form

    return render(request, 'create_event.html', context)


@login_required
def manage_food_items(request, event_id):
    if request.user.role != CustomUser.ORGANIZER:
        messages.error(request, "Only organizers can manage food items.")
        return redirect('home')

    event = get_object_or_404(Event, id=event_id, organizer=request.user)
    food_items = FoodItem.objects.filter(event=event).order_by('-created_at')

    form = FoodItemForm()

    if request.method == "POST":
        form = FoodItemForm(request.POST)

        if form.is_valid():
            food_item = form.save(commit=False)
            food_item.event = event
            food_item.save()

            messages.success(request, "Food item added successfully.")
            return redirect('manage_food_items', event_id=event.id)

    context = get_auth_forms()
    context['event'] = event
    context['food_items'] = food_items
    context['form'] = form

    return render(request, 'manage_food_items.html', context)


def event_list(request):
    events = Event.objects.filter(status=Event.PUBLISHED).order_by('event_date')

    context = get_auth_forms()
    context['events'] = events

    return render(request, 'event_list.html', context)


def event_detail(request, event_id):
    event = get_object_or_404(Event, id=event_id, status=Event.PUBLISHED)
    food_items = FoodItem.objects.filter(event=event, is_available=True, quantity_available__gt=0)

    already_registered = False

    if request.user.is_authenticated:
        already_registered = EventRegistration.objects.filter(user=request.user, event=event).exists()

    context = get_auth_forms()
    context['event'] = event
    context['food_items'] = food_items
    context['already_registered'] = already_registered

    return render(request, 'event_detail.html', context)


@login_required
def register_and_book_food(request, event_id):
    if request.user.role != CustomUser.USER:
        messages.error(request, "Only normal users can register for events.")
        return redirect('event_detail', event_id=event_id)

    event = get_object_or_404(Event, id=event_id, status=Event.PUBLISHED)
    food_items = FoodItem.objects.filter(event=event, is_available=True, quantity_available__gt=0)

    registration, created = EventRegistration.objects.get_or_create(
        user=request.user,
        event=event
    )

    if request.method == "POST":
        if registration_has_pending_unpaid_bookings(registration):
            messages.warning(
                request,
                "You have a food order awaiting payment. Complete or cancel it from My Bookings.",
            )
            return redirect('my_bookings')

        cart_lines = []
        for item in food_items:
            quantity_value = request.POST.get(f'quantity_{item.id}')
            if quantity_value:
                try:
                    quantity = int(quantity_value)
                except ValueError:
                    quantity = 0

                if quantity > 0:
                    if quantity > item.quantity_available:
                        messages.error(
                            request,
                            f"Only {item.quantity_available} quantity available for {item.name}.",
                        )
                        return redirect('register_and_book_food', event_id=event.id)

                    total_price = item.price * Decimal(quantity)
                    cart_lines.append({'item': item, 'qty': quantity, 'total_price': total_price})

        if not cart_lines:
            messages.success(request, "You registered for the event without booking food.")
            return redirect('my_bookings')

        grand_total = sum((line['total_price'] for line in cart_lines), Decimal('0'))

        if not settings.STRIPE_SECRET_KEY:
            messages.error(
                request,
                "Stripe is not configured. Add STRIPE_SECRET_KEY to your .env file (see .env.example).",
            )
            return redirect('register_and_book_food', event_id=event.id)

        success_path = reverse('stripe_success')
        cancel_path = reverse('stripe_cancel')

        try:
            with transaction.atomic():
                item_ids = [line['item'].id for line in cart_lines]
                locked_items = {
                    fi.id: fi
                    for fi in FoodItem.objects.select_for_update().filter(
                        id__in=item_ids,
                        event=event,
                    )
                }

                bookings_created = []
                line_items_stripe = []

                for line in cart_lines:
                    qty = line['qty']
                    fi = locked_items.get(line['item'].id)
                    if fi is None or qty > fi.quantity_available:
                        raise ValueError("stock")

                    fi.quantity_available -= qty
                    fi.save(update_fields=['quantity_available'])

                    fb = FoodBooking.objects.create(
                        registration=registration,
                        food_item=fi,
                        quantity=qty,
                        total_price=line['total_price'],
                        payment_status=FoodBooking.PENDING,
                    )
                    bookings_created.append(fb)

                    unit_cents = int((fi.price * Decimal('100')).quantize(Decimal('1')))
                    line_items_stripe.append({
                        'price_data': {
                            'currency': settings.STRIPE_CURRENCY,
                            'product_data': {'name': fi.name},
                            'unit_amount': unit_cents,
                        },
                        'quantity': qty,
                    })

                session = create_checkout_session(
                    registration,
                    line_items_stripe,
                    success_path,
                    cancel_path,
                )
                sid = session.id

                for fb in bookings_created:
                    fb.stripe_checkout_session_id = sid
                    fb.save(update_fields=['stripe_checkout_session_id'])

                registration.stripe_session_id = sid
                registration.total_amount = grand_total
                registration.save(update_fields=['stripe_session_id', 'total_amount'])
                sync_registration_payment_status(registration)

        except ValueError:
            messages.error(
                request,
                "Stock changed while placing your order. Please try again.",
            )
            return redirect('register_and_book_food', event_id=event.id)
        except stripe.error.StripeError as exc:
            um = getattr(exc, 'user_message', None) or str(exc)
            messages.error(request, f"Payment setup failed: {um}")
            return redirect('register_and_book_food', event_id=event.id)

        return HttpResponseRedirect(session.url, status=303)

    context = get_auth_forms()
    context['event'] = event
    context['food_items'] = food_items
    context['registration'] = registration

    return render(request, 'book_food.html', context)


@login_required
def stripe_success(request):
    session_id = request.GET.get('session_id')
    if not session_id:
        messages.error(request, "Missing payment session.")
        return redirect('my_bookings')

    if not settings.STRIPE_SECRET_KEY:
        messages.error(request, "Stripe is not configured.")
        return redirect('my_bookings')

    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.error.StripeError:
        messages.error(request, "Could not verify payment session.")
        return redirect('my_bookings')

    reg_id = session.metadata.get('registration_id')
    if not reg_id:
        messages.error(request, "Invalid session metadata.")
        return redirect('my_bookings')

    registration = get_object_or_404(EventRegistration, pk=reg_id)
    if registration.user_id != request.user.id:
        messages.error(request, "You cannot view this payment session.")
        return redirect('home')

    context = get_auth_forms()
    context['registration'] = registration
    return render(request, 'stripe_success.html', context)


@login_required
def stripe_cancel(request):
    session_id = request.GET.get('session_id')
    if not session_id:
        messages.warning(request, "Missing checkout session.")
        return redirect('my_bookings')

    if not settings.STRIPE_SECRET_KEY:
        messages.error(request, "Stripe is not configured.")
        return redirect('my_bookings')

    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.error.StripeError:
        messages.warning(request, "Could not verify cancelled checkout.")
        return redirect('my_bookings')

    reg_id = session.metadata.get('registration_id')
    if not reg_id:
        return redirect('my_bookings')

    registration = get_object_or_404(EventRegistration, pk=reg_id)
    if registration.user_id != request.user.id:
        messages.error(request, "Invalid session.")
        return redirect('home')

    release_checkout_session_bookings(session_id, FoodBooking.CANCELLED)

    context = get_auth_forms()
    context['registration'] = registration
    context['event'] = registration.event
    messages.info(request, "Checkout cancelled. Reserved stock has been released.")
    return render(request, 'stripe_cancel.html', context)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    if not settings.STRIPE_WEBHOOK_SECRET:
        return HttpResponse(status=400)

    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            settings.STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        return HttpResponse(status=400)

    if event['type'] == 'checkout.session.completed':
        obj = event['data']['object']
        mark_checkout_session_paid(obj['id'], obj.get('payment_intent'))
    elif event['type'] == 'checkout.session.expired':
        obj = event['data']['object']
        release_checkout_session_bookings(obj['id'], FoodBooking.EXPIRED)

    return HttpResponse(status=200)


@login_required
def resume_stripe_checkout(request, registration_id):
    if request.user.role != CustomUser.USER:
        messages.error(request, "Only customers can resume checkout.")
        return redirect('home')

    registration = get_object_or_404(EventRegistration, pk=registration_id, user=request.user)
    pending = registration.food_bookings.filter(payment_status=FoodBooking.PENDING)

    if not pending.exists():
        messages.info(request, "There is no pending payment for this registration.")
        return redirect('my_bookings')

    if not settings.STRIPE_SECRET_KEY:
        messages.error(request, "Stripe is not configured.")
        return redirect('my_bookings')

    line_items = build_line_items_for_bookings(pending)
    try:
        session = create_checkout_session(
            registration,
            line_items,
            reverse('stripe_success'),
            reverse('stripe_cancel'),
        )
    except stripe.error.StripeError as exc:
        um = getattr(exc, 'user_message', None) or str(exc)
        messages.error(request, f"Could not start checkout: {um}")
        return redirect('my_bookings')

    new_sid = session.id
    pending.update(stripe_checkout_session_id=new_sid)
    registration.stripe_session_id = new_sid
    registration.save(update_fields=['stripe_session_id'])

    return HttpResponseRedirect(session.url, status=303)


@login_required
def my_bookings(request):
    if request.user.role != CustomUser.USER:
        messages.error(request, "Only normal users can view bookings.")
        return redirect('home')

    registrations = EventRegistration.objects.filter(user=request.user).order_by('-registered_at')

    context = get_auth_forms()
    context['registrations'] = registrations

    return render(request, 'my_bookings.html', context)