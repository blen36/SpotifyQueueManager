from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import Room, Vote
from .forms import CreateRoomForm, JoinRoomForm
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from requests import Request, post
from django.conf import settings
from .utils import update_or_create_user_tokens, is_spotify_authenticated
from .spotify_util import get_current_song, pause_song, play_song, skip_song
import base64
from .utils import TOKEN_URL
import requests


def home(request):
    """Главная страница: выбор (Создать или Войти)"""
    # Здесь используется твой шаблон home.html
    return render(request, 'jukebox/home.html')

@login_required(login_url='/admin/login/')
def create_room(request):
    """Логика создания комнаты"""
    if request.method == 'POST':
        form = CreateRoomForm(request.POST)
        if form.is_valid():
            room = form.save(commit=False)
            room.host = request.user
            room.save()

            # Запоминаем в сессии, что этот юзер сидит в этой комнате
            request.session['room_code'] = room.code
            # Перенаправляем на функцию room (см. ниже)
            return redirect('room', room_code=room.code)
    else:
        form = CreateRoomForm()

    # Внимание: тут нужен шаблон create_room.html (его пока нет, это нормально)
    return render(request, 'jukebox/create_room.html', {'form': form})

def join_room(request):
    """Логика входа в существующую комнату"""
    if request.method == 'POST':
        form = JoinRoomForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data['code']
            if Room.objects.filter(code=code).exists():
                request.session['room_code'] = code
                return redirect('room', room_code=code)
            else:
                return render(request, 'jukebox/join_room.html', {
                    'form': form,
                    'error': 'Комната не найдена!'
                })
    else:
        form = JoinRoomForm()

    # Внимание: тут нужен шаблон join_room.html
    return render(request, 'jukebox/join_room.html', {'form': form})

def room(request, room_code):
    """Страница самой комнаты"""
    room_qs = Room.objects.filter(code=room_code)

    if room_qs.exists():
        room = room_qs.first()
        is_host = room.host == request.user
        context = {
            'room': room,
            'is_host': is_host,
            # 'room_code': room.code — можно добавить, но оно есть в объекте room
        }
        # Здесь используется твой шаблон room.html
        return render(request, 'jukebox/room.html', context)
    else:
        return redirect('home')


# jukebox/views.py (внутри AuthURL)

class AuthURL(APIView):
    def get(self, request, format=None):
        # ОПРЕДЕЛЯЕМ ВСЕ НЕОБХОДИМЫЕ ПРАВА (SCOPES)
        # Эти права нужны для чтения статуса, управления воспроизведением и постановки в очередь.
        scopes = (
            'user-read-playback-state '
            'user-modify-playback-state '
            'user-read-currently-playing '
            'playlist-read-private '  # Для чтения плейлистов
            'playlist-modify-public ' # Для управления плейлистами (если нужно)
            'user-read-email'         # Для проверки аккаунта
        )

        # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем настоящий URL авторизации Spotify
        spotify_auth_url = 'https://accounts.spotify.com/authorize'

        url = Request('GET', spotify_auth_url, params={
            'scope': scopes,
            'response_type': 'code',
            'redirect_uri': settings.SPOTIPY_REDIRECT_URI,
            'client_id': settings.SPOTIPY_CLIENT_ID,
            'show_dialog': 'true' # <-- КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: Форсирует повторное согласие, чтобы обновить права (Scope)
        }).prepare().url

        return Response({'url': url}, status=status.HTTP_200_OK)

def check_user_session(request):
    # Этот код гарантирует, что у пользователя есть сессия
    if not request.session.exists(request.session.session_key):
        request.session.create()

def spotify_callback(request):
    """
    Обрабатывает ответ от Spotify после попытки авторизации.
    Обменивает код авторизации на токены и сохраняет их в базе данных/сессии.
    """
    code = request.GET.get('code')
    error_query = request.GET.get('error')
    check_user_session(request)

    code = request.GET.get('code')
    # 1. Проверяем ошибку авторизации
    if error_query is not None:
        return redirect('/')

    # 2. Создание строки Basic Base64(ID:SECRET)
    auth_string = f"{settings.SPOTIPY_CLIENT_ID}:{settings.SPOTIPY_CLIENT_SECRET}"
    auth_bytes = auth_string.encode('utf-8')
    auth_base64 = base64.b64encode(auth_bytes).decode('utf-8')

    headers = {
        'Authorization': f'Basic {auth_base64}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': settings.SPOTIPY_REDIRECT_URI,
    }

    # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Прямая ссылка на токен-эндпоинт Spotify
    TOKEN_EXCHANGE_URL = 'https://accounts.spotify.com/api/token'

    # 3. Выполнение POST-запроса
    try:
        response = post(TOKEN_EXCHANGE_URL, headers=headers, data=data)
        response.raise_for_status()  # Вызовет исключение, если статус 4xx или 5xx
        response_json = response.json()
    except requests.exceptions.RequestException as e:
        # Логируем, если запрос не удался (например, ошибка 400 Bad Request от Spotify)
        print(f"Spotify token exchange failed with exception: {e}")
        try:
            print(f"Response content: {response.text}")
        except NameError:
            pass
        return redirect('/')
    except ValueError:
        # Если ответ не JSON (например, 204 No Content, хотя тут не должно быть)
        print("Spotify returned non-JSON response.")
        return redirect('/')

    access_token = response_json.get('access_token')
    refresh_token = response_json.get('refresh_token')
    expires_in = response_json.get('expires_in')
    error_response = response_json.get('error')

    # 4. Проверка ответа Spotify
    if error_response or not access_token:
        # Часто здесь будет 'invalid_client' или 'invalid_grant'
        print(f"Spotify token exchange failed. Error: {error_response}. Full response: {response_json}")
        return redirect('/')

    # 5. Сохранение токенов
    if request.user.is_authenticated:
        # УСПЕХ: Пользователь залогинен, сохраняем токен
        update_or_create_user_tokens(
            request.user,
            access_token,
            response_json.get('token_type'),
            expires_in,
            refresh_token
        )
        return redirect('/')
    else:
        # Это сообщение НЕ ДОЛЖНО появляться после логина в админке
        print("User is not authenticated in Django. (SHOULD NOT HAPPEN)")
        return redirect('/')
class IsAuthenticated(APIView):
    def get(self, request, format=None):
        is_authenticated = is_spotify_authenticated(request.user)
        return Response({'status': is_authenticated}, status=status.HTTP_200_OK)


class CurrentSong(APIView):
    def get(self, request, format=None):
        room_code = self.request.session.get('room_code')
        room = Room.objects.filter(code=room_code).first()

        if not room:
            return Response({}, status=status.HTTP_404_NOT_FOUND)

        host = room.host
        # Вызываем логику Человека 2
        song = get_current_song(host)

        if song is None:
            return Response({'is_playing': False}, status=status.HTTP_200_OK)

        # Докидываем инфу, если нужно
        song['is_host'] = self.request.session.session_key == host.session_key

        return Response(song, status=status.HTTP_200_OK)


class PauseSong(APIView):
    def put(self, request, format=None):
        room_code = self.request.session.get('room_code')
        room = Room.objects.filter(code=room_code).first()

        # Проверка прав (Хост или разрешено гостям)
        if self.request.session.session_key == room.host.session_key or room.guest_can_pause:
            pause_song(room.host)  # Функция Человека 2
            return Response({}, status=status.HTTP_204_NO_CONTENT)

        return Response({}, status=status.HTTP_403_FORBIDDEN)


class PlaySong(APIView):
    def put(self, request, format=None):
        room_code = self.request.session.get('room_code')
        room = Room.objects.filter(code=room_code).first()

        if self.request.session.session_key == room.host.session_key or room.guest_can_pause:
            play_song(room.host)  # Функция Человека 2
            return Response({}, status=status.HTTP_204_NO_CONTENT)

        return Response({}, status=status.HTTP_403_FORBIDDEN)


class SkipSong(APIView):
    def post(self, request, format=None):
        room_code = self.request.session.get('room_code')
        room = Room.objects.filter(code=room_code).first()

        if self.request.session.session_key == room.host.session_key:
            skip_song(room.host)  # Функция Человека 2
            return Response({}, status=status.HTTP_204_NO_CONTENT)

        return Response({}, status=status.HTTP_403_FORBIDDEN)


class SearchSong(APIView):
    """
    Ищет треки и возвращает HTML (для HTMX).
    """

    def get(self, request, format=None):
        room_code = self.request.session.get('room_code')
        room = Room.objects.filter(code=room_code).first()

        if not room:
            return Response({}, status=status.HTTP_404_NOT_FOUND)

        query = request.GET.get('query')

        # Если поиск пустой, возвращаем пустой HTML или ничего
        if not query:
            return Response('')

        # Вызываем функцию поиска (пишет Человек №2)
        results = search_spotify(room.host, query)

        # ВАЖНО: Возвращаем HTML, а не JSON!
        # Файл search_results.html создаст Человек №3, мы просто ссылаемся на него.
        return render(request, 'jukebox/partials/search_results.html', {'songs': results})


class AddToQueue(APIView):
    """
    Добавляет выбранный трек в очередь.
    """

    def post(self, request, format=None):
        room_code = self.request.session.get('room_code')
        room = Room.objects.filter(code=room_code).first()

        if not room:
            return Response({}, status=status.HTTP_404_NOT_FOUND)

        uri = request.data.get('uri')  # Получаем URI трека от фронтенда
        add_to_queue(room.host, uri)  # Функция Человека №2

        return Response({}, status=status.HTTP_204_NO_CONTENT)


class VoteToSkip(APIView):
    """
    Логика голосования за пропуск трека.
    """

    def post(self, request, format=None):
        room_code = self.request.session.get('room_code')
        room = Room.objects.filter(code=room_code).first()

        if not room:
            return Response({}, status=status.HTTP_404_NOT_FOUND)

        # 1. Узнаем, что сейчас играет
        song_info = get_current_song(room.host)
        if not song_info or 'id' not in song_info:
            return Response({'message': 'Nothing playing'}, status=status.HTTP_204_NO_CONTENT)

        current_song_id = song_info.get('id')
        user_session = self.request.session.session_key

        # 2. Очистка старых голосов (если песня сменилась)
        # Удаляем все голоса в этой комнате, где ID песни НЕ совпадает с текущей
        Vote.objects.filter(room=room).exclude(song_id=current_song_id).delete()

        # 3. Проверяем, голосовал ли уже этот пользователь за ЭТУ песню
        vote_exists = Vote.objects.filter(room=room, user=user_session, song_id=current_song_id).exists()

        if not vote_exists:
            # Создаем голос
            Vote.objects.create(room=room, user=user_session, song_id=current_song_id)

        # 4. Считаем общее количество голосов
        votes_count = Vote.objects.filter(room=room, song_id=current_song_id).count()

        # 5. Проверяем, набралось ли достаточно голосов для пропуска
        # votes_to_skip берем из настроек комнаты (по умолчанию 2)
        if votes_count >= room.votes_to_skip:
            skip_song(room.host)  # Функция Человека №2
            # После пропуска можно удалить голоса, но это необязательно,
            # так как шаг 2 почистит их при следующем вызове
            Vote.objects.filter(room=room, song_id=current_song_id).delete()

        return Response({}, status=status.HTTP_204_NO_CONTENT)
