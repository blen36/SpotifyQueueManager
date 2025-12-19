from django import forms
from .models import Room
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError # Обязательно для проверки почты

class CreateRoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ['guest_can_pause', 'votes_to_skip']

class JoinRoomForm(forms.Form):
    code = forms.CharField(label='Code', max_length=8)

class UserRegisterForm(UserCreationForm):
    email = forms.EmailField(required=True) # Делаем поле обязательным

    class Meta:
        model = User
        fields = ['username', 'email'] # Здесь НЕ должно быть слова return

    # Метод проверки уникальности почты
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise ValidationError("Пользователь с такой почтой уже зарегистрирован.")
        return email