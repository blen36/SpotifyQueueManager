from django.urls import path
from django.contrib.auth import views as auth_views
from .views import (
    home, create_room, join_room, room, register,
    AuthURL, IsAuthenticated, CurrentSong,
    PauseSong, PlaySong, SkipSong, SearchSong,
    AddToQueue, VoteToSkip, LeaveRoom, UpdateRoom,
    GetRoom, spotify_callback, PrevSong, GetQueue
)

urlpatterns = [
    # Исправлено: убрали "views.", так как мы импортировали функции напрямую
    path('register/', register, name='register'),
    path('login/', auth_views.LoginView.as_view(template_name='jukebox/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    # Страницы
    path('', home, name='home'),
    path('create-room/', create_room, name='create_room'),
    path('join-room/', join_room, name='join_room'),
    path('room/<str:room_code>/', room, name='room'),

    # API
    path('api/current-song/', CurrentSong.as_view(), name='current_song'),
    path('api/pause-song/', PauseSong.as_view()),
    path('api/play-song/', PlaySong.as_view()),
    path('api/skip-song/', SkipSong.as_view()),
    path('api/prev-song/', PrevSong.as_view()),
    path('api/spotify/search/', SearchSong.as_view()),
    path('api/add-to-queue/', AddToQueue.as_view()),
    path('api/vote-to-skip/', VoteToSkip.as_view()),
    path('api/queue/', GetQueue.as_view()),
    path('api/is-authenticated/', IsAuthenticated.as_view()),
    path('api/get-auth-url/', AuthURL.as_view()),
    path('api/get-room/', GetRoom.as_view()),
    path('leave-room/', LeaveRoom.as_view()),
    path('update-room/', UpdateRoom.as_view()),
    path('redirect/', spotify_callback, name='spotify_callback'),
]