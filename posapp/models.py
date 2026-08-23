from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta


class Supplier(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=200,  blank=True)
    total_debt_to_them = models.DecimalField(max_digits=12,decimal_places=2,default=0)

    def __str__(self):
        return f"Yetkazib beruvchi: {self.name}"
    
class SupplierLog(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='logs')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    type = models.CharField(choices=(('take', 'Tovar oldik'), ('pay', 'Pul berdik'),('return', 'Tovarni qaytardik')), max_length=10)
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Transaction(models.Model):
    TRANSACTION_TYPES = (
        ('sale', 'Savdo kirim'),
        ('customer_pay','Mijoz to`lovi kirim'),
        ('supplier_pay', 'Tovarga to`lov chiqim'),
        ('expense', 'Xarajat Chiqim'),
        ('return_sale', 'Vozvrat — Savdo ayirish'),
    )
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    type = models.CharField(choices=TRANSACTION_TYPES, max_length=50)
    payment_method = models.CharField(max_length=10, default='cash')
    content_type = models.ForeignKey('contenttypes.ContentType', on_delete=models.SET_NULL, null=True)
    object_id = models.PositiveIntegerField(null=True)
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Customer(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=200)
    total_debt = models.DecimalField(max_digits=12, decimal_places=2,default=0)

    class Meta:
        unique_together = ['owner', 'phone']

    def __str__(self):
        return f"{self.name} - {self.total_debt} so'm"

class DebtLog(models.Model):
    TYPES = (('borrow', 'Qarz Berish'),('pay', 'Qarz qaytarish'),('return', 'Tovar qaytardi'),)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='logs')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    type = models.CharField(choices=TYPES, max_length=10)
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)

    def __str__(self):
        return f"{self.customer.name}: {self.type} - {self.amount}"

class Category(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE,default=1)
    name = models.CharField(max_length=200)
    def __str__(self):
        return self.name

class Product(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True)
    name = models.CharField(max_length=200)
    barcode = models.CharField(max_length=200)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['owner', 'barcode']

    def __str__(self):
        return f"{self.name} - {self.owner.username}"

class AccessoryInventory(models.Model):
    product = models.OneToOneField(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.product.name} - {self.product.owner.username}"

class StocLog(models.Model):
    PAYMENT_METHODS = (
        ('cash', 'Naqd'),
        ('debt', 'Nasiya')
    )
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    seller = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='my_cash_sales')
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    payment_method = models.CharField(choices=PAYMENT_METHODS, max_length=10, default='none')
    created_at = models.DateTimeField(auto_now_add=True)
    daily_id = models.PositiveBigIntegerField(null=True,blank=True)
    note = models.TextField(blank=True)

    def __str__(self):
        return f"#{self.id} - ({self.payment_method})"

class StocLogItem(models.Model):
    stoc_log = models.ForeignKey(StocLog, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    purchase_price_at_time = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price_at_time = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

class ReturnLog(models.Model):
    PAYMENT_METHODS = (
        ('cash', 'Naqd'),
        ('debt', 'Nasiya (Qarzdan chegirish)')
    )
    original_sale = models.ForeignKey(StocLog, on_delete=models.SET_NULL, null=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL,null=True,blank=True)
    quantity = models.PositiveIntegerField()
    amount_returned = models.DecimalField(max_digits=10, decimal_places=2,default=0)  # Qaytarilgan pul miqdori
    payment_method = models.CharField(choices=PAYMENT_METHODS, max_length=10, default='cash')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Return: {self.product.name} ({self.quantity})"

class Plan(models.Model):
    name = models.CharField(max_length=100) # Masalan: "Kumush", "Oltin"
    price = models.DecimalField(max_digits=10, decimal_places=2)
    duration_days = models.IntegerField(default=30)
    # Funksiyalar uchun limitlar
    max_baranchs = models.IntegerField(default=1)
    max_users = models.IntegerField(default=2)
    can_see_reports = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name}"

class Subscription(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="subscription")
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, blank=True, null=True)
    start_date = models.DateTimeField(auto_now_add=True)
    phone = models.CharField(max_length=12,default=998901234567)
    trial_end = models.DateTimeField(null=True, blank=True)
    is_active_status = models.BooleanField(default=True, verbose_name="Admin tomonidan faollik")
    is_paid = models.BooleanField(default=False)
    telegram_chat_id = models.CharField(max_length=100, null=True, blank=True)
    otp_code = models.CharField(max_length=10, null=True, blank=True)
    def save(self, *args, **kwargs):
        if not self.pk and not self.trial_end:
            self.trial_end = timezone.now() + timedelta(days=14)
        if self.pk:  
            try:
                old_obj = Subscription.objects.get(pk=self.pk)
                # To'lov endi tasdiqlanganda muddatni uzaytirish
                if not old_obj.is_paid and self.is_paid:
                    days = self.plan.duration_days if self.plan else 30
                    # Agar trial hali tugamagan bo'lsa, o'sha tugash sanasiga qo'shamiz
                    # Agar o'tib ketgan bo'lsa, bugungi kunga qo'shamiz
                    current_end = old_obj.trial_end if old_obj.trial_end else timezone.now()
                    start_point = max(current_end, timezone.now())
                    self.trial_end = start_point + timedelta(days=days)
            except Subscription.DoesNotExist:
                pass
        super().save(*args, **kwargs)
    @property
    def days_left(self):
        if self.trial_end > timezone.now():
            return (self.trial_end - timezone.now()).days
        return 0
    def is_active(self):
        if not self.is_active_status: return False
        if self.trial_end and self.trial_end > timezone.now():
            return True
        return False
    def __str__(self):
        status = "Faol" if self.is_active() else "Bloklangan/Muddati tugagan"
        return f"{self.user.username} - {status} - {self.days_left} kun"
    
class PurchaseLog(models.Model):
    PAYMENT_METHODS = (('cash', 'Naqd'), ('debt', 'Nasiya'))
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True)
    supplier_log = models.ForeignKey(SupplierLog, on_delete=models.CASCADE,related_name='items', null=True,blank=True)
    quantity = models.PositiveIntegerField()
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(choices=PAYMENT_METHODS, max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"Kirim: {self.product.name} - {self.quantity} ta"
    
class Seller(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='seller_profile')
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='my_sellers')
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True) # Sotuvchini ishdan bo'shatish uchun
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
    def __str__(self):
        return f"{self.full_name} ({self.owner.username} xodimi)"      
    def get_user_status(user):
        if user.is_superuser:
            return "active", "superadmin", "/admin-panel"

        is_seller = hasattr(user, 'seller_profile')
        owner = user.seller_profile.owner if is_seller else user

       
        sub = getattr(owner, 'subscription', None)
        is_sub_active = sub and sub.is_active()

       
        if is_seller:
          
            if is_sub_active:
                return "active", "seller", "/pos"
            else:
                return "blocked", "seller", "/login" # Yoki maxsus "Access Denied" sahifasi

        else:
           
            if is_sub_active:
                return "active", "owner", "/dashboard"
            else:
                return "expired", "owner", "/subscription-plan"

# models.py oxiriga shuni qo'shing (import qatorlariga tegmang, faqat pastga qo'shing):

class PushToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='push_tokens')
    token = models.CharField(max_length=255, unique=True)
    platform = models.CharField(max_length=20, blank=True, default='android')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.token[:25]}..."


class AppVersion(models.Model):
    platform = models.CharField(max_length=20, default='android', unique=True)
    minimum_version = models.CharField(
        max_length=20,
        help_text="Bu versiyadan PASTKI versiyalar majburiy yangilashga yo'naltiriladi. Masalan: 1.2.0"
    )
    latest_version = models.CharField(max_length=20, help_text="Play Store'dagi eng oxirgi versiya raqami")
    update_message = models.TextField(
        blank=True,
        default="Ilovaning yangi versiyasi chiqdi! Davom etish uchun yangilang."
    )
    store_url = models.URLField(
        blank=True,
        default="https://play.google.com/store/apps/details?id=com.murod999.posmobile"
    )
    updated_at = models.DateTimeField(auto_now=True)
 
    def __str__(self):
        return f"{self.platform} - min:{self.minimum_version} / latest:{self.latest_version}"