from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
import os
from dotenv import load_dotenv
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


SECRET_KEY = os.getenv("SECRET_KEY")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv("DEBUG") == "True"

ALLOWED_HOSTS = ["127.0.0.1", '*', "192.168.100.118","10.67.243.66", "barakapos.uz", "localhost", "backend"]


# Application definition

INSTALLED_APPS = [
    'daphne',
    'channels',
    'corsheaders',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework.authtoken',
    'django_celery_beat',
    'posapp',
    'telegram_bot',
    'drf_spectacular',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}
SPECTACULAR_SETTINGS = {
    'TITLE': 'Sklad va Savdo API',
    'DESCRIPTION': 'Sotuvchilar va Ownerlar uchun savdo tizimi API hujjatlari',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    # Agar JWT ishlatsangiz, buni qo'shish kerak (authorize tugmasi chiqishi uchun)
    'COMPONENT_SPLIT_PATCH': True,
}

CORS_ALLOWED_ORIGINS = [
    "https://barakapos.uz",
    "https://www.barakapos.uz",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://192.168.100.118:8000",
    "http://10.67.243.66:8000",      # <--- Yangi Wi-Fi IP-manzilingiz
    "http://10.67.243.66:19000",     # <--- Expo Metro Bundler
    "http://10.67.243.66:8081",      # <--- Expo React Native
]

CSRF_TRUSTED_ORIGINS = ["https://barakapos.uz", "https://www.barakapos.uz"]
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

CORS_ALLOW_ALL_ORIGINS  = True
CORS_EXPOSE_HEADERS = ['Content-Disposition']
CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]
ROOT_URLCONF = 'pos.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'pos.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv("DB_NAME"),
        'USER': os.getenv("DB_USER"),
        'PASSWORD': os.getenv("DB_PASSWORD"),
        'HOST': os.getenv("DB_HOST"),
        'PORT': os.getenv("DB_PORT", "5432"),
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.pubsub.RedisPubSubChannelLayer",
        "CONFIG": {
            "hosts": [("redis", 6379)],
        },
    },
}



LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Tashkent'

USE_I18N = True

USE_TZ = True


STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
CELERY_BROKER_URL = 'redis://redis:6379/0'
CELERY_RESULT_BACKEND = 'redis://redis:6379/0'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_TASK_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Asia/Tashkent'


ASGI_APPLICATION = 'pos.asgi.application'