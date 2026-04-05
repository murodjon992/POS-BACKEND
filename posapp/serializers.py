from rest_framework import serializers
from django.utils import timezone
from django.db import transaction
from .models import Product, AccessoryInventory, Category,Customer,DebtLog,StocLog,User,Subscription,Plan,ReturnLog
from rest_framework.validators import UniqueValidator


class CategorySerializer(serializers.ModelSerializer):
    owner_name = serializers.ReadOnlyField(source='owner.username')
    class Meta:
        model = Category
        fields = ["id", "name","owner_name"]


class ProductSerializer(serializers.ModelSerializer):
    stock_count = serializers.ReadOnlyField(source='accessoryinventory.quantity', default=0)
    category_name = serializers.ReadOnlyField(source='category.name')
    owner_name = serializers.ReadOnlyField(source='owner.username')

    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all(),required=False,allow_null=True)

    class Meta:
        model = Product
        fields = ["id", "name","purchase_price","sale_price", "barcode", "stock_count","category","category_name","owner_name"]

    def create(self, validated_data):
        # Mahsulotni yaratish
        product = Product.objects.create(**validated_data)
        # Mahsulot yaratilishi bilan uning inventarini (omborini) ham ochib qo'yamiz
        AccessoryInventory.objects.create(product=product, quantity=0)
        return product

    def get_stock_count(self, obj):
        # AccessoryInventory'dan miqdorni olamiz
        try:
            return obj.accessoryinventory.quantity
        except:
            return 0  # Agar hali omborga kiritilmagan bo'lsa 0 qaytaramiz


class InventorySerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source='product.owner.username',read_only=True,default="")
    product_name = serializers.ReadOnlyField(source='product.name')
    category_name = serializers.CharField(source='product.category',read_only=True,default="")
    barcode = serializers.ReadOnlyField(source='product.barcode')
    sale_price = serializers.ReadOnlyField(source='product.sale_price')
    purchase_price = serializers.ReadOnlyField(source='product.purchase_price')
    class Meta:
        model = AccessoryInventory
        fields = ["id", "product_name", "owner_name", "category_name", "barcode","purchase_price", "sale_price", "quantity","updated_at" ]

    def get_category_name(self, obj):
        if obj.product.category:
            return obj.product.category.name
        return None

class NasiyaSaleSerializer(serializers.Serializer):
    customer_name = serializers.CharField(max_length=200)
    customer_phone = serializers.CharField(max_length=20, required=False, default="")
    items = serializers.ListField(
        child=serializers.DictField()
    )

class DebtLogSerializer(serializers.ModelSerializer):
    formatted_date = serializers.SerializerMethodField()
    class Meta:
        model = DebtLog
        fields = ['id', 'amount', 'type', 'created_at', 'note', 'formatted_date']
    def get_formatted_date(self, obj):
        return obj.created_at.strftime("%d.%m.%Y %H:%M")

class CustomerSerializer(serializers.ModelSerializer):
    history = DebtLogSerializer(source='logs', many=True, read_only=True)
    class Meta:
        model = Customer
        fields = ['id', 'name', 'phone', 'total_debt','history']

class DailySummarySerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source='product.name')
    total_price = serializers.SerializerMethodField()

    class Meta:
        model = StocLog
        fields = ['id', 'product_name', 'quantity', 'price_at_time', 'total_price', 'payment_method', 'created_at']

    def get_total_price(self, obj):
        return obj.quantity * obj.price_at_time


class UserSerializer(serializers.ModelSerializer):
    # Qo'shimcha: Foydalanuvchi qachon qo'shilganini o'qishga oson formatda chiqarish
    username = serializers.CharField(
        validators=[UniqueValidator(queryset=User.objects.all(), lookup='iexact')],
        required=False  # Tahrirlashda username yuborilmasa ham xato bermaydi
    )
    date_joined = serializers.DateTimeField(format="%Y-%m-%d %H:%M", read_only=True)

    class Meta:
        model = User
        # React-da ko'rsatmoqchi bo'lgan hamma maydonlarni shu yerga yozamiz
        fields = [
            'id',
            'username',
            'email',
            'first_name',
            'last_name',
            'is_staff',  # Admin panelga kira olishi
            'is_superuser',  # Superadminligi
            'is_active',  # Profili yoqilgan yoki o'chirilganligi
            'date_joined'  # Ro'yxatdan o'tgan sana
        ]

class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = '__all__'

class SubscriptionSerializer(serializers.ModelSerializer):
    # Model ichidagi is_active() metodini API-da maydon sifatida ko'rsatamiz
    username = serializers.ReadOnlyField(source='user.username')
    email = serializers.EmailField(source='user.email', read_only=True)
    is_active = serializers.SerializerMethodField()
    days_left = serializers.ReadOnlyField()
    plan_details = PlanSerializer(source='plan', read_only=True)

    # Front-endda select yasash uchun barcha planlarni yuboramiz
    all_plans = serializers.SerializerMethodField()

    # Sanalarni o'qishga qulay formatga keltiramiz (ixtiyoriy)
    start_date = serializers.DateTimeField(format="%Y-%m-%d %H:%M", read_only=True)
    trial_end = serializers.DateTimeField(format="%Y-%m-%d %H:%M")

    # Foydalanuvchi nomini ham ko'rib turish uchun

    class Meta:
        model = Subscription
        fields = ['id', 'user','username','phone','plan','plan_details','email','start_date','trial_end','all_plans','is_paid','days_left','is_active']
        read_only_fields = ['user', 'start_date', 'is_paid']

    def get_is_active(self, obj):
        # Model ichidagi is_active funksiyasini chaqiradi
        return obj.is_active()

    def validate_trial_end(self, value):
        # Sinov muddati hozirgi vaqtdan oldin bo'lishini tekshirish (xavfsizlik uchun)
        if value < timezone.now():
            raise serializers.ValidationError("Trial muddati o'tmishda bo'lishi mumkin emas!")
        return value

    def get_all_plans(self, obj):
        from .models import Plan
        plans = Plan.objects.all()
        # Front-endda select optionlari uchun qulay formatda qaytaramiz
        return [{"id": p.id, "name": p.name, "price": p.price} for p in plans]

    def get_days_left(self, obj):
        # Modelingizda qaysi nom bo'lsa o'shani tekshiradi (trial_end yoki end_date)
        target_date = getattr(obj, 'trial_end', getattr(obj, 'end_date', None))

        if target_date and target_date > timezone.now():
            diff = target_date - timezone.now()
            return diff.days
        return 0

class StocLogSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source='product.name')
    total_price = serializers.SerializerMethodField()
    owner_name = serializers.ReadOnlyField(source='product.owner.username')

    class Meta:
        model = StocLog
        fields = [
            'id', 'product', 'product_name', 'quantity',
            'price_at_time', 'total_price', 'action',
            'payment_method', 'created_at', 'note', 'owner_name'
        ]

    def get_total_price(self, obj):
        return obj.quantity * obj.price_at_time

class ReturnLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReturnLog
        fields = ['original_sale', 'product', 'quantity', 'amount_returned', 'payment_method']

    def create(self, validated_data):
        with transaction.atomic():
            sale = validated_data['original_sale']
            qty = validated_data['quantity']
            product = validated_data['product']
            return_amount = validated_data['amount_returned']

            # 1. Omborga qaytarish
            inventory = AccessoryInventory.objects.get(product=product)
            inventory.quantity += qty
            inventory.save()

            # 2. Nasiya bo'lsa mijoz qarzini kamaytirish
            if sale.payment_method == 'debt':
                # Bu yerda mijozni topish uchun DebtLog'dan foydalanamiz
                debt_entry = DebtLog.objects.filter(type='borrow').last() # Eng oxirgi qarz
                if debt_entry:
                    customer = debt_entry.customer
                    customer.total_debt -= return_amount
                    customer.save()
                    # Qarz kamayganini bildirish uchun note'ga VOZVRAT deb yozamiz
                    DebtLog.objects.create(
                        customer=customer,
                        amount=return_amount,
                        type='pay',
                        note=f"VOZVRAT: {product.name}"
                    )

            return super().create(validated_data)