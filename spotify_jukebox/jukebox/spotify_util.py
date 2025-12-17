import requests
from django.utils import timezone
from datetime import timedelta
from django.conf import settings
from .models import SpotifyToken
import json
import base64  # <--- Добавил этот импорт, он нужен для обновления токена

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
    ИСПРАВЛЕНО: Теперь использует правильную авторизацию через заголовки.
    """
    # Проверяем, истек ли токен (или истекает вот-вот)
    if user_tokens.expires_in <= timezone.now():

        # 1. Подготовка Basic Auth (Client ID и Secret)
        auth_string = f"{settings.SPOTIPY_CLIENT_ID}:{settings.SPOTIPY_CLIENT_SECRET}"
        auth_base64 = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': 'Basic ' + auth_base64
        }

        # 2. Тело запроса
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': user_tokens.refresh_token
        }

        try:
            response = requests.post(TOKEN_URL, data=data, headers=headers).json()
        except:
            return  # Если ошибка сети, выходим

        # Получаем новые данные
        access_token = response.get('access_token')
        expires_in = response.get('expires_in')  # Обычно 3600 секунд
        token_type = response.get('token_type')

        # Обновляем запись в БД
        if access_token:
            user_tokens.access_token = access_token
            # Пересчитываем абсолютное время истечения
            user_tokens.expires_in = timezone.now() + timedelta(seconds=expires_in)
            if token_type:
                user_tokens.token_type = token_type
            user_tokens.save(update_fields=['access_token', 'expires_in', 'token_type'])


def execute_spotify_api_request(host_user, endpoint, post_=False, put_=False, data=None):
    tokens = get_user_tokens(host_user)
    if not tokens:
        return {'error': 'User not authenticated'}  # Пишем error с маленькой

    refresh_spotify_token(tokens)

    headers = {'Content-Type': 'application/json', 'Authorization': "Bearer " + tokens.access_token}

    # ИСПРАВЛЕНИЕ: Убедись, что BASE_URL заканчивается на /, а endpoint НЕ начинается с него,
    # или используй правильную склейку:
    url = f"https://api.spotify.com/v1/{endpoint}"  # Используй прямой URL для надежности

    try:
        if post_:
            response = requests.post(url, headers=headers, json=data)
        elif put_:
            response = requests.put(url, headers=headers, json=data)
        else:
            response = requests.get(url, headers=headers)

        # Spotify возвращает 204, если плеер неактивен. Это НЕ ошибка, это просто пустота.
        if response.status_code == 204:
            return {'no_content': True}

        if not response.content:
            return {}

        return response.json()
    except Exception as e:
        return {'error': str(e)}


def get_current_song(user):
    endpoint = "me/player/currently-playing"  # ИСПРАВЛЕНО: me/player/...
    response = execute_spotify_api_request(user, endpoint)

    # Если в ответе ошибка или нет данных о треке
    if 'error' in response or 'item' not in response or response.get('no_content'):
        return {}

    item = response.get('item')
    # Проверка на None для item (бывает при переключении треков)
    if not item:
        return {}

    duration = item.get('duration_ms')
    progress = response.get('progress_ms')
    album_cover = item.get('album', {}).get('images', [{}])[0].get('url', '')
    is_playing = response.get('is_playing')
    song_id = item.get('id')

    artist_names = ", ".join([artist.get('name') for artist in item.get('artists', [])])

    return {
        'title': item.get('name'),
        'artist': artist_names,
        'duration': duration,
        'time': progress,
        'image_url': album_cover,
        'is_playing': is_playing,
        'votes': 0,
        'id': song_id
    }

def pause_song(host_user):
    return execute_spotify_api_request(host_user, "me/player/pause", put_=True)


def play_song(host_user):
    return execute_spotify_api_request(host_user, "me/player/play", put_=True)


def skip_song(host_user):
    return execute_spotify_api_request(host_user, "me/player/next", post_=True)


# --- НОВЫЕ ФУНКЦИИ (которых не хватало для views.py) ---

def search_spotify(host_user, query):
    """Ищет треки в Spotify."""
    # Кодируем пробелы для URL
    formatted_query = requests.utils.quote(query)
    endpoint = f"search?q={formatted_query}&type=track&limit=5"

    response = execute_spotify_api_request(host_user, endpoint)

    if 'tracks' not in response:
        return []

    tracks = response['tracks']['items']
    results = []

    for track in tracks:
        # Собираем артистов
        artist_names = ", ".join([artist['name'] for artist in track['artists']])

        results.append({
            'title': track['name'],
            'artist': artist_names,
            'image_url': track['album']['images'][-1]['url'] if track['album']['images'] else '',
            'uri': track['uri'],  # URI нужен для добавления в очередь
            'id': track['id']
        })

    return results


def add_to_queue(host_user, uri):
    """Добавляет трек в очередь воспроизведения."""
    endpoint = f"me/player/queue?uri={uri}"
    execute_spotify_api_request(host_user, endpoint, post_=True)

def prev_song(host_user):
    # Конечная точка me/player/previous переключает на прошлый трек
    return execute_spotify_api_request(host_user, "me/player/previous", post_=True)