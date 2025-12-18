from django import forms
from .models import Room
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

class CreateRoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ['guest_can_pause', 'votes_to_skip']

class JoinRoomForm(forms.Form):
    code = forms.CharField(label='Code', max_length=8)

class UserRegisterForm(UserCreationForm):
    email = forms.EmailField() # Добавляем поле email, чтобы знать почту друзей

    class Meta:
        model = User
        fields = ['username', 'email']