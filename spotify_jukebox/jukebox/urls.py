from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('create/', views.create_room, name='create_room'),
    path('join/', views.join_room, name='join_room'),
    # Важный момент: теперь URL комнаты выглядит как /room/ABCD123/
    path('room/<str:room_code>/', views.room, name='room'),
]