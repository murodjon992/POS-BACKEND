from django.contrib import admin
from .models import Category, Product, AccessoryInventory, StocLog,Customer,DebtLog,Subscription,Plan,ReturnLog,PushToken


admin.site.register(Category)
admin.site.register(Product)
admin.site.register(AccessoryInventory)
admin.site.register(StocLog)
admin.site.register(Customer)
admin.site.register(DebtLog)
admin.site.register(PushToken)
@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'is_paid', 'trial_end')
    list_editable = ('is_paid',) # Ro'yxatning o'zidayoq tasdiqlash uchun
    search_fields = ('user__username', 'phone')
admin.site.register(Plan)
admin.site.register(ReturnLog)
