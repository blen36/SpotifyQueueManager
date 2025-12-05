# spotify_jukebox/jukebox/views.py

from django.shortcuts import render

# Вид для главной страницы (home.html)
def home_view(request):
    return render(request, 'jukebox/home.html')

# Вид для страницы комнаты (room.html)
def room_view(request):
    # Данные-заглушки для отображения кода комнаты
    context = {
        'room_code': 'ABCD123',
        'is_host': True # Для отображения статуса хоста
    }
    return render(request, 'jukebox/room.html', context)