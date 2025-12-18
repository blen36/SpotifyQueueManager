from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import Room, Vote, Track
from .forms import CreateRoomForm, JoinRoomForm, UserRegisterForm
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from requests import Request, post
from django.conf import settings
from .utils import update_or_create_user_tokens, is_spotify_authenticated, user_is_host
# ИСПРАВЛЕНО: Добавлены search_spotify и add_to_queue в импорт
from .spotify_util import get_current_song, pause_song, play_song, skip_song, search_spotify, add_to_queue
import base64
import requests
from django.http import HttpResponse
from .serializers import RoomSerializer, CreateRoomSerializer, UpdateRoomSerializer
from django.template.loader import render_to_string
from django.shortcuts import render, redirect
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib import messages

def home(request):
    return render(request, 'jukebox/home.html')


@login_required(login_url='/admin/login/')
def create_room(request):
    if request.method == 'POST':
        form = CreateRoomForm(request.POST)
        if form.is_valid():
            room = form.save(commit=False)
            room.host = request.user
            room.save()
            request.session['room_code'] = room.code
            return redirect('room', room_code=room.code)
    else:
        form = CreateRoomForm()
    return render(request, 'jukebox/create_room.html', {'form': form})


def join_room(request):
    if request.method == 'POST':
        form = JoinRoomForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data['code']
            if Room.objects.filter(code=code).exists():
                request.session['room_code'] = code
                return redirect('room', room_code=code)
            else:
                return render(request, 'jukebox/join_room.html', {'form': form, 'error': 'Комната не найдена!'})
    else:
        form = JoinRoomForm()
    return render(request, 'jukebox/join_room.html', {'form': form})

def room(request, room_code):
    room_qs = Room.objects.filter(code=room_code)
    if room_qs.exists():
        room = room_qs.first()
        # ИСПРАВЛЕНО: Сравнение объектов User, а не строк
        is_host = request.user.is_authenticated and room.host == request.user
        context = {
            'room': room,
            'is_host': is_host,
        }
        return render(request, 'jukebox/room.html', context)
    else:
        return redirect('home')


class AuthURL(APIView):
    def get(self, request, format=None):
        scopes = 'user-read-playback-state user-modify-playback-state user-read-currently-playing playlist-read-private playlist-modify-public user-read-email'

        # РЕАЛЬНЫЙ URL Spotify
        spotify_auth_url = 'https://accounts.spotify.com/authorize'

        url = Request('GET', spotify_auth_url, params={
            'scope': scopes,
            'response_type': 'code',
            'redirect_uri': settings.SPOTIPY_REDIRECT_URI,
            'client_id': settings.SPOTIPY_CLIENT_ID,
            'show_dialog': 'true'
        }).prepare().url

        return Response({'url': url}, status=status.HTTP_200_OK)

def check_user_session(request):
    if not request.session.exists(request.session.session_key):
        request.session.create()


def spotify_callback(request):
    code = request.GET.get('code')
    error_query = request.GET.get('error')
    check_user_session(request)

    if error_query is not None:
        return redirect('/')

    auth_string = f"{settings.SPOTIPY_CLIENT_ID}:{settings.SPOTIPY_CLIENT_SECRET}"
    auth_bytes = auth_string.encode('utf-8')
    auth_base64 = base64.b64encode(auth_bytes).decode('utf-8')

    headers = {'Authorization': f'Basic {auth_base64}', 'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': settings.SPOTIPY_REDIRECT_URI}
    TOKEN_EXCHANGE_URL = 'https://accounts.spotify.com/api/token'

    try:
        response = post(TOKEN_EXCHANGE_URL, headers=headers, data=data)
        response.raise_for_status()
        response_json = response.json()
    except Exception as e:
        print(f"Spotify token exchange failed: {e}")
        return redirect('/')

    access_token = response_json.get('access_token')
    refresh_token = response_json.get('refresh_token')
    expires_in = response_json.get('expires_in')
    error_response = response_json.get('error')

    if error_response or not access_token:
        return redirect('/')

    if request.user.is_authenticated:
        update_or_create_user_tokens(
            request.user,
            access_token,
            response_json.get('token_type'),
            expires_in,
            refresh_token
        )

        # 🔥 ВАЖНО: возвращаемся В КОМНАТУ
        room_code = request.session.get('room_code')
        if room_code:
            return redirect(f'/room/{room_code}/')

        return redirect('/')
    else:
        return redirect('/')


class IsAuthenticated(APIView):
    def get(self, request, format=None):
        is_authenticated = is_spotify_authenticated(request.user)
        return Response({'status': is_authenticated}, status=status.HTTP_200_OK)


