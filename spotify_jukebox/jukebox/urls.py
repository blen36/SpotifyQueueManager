from django.urls import path
from .views import (
    home, create_room, join_room, room,
    AuthURL, IsAuthenticated, CurrentSong,
    PauseSong, PlaySong, SkipSong, SearchSong,
    AddToQueue, VoteToSkip, LeaveRoom, UpdateRoom,
    GetRoom, spotify_callback, PrevSong  # <--- Проверь, что здесь PrevSong
)

urlpatterns = [
    # Страницы
    path('', home, name='home'),
    path('create-room', create_room, name='create_room'),
    path('join-room', join_room, name='join_room'),
    path('room/<str:room_code>/', room, name='room'),

    # API Управление плеером
    path('api/current-song/', CurrentSong.as_view(), name='current_song'),
    path('api/pause-song', PauseSong.as_view()),
    path('api/play-song', PlaySong.as_view()),
    path('api/skip-song', SkipSong.as_view()),
    path('api/prev-song', PrevSong.as_view()), # <--- Исправлено (убрал views.)

    # API Поиск и очередь
    path('api/spotify/search', SearchSong.as_view()),
    path('api/add-to-queue', AddToQueue.as_view()),
    path('api/vote-to-skip', VoteToSkip.as_view()),

    # API Настройки и сессия
    path('api/is-authenticated', IsAuthenticated.as_view()),
    path('api/get-auth-url', AuthURL.as_view()),
    path('api/get-room', GetRoom.as_view()),
    path('leave-room', LeaveRoom.as_view()),
    path('update-room', UpdateRoom.as_view()),
    path('redirect', spotify_callback),
]