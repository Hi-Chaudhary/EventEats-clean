from django import forms
from django.contrib.auth import authenticate
from django.db import IntegrityError

from .models import CustomUser, Event, FoodItem

_DUPLICATE_EMAIL_MSG = (
    "An account with this email already exists. Try logging in instead."
)


class UserRegisterForm(forms.ModelForm):
    name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your full name'
        })
    )

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter password'
        })
    )

    class Meta:
        model = CustomUser
        fields = ['name', 'email', 'password']

        widgets = {
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter your email'
            }),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            email = email.strip().lower()
            if CustomUser.objects.filter(username__iexact=email).exists():
                raise forms.ValidationError(_DUPLICATE_EMAIL_MSG)
        return email

    def save(self, commit=True):
        email = self.cleaned_data['email']
        user = CustomUser()
        user.username = email
        user.email = email
        user.first_name = self.cleaned_data['name']
        user.role = CustomUser.USER
        user.set_password(self.cleaned_data['password'])

        if commit:
            try:
                user.save()
            except IntegrityError:
                raise forms.ValidationError({'email': [_DUPLICATE_EMAIL_MSG]}) from None

        return user


class OrganizerRegisterForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter password'
        })
    )

    class Meta:
        model = CustomUser
        fields = [
            'organization_name',
            'contact_person',
            'email',
            'phone',
            'password'
        ]

        widgets = {
            'organization_name': forms.TextInput(attrs={'class': 'form-control'}),
            'contact_person': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            email = email.strip().lower()
            if CustomUser.objects.filter(username__iexact=email).exists():
                raise forms.ValidationError(_DUPLICATE_EMAIL_MSG)
        return email

    def save(self, commit=True):
        email = self.cleaned_data['email']
        user = CustomUser()
        user.username = email
        user.email = email
        user.organization_name = self.cleaned_data['organization_name']
        user.contact_person = self.cleaned_data['contact_person']
        user.phone = self.cleaned_data['phone']
        user.role = CustomUser.ORGANIZER
        user.set_password(self.cleaned_data['password'])

        if commit:
            try:
                user.save()
            except IntegrityError:
                raise forms.ValidationError({'email': [_DUPLICATE_EMAIL_MSG]}) from None

        return user


class LoginForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter email'
        })
    )

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter password'
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        password = cleaned_data.get('password')

        if email and password:
            user = authenticate(username=email, password=password)

            if user is None:
                raise forms.ValidationError("Invalid email or password.")

            cleaned_data['user'] = user

        return cleaned_data


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ['title', 'description', 'venue', 'event_date', 'event_time']

        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'venue': forms.TextInput(attrs={'class': 'form-control'}),
            'event_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'event_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
        }


class FoodItemForm(forms.ModelForm):
    class Meta:
        model = FoodItem
        fields = ['name', 'description', 'price', 'quantity_available', 'is_available']

        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Example: Burger'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Short food description'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'Example: 99.00'
            }),
            'quantity_available': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'placeholder': 'Example: 100'
            }),
            'is_available': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }