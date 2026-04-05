from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

# Create your models here.


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
    TYPES = (('borrow', 'Qarz Berish'),('pay', 'Qarz qaytarish'))
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
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    price_at_time = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_method = models.CharField(choices=PAYMENT_METHODS, max_length=10, default='none')
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)

    def __str__(self):
        return f"{self.product.name} - ({self.payment_method})"

class ReturnLog(models.Model):
    PAYMENT_METHODS = (
        ('cash', 'Naqd'),
        ('debt', 'Nasiya (Qarzdan chegirish)')
    )
    # Qaysi sotuvdan qaytarildi?
    original_sale = models.ForeignKey(StocLog, on_delete=models.SET_NULL, null=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
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
    trial_end = models.DateTimeField()
    is_paid = models.BooleanField(default=False)
    telegram_chat_id = models.CharField(max_length=100, null=True, blank=True)
    otp_code = models.CharField(max_length=10, null=True, blank=True)


    def is_active(self):
        if self.is_paid:
            return True

        if self.trial_end and self.trial_end > timezone.now():
            return True
        return False

    @property
    def days_left(self):
        if self.trial_end and self.trial_end > timezone.now():
            diff = self.trial_end - timezone.now()
            return diff.days
        return 0

    def save(self, *args, **kwargs):
        # Agar is_paid True bo'lsa va plan tanlangan bo'lsa
        if self.id:  # obyekt bazada mavjud bo'lsa
            old_instance = Subscription.objects.get(id=self.id)
            # Agar oldin False bo'lib, hozir True qilingan bo'lsa (Admin tomonidan)
            if not old_instance.is_paid and self.is_paid:
                if self.plan:
                    # Amaldagi vaqtdan boshlab tarif kunini qo'shamiz
                    # Agar plan modelida duration_days bo'lsa:
                    days = self.plan.duration_days if hasattr(self.plan, 'duration_days') else 30
                    self.trial_end = timezone.now() + timedelta(days=days)

        super(Subscription, self).save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} - {'Sinov' if not self.is_paid else 'To`langan'} - {self.days_left} kun qoldi"