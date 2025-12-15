from datetime import timedelta
from django.utils import timezone
from requests import post, put, get, Request, exceptions
from django.conf import settings
import base64
import requests
from .models import Room

# Основные URL Spotify API
BASE_URL = "https://api.spotify.com/v1/"
TOKEN_URL = "https://accounts.spotify.com/api/token" # Адрес для токенов
# python manage.py shell

PLAY_URL = "https://api.spotify.com/v1/me/player/play"
PAUSE_URL = "https://api.spotify.com/v1/me/player/pause"

# ==========================================
# 1. УПРАВЛЕНИЕ ТОКЕНАМИ
# ==========================================

def get_user_tokens(user):
    # ВАЖНО: Импорт внутри функции предотвращает ошибку Circular Import
    from .models import SpotifyToken

    user_tokens = SpotifyToken.objects.filter(user=user)
    if user_tokens.exists():
        return user_tokens[0]
    return None


def update_or_create_user_tokens(user, access_token, token_type, expires_in, refresh_token):
    from .models import SpotifyToken

    tokens = get_user_tokens(user)
    # Spotify возвращает время жизни в секундах, превращаем в дату
    expires_in = timezone.now() + timedelta(seconds=expires_in)

    if tokens:
        tokens.access_token = access_token
        tokens.refresh_token = refresh_token
        tokens.expires_in = expires_in
        tokens.token_type = token_type
        tokens.save(update_fields=['access_token', 'refresh_token', 'expires_in', 'token_type'])
    else:
        tokens = SpotifyToken(
            user=user,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            token_type=token_type
        )
        tokens.save()


def is_spotify_authenticated(user):
    from .models import SpotifyToken

    tokens = get_user_tokens(user)
    if tokens:
        expiry = tokens.expires_in
        if expiry <= timezone.now():
            refresh_spotify_token(user)
        return True
    return False


def refresh_spotify_token(user):
    from .models import SpotifyToken

    refresh_token = get_user_tokens(user).refresh_token

    # --- ИСПРАВЛЕНИЕ НАЧАЛОСЬ ЗДЕСЬ ---

    # 1. Создаем строку Basic Base64(ID:SECRET)
    auth_string = f"{settings.SPOTIPY_CLIENT_ID}:{settings.SPOTIPY_CLIENT_SECRET}"
    auth_bytes = auth_string.encode('utf-8')
    auth_base64 = base64.b64encode(auth_bytes).decode('utf-8')

    headers = {
        'Authorization': f'Basic {auth_base64}',
        'Content-Type': 'application/x-www-form-urlencoded'  # Обязательно для POST-запроса на токен
    }

    data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
    }

    try:
        response = post(TOKEN_URL, headers=headers, data=data).json()

        # --- ИСПРАВЛЕНИЕ ЗАКОНЧИЛОСЬ ЗДЕСЬ ---

        access_token = response.get('access_token')
        token_type = response.get('token_type')
        expires_in = response.get('expires_in')
        new_refresh_token = response.get('refresh_token', refresh_token)

        # Проверка на наличие токена перед обновлением
        if access_token:
            update_or_create_user_tokens(user, access_token, token_type, expires_in, new_refresh_token)
        else:
            print(f"Error refreshing token: Token was not returned. Response: {response}")

    except Exception as e:
        print(f"Error refreshing token: {e}")
# ==========================================
# 2. ФУНКЦИИ API (ПОИСК, ПЛЕЕР, ОЧЕРЕДЬ)
# ==========================================

