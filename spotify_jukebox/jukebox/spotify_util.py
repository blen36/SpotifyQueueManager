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
    """
    Универсальная функция для отправки запросов к Spotify API.
    Автоматически обновляет токен перед запросом.
    Добавлен аргумент data для отправки тела запроса (например, для очереди).
    """
    tokens = get_user_tokens(host_user)
    if not tokens:
        return {'Error': 'User not authenticated with Spotify'}

    # 1. Гарантируем свежесть токена перед запросом
    refresh_spotify_token(tokens)

    headers = {'Content-Type': 'application/json', 'Authorization': "Bearer " + tokens.access_token}
    url = BASE_URL + endpoint

    # 2. Выполняем запрос
    try:
        if post_:
            response = requests.post(url, headers=headers, json=data)  # ИСПРАВЛЕНО: передаем json=data
        elif put_:
            response = requests.put(url, headers=headers, json=data)
        else:
            response = requests.get(url, {}, headers=headers)

        # Пробуем вернуть JSON, если нет — пустой словарь
        if not response.content:
            return {}
        return response.json()

    except Exception as e:
        return {'Error': f'Request failed: {str(e)}'}


def get_current_song(user):
    """Получает информацию о текущем проигрываемом треке."""
    endpoint = "player/currently-playing"
    response = execute_spotify_api_request(user, endpoint)

    if 'error' in response or 'item' not in response:
        return {}

    item = response.get('item')
    duration = item.get('duration_ms')
    progress = response.get('progress_ms')
    album_cover = item.get('album').get('images')[0].get('url')
    is_playing = response.get('is_playing')
    song_id = item.get('id')

    # Формируем строку артистов (Artist1, Artist2...)
    artist_names = ""
    for i, artist in enumerate(item.get('artists')):
        if i > 0:
            artist_names += ", "
        name = artist.get('name')
        artist_names += name

    song = {
        'title': item.get('name'),
        'artist': artist_names,
        'duration': duration,
        'time': progress,
        'image_url': album_cover,
        'is_playing': is_playing,
        'votes': 0,
        'id': song_id
    }

    return song


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