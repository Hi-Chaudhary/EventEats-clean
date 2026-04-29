from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Event, FoodItem, EventRegistration, FoodBooking


class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'is_staff', 'is_superuser')
    list_filter = ('role', 'is_staff', 'is_superuser')

    fieldsets = UserAdmin.fieldsets + (
        ('Role Information', {
            'fields': ('role', 'organization_name', 'contact_person', 'phone')
        }),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Role Information', {
            'fields': ('role', 'organization_name', 'contact_person', 'phone')
        }),
    )


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'organizer', 'venue', 'event_date', 'event_time', 'status')
    list_filter = ('status', 'event_date')
    search_fields = ('title', 'venue', 'organizer__email')
    list_editable = ('status',)


@admin.register(FoodItem)
class FoodItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'event', 'price', 'quantity_available', 'is_available')
    list_filter = ('is_available', 'event')
    search_fields = ('name', 'event__title')


@admin.register(EventRegistration)
class EventRegistrationAdmin(admin.ModelAdmin):
    list_display = ('user', 'event', 'registered_at')
    list_filter = ('event', 'registered_at')
    search_fields = ('user__email', 'event__title')


@admin.register(FoodBooking)
class FoodBookingAdmin(admin.ModelAdmin):
    list_display = ('registration', 'food_item', 'quantity', 'total_price', 'booked_at')
    list_filter = ('food_item', 'booked_at')
    search_fields = ('registration__user__email', 'food_item__name')


admin.site.register(CustomUser, CustomUserAdmin)