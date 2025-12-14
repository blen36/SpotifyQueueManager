import requests
from django.utils import timezone
from datetime import timedelta
from django.conf import settings
from .models import SpotifyToken
import json
# Базовые URL Spotify
BASE_URL = "https://api.spotify.com/v1/"
TOKEN_URL = "https://accounts.spotify.com/api/token"


def get_user_tokens(host_user):
    """Вспомогательная функция для получения токена по пользователю."""
    user_tokens = SpotifyToken.objects.filter(user=host_user)
    if user_tokens.exists():
        return user_tokens[0]
    return None


def refresh_spotify_token(user_tokens):
    """
    Проверяет срок действия токена и обновляет его, если он истек.
    """
    # Проверяем, истек ли токен (или истекает вот-вот)
    if user_tokens.expires_in <= timezone.now():
        response = requests.post(TOKEN_URL, data={
            'grant_type': 'refresh_token',
            'refresh_token': user_tokens.refresh_token,
            'client_id': settings.SPOTIFY_CLIENT_ID,
            'client_secret': settings.SPOTIFY_CLIENT_SECRET
        }).json()

        # Получаем новые данные
        access_token = response.get('access_token')
        expires_in = response.get('expires_in')  # Обычно 3600 секунд

        # Обновляем запись в БД
        if access_token:
            user_tokens.access_token = access_token
            # Пересчитываем абсолютное время истечения
            user_tokens.expires_in = timezone.now() + timedelta(seconds=expires_in)
            user_tokens.save(update_fields=['access_token', 'expires_in'])


def execute_spotify_api_request(host_user, endpoint, post_=False, put_=False):
    """
    Универсальная функция для отправки запросов к Spotify API.
    Автоматически обновляет токен перед запросом.
    """
    tokens = get_user_tokens(host_user)
    if not tokens:
        return {'Error': 'User not authenticated with Spotify'}

    # 1. Гарантируем свежесть токена перед запросом
    refresh_spotify_token(tokens)

    headers = {'Content-Type': 'application/json', 'Authorization': "Bearer " + tokens.access_token}
    url = BASE_URL + endpoint

    # 2. Выполняем запрос
    if post_:
        response = requests.post(url, headers=headers)
    elif put_:
        response = requests.put(url, headers=headers)
    else:
        response = requests.get(url, {}, headers=headers)

    # Обработка ответов
    try:
        return response.json()
    except:
        # Часто методы типа pause/play возвращают пустой ответ (204 No Content),
        # поэтому возвращаем ошибку только если это действительно ошибка
        return {'Error': 'Request failed or returned no content'}


def get_current_song(user):
    """
    Получает информацию о текущем проигрываемом треке от Spotify.
    """
    endpoint = "player/currently-playing"
    response = execute_spotify_api_request(user, endpoint)

    # 1. Проверка на ошибки или пустой ответ
    if response.status_code == 204:  # 204 No Content - ничего не играет
        return {}

    try:
        data = response.json()
    except Exception:
        # Если ответ не JSON, возвращаем пустой объект
        return {}

    # ----------------------------------------------------
    # --- БЛОК ОТЛАДКИ (DEBUGGING BLOCK) ---
    # Этот код покажет нам, что именно Spotify присылает,
    # чтобы мы поняли, почему 'is_playing' ложно.
    print("\n--- RAW SPOTIFY RESPONSE START ---")
    # Используем json.dumps для красивого форматирования вывода
    print(json.dumps(data, indent=4, ensure_ascii=False))
    print("--- RAW SPOTIFY RESPONSE END ---\n")
    # ----------------------------------------------------

    if data.get('item') is None:
        return {}

    # 2. Парсинг данных трека
    item = data.get('item')
    duration = item.get('duration_ms')
    progress = data.get('progress_ms')
    album_cover = item.get('album').get('images')[0].get('url')

    # ПРОВЕРКА: Почему is_playing = False? (ЭТО КЛЮЧЕВАЯ ПЕРЕМЕННАЯ!)
    is_playing = data.get('is_playing')

    song = {
        'title': item.get('name'),
        'artist': item.get('artists')[0].get('name'),
        'duration': duration,
        'time': progress,
        'image_url': album_cover,
        'is_playing': is_playing,
        'votes': 0,  # Временно 0, голоса считаются в views
        'id': item.get('id')
    }

    return song


def pause_song(host_user):
    """Ставит воспроизведение на паузу."""
    return execute_spotify_api_request(host_user, "me/player/pause", put_=True)


def play_song(host_user):
    """Запускает воспроизведение."""
    return execute_spotify_api_request(host_user, "me/player/play", put_=True)


def skip_song(host_user):
    """Переключает на следующий трек."""
    return execute_spotify_api_request(host_user, "me/player/next", post_=True)
