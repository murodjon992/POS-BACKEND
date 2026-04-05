from rest_framework import permissions
from .models import Subscription


class HasActiveSubscription(permissions.BasePermission):
    message = "Sizda faol obuna mavjud emas. Iltimos, tarifni yangilang."
    def has_permission(self, request, view):
        if not request.user.is_authenticated or not request.user:
            return False

        try:
            sub = request.user.subscription
            return sub.is_active()  # Yuqoridagi metodni chaqiradi
        except (AttributeError, Subscription.DoesNotExist):
            return False