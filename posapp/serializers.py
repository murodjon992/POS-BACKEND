from rest_framework import serializers
from django.utils import timezone
from django.db import transaction
from .models import Product, AccessoryInventory, Category,Customer,DebtLog,StocLog,User,Subscription,Plan,ReturnLog,Supplier,SupplierLog,Transaction,Seller,StocLogItem,PurchaseLog,AppVersion
from rest_framework.validators import UniqueValidator
from django.db.models import Sum


class UserSerializer(serializers.ModelSerializer):
    username = serializers.CharField(validators=[UniqueValidator(queryset=User.objects.all(), lookup='iexact')],required=False  )
    date_joined = serializers.DateTimeField(format="%Y-%m-%d %H:%M", read_only=True)

    class Meta:
        model = User
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

class CategorySerializer(serializers.ModelSerializer):
    owner_name = serializers.ReadOnlyField(source='owner.username')
    class Meta:
        model = Category
        fields = ["id", "name","owner", "owner_name"]

class ProductSerializer(serializers.ModelSerializer):
    stock_count = serializers.ReadOnlyField(source='accessoryinventory.quantity', default=0)
    category_name = serializers.ReadOnlyField(source='category.name',read_only=True, default="Kategoriyasiz")
    owner_name = serializers.ReadOnlyField(source='owner.username', read_only=True, default="Noma'lum")
    owner = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), required=False)
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all(),required=False,allow_null=True)

    class Meta:
        model = Product
        fields = ["id", "name","purchase_price","sale_price", "owner", "barcode", "stock_count","category","category_name","owner_name"]

    def get_stock_count(self, obj):
        # AccessoryInventory'dan miqdorni olamiz
        try:
            return obj.accessoryinventory.quantity
        except:
            return 0
        
    def __init__(self, *args, **kwargs):
        super(ProductSerializer, self).__init__(*args, **kwargs)
        request = self.context.get('request')
        if request and hasattr(request, 'user') and request.user.is_authenticated:
            if request.user.is_superuser:
                self.fields['category'].queryset = Category.objects.all()
            else:
                self.fields['category'].queryset = Category.objects.filter(owner=request.user)

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

class SellerCreateSerializer(serializers.ModelSerializer):
    username = serializers.CharField(write_only=True, validators=[UniqueValidator(queryset=User.objects.all(), lookup='iexact')])
    password = serializers.CharField(write_only=True)
    # user fieldini read_only qilamiz, chunki uni create ichida o'zimiz yaratamiz
    user = UserSerializer(read_only=True) 

    class Meta:
        model = Seller
        fields = ['id', 'user', 'username', 'password', 'full_name', 'phone']

    def create(self, validated_data):
        username = validated_data.pop('username')
        password = validated_data.pop('password')
        
        # User yaratish
        user = User.objects.create_user(username=username, password=password)
        
        # Seller yaratish
        owner = self.context['request'].user
        seller = Seller.objects.create(
            user=user,
            owner=owner,
            full_name=validated_data.get('full_name', ''),
            phone=validated_data.get('phone', '')
        )
        return seller

class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = '__all__'

class SubscriptionSerializer(serializers.ModelSerializer):
    username = serializers.ReadOnlyField(source='user.username')
    is_active = serializers.SerializerMethodField()
    days_left = serializers.ReadOnlyField() # Model property'dan oladi
    plan_details = PlanSerializer(source='plan', read_only=True)
    all_plans = serializers.SerializerMethodField()  
    start_date = serializers.DateTimeField(format="%Y-%m-%d %H:%M", read_only=True)
    trial_end = serializers.DateTimeField(format="%Y-%m-%d %H:%M", required=False)
    trial_end_display = serializers.DateTimeField(source='trial_end', format="%Y-%m-%d", read_only=True)
    class Meta:
        model = Subscription
        fields = [
            'id', 'user', 'username', 'phone', 'plan', 'plan_details', 
            'start_date', 'trial_end', 'all_plans', 'is_paid', 'trial_end_display',
            'days_left', 'is_active', 'is_active_status'
        ]
        read_only_fields = ['user', 'start_date'] 
    def update(self, instance, validated_data):
        # Agar Admin 'is_paid'ni True qilsa, React'dan kelgan trial_end'ni o'chiramiz
        # Shunda Model o'zi bazadagi sanaga +30 kun qo'shadi.
        if validated_data.get('is_paid') is True:
            validated_data.pop('trial_end', None)
            
        return super().update(instance, validated_data)
    def get_is_active(self, obj):
        return obj.is_active()

    def get_all_plans(self, obj):
        from .models import Plan
        plans = Plan.objects.all()
        return [{"id": p.id, "name": p.name, "price": p.price} for p in plans]

    
    def validate_trial_end(self, value):
       
        return value

class StocLogItemSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source='product.name')
    barcode = serializers.ReadOnlyField(source='product.barcode')
    sold_qty = serializers.IntegerField(source='quantity')
    total_price = serializers.SerializerMethodField()
    returned_qty = serializers.SerializerMethodField()
    remaining_qty = serializers.SerializerMethodField()

    class Meta:
        model = StocLogItem
        fields = ['id', 'product','stoc_log', 'product_name', 'quantity', 'barcode', 'price_at_time', 'purchase_price_at_time', 'total_price','returned_qty','remaining_qty','sold_qty']

    def get_total_price(self, obj):
        return obj.quantity * obj.price_at_time
    
    def get_returned_qty(self, obj):
        qty = ReturnLog.objects.filter(customer=obj.stoc_log.customer, original_sale=obj.stoc_log, product=obj.product,created_at__gte=obj.stoc_log.created_at).aggregate(total=Sum('quantity'))['total'] or 0
        return qty

    def get_remaining_qty(self, obj):
        return obj.quantity - self.get_returned_qty(obj)

class StocLogSerializer(serializers.ModelSerializer):
    seller_name = serializers.ReadOnlyField(source='seller.username')
    items = StocLogItemSerializer(many=True)
    customer_name = serializers.ReadOnlyField(source='customer.name')
    is_paid = serializers.SerializerMethodField()
    is_returned = serializers.SerializerMethodField()

    class Meta:
        model = StocLog
        fields = [
            'id', 'owner', 'customer', 'seller', 'seller_name','customer_name', 'total_amount', 
            'payment_method','daily_id', 'note', 'created_at', 'items','is_paid','is_returned'
        ]
        read_only_fields = ['owner','daily_id','seller']
    

    def create(self, validated_data):
        request = self.context.get('request')
        print(f"DEBUG: Request user: {request.user}") # Terminalga qarang
        print(f"DEBUG: Validated data: {validated_data}")
        items_data = validated_data.pop('items')


        request = self.context.get('request')
        user = request.user

        validated_data['seller'] = user

        if hasattr(user,'seller_profile'):
            validated_data['owner'] = user.seller_profile.owner
        else:
            validated_data['owner'] = user
        
        stoc_log = StocLog.objects.create(**validated_data)

        for item_data in items_data:
            StocLogItem.objects.create(stoc_log=stoc_log, **item_data)

        return stoc_log
    
    def get_is_paid(self,obj):
        if self.get_is_returned(obj):
            return False
        
        if obj.payment_method == 'cash': return True

        if not obj.customer or obj.customer.total_debt <= 0:
            return True
        return False
    
    def get_has_partial_return(self,obj):
        if self.get_is_returned(obj):
            return False
        return any(self.get_item_returned_qty(item) > 0 for item in obj.items.all())
    
    def get_is_returned(self, obj):
        items = obj.items.all()
        if not items: return False

        total_sold = sum(item.quantity for item in items) 
        total_returned = sum(self.get_item_returned_qty(item) for item in items)

        return total_sold > 0 and total_sold == total_returned

        # Agar sotilgan va qaytarilgan miqdor teng bo'lsa va 0 dan katta bo'lsa
        return total_sold > 0 and total_sold == total_returned

    def get_item_returned_qty(self, item_obj):
        from .models import ReturnLog
        from django.db.models import Sum
        return ReturnLog.objects.filter(
            customer=item_obj.stoc_log.customer,
            product=item_obj.product,
            created_at__gte=item_obj.stoc_log.created_at
        ).aggregate(total=Sum('quantity'))['total'] or 0
    
class ReturnLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReturnLog
        fields = ['original_sale', 'product', 'quantity', 'amount_returned', 'payment_method']

class PurchaseItemSerializer(serializers.ModelSerializer):
    current_stock = serializers.SerializerMethodField()
    product_name = serializers.ReadOnlyField(source='product.name')
    barcode = serializers.ReadOnlyField(source='product.barcode')
    class Meta:
        model = PurchaseLog
        fields = ['product_name', 'quantity', 'purchase_price','barcode','current_stock',]

    def get_current_stock(self, obj):
        try:
            inventory = AccessoryInventory.objects.get(product=obj.product)
            return inventory.quantity
        except AccessoryInventory.DoesNotExist:
            return 0

class SupplierLogSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(format="%d-%m-%Y %H:%M")
    items = PurchaseItemSerializer(many=True,read_only=True)
    class Meta:
        model = SupplierLog
        fields = ['id', 'amount', 'type', 'created_at','note','items']

class SupplierSerializer(serializers.ModelSerializer):
    history = SupplierLogSerializer(source='logs', many=True, read_only=True)
    class Meta:
        model = Supplier
        fields = ['id','name','phone','total_debt_to_them','history']
        read_only_fields = ['owner']

class TransactionSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    class Meta:
        model = Transaction
        fields = ['id', 'amount', 'type', 'type_display', 'payment_method', 'created_at']
        read_only_fields = ['owner', 'created_at']


class AppVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppVersion
        fields = ['id', 'platform', 'minimum_version', 'latest_version', 'update_message', 'store_url', 'updated_at']
        read_only_fields = ['id', 'updated_at']