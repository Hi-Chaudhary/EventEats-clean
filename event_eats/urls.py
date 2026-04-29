from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('logout/', views.logout_view, name='logout'),

    path('organizer/dashboard/', views.organizer_dashboard, name='organizer_dashboard'),
    path('organizer/create-event/', views.create_event, name='create_event'),
    path('organizer/event/<int:event_id>/food-items/', views.manage_food_items, name='manage_food_items'),

    path('events/', views.event_list, name='event_list'),
    path('events/<int:event_id>/', views.event_detail, name='event_detail'),
    path('events/<int:event_id>/book-food/', views.register_and_book_food, name='register_and_book_food'),

    path('my-bookings/', views.my_bookings, name='my_bookings'),
]