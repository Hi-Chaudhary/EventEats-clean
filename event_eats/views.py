from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required

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
                user = user_register_form.save()
                login(request, user)
                messages.success(request, "User account created successfully.")
                return redirect('home')
            else:
                messages.error(request, "Please correct the user registration form.")

        elif 'organizer_register' in request.POST:
            organizer_register_form = OrganizerRegisterForm(request.POST)

            if organizer_register_form.is_valid():
                user = organizer_register_form.save()
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
        booking_created = False

        for item in food_items:
            quantity_value = request.POST.get(f'quantity_{item.id}')

            if quantity_value:
                try:
                    quantity = int(quantity_value)
                except ValueError:
                    quantity = 0

                if quantity > 0:
                    if quantity > item.quantity_available:
                        messages.error(request, f"Only {item.quantity_available} quantity available for {item.name}.")
                        return redirect('register_and_book_food', event_id=event.id)

                    total_price = item.price * Decimal(quantity)

                    FoodBooking.objects.create(
                        registration=registration,
                        food_item=item,
                        quantity=quantity,
                        total_price=total_price
                    )

                    item.quantity_available -= quantity
                    item.save()

                    booking_created = True

        if booking_created:
            messages.success(request, "Event registration and food booking completed successfully.")
        else:
            messages.success(request, "You registered for the event without booking food.")

        return redirect('my_bookings')

    context = get_auth_forms()
    context['event'] = event
    context['food_items'] = food_items
    context['registration'] = registration

    return render(request, 'book_food.html', context)


@login_required
def my_bookings(request):
    if request.user.role != CustomUser.USER:
        messages.error(request, "Only normal users can view bookings.")
        return redirect('home')

    registrations = EventRegistration.objects.filter(user=request.user).order_by('-registered_at')

    context = get_auth_forms()
    context['registrations'] = registrations

    return render(request, 'my_bookings.html', context)