class CurrentSong(APIView):
    def get(self, request, format=None):
        # 1. Пытаемся достать код комнаты из сессии
        room_code = request.session.get('room_code')
        room = Room.objects.filter(code=room_code).first()

        # 2. Если в сессии пусто, но юзер авторизован - ищем его как хоста
        if not room and request.user.is_authenticated:
            room = Room.objects.filter(host=request.user).last()
            if room:
                request.session['room_code'] = room.code  # Восстанавливаем сессию

        # 3. Если комнату так и не нашли
        if not room:
            return render(request, 'jukebox/song.html', {
                'is_playing': False,
                'error_message': "Room not found. Please join again."
            })

        host = room.host

        # 4. Проверяем авторизацию в Spotify (и обновляем токен если надо)
        if not is_spotify_authenticated(host):
            return render(request, 'jukebox/song.html', {
                'is_playing': False,
                'needs_auth': True,  # Флаг для шаблона, чтобы показать кнопку Connect
                'is_host': (request.user == host)
            })

        # 5. Получаем текущий трек
        song_info = get_current_song(host)

        # Синхронизация очереди (удаляем трек из БД, если он заиграл в Spotify)
        if song_info and 'id' in song_info:
            current_spotify_id = song_info['id']
            first_track = Track.objects.filter(room=room).order_by('added_at').first()
            if first_track:
                queued_spotify_id = first_track.spotify_uri.split(':')[-1]
                if queued_spotify_id == current_spotify_id:
                    first_track.delete()

        # 6. Если данные есть — формируем контекст
        if song_info and 'id' in song_info:
            duration = song_info.get('duration', 0)
            current_time = song_info.get('time', 0)
            progress = (current_time / duration * 100) if duration > 0 else 0

            context = {
                'title': song_info.get('title'),
                'artist': song_info.get('artist'),
                'image_url': song_info.get('image_url'),
                'is_playing': song_info.get('is_playing'),
                'votes': Vote.objects.filter(room=room, song_id=song_info.get('id')).count(),
                'votes_required': room.votes_to_skip,
                'progress_percent': progress,
                'display_time': f"{int((current_time / 1000) // 60)}:{int((current_time / 1000) % 60):02d}",
                'display_duration': f"{int((duration / 1000) // 60)}:{int((duration / 1000) % 60):02d}",
                'is_host': (request.user == host),
            }
            return render(request, 'jukebox/song.html', context)

        # 7. Если Spotify открыт, но ничего не играет
        return render(request, 'jukebox/song.html', {
            'is_playing': False,
            'error_message': "No active device found. Play music on Spotify!"
        })

class PauseSong(APIView):
    def put(self, request, format=None):
        room_code = self.request.session.get('room_code')
        room = Room.objects.filter(code=room_code).first()

        # ИСПРАВЛЕНО: Логика сравнения хоста
        is_host = request.user.is_authenticated and room.host == request.user

        if is_host or room.guest_can_pause:
            pause_song(room.host)
            return Response({}, status=status.HTTP_204_NO_CONTENT)

        return Response({}, status=status.HTTP_403_FORBIDDEN)


class PlaySong(APIView):
    def put(self, request, format=None):
        room_code = self.request.session.get('room_code')
        room = Room.objects.filter(code=room_code).first()

        # ИСПРАВЛЕНО: Логика сравнения хоста
        is_host = request.user.is_authenticated and room.host == request.user

        if is_host or room.guest_can_pause:
            play_song(room.host)
            return Response({}, status=status.HTTP_204_NO_CONTENT)

        return Response({}, status=status.HTTP_403_FORBIDDEN)


class SkipSong(APIView):
    def post(self, request, format=None):
        room_code = self.request.session.get('room_code')
        room = Room.objects.filter(code=room_code).first()

        # ИСПРАВЛЕНО: Логика сравнения хоста (Только хост может скипать без голосования)
        is_host = request.user.is_authenticated and room.host == request.user

        if is_host:
            skip_song(room.host)
            return Response({}, status=status.HTTP_204_NO_CONTENT)

        return Response({}, status=status.HTTP_403_FORBIDDEN)


class SearchSong(APIView):
    def get(self, request, format=None):
        room_code = request.session.get('room_code')
        room = Room.objects.filter(code=room_code).first()
        if not room:
            return Response({}, status=status.HTTP_404_NOT_FOUND)

        query = request.GET.get('query')
        if not query:
            return render(request, 'jukebox/partials/search_results.html', {'songs': []})

        # 🔴 ВАЖНО: проверяем, авторизован ли ХОСТ в Spotify
        if not is_spotify_authenticated(room.host):
            return render(
                request,
                'jukebox/partials/search_results.html',
                {
                    'songs': [],
                    'spotify_not_connected': True
                }
            )

        # 🔴 Поиск ТОЛЬКО от имени хоста
        songs = search_spotify(room.host, query)

        return render(
            request,
            'jukebox/partials/search_results.html',
            {'songs': songs}
        )


class PrevSong(APIView):
    def post(self, request, format=None):
        room_code = self.request.session.get('room_code')
        room = Room.objects.filter(code=room_code).first()

        # Только хост может переключать назад
        if request.user.is_authenticated and room.host == request.user:
            from .spotify_util import prev_song  # Импорт функции
            prev_song(room.host)
            return Response({}, status=status.HTTP_204_NO_CONTENT)

        return Response({}, status=status.HTTP_403_FORBIDDEN)

class AddToQueue(APIView):
    def post(self, request, format=None):
        room_code = request.session.get('room_code')
        room = Room.objects.filter(code=room_code).first()

        if not room:
            return Response({'error': 'Room not found'}, status=404)

        uri = request.data.get('uri') or request.POST.get('uri')
        title = request.data.get('title')
        artist = request.data.get('artist')
        image_url = request.data.get('image_url')

        if not uri:
            return Response({'error': 'No URI'}, status=400)

        # 1. Сначала сохраняем в нашу базу (чтобы гость сразу увидел песню)
        track = Track.objects.create(
            room=room,
            added_by=request.user if request.user.is_authenticated else room.host,
            title=title,
            artist=artist,
            spotify_uri=uri,
            album_cover_url=image_url
        )

        # 2. Потом отправляем в Spotify
        try:
            is_spotify_authenticated(room.host)
            add_to_queue(room.host, uri)
        except Exception as e:
            print(f"Spotify Queue Error: {e}")
            # Мы не удаляем трек из базы, даже если Spotify временно недоступен

        return Response({}, status=204)

class VoteToSkip(APIView):
    def post(self, request, format=None):
        room_code = self.request.session.get('room_code')
        room = Room.objects.filter(code=room_code).first()
        if not room: return Response({}, status=status.HTTP_404_NOT_FOUND)

        song_info = get_current_song(room.host)
        if not song_info or 'id' not in song_info:
            return Response({'message': 'Nothing playing'}, status=status.HTTP_204_NO_CONTENT)

        current_song_id = song_info.get('id')
        user_session = self.request.session.session_key

        Vote.objects.filter(room=room).exclude(song_id=current_song_id).delete()
        vote_exists = Vote.objects.filter(room=room, user=user_session, song_id=current_song_id).exists()

        if not vote_exists:
            Vote.objects.create(room=room, user=user_session, song_id=current_song_id)

        votes_count = Vote.objects.filter(room=room, song_id=current_song_id).count()

        if votes_count >= room.votes_to_skip:
            skip_song(room.host)
            Vote.objects.filter(room=room, song_id=current_song_id).delete()

        return Response({}, status=status.HTTP_204_NO_CONTENT)


class LeaveRoom(APIView):
    def post(self, request, format=None):
        if 'room_code' in request.session:
            self.request.session.pop('room_code')

            # ИСПРАВЛЕНО: Проверка на хоста через request.user (если залогинен)
            if request.user.is_authenticated:
                room_results = Room.objects.filter(host=request.user)
                if room_results.exists():
                    room_results[0].delete()

        response = HttpResponse(status=200, content='Success')
        response['HX-Redirect'] = '/'
        return response


class UpdateRoom(APIView):
    serializer_class = UpdateRoomSerializer

    def patch(self, request, format=None):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            guest_can_pause = serializer.validated_data.get('guest_can_pause')
            votes_to_skip = serializer.validated_data.get('votes_to_skip')
            code = serializer.validated_data.get('code')

            queryset = Room.objects.filter(code=code)
            if not queryset.exists():
                return Response({'msg': 'Room not found.'}, status=status.HTTP_404_NOT_FOUND)

            room = queryset[0]
            # ИСПРАВЛЕНО: Проверка прав хоста
            if room.host != request.user:
                return Response({'msg': 'You are not the host.'}, status=status.HTTP_403_FORBIDDEN)

            room.guest_can_pause = guest_can_pause
            room.votes_to_skip = votes_to_skip
            room.save(update_fields=['guest_can_pause', 'votes_to_skip'])
            return Response(UpdateRoomSerializer(room).data, status=status.HTTP_200_OK)
        return Response({'Bad Request': "Invalid Data..."}, status=status.HTTP_400_BAD_REQUEST)


class GetRoom(APIView):
    def get(self, request, format=None):
        code = request.GET.get('code')
        if not code: code = request.session.get('room_code')

        if code:
            try:
                room = Room.objects.get(code=code)
                if not request.session.exists(request.session.session_key):
                    request.session.create()

                data = {
                    'votes_to_skip': room.votes_to_skip,
                    'guest_can_pause': room.guest_can_pause,
                    # ИСПРАВЛЕНО: Проверка хоста
                    'is_host': request.user.is_authenticated and room.host == request.user
                }
                return Response(data, status=status.HTTP_200_OK)
            except Room.DoesNotExist:
                return Response({'Room Not Found': 'Invalid Room Code.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'Bad Request': 'Code param not found in request or session.'},
                        status=status.HTTP_400_BAD_REQUEST)

class GetQueue(APIView):
    def get(self, request, format=None):
        room_code = request.session.get('room_code')
        room = Room.objects.filter(code=room_code).first()

        if not room:
            return HttpResponse("Room not found", status=404)

        tracks = room.tracks.order_by('added_at')

        return render(
            request,
            'jukebox/partials/queue.html',
            {'tracks': tracks}
        )

def register(request):
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            form.save() # Сохраняем пользователя в PostgreSQL через Docker
            username = form.cleaned_data.get('username')
            messages.success(request, f'Аккаунт создан для {username}!')
            return redirect('login') # После регистрации отправляем на вход
    else:
        form = UserRegisterForm()
    return render(request, 'jukebox/register.html', {'form': form})