def execute_spotify_api_request(host, endpoint, post_=False, put_=False, data=None):
    from .models import SpotifyToken  # Оставляем импорт здесь

    tokens = get_user_tokens(host)
    if not tokens:
        return {'error': 'No tokens found'}

    # Проверка и обновление токена (Критически важно!)
    if not is_spotify_authenticated(host):
        return {'error': 'Token not authenticated or failed refresh'}

    headers = {'Content-Type': 'application/json', 'Authorization': "Bearer " + tokens.access_token}

    # Собираем URL
    url = BASE_URL + endpoint

    try:
        if post_:
            response = post(url, headers=headers, json=data)
        elif put_:
            response = put(url, headers=headers, json=data)
        else:
            response = get(url, {}, headers=headers)

        if response.status_code == 204:
            return {'Status': 'Success'}

        # Если код 200, возвращаем JSON
        if response.status_code == 200:
            return response.json()

        # Если код не 200, вызываем исключение, чтобы попасть в except-блок
        response.raise_for_status()

    except requests.exceptions.HTTPError as e:
        # --- НОВЫЙ БЛОК ОБРАБОТКИ ОШИБОК HTTP (4xx/5xx) ---
        print(f"DEBUG: HTTPError {response.status_code} для {endpoint}")  # <-- Лог статуса

        try:
            error_json = response.json()
            # Логируем полный JSON-ответ, чтобы увидеть, что не так со Scope
            print(f"DEBUG: Spotify JSON Error Details: {error_json}")

            return {'Error': f"Spotify API Error: {error_json.get('error', {}).get('message', 'Unknown Error')}",
                    'Status_Code': response.status_code}
        except Exception:
            # Если Spotify вернул 403, но без JSON
            return {'Error': f'HTTP Error {response.status_code}. No JSON body.',
                    'Status_Code': response.status_code}

    except requests.exceptions.RequestException as e:
        # Общая ошибка сети/коннекта
        return {'Error': f'Network Issue: {str(e)}'}

    except Exception as e:
        return {'Error': f'General Issue: {str(e)}'}

def search_spotify(host_user, query):
    """
    Поиск треков
    """
    if not query:
        return []

    # Кодируем пробелы для URL
    query_formatted = query.replace(' ', '%20')
    endpoint = f"search?q={query_formatted}&type=track&limit=10"

    response = execute_spotify_api_request(host_user, endpoint)

    if 'error' in response or 'tracks' not in response:
        return []

    tracks = []
    items = response.get('tracks', {}).get('items', [])

    for item in items:
        # Собираем только нужные данные
        track = {
            'title': item.get('name'),
            'artist': ", ".join([artist.get('name') for artist in item.get('artists', [])]),
            'uri': item.get('uri'),
            'image_url': item.get('album', {}).get('images', [{}])[0].get('url'),
            'id': item.get('id')
        }
        tracks.append(track)

    return tracks


def add_to_queue(host_user, track_uri):
    """
    Добавить трек в очередь
    """
    endpoint = f"me/player/queue?uri={track_uri}"
    return execute_spotify_api_request(host_user, endpoint, post_=True)


def get_spotify_devices(user):
    """
    Получает список всех доступных Spotify Connect устройств.
    """
    endpoint = "me/player/devices"
    response = execute_spotify_api_request(user, endpoint)

    # --- КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: ЛОГИКА ПРОВЕРКИ ---

    # 1. Проверяем, есть ли ошибка HTTP (403, 401, 400)
    if response and response.get('Status_Code') in [400, 401, 403]:
        print(f"🛑 ОШИБКА АВТОРИЗАЦИИ/ПРАВ: {response.get('Error', 'Неизвестная ошибка 4xx')}")
        # Выводим весь ответ, чтобы увидеть детали ошибки
        print(f"🛑 ПОЛНЫЙ ОТВЕТ: {response}")
        return []

    # 2. Проверяем, есть ли поле 'devices'
    if not response or 'devices' not in response:
        print(f"DEBUG: API вернул некорректный ответ. Ответ: {response}")
        return []

    return response.get('devices', [])

# --- НОВАЯ ФУНКЦИЯ ---
def user_is_host(room_code, session_key):
    """
    Проверяет, является ли владелец сессии хостом комнаты.
    """
    try:
        room = Room.objects.get(code=room_code)
        # Сравниваем session_key хоста комнаты с текущим session_key пользователя
        return room.host == session_key
    except Room.DoesNotExist:
        return False


def play_song(user):
    """
    Отправляет команду Play на активное устройство Spotify.
    """
    # 1. Токен должен быть обновлен Человеком №1, но пока используем is_spotify_authenticated
    # (который сам вызывает refresh, если нужно)
    if not is_spotify_authenticated(user):
        return {'error': 'User not authenticated'}

    tokens = get_user_tokens(user)

    headers = {
        'Content-Type': 'application/json',
        'Authorization': "Bearer " + tokens.access_token
    }

    try:
        # Используем PUT, так как это команда управления плеером
        response = put(PLAY_URL, headers=headers)

        # Проверка ответа: 204 No Content означает успех
        if response.status_code == 204:
            return {'success': True}

        # Обработка других ошибок (например, 403 Forbidden - нет активного девайса)
        response.raise_for_status()
        return {'success': True}  # Не должно быть достигнуто, если status_code < 200

    except exceptions.HTTPError as e:
        # 404/403: Ошибка API
        error_message = f"Spotify Control Error: {response.status_code}. No active device or permission denied."
        try:
            error_details = response.json()
            error_message = error_details.get('error', {}).get('message', error_message)
        except Exception:
            pass

        return {'error': error_message, 'status_code': response.status_code}
    except Exception as e:
        return {'error': f"Network or request issue: {str(e)}"}


def pause_song(user):
    """
    Отправляет команду Pause на активное устройство Spotify.
    """
    if not is_spotify_authenticated(user):
        return {'error': 'User not authenticated'}

    tokens = get_user_tokens(user)

    headers = {
        'Content-Type': 'application/json',
        'Authorization': "Bearer " + tokens.access_token
    }

    try:
        # Используем PUT
        response = put(PAUSE_URL, headers=headers)

        if response.status_code == 204:
            return {'success': True}

        response.raise_for_status()
        return {'success': True}

    except exceptions.HTTPError as e:
        error_message = f"Spotify Control Error: {response.status_code}. No active device or permission denied."
        try:
            error_details = response.json()
            error_message = error_details.get('error', {}).get('message', error_message)
        except Exception:
            pass

        return {'error': error_message, 'status_code': response.status_code}
    except Exception as e:
        return {'error': f"Network or request issue: {str(e)}"}


def get_current_song(host):
    """
    Получить текущий трек + данные о голосовании (ОБНОВЛЕНО)

    Возвращает точные тайминги (duration_ms, progress_ms) для прогресс-бара.
    """
    # Импортируем модели Room и Vote здесь, чтобы избежать ошибки импорта
    from .models import Room, Vote

    endpoint = "me/player/currently-playing"

    # Предполагаем, что execute_spotify_api_request уже обновляет токен при необходимости
    response = execute_spotify_api_request(host, endpoint)

    # Проверка на ошибку или отсутствие активного устройства
    if 'error' in response or 'item' not in response:
        return {'error': 'No Active Device'}

    item = response.get('item')
    if not item:
        return {'error': 'No music playing'}

    # === КРИТИЧЕСКИЕ ДАННЫЕ ДЛЯ ПРОГРЕСС-БАРА (ОБНОВЛЕНИЕ) ===
    # Используем новые, более точные имена (progress_ms, duration_ms)
    duration_ms = item.get('duration_ms')
    progress_ms = response.get('progress_ms')
    is_playing = response.get('is_playing')
    # ========================================================

    album_cover = item.get('album', {}).get('images', [{}])[0].get('url')
    song_id = item.get('id')

    # Формируем строку авторов (Artist 1, Artist 2)
    artist_string = ""
    for i, artist in enumerate(item.get('artists')):
        if i > 0:
            artist_string += ", "
        artist_string += artist.get('name')

    # === ЛОГИКА ГОЛОСОВАНИЯ ===
    votes = 0
    votes_required = 0

    try:
        room = Room.objects.get(host=host)
        votes_required = room.votes_to_skip
        votes = Vote.objects.filter(room=room, song_id=song_id).count()
    except Exception:
        pass

    song = {
        'title': item.get('name'),
        'artist': artist_string,

        # ОБНОВЛЕННЫЕ ПОЛЯ ДЛЯ ПРОГРЕСС-БАРА:
        'duration': duration_ms,
        'time': progress_ms,
        'is_playing': is_playing,
        # ----------------------------------

        'image_url': album_cover,
        'votes': votes,
        'votes_required': votes_required,
        'id': song_id
    }

    return song