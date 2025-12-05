# spotify_jukebox/jukebox/urls.py

from django.urls import path
from . import views

urlpatterns = [
    # 'home' - это маршрут для лендинга
    path('', views.home_view, name = 'home'),

    # 'room' - маршрут для страницы комнаты (пока без динамического кода)
    path('room/', views.room_view, name = 'room'),

    # Чтобы другие разработчики смогли создать URL с динамическим кодом,
    # они могут добавить path('room/<str:roomCode>/', views.room_view, name='room_details')
]