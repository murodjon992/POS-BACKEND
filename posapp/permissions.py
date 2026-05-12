from rest_framework import permissions
from .models import Subscription
from django.utils import timezone


class HasActiveSubscription(permissions.BasePermission):
    message = "Sizda faol obuna mavjud emas. Iltimos, tarifni yangilang."
    def has_permission(self, request, view):
        user = request.user
        if hasattr(user,'seller_profile'):
            actual_owner = user.seller_profile.owner
        else:
            actual_owner = user

        sub = getattr(actual_owner,'subscription', None)

        if request.user.is_superuser:
            return True
        
        if not request.user.is_authenticated or not request.user:
            return False

        if sub and sub.is_active():
            return True
        return False