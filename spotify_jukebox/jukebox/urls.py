from django.urls import path
# Импортируем все вьюхи явно, чтобы не было ошибок
from .views import (
    home, create_room, join_room, room,
    AuthURL, IsAuthenticated, CurrentSong,
    PauseSong, PlaySong, SkipSong, SearchSong,
    AddToQueue, VoteToSkip, LeaveRoom, UpdateRoom,
    GetRoom, spotify_callback
)

urlpatterns = [
    # Главная страница
    path('', home, name='home'),

    # 👇 ВАЖНО: Проверьте эти две строки. Параметр name='...' обязателен!
    path('create-room', create_room, name='create_room'),
    path('join-room', join_room, name='join_room'),

    # Страница комнаты
    path('room/<str:room_code>/', room, name='room'),

    # API ENDPOINTS
    path('api/is-authenticated', IsAuthenticated.as_view()),
    path('api/get-auth-url', AuthURL.as_view()),
    path('api/current-song/', CurrentSong.as_view(), name='current_song'),
    path('api/pause-song', PauseSong.as_view()),
    path('api/play-song', PlaySong.as_view()),
    path('api/skip-song', SkipSong.as_view()),
    path('api/spotify/search', SearchSong.as_view()),
    path('api/add-to-queue', AddToQueue.as_view()),
    path('api/vote-to-skip', VoteToSkip.as_view()),
    path('api/get-room', GetRoom.as_view()),

    # Служебные
    path('leave-room', LeaveRoom.as_view()),
    path('update-room', UpdateRoom.as_view()),
    path('redirect', spotify_callback),
]