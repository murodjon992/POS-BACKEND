from django.utils import timezone
from datetime import timedelta
from django.shortcuts import get_object_or_404
from django.db.models import Sum,F,DecimalField
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view,permission_classes,authentication_classes
from django.db.models.functions import Coalesce
from rest_framework.pagination import PageNumberPagination
from .permissions import HasActiveSubscription
from django.db import transaction
from .models import Product, AccessoryInventory, StocLog, Customer,DebtLog,Subscription,Plan,Category,ReturnLog,Supplier,Transaction,Seller,StocLogItem,SupplierLog,PurchaseLog
from .serializers import ProductSerializer, InventorySerializer,CustomerSerializer,TransactionSerializer,UserSerializer,CategorySerializer,DebtLogSerializer,SubscriptionSerializer,PlanSerializer,SupplierSerializer,ReturnLogSerializer,SellerCreateSerializer,StocLogSerializer,PurchaseItemSerializer
from django.db.models import Q
from rest_framework.response import Response
from PIL import Image as PILImage
from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated,AllowAny,IsAdminUser
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from barcode.writer import ImageWriter
import pandas as pd
from decimal import Decimal
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import io
import random
import os
import barcode
import openpyxl
from openpyxl.styles import Font
from django.conf import settings
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from telegram_bot.bot import send_telegram_otp
from rest_framework import viewsets
DF = DecimalField(max_digits=15, decimal_places=2)
from .signals import broadcast_data



def get_actual_owner(user):
    if hasattr(user, 'seller_profile'):
        return user.seller_profile.owner
    return user

def get_user_info(user):
    # 1. Rolni aniqlaymiz
    is_seller = hasattr(user, 'seller_profile')
    role = "seller" if is_seller else "owner"
    if user.is_superuser:
        role = "superadmin"

    # 2. Asosiy egasini (owner) topamiz (Obunani tekshirish uchun)
    owner = user.seller_profile.owner if is_seller else user
    
    # 3. Obunani tekshiramiz
    sub = getattr(owner, 'subscription', None)
    if user.is_superuser:
        status = "active"
    elif sub and sub.is_active(): # .is_active() metodi Subscription modelida bo'lishi kerak
        status = "active"
    else:
        status = "expired"

    return status, role

# Font fayllari yo'lini ko'rsatamiz
FONT_REG = os.path.join(settings.BASE_DIR, 'static', 'fonts', 'Montserrat-Regular.ttf')
FONT_BOLD = os.path.join(settings.BASE_DIR, 'static', 'fonts', 'Montserrat-Bold.ttf')

# Fontlarni ro'yxatdan o'tkazamiz
pdfmetrics.registerFont(TTFont('Montserrat', FONT_REG))
pdfmetrics.registerFont(TTFont('Montserrat-Bold', FONT_BOLD))


class SupplierViewSet(viewsets.ModelViewSet):
    serializer_class = SupplierSerializer
    permission_classes = [IsAuthenticated,HasActiveSubscription]

    def get_queryset(self):
        return Supplier.objects.filter(owner=self.request.user)
    
    def perform_create(self,serializer):
        serializer.save(owner=self.request.user)

# ========================AUTHENTIKATSIYA=========================

@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    try:
        username = request.data.get("username","").strip()
        phone = request.data.get("phone","").strip()
        password = request.data.get("password","")

        if not username or not password or not phone:
            return Response({"error": "Barcha maydonlarni to'ldiring"}, status=400)

        if User.objects.filter(username=username).exists():
            return Response({"error": "Bunday foydalanuvchi mavjud"}, status=400)

        if Subscription.objects.filter(phone=phone).exists():
            return Response({"error": "Bu telefon raqami allaqachon ro'yxatdan o'tgan"}, status=400)
        with transaction.atomic():  # Hammasi bajariladi yoki hech biri bajarilmaydi
            user = User.objects.create_user(username=username, password=password)

            trial_days = 14
            trial_limit = timezone.now() + timedelta(days=trial_days
                                                     )
            Subscription.objects.create(
                user=user,
                phone=phone,
                trial_end=trial_limit,
                is_paid=False
            )

            token = Token.objects.create(user=user)

        return Response({
            "token": token.key,
            "username": user.username,
            'days_left': trial_days,
            "bot_url": f"https://t.me/barakapos_bot?start={user.id}",
            "message": f"Ro'yxatdan muvaffaqqiyatli o'tdingiz. {trial_days} kunlik bepul sinov muddati faollashtirildi!",
            "instruction": "Diqqat! Kunlik hisobotlarni olish va xavfsizlikni ta'minlash uchun Telegram botimizga a'zo bo'ling."
        }, status=201)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(['POST'])
def login(request):
    username = request.data.get("username")
    password = request.data.get("password")
    try:

        # 1. Avvalo username bazada borligini tekshiramiz
        try:
            user_obj = User.objects.get(username=username)
        except User.DoesNotExist:
            return Response({"error": "Bunday foydalanuvchi nomi mavjud emas"}, status=404)

        # 2. Endi parolni tekshiramiz
        user = authenticate(username=username, password=password)

        if user is None:
            # Agar username bor bo'lsa-yu, authenticate None qaytarsa - demak parol xato
            return Response({"error": "Parol noto'g'ri kiritildi"}, status=400)

        # 3. Muvaffaqiyatli login
        token, _ = Token.objects.get_or_create(user=user)
        status,role = get_user_info(user)

        return Response({
            "token": token.key,
            "user": {
                "id": user.id,
                "username": user.username,
                "is_superuser": user.is_superuser,
                "role":role,
                "status":status
            }
        })
    except Exception as e:
        return Response({"error": f"Tizim xatosi: {str(e)}"}, status=500)

@api_view(['POST'])
@permission_classes([AllowAny])
def request_password_reset(request):
    phone = request.data.get('phone', '').replace('+', '').strip()
    # Telefon raqami bo'yicha subscriptionni qidiramiz
    sub = Subscription.objects.filter(phone=phone).first()
    if not sub:
        return Response({"error": "Ushbu raqamga bog'langan profil topilmadi"}, status=404)
    # Botga ulanmagan bo'lsa
    if not sub.telegram_chat_id:
        return Response({
            "error": "telegram_not_linked",
            "user_id":sub.user.id,
            "message": "Avval botga ulaning!",
            "bot_url": f"https://t.me/barakapos_bot?start={sub.user.id}"
        }, status=400)

    # OTP yaratish va saqlash
    otp_code = str(random.randint(100000, 999999))
    sub.otp_code = otp_code
    sub.save()


    send_telegram_otp(sub.telegram_chat_id, otp_code)

    return Response({"message": "Kod Telegramga yuborildi!"})

@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password(request):
    phone = request.data.get('phone', '').strip()
    otp = request.data.get('otp')
    new_password = request.data.get('new_password')

    # 1. Ma'lumotlar to'liqligini tekshirish
    if not all([phone, otp, new_password]):
        return Response({"error": "Barcha maydonlarni to'ldiring"}, status=400)

    try:
        # 2. Subscription orqali userni va kodni topamiz
        sub = Subscription.objects.get(phone=phone)

        # 3. Kodni solishtirish (Bazadagi otp_code bilan)
        if sub.otp_code == str(otp) and sub.otp_code is not None:
            user = sub.user

            # 4. Parolni yangilash
            user.set_password(new_password)
            user.save()

            # 5. Ishlatilgan kodni o'chirib tashlaymiz (xavfsizlik uchun)
            sub.otp_code = None
            sub.save()

            return Response({"message": "Parol muvaffaqiyatli yangilandi"}, status=200)

        else:
            return Response({"error": "Tasdiqlash kodi noto'g'ri"}, status=400)

    except Subscription.DoesNotExist:
        return Response({"error": "Foydalanuvchi topilmadi"}, status=404)
    except Exception as e:
        return Response({"error": f"Tizim xatosi: {str(e)}"}, status=500)
    

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_profile(request):
    user = request.user
    data = request.data

    # 1. User modelidagi username-ni yangilash
    new_username = data.get('username')
    if new_username:
        user.username = new_username
        user.save()

    # 2. Subscription modelidagi phone-ni yangilash
    sub = Subscription.objects.get(user=user)
    new_phone = data.get('phone')
    if new_phone:
        sub.phone = new_phone
        sub.save()

    return Response({
        "message": "Profil muvaffaqiyatli yangilandi",
        "username": user.username,
        "phone": sub.phone
    }, status=200)

temp_otp_store = {}
# =====================AUTHENTIKATSIYA TUAGSHI=========================================================================================================
# =====================MAHSULOTLAR ====================================================================================================================
@api_view(["GET"])
@permission_classes([HasActiveSubscription])
def get_product_by_barcode(request, barcode):
    try:
        actual_owner = get_actual_owner(request.user)
        product = Product.objects.get(barcode=barcode,owner=actual_owner)
        serializer = ProductSerializer(product)
        return Response(serializer.data)

    except Product.DoesNotExist:
        return Response({"error": "Product not found"})

@api_view(["POST"])
@permission_classes([IsAuthenticated,HasActiveSubscription])
@transaction.atomic
def sell_product(request):
    try:
        data = request.data
        items_data = data.get("items", [])
        user = request.user
        actual_owner = user.seller_profile.owner if hasattr(user, 'seller_profile') else user
        today = timezone.now().date()

        last_sale = StocLog.objects.filter(owner=actual_owner,created_at__date=today).order_by('-daily_id').first()
        new_daily_id = (last_sale.daily_id + 1) if (last_sale and last_sale.daily_id) else 1

        customer = None
        if data.get("customer_id"):
            customer = Customer.objects.get(id=data.get("customer_id"), owner=actual_owner)
        elif data.get("customer_name"):
            customer = Customer.objects.create(
                owner=actual_owner,
                name=data.get("customer_name"),
                phone=data.get("customer_phone", "")
            )
        total_sum = 0
        temp_items = []
        for item in items_data:
            product = Product.objects.get(barcode=item['barcode'], owner=actual_owner)
            qty = int(item['quantity'])
            total_sum += (product.sale_price * qty)
            temp_items.append({'product': product, 'qty': qty})

        # 3. ENDI StocLog yaratamiz. Signal hozir ishga tushadi va total_amount ni TO'G'RI ko'radi.
        stoc_log = StocLog.objects.create(
            owner=actual_owner,
            seller=user,
            daily_id = new_daily_id,
            customer=customer,
            payment_method=data.get("payment_method", "cash"),
            total_amount=total_sum, # Summa darrov yozildi
            note=data.get("note", "")
        )

        # 4. Itemlarni yaratish
        for it in temp_items:
            StocLogItem.objects.create(
                stoc_log=stoc_log,
                product=it['product'],
                quantity=it['qty'],
                price_at_time=it['product'].sale_price,
                purchase_price_at_time=it['product'].purchase_price
            )
        next_daily_id = new_daily_id + 1

        return Response({"status": "success", "total": total_sum,"next_daily_id": next_daily_id}, status=201)

    except Exception as e:
        return Response({"error": str(e)}, status=500)
    

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def product_search(request):
    query = request.GET.get("q", "").strip()
    actual_owner = get_actual_owner(request.user)

    products = Product.objects.filter(
        Q(name__icontains=query) |
        Q(barcode__icontains=query),
        owner=actual_owner
    ).order_by('name')[:20]
    # Agar topilmasa, error emas, bo'sh list [] qaytaramiz
    serializer = ProductSerializer(products, many=True)
    return Response(serializer.data)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def product_list_create(request):
    try:
        actual_owner = get_actual_owner(request.user)
        if request.method == 'GET':
            # 1. Querysetni olish (select_related tezlik uchun)
            products = Product.objects.select_related('category', 'owner').all().order_by('-id')

            # User filtratsiyasi
            if not request.user.is_superuser:
                products = products.filter(owner=actual_owner)

            # Qidiruv
            search = request.query_params.get('search', None)
            if search:
                products = products.filter(name__icontains=search) | products.filter(barcode__icontains=search)

            category_id = request.query_params.get('category', None)
            if category_id:
                products = products.filter(category_id=category_id)


            paginator = PageNumberPagination()
            paginator.page_size = 20 
            # 3. Querysetni qirqish
            page = paginator.paginate_queryset(products, request)

            if page is not None:
                serializer = ProductSerializer(page, many=True)
                # Bu joyda count, next, previous va results avtomatik generatsiya bo'ladi
                return paginator.get_paginated_response(serializer.data)

            # Agar biron sababga ko'ra pagination ishlamasa (masalan, page=999 bo'lsa)
            serializer = ProductSerializer(products, many=True)
            return Response(serializer.data)

        elif request.method == 'POST':
            serializer = ProductSerializer(data=request.data)
            if serializer.is_valid():
                serializer.save(owner=actual_owner)
                return Response(serializer.data, status=201)
            return Response(serializer.errors, status=400)
    except Exception as e:
            return Response({"error": str(e)}, status=500)

@api_view(['GET','PUT','DELETE'])
@permission_classes([IsAuthenticated])
def product_detail(request, pk):
    try:
        if request.user.is_superuser:
            product = Product.objects.get(pk=pk)
        else:
            product = Product.objects.get(pk=pk, owner=request.user)
    except Product.DoesNotExist:
        return Response({"error": "Mahsulot topilmadi yoki sizga tegishli emas"}, status=404)

    if request.method == 'GET':
        serializer = ProductSerializer(product)
        return Response(serializer.data)

    if request.method == 'PUT':
        serializer = ProductSerializer(product, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    elif request.method == 'DELETE':
        product.delete()
        return Response(status=204)
    


# ===============================================================MAHSULOTLAR TUGASHI=======================================================================
# ==============================================================OMBOR ====================================================================================
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def stock_in(request):
    barcode = request.data.get('barcode')
    quantity = int(request.data.get('quantity', 0))
    payment_method = request.data.get('payment_method')
    supplier_id = request.data.get('supplier_id')
    
    try:
        product = Product.objects.get(barcode=barcode, owner=request.user)
        inventory, _ = AccessoryInventory.objects.get_or_create(product=product)
        total_cost = product.purchase_price * quantity
        
        with transaction.atomic():
            # 1. Ombordagi sonini yangilash
            inventory.quantity += quantity
            inventory.save()
            
            # 2. SupplierLog yaratish (Tarix zanjiri boshlanishi)
            s_log = None
            if supplier_id:
                supplier = Supplier.objects.get(id=supplier_id, owner=request.user)
                s_log = SupplierLog.objects.create(
                    supplier=supplier,
                    amount=total_cost,
                    type='take',
                    note=f"Kirim: {product.name}"
                )

            # 3. PurchaseLog yaratish (Mahsulotlar ro'yxati uchun)
            PurchaseLog.objects.create(
                owner=request.user,
                product=product,
                supplier_id=supplier_id,
                quantity=quantity,
                purchase_price=product.purchase_price,
                payment_method=payment_method,
                supplier_log=s_log # Bu yerda bog'liqlik hosil bo'ladi
            )
            
            # 4. Naqd bo'lsa darhol to'lov logini ham yaratamiz
            if payment_method == 'cash':
                Transaction.objects.create(
                    owner=request.user,
                    amount=total_cost,
                    type='supplier_pay',
                    payment_method='cash',
                )
                if s_log: # Agarda supplier tanlangan bo'lsa, qarzni yopish uchun 'pay' logi
                     SupplierLog.objects.create(
                        supplier=s_log.supplier,
                        amount=total_cost,
                        type='pay',
                        note="Naqd to'lov yopildi"
                    )
        broadcast_data("STOCK_UPDATE", {
            "action": "STOCK_UPDATE",
            "product_name": product.name,
            "message": "Yangi mahsulot kirim qilindi"
        })
        # --------------------------------

        return Response({"status": "success", "message": "Kirim saqlandi!"})
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=400)
    

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def inventory_view(request):
    inventory = AccessoryInventory.objects.select_related("product", "product__category").order_by('-updated_at')

    if not request.user.is_superuser:
        inventory = inventory.filter(product__owner=request.user)

        # 2. Agar oddiy do'kon egasi bo'lsa - faqat o'zinikini olamiz
    out_of_stock_count = inventory.filter(Q(quantity=0) | Q(quantity__isnull=True)).count()
    low_stock_count = inventory.filter(quantity__gt=0, quantity__lte=10).count()

    search_query = request.query_params.get("search", "")
    if search_query:
        inventory = inventory.filter(
            Q(product__name__icontains=search_query) | 
            Q(product__barcode__icontains=search_query)
        )

    # B) Kategoriya bo'yicha filtr
    category_id = request.query_params.get("category")
    if category_id:
        inventory = inventory.filter(product__category_id=category_id)

    # Status bo'yicha filtr (QuerySet hali ishga tushmadi, bu tekin)
    status = request.query_params.get("status")
    if status == "out":
        inventory = inventory.filter(Q(quantity=0) | Q(quantity__isnull=True)) # Xatoni to'g'irladim: isnull=True bo'ladi
    elif status == "low":
        inventory = inventory.filter(quantity__gt=0, quantity__lte=10)

    category_id = request.query_params.get("category")
    if category_id:
        inventory = inventory.filter(product__category_id=category_id)

    # 2. PAGINATION QO'SHAMIZ (Eng muhim joyi!)
    paginator = StandardResultsSetPagination()
    page = paginator.paginate_queryset(inventory, request)
    
    if page is not None:
        serializer = InventorySerializer(page, many=True)
        return paginator.get_paginated_response({
            "alerts": {
                "out_of_stock": out_of_stock_count,
                "low_stock": low_stock_count,
                "has_warning": out_of_stock_count > 0 or low_stock_count > 0
            },
            "results": serializer.data
        })

    # Agar pagination bo'lmasa (kam ma'lumot bo'lsa)
    serializer = InventorySerializer(inventory, many=True)
    return Response({
        "alerts": {"out_of_stock": out_of_stock_count, "low_stock": low_stock_count},
        "results": serializer.data
    })
# ==============================================================OMBOR TUGASHI=============================================================================
# ==============================================================YETKAZIB BERUVCHILAR =====================================================================
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_debtor_details(request, customer_id):
    try:
        customer = Customer.objects.get(id=customer_id, owner=request.user)
        
        # 1. Mijozning barcha NASIYA savdolari (StocLog)
        sales = StocLog.objects.filter(
            customer=customer, 
            payment_method='debt'
        ).order_by('-created_at')
        
        # 2. Mijozning barcha to'lov va qaytarish operatsiyalari (DebtLog)
        logs = DebtLog.objects.filter(customer=customer).order_by('-created_at')
        
        return Response({
            "customer_name": customer.name,
            "total_debt": customer.total_debt,
            "sales": StocLogSerializer(sales, many=True).data,
            "logs": DebtLogSerializer(logs, many=True).data
        })
    except Customer.DoesNotExist:
        return Response({"error": "Mijoz topilmadi"}, status=404)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def customers_view(request):
    # Faqat joriy foydalanuvchiga tegishli mijozlarni olish
    customers = Customer.objects.filter(owner=request.user)
    serializer = CustomerSerializer(customers, many=True)
    return Response(serializer.data)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def suppliers_view(request):
    if request.method == 'GET':
        # Faqat foydalanuvchiga tegishli supplierlarni olish
        suppliers = Supplier.objects.filter(owner=request.user).order_by('name')
        serializer = SupplierSerializer(suppliers, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        # Yangi supplier yaratish
        serializer = SupplierSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(owner=request.user)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
    
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def supplier_history(request, supplier_id):
    # Faqat ushbu foydalanuvchiga tegishli supplieni topamiz
    supplier = get_object_or_404(Supplier.objects.prefetch_related('logs'), id=supplier_id,owner=request.user)    
    serializer = SupplierSerializer(supplier)
    history_data = serializer.data.get('history') or []
    data = {
        "supplier_name": serializer.data['name'],
        "total_debt_to_them": serializer.data['total_debt_to_them'],
        "history": history_data[::-1] # Eng yangi harakatlar tepada bo'lishi uchun
    }
    
    return Response(data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def pay_supplier_debt(request, supplier_id):
    try:
        supplier = get_object_or_404(Supplier, id=supplier_id, owner=request.user)
        amount_to_pay = float(request.data.get('amount', 0))
        if amount_to_pay <= 0:
            return Response({"error": "Summa noldan katta bo'lishi kerak"}, status=400)
        
        with transaction.atomic():
            current_debt = float(supplier.total_debt_to_them)
            
            actual_pay = min(amount_to_pay, current_debt)
            
            SupplierLog.objects.create(
                supplier=supplier,
                amount=actual_pay,
                type='pay'
            )

            if amount_to_pay >= current_debt:
                supplier.delete() 
                return Response({
                    "status": "deleted", 
                    "message": "To'lov qilindi, kassa yangilandi va supplier o'chirildi"
                })
            else:
                supplier.refresh_from_db()
                return Response({
                    "status": "success", 
                    "total_debt": supplier.total_debt_to_them
                })
    except Exception as e:
        return Response({"error": str(e)}, status=500)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def return_to_supplier(request, supplier_id):
    try:
        supplier = get_object_or_404(Supplier, id=supplier_id, owner=request.user)
        barcode = request.data.get('barcode')
        qty = int(request.data.get('quantity', 0))
        is_cash = request.data.get('is_cash') in [True, 'true', 'True']

        product = get_object_or_404(Product, barcode=barcode, owner=request.user)
        inventory = AccessoryInventory.objects.get(product=product)

        if inventory.quantity < qty:
            return Response({"error": "Omborda yetarli mahsulot yo'q"}, status=400)

        price = product.purchase_price
        return_amount = price * qty

        with transaction.atomic():
            # 1. Ombor qoldig'ini kamaytiramiz
            inventory.quantity -= qty
            inventory.save()

            # 2. Vozvrat turi bo'yicha log yaratish
            if not is_cash:
                # FAQAT NAQD BO'LMASA qarzni kamaytiradigan 'return' logi yaratiladi
                SupplierLog.objects.create(
                    supplier=supplier,
                    amount=return_amount,
                    type='return',
                    note=f"Vozvrat (qarzdan ayirish): {product.name} ({qty} dona)"
                )
            else:
                # Agar NAQD bo'lsa, kassa ko'payadi, lekin supplier qarziga tegmaymiz
                Transaction.objects.create(
                    owner=request.user,
                    amount=return_amount,
                    type='income',
                    payment_method='cash',
                    note=f"Vozvrat naqd olindi: {product.name}"
                )
                # Bu yerda SupplierLog yaratish shart emas, chunki qarz o'zgarmaydi.
                # Lekin tarixda ko'rinishi uchun 'note' sifatida oddiy log qolsa bo'ladi (type='pay' emas)

            # 3. Serializers ko'rishi uchun PurchaseLog (miqdorni minus bilan yozish mumkin yoki alohida field)
            PurchaseLog.objects.create(
                owner=request.user,
                product=product,
                supplier=supplier,
                quantity=qty, # Vozvrat bo'lgani uchun minus bilan belgilash foydali
                purchase_price=price,
                payment_method='cash' if is_cash else 'debt'
            )

        # --- MUHIM: QARZNI TEKSHIRISH ---
        # Transaction atomic tugagandan so'ng qarzni qayta hisoblaymiz
        supplier.refresh_from_db()
        if float(supplier.total_debt_to_them) <= 0:
            supplier.delete()
            return Response({"status": "deleted", "message": "Qarz yopildi va supplier o'chirildi"})

        return Response({"status": "success"})
    
    except Exception as e:
        return Response({"error": str(e)}, status=400)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def supplier_general_return(request):
    try:
        barcode = request.data.get('barcode')
        qty = int(request.data.get('quantity', 0))

        product = get_object_or_404(Product, barcode=barcode, owner=request.user)
        inventory = AccessoryInventory.objects.get(product=product)

        if inventory.quantity < qty:
            return Response({"error": "Omborda yetarli mahsulot yo'q"}, status=400)

        price = product.purchase_price
        return_amount = price * qty

        with transaction.atomic():
            inventory.quantity -= qty
            inventory.save()

            Transaction.objects.create(
                owner=request.user,
                amount=return_amount,
                type='income',
                payment_method='cash',
            )

        return Response({"status": "success", "message": "Vozvrat amalga oshdi, pul kassaga qo'shildi"})
    except Exception as e:
        print(f"Xato yuz berdi: {str(e)}") 
        return Response({"error": str(e)}, status=400)
    
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def all_purchase_history(request):
    purchases = PurchaseLog.objects.filter(owner=request.user).order_by('-created_at')
    
    data = []
    for p in purchases:
        try:
            inventory = AccessoryInventory.objects.get(product=p.product)
            stock_qty = inventory.quantity
        except AccessoryInventory.DoesNotExist:
            stock_qty = 0
        data.append({
            "id": p.id,
            "product_name": p.product.name,
            "barcode": p.product.barcode,
            "quantity": p.quantity,
            "current_stock": stock_qty,
            "purchase_price": p.purchase_price,
            "supplier_name": p.supplier.name if p.supplier else "Noma'lum",
            "supplier_id": p.supplier.id if p.supplier else None,
            "payment_method": p.payment_method, # cash yoki debt
            "date": p.created_at.strftime("%d.%m.%Y %H:%M")
        })
    
    return Response(data)
# ==============================================================YETKAZIB BERUVCHILAR TUGASHI==============================================================
# ==============================================================QARZDORLAR ===============================================================================
@api_view(["GET"])
@permission_classes([IsAuthenticated, HasActiveSubscription])
def get_debtors(request):
    actual_owner = get_actual_owner(request.user)
    try:
        user = actual_owner
        if hasattr(user, 'seller_profile'):
            actual_owner = user.seller_profile.owner
        else:
            actual_owner = user

        debtors = Customer.objects.filter(
            owner=actual_owner, total_debt__gt=0).order_by('-total_debt')
        serializer = CustomerSerializer(debtors, many=True)
        return Response(serializer.data)  
    except Exception as e:
        return Response({"error": str(e)}, status=500)
    

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def customer_debt_history(request, customer_id):
    user = request.user
    actual_owner = user.seller_profile.owner if hasattr(user, 'seller_profile') else user
    
    try:
        customer = Customer.objects.get(id=customer_id, owner=actual_owner)
    except Customer.DoesNotExist:
        return Response({"error": "Mijoz topilmadi"}, status=404)
    
    # Barcha DebtLog yozuvlarini olish
    logs = customer.logs.all().order_by('-created_at')
    
    data = {
        "customer_name": customer.name,
        "total_debt": customer.total_debt,
        "history": []
    }
    
    for log in logs:
        log_data = {
            "id": log.id,
            "amount": log.amount,
            "type": log.type,  # 'borrow', 'pay', 'return'
            "date": log.created_at.strftime("%Y-%m-%d %H:%M"),
            "note": log.note,
            "items": []  # Mahsulotlar ro'yxati (faqat 'borrow' uchun)
        }
        
        # Agar qarz olish bo'lsa (borrow), tegishli savdoni topamiz
        if log.type == 'borrow':
            # log.note da "Savdo #DAILY_ID dan qarz" ko'rinishida yozilgan
            # DAILY_ID ni o'qib, StocLog ni topamiz
            try:
                # Note dari "Savdo #3 dan qarz" → daily_id = 3
                daily_id = int(log.note.split('#')[1].split()[0])
                stoc_log = StocLog.objects.get(
                    customer=customer,
                    daily_id=daily_id
                )
                
                # Bu StocLog ning barcha item-larini olish
                items = stoc_log.items.all()
                
                for item in items:
                    # Har bir mahsulotga oid return ma'lumotini hisoblash
                    total_returned = ReturnLog.objects.filter(
                        customer=customer,
                        product=item.product,
                        created_at__gte=stoc_log.created_at
                    ).aggregate(total=Sum('quantity'))['total'] or 0
                    
                    remaining_qty = item.quantity - total_returned
                    
                    log_data["items"].append({
                        "id": item.id,
                        "product_id": item.product.id,
                        "name": item.product.name,
                        "barcode": item.product.barcode,
                        "qty_sold": item.quantity,
                        "qty_returned": total_returned,
                        "remaining_qty": remaining_qty,
                        "sale_price": float(item.price_at_time),
                        "purchase_price": float(item.purchase_price_at_time),
                    })
            except (ValueError, IndexError, StocLog.DoesNotExist):
                # Note formatı noto'g'ri yoki StocLog topilmasa
                pass
        
        data["history"].append(log_data)
    
    return Response(data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def pay_debtor_debt(request, customer_id):
    try:
        customer = get_object_or_404(Customer, id=customer_id)
        
        try:
            amount = float(request.data.get('amount', 0))
        except (ValueError, TypeError):
            return Response({"error": "Summa noto'g'ri formatda"}, status=400)

        if amount <= 0:
            return Response({"error": "Summa 0 dan katta bo'lishi kerak"}, status=400)

        current_debt = float(customer.total_debt)
        new_debt = current_debt - amount

        if new_debt <= 0:
            # DebtLog yaratamiz → signal Transaction ni o'zi yaratadi
            DebtLog.objects.create(
                customer=customer,
                amount=amount,
                type='pay',
                note="Qarz to'liq uzildi"
            )
            customer.delete()
            return Response({"status": "deleted", "message": "Qarz uzildi, mijoz o'chirildi"})
        else:
            customer.total_debt = new_debt
            customer.save()

            # DebtLog yaratamiz → signal Transaction ni o'zi yaratadi
            DebtLog.objects.create(
                customer=customer,
                amount=amount,
                type='pay'
            )

            return Response({
                "status": "success",
                "total_debt": customer.total_debt
            })

    except Exception as e:
        print(f"Server xatosi: {str(e)}")
        return Response({"error": str(e)}, status=500)
# ==============================================================QARZDORLAR TUGASHI========================================================================
# ==============================================================SUPERADMIN ===============================================================================
@api_view(['GET'])
@permission_classes([IsAdminUser]) # Faqat Superadmin ko'ra oladi
def get_all_users(request):
    users = User.objects.filter(is_superuser=False, seller_profile__isnull=True).order_by('-date_joined')
    serializer = UserSerializer(users, many=True)
    return Response(serializer.data)

@api_view(['PUT'])
def update_user(request, pk):
    user = User.objects.get(pk=pk)
    serializer = UserSerializer(user, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=400)

@api_view(['DELETE'])
def delete_user(request, pk):
    user = User.objects.get(pk=pk)
    user.delete()
    return Response(status=204)

@api_view(['POST'])
@permission_classes([IsAdminUser])
def super_admin_excel_upload(request):
    file = request.FILES.get('file')
    target_owner_id = request.data.get('owner_id')
    if not file or not target_owner_id:
        return Response({"error": "Fayl va Owner ID yuborilishi shart!"}, status=400)
    try:
        target_owner = User.objects.get(id=target_owner_id)
        df = pd.read_excel(file)
        required_columns = ['barcode', 'name', 'purchase_price', 'sale_price', 'category']
        for col in required_columns:
            if col not in df.columns:
                return Response({"error": f"Excelda '{col}' ustuni topilmadi!"}, status=400)
        with transaction.atomic():
            for index, row in df.iterrows():
                barcode = str(row['barcode']).strip()
                p_name = str(row['name']).strip()
                category_name = row.get('category')
                category_obj = None
                if category_name and str(category_name).strip():
                    category_obj, _ = Category.objects.get_or_create(
                        name=str(category_name).strip(),
                        owner=target_owner
                    )              
                product, created = Product.objects.update_or_create(
                    owner=target_owner,
                    barcode=barcode,
                    defaults={
                        'name': p_name,
                        'category': category_obj,
                        'purchase_price': row.get('purchase_price', 0),
                        'sale_price': row.get('sale_price', 0),
                    }
                )
                inventory, _ = AccessoryInventory.objects.get_or_create(product=product)
                qty = row.get('quantity', 0)
                inventory.quantity = int(qty) if pd.notnull(qty) else 0
                inventory.save()
        return Response({"message": f"{len(df)} ta mahsulot muvaffaqiyatli yuklandi!"}, status=201)
    except User.DoesNotExist:
        return Response({"error": "Bunday foydalanuvchi topilmadi!"}, status=404)
    except Exception as e:
        return Response({"error": f"Xatolik: {str(e)}"}, status=500)
    

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@transaction.atomic # Butun jarayon xavfsiz bo'lishi uchun
def owner_excel_upload(request):
    file = request.FILES.get('file')
    target_owner = request.user 
    if not file:
        return Response({"error": "Fayl topilmadi!"}, status=400)
    try:
        # Excelni o'qish
        df = pd.read_excel(file)
        
        # 1. Ustunlar mavjudligini tekshirish (Kategoriyani ham qo'shdik)
        required_columns = ['barcode', 'name', 'purchase_price', 'sale_price', 'category']
        for col in required_columns:
            if col not in df.columns:
                return Response({"error": f"Excelda '{col}' ustuni topilmadi!"}, status=400)

        count = 0
        for index, row in df.iterrows():
            # Ma'lumotlarni tozalash
            barcode = str(row['barcode']).strip()
            p_name = str(row['name']).strip()
            c_name = str(row.get('category', '')).strip() # Kategoriya nomi

            # 2. Kategoriyani topish yoki yaratish
            category_obj = None
            if c_name and c_name.lower() != 'nan': # Exceldagi bo'sh katak 'nan' bo'lib kelishi mumkin
                category_obj, _ = Category.objects.get_or_create(
                    name=c_name,
                    owner=target_owner
                )

            # 3. Mahsulotni yaratish yoki yangilash
            product, _ = Product.objects.update_or_create(
                owner=target_owner,
                barcode=barcode,
                defaults={
                    'name': p_name,
                    'category': category_obj, # Mana shu yerda bog'lanadi
                    'purchase_price': float(row.get('purchase_price', 0)),
                    'sale_price': float(row.get('sale_price', 0)),
                }
            )

            # 4. Inventarizatsiya
            inventory, _ = AccessoryInventory.objects.get_or_create(product=product)
            qty = row.get('quantity', 0)
            inventory.quantity = int(qty) if pd.notnull(qty) else 0
            inventory.save()
            count += 1

        return Response({"message": f"{count} ta mahsulot muvaffaqiyatli yuklandi!"}, status=201)

    except Exception as e:
        return Response({"error": f"Xatolik: {str(e)}"}, status=500)

from rest_framework.renderers import StaticHTMLRenderer, JSONRenderer
from rest_framework.decorators import renderer_classes
from django.views.decorators.csrf import csrf_exempt
@csrf_exempt
@api_view(["POST", "OPTIONS"])
@permission_classes([])
@authentication_classes([])
@renderer_classes([StaticHTMLRenderer, JSONRenderer])
# Vaqtincha hammani tekshiruvsiz o'tkazamiz
def generate_product_barcodes_pdf(request):
    if request.method == "OPTIONS":
        return Response(status=200)

    try:
        # 1. Ma'lumotlarni olish
        product_ids = request.data.get('product_ids', [])
        options = request.data.get('options', {})
        
        show_name = options.get('includeName', True)
        show_price = options.get('includePrice', True)
        show_barcode_text = options.get('includeBarcodeText', True)

        if product_ids:
            products = Product.objects.filter(id__in=product_ids).select_related('category')
        else:
            products = Product.objects.all()[:20]

        if not products.exists():
            return HttpResponse("Mahsulotlar topilmadi", status=404)

        # 2. PDF sozlamalari
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        
        x_start = 30
        margin_top = 30
        margin_bottom = 30
        
        # JORIY QATORNING TEPASI
        current_y = height - margin_top 
        
        columns = 4
        item_width = 140
        item_height = 110 # Har bir blok balandligi
        
        for index, product in enumerate(products):
            col_index = index % columns
            
            # Yangi qator boshlanishida pastga tushish va sahifa tekshiruvi
            if col_index == 0 and index > 0:
                current_y -= item_height
                
                # Agar keyingi qator sahifaga sig'masa - Yangi sahifa
                if current_y < margin_bottom + 100:
                    p.showPage()
                    current_y = height - margin_top
            
            # X koordinatasini hisoblash
            x_offset = x_start + (col_index * item_width)

            try:
                # 3. Barcode yaratish
                CODE128 = barcode.get_barcode_class('code128')
                bc_value = str(product.barcode) if product.barcode else "000000"
                
                writer = ImageWriter()
                # 'write_text' deb yozilishi shart
                options_bc = {
                    "module_height": 5.0, 
                    "text_distance": 3.5, 
                    "font_size": 8 if show_barcode_text else 0, 
                    "write_text": show_barcode_text,
                    "font_path" : FONT_REG
                }
                
                ean = CODE128(bc_value, writer=writer)
                bc_buffer = io.BytesIO()
                ean.write(bc_buffer, options=options_bc)
                bc_buffer.seek(0)
                img = PILImage.open(bc_buffer)

                # --- CHIZISH (current_y dan pastga qarab) ---
                
                # 1. Mahsulot nomi
                if show_name:
                    category_name = f"({product.category.name})" if product.category else ""
                    full_name = f"{product.name} {category_name}"
                    p.setFont("Montserrat-Bold", 9)
                    # Nomni qirqib olish (yoniga o'tib ketmasligi uchun)
                    p.drawString(x_offset, current_y - 15, full_name[:25])

                # 2. Barcode rasmi (Nomi bo'lsa ham bo'lmasa ham joyi aniq)
                p.drawInlineImage(img, x_offset, current_y - 70, width=120, height=50)

                # 3. Narxi
                if show_price:
                    p.setFont("Montserrat-Bold", 10)
                    price_text = f"Narxi: {round(product.sale_price):,} so'm".replace(',', ' ')
                    p.drawString(x_offset + 5, current_y - 75, price_text)

            except Exception as e:
                print(f"Shtrix kod chizishda xato ({product.name}): {e}")
                continue

        p.save()
        pdf = buffer.getvalue()
        buffer.close()
        
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Access-Control-Allow-Origin'] = '*'
        return response

    except Exception as global_e:
        print(f"GLOBAL XATO: {global_e}")
        return HttpResponse(f"Serverda xato: {str(global_e)}", status=500)
# ============================================================== SUPERADMIN TUGASHI   ====================================================================


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sales_history(request):
    try:
        user = request.user
        today = timezone.now().date()
        is_seller = hasattr(user, 'seller_profile')

        actual_owner = get_actual_owner(user)


        date_str = request.query_params.get('date')
        seller_id = request.query_params.get('seller_id')

        if is_seller:
            sales_query = StocLog.objects.filter(seller=user,created_at__date=today)
        else:
            sales_query = StocLog.objects.filter(owner=user)
            try:
                filter_date = timezone.datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else today
            except ValueError:
                filter_date = today
            sales_query = StocLog.objects.filter(owner=actual_owner,created_at__date=filter_date)  
            if seller_id:
                sales_query = sales_query.filter(seller_id=seller_id)

        # Savdolarni olish va bog'liqliklarni yuklash (Optimization)
        sales_query = sales_query.select_related('customer').prefetch_related('items__product').order_by('-created_at')
        serializer = StocLogSerializer(sales_query, many=True)

        # Keyingi ID ni hisoblash (Faqat bugun uchun)
        last_sale_today = StocLog.objects.filter(owner=actual_owner,created_at__date=today).only('daily_id').order_by('-daily_id').first()

        next_id = (last_sale_today.daily_id + 1) if last_sale_today else 1

        return Response({
            "sales": serializer.data,
            "next_daily_id": next_id,
            "is_owner": not is_seller,
            "current_filter_date": today if is_seller else (filter_date if 'filter_date' in locals() else today)
        })
    except Exception as e:
        return Response({"error": str(e)}, status=500)


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20  # Har safar 20 tadan ma'lumot chiqadi
    page_size_query_param = 'page_size'
    max_page_size = 100


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_sellers(request):
    sellers = User.objects.filter(seller_profile__owner=request.user)
    data = [{"id": s.id, "username": s.username} for s in sellers]
    return Response(data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def return_product(request):
    data = request.data
    sale_id = data.get('sale_id')
    customer_id = data.get('customer_id')
    method = data.get('payment_method', 'debt')
    items_data = data.get('items', [])

    try:
        with transaction.atomic():
            customer = Customer.objects.get(id=customer_id, owner=request.user) if customer_id else None
            
            for item in items_data:
                product = Product.objects.get(barcode=item['barcode'], owner=request.user)
                qty_to_return = int(item['quantity'])

                # 1. Savdo elementini topamiz (Lekin quantity-ni kamaytirmaymiz!)
                sale_item = StocLogItem.objects.get(stoc_log_id=sale_id, product=product)

                # 2. Haqiqiy qoldiqni tekshiramiz (Oldin qaytarilganlarni hisobga olgan holda)
                already_returned = ReturnLog.objects.filter(
                    original_sale_id=sale_id, 
                    product=product
                ).aggregate(total=Sum('quantity'))['total'] or 0
                
                remaining_in_sale = sale_item.quantity - already_returned

                if qty_to_return > remaining_in_sale:
                    raise Exception(f"Xato: Maksimal {remaining_in_sale} ta qaytarish mumkin!")

                # 3. Faqat ReturnLog yaratamiz
                # Signal (handle_return_log) avtomatik qarzni ayiradi va omborga qo'shadi
                amount_to_refund = Decimal(str(sale_item.price_at_time)) * qty_to_return
                
                ReturnLog.objects.create(
                    original_sale_id=sale_id,
                    product=product,
                    customer=customer,
                    quantity=qty_to_return,
                    amount_returned=amount_to_refund,
                    payment_method=method )
        if customer:
                customer.refresh_from_db()
                if customer.total_debt <= 0:
                    customer.delete() # Qarz 0 bo'lsa mijoz bazadan o'chadi
                    return Response({"status": "ok", "message": "Mahsulot qaytarildi va mijoz o'chirildi (qarz 0)"})

        return Response({"status": "ok", "message": "Mahsulot qaytarildi"})
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=400)



@api_view(['POST'])
@permission_classes([IsAuthenticated])
def select_plan(request):
    plan_id = request.data.get('plan_id')
    try:
        plan = Plan.objects.get(id=plan_id)
        sub, created = Subscription.objects.get_or_create(user=request.user)
        
        sub.plan = plan
        sub.is_paid = False  # Yangi plan tanlanganda to'lovni kutish holatiga o'tkazamiz
        # Agar yangi plan tanlasa, muddati o'zgarmaydi, faqat admin tasdiqlashi kerak bo'ladi
        sub.save()
        
        return Response({"message": f"{plan.name} planiga ariza qabul qilindi. Tasdiqlashni kuting."})
    except Plan.DoesNotExist:
        return Response({"error": "Plan topilmadi"}, status=404)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def extend_subscription(request):
    sub = Subscription.objects.get(user=request.user)
    sub.is_paid = False
    sub.save()
    return Response({"status": "Arizangiz qabul qilindi, tasdiqlashni kuting."})
   
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated,HasActiveSubscription])
def category_list(request):
    actual_owner = get_actual_owner(request.user)
    try:  
        if request.method == 'GET':
            if request.user.is_superuser:
                categories = Category.objects.all()
            else:
                categories = Category.objects.filter(owner=actual_owner)
            serializer = CategorySerializer(categories, many=True)
            return Response(serializer.data)

        elif request.method == 'POST':
            serializer = CategorySerializer(data=request.data)
            if serializer.is_valid():
                # 1. Default holatda egasi - hozirgi user
                owner = actual_owner

                # 2. Agar superuser bo'lsa va owner_id yuborgan bo'lsa
                if request.user.is_superuser and 'owner_id' in request.data:
                    try:
                        owner = User.objects.get(id=request.data['owner_id'])
                    except User.DoesNotExist:
                        return Response({"error": "Tanlangan foydalanuvchi topilmadi!"}, status=404)

                # 3. Kategoriya saqlanadi
                serializer.save(owner=owner)
                return Response(serializer.data, status=201)

            return Response(serializer.errors, status=400)
    except Exception as e:
            return Response({"error": str(e)}, status=500)

@api_view(['PUT','PATCH', 'DELETE'])
def category_detail(request, pk):
    try:
        category = Category.objects.get(pk=pk, owner=request.user)
    except Category.DoesNotExist:
        return Response({"error": 'Kategoriya topilmadi'},status=404)

    if request.method == 'PUT':
        serializer = CategorySerializer(category, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    elif request.method == 'DELETE':
        category.delete()
        return Response(status=204)


@api_view(['GET'])
@permission_classes([IsAdminUser]) # Faqat superadmin uchun
def get_all_subscriptions(request):
    subs = Subscription.objects.all().select_related('user', 'plan').order_by('-id')
    serializer = SubscriptionSerializer(subs, many=True)
    return Response(serializer.data)

@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def update_subscription_admin(request, pk):
    sub = get_object_or_404(Subscription, pk=pk)
    
    # partial=True bo'lishi shart, chunki React'dan hamma field kelmaydi
    serializer = SubscriptionSerializer(sub, data=request.data, partial=True)
    
    if serializer.is_valid():
        serializer.save() 
        return Response(serializer.data)
    return Response(serializer.errors, status=400)

class PlanViewSet(viewsets.ModelViewSet):
    queryset = Plan.objects.all()
    serializer_class = PlanSerializer

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            return [AllowAny()]
        return [IsAdminUser()]


class SellerViewSet(viewsets.ModelViewSet):
    serializer_class = SellerCreateSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Seller.objects.filter(owner=self.request.user).order_by('-id')

    def get_serializer_class(self):
        if self.action == 'create':
            return SellerCreateSerializer
        return SellerCreateSerializer
    
    def perform_destroy(self, instance):
        user = instance.user 
        instance.delete()
        user.delete()


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_subscription(request):
    actual_owner = get_actual_owner(request.user)
    sub, created = Subscription.objects.get_or_create(
        user=actual_owner,
        defaults={
            'trial_end': timezone.now() + timedelta(days=14), # Trial muddati
            'is_paid': False,
            'phone': 'Nomalum'
        }
    )
    data = SubscriptionSerializer(sub).data
    data["is_active_status"] = sub.is_active()
    return Response(data)



@api_view(['GET'])
@permission_classes([IsAdminUser])
def superadmin_dashboard_stats(request):
    now = timezone.now()
    last_30_days = now - timedelta(days=30)

    try:
        # 1. DO'KONLAR STATISTIKASI
        total_stores = User.objects.filter(is_superuser=False, seller_profile__isnull=True).count()
        active_stores = Subscription.objects.filter(trial_end__gt=now).count()
        new_stores_30d = User.objects.filter(is_superuser=False,seller_profile__isnull=True, date_joined__gte=last_30_days).count()
        
        expiring_soon = Subscription.objects.filter(
            trial_end__gt=now, 
            trial_end__lte=now + timedelta(days=5)
        ).count()

        # 2. MOLIYAVIY STATISTIKA - OBUNALARDAN KELGAN PULU
        total_profit = Subscription.objects.filter(is_paid=True).aggregate(
            total=Coalesce(Sum('plan__price', output_field=DF), 0, output_field=DF)
        )['total'] or 0

        # 3. GLOBAL SAVDO - StocLog.total_amount dan (to'liq summa)
        # XATO: StocLog.quantity yo'q! 
        # TO'G'RI: StocLog.total_amount ishlatamiz
        total_system_sales = StocLog.objects.all().aggregate(
            total=Coalesce(Sum('total_amount', output_field=DF), 0, output_field=DF)
        )['total'] or 0

        # 4. DO'KONLAR RO'YXATI
        stores_list = []
        users_queryset = User.objects.filter(is_superuser=False, seller_profile__isnull=True).order_by('-date_joined')
        
        for user in users_queryset:
            sub = Subscription.objects.filter(user=user).first()
            
            # Har bir userning aylanmasi - StocLog.total_amount dan
            user_sales = StocLog.objects.filter(
                owner=user
            ).aggregate(
                total=Coalesce(Sum('total_amount', output_field=DF), 0, output_field=DF)
            )['total'] or 0
            
            days_left = 0
            current_plan_price = 0
            expiry_date = None
            phone = "Kiritilmagan"
            
            if sub:
                phone = getattr(sub, 'phone', 'Kiritilmagan')
                if sub.trial_end:
                    days_left = max(0, (sub.trial_end - now).days)
                    expiry_date = sub.trial_end
                if sub.is_paid and sub.plan:
                    current_plan_price = sub.plan.price

            stores_list.append({
                "id": user.id,
                "username": user.username,
                "phone": phone,
                "total_sales": float(user_sales),
                "system_profit": float(current_plan_price),
                "days_left": days_left,
                "expiry_date": expiry_date,
                "date_joined": user.date_joined
            })

        return Response({
            "main_stats": {
                "total_profit": float(total_profit),
                "active_stores": active_stores,
                "total_stores": total_stores,
                "total_gmv": float(total_system_sales),
                "expiring_soon": expiring_soon,
            },
            "stores": stores_list,
            "cards": [
                {
                    "label": "Tizim Foydasi",
                    "value": f"{float(total_profit):,.0f} so'm",
                    "subValue": "Jami obunalar",
                    "icon": "trending-up",
                    "color": "emerald"
                },
                {
                    "label": "Aktiv Do'konlar",
                    "value": active_stores,
                    "subValue": f"+{new_stores_30d} yangi",
                    "icon": "store",
                    "color": "indigo"
                },
                {
                    "label": "Tizim GMV",
                    "value": f"{float(total_system_sales):,.0f} so'm",
                    "subValue": "Umumiy savdo",
                    "icon": "package",
                    "color": "amber"
                },
                {
                    "label": "Qarzdorlik",
                    "value": expiring_soon,
                    "subValue": "To'lov kutilmoqda",
                    "icon": "alert-circle",
                    "color": "red"
                }
            ]
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_expense(request):
    try:
        actual_owner = get_actual_owner(request.user)
        amount = float(request.data.get('amount', 0))
        note = request.data.get('note', '').strip()
 
        if amount <= 0:
            return Response({"error": "Summa 0 dan katta bo'lishi kerak"}, status=400)
        if not note:
            return Response({"error": "Izoh (note) majburiy"}, status=400)
 
        Transaction.objects.create(
            owner=actual_owner,
            amount=amount,
            type='expense',
            payment_method='cash',
            note=note
        )
        return Response({"status": "success", "message": f"{note} — {amount:,.0f} so'm chiqim qo'shildi"})
    except Exception as e:
        return Response({"error": str(e)}, status=500)
 
 
# ─── Kunlik chiqimlar ro'yxati ────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_expenses(request):
    try:
        actual_owner = get_actual_owner(request.user)
        date_str = request.query_params.get('date')
        try:
            filter_date = timezone.datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else timezone.now().date()
        except (ValueError, TypeError):
            filter_date = timezone.now().date()
 
        expenses = Transaction.objects.filter(
            owner=actual_owner,
            type='expense',
            created_at__date=filter_date
        ).order_by('-created_at')
 
        data = [
            {
                "id": e.id,
                "amount": e.amount,
                "note": getattr(e, 'note', ''),
                "date": e.created_at.strftime("%H:%M")
            }
            for e in expenses
        ]
        total = sum(float(e.amount) for e in expenses)
        return Response({"total": total, "expenses": data})
    except Exception as e:
        return Response({"error": str(e)}, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated,HasActiveSubscription])
def dashboard_stats(request):
    try:
        actual_owner = get_actual_owner(request.user)
 
        date_str = request.query_params.get('date')
        try:
            filter_date = timezone.datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else timezone.now().date()
        except ValueError:
            filter_date = timezone.now().date()
 
        # ── 1. SEYF — hamma vaqtdagi real naqd pul ──────────────────────────
        # Kirim turlarini va chiqim turlarini aniq ajratamiz
        seyf_qs = Transaction.objects.filter(
            owner=actual_owner,
            payment_method='cash'
        )
 
        seyf_kirim = seyf_qs.filter(
            type__in=['sale', 'customer_pay', 'income']
        ).aggregate(s=Coalesce(Sum('amount', output_field=DF), 0, output_field=DF))['s']
 
        seyf_chiqim = seyf_qs.filter(
            type__in=['supplier_pay', 'expense', 'return_sale']
        ).aggregate(s=Coalesce(Sum('amount', output_field=DF), 0, output_field=DF))['s']
 
        safe_balance = seyf_kirim - seyf_chiqim
 
        # ── 2 & 3. KUNLIK SAVDO ──────────────────────────────────────────────
        # Barcha kunlik transaksiyalar
        daily_tx = Transaction.objects.filter(
            owner=actual_owner,
            created_at__date=filter_date
        )
 
        # 2. Kunlik jami savdo = naqd + nasiya (sale type, hamma payment_method)
        daily_sales = daily_tx.filter(type='sale').aggregate(s=Coalesce(Sum('amount', output_field=DF), 0, output_field=DF))['s']

        daily_returns = daily_tx.filter(type='return_sale').aggregate(s=Coalesce(Sum('amount', output_field=DF), 0, output_field=DF))['s']

        daily_total_sales = daily_sales - daily_returns
 
        # 3. Kunlik naqd kassa = naqd savdo + bugungi nasiya to'lovlari
        daily_cash_sales = daily_tx.filter(
            type='sale', payment_method='cash'
        ).aggregate(
            s=Coalesce(Sum('amount', output_field=DF), 0, output_field=DF)
        )['s']
 
        daily_customer_payments = daily_tx.filter(
            type='customer_pay', payment_method='cash'
        ).aggregate(
            s=Coalesce(Sum('amount', output_field=DF), 0, output_field=DF)
        )['s']
 
        daily_cash_in = daily_cash_sales + daily_customer_payments
 
        # ── 4. SUPPLIER QARZI ────────────────────────────────────────────────
        # Jami: Supplier modelidagi total_debt_to_them (signal bilan yangilanib turadi)
        total_supplier_debt = Supplier.objects.filter(
            owner=actual_owner
        ).aggregate(
            s=Coalesce(Sum('total_debt_to_them', output_field=DF), 0, output_field=DF)
        )['s']
 
        # Bugungi yangi nasiya tovarlar (supplier dan nasiyaga olindi)
        # StocLog emas — SupplierLog da 'take' type, bugun
        daily_supplier_new_debt = SupplierLog.objects.filter(
            supplier__owner=actual_owner,
            type='take',
            created_at__date=filter_date
        ).aggregate(
            s=Coalesce(Sum('amount', output_field=DF), 0, output_field=DF)
        )['s']

        daily_supplier_return = SupplierLog.objects.filter(supplier__owner=actual_owner,type='return', created_at__date=filter_date
        ).aggregate(s=Coalesce(Sum('amount', output_field=DF), 0, output_field=DF))['s']

        # Bugun supplierga to'langan pul
        daily_supplier_pay = daily_tx.filter(type='supplier_pay').aggregate(
            s=Coalesce(Sum('amount', output_field=DF), 0, output_field=DF)
        )['s']
 
        # ── 5. QARZDORLAR (MIJOZLAR) ─────────────────────────────────────────
        # Jami: Customer modelidagi total_debt
        total_customer_debt = Customer.objects.filter(
            owner=actual_owner
        ).aggregate(
            s=Coalesce(Sum('total_debt', output_field=DF), 0, output_field=DF)
        )['s']
 
        # Bugungi yangi nasiya savdolar
        daily_new_debt = daily_tx.filter(
            type='sale', payment_method='debt'
        ).aggregate(
            s=Coalesce(Sum('amount', output_field=DF), 0, output_field=DF)
        )['s']
 
        # Bugun mijozlardan kelgan to'lovlar
        daily_debt_collected = daily_tx.filter(type='customer_pay').aggregate(
            s=Coalesce(Sum('amount', output_field=DF), 0, output_field=DF)
        )['s']
 
        # ── 6. KUNLIK CHIQIMLAR ──────────────────────────────────────────────
        daily_expenses = daily_tx.filter(type='expense').aggregate(
            s=Coalesce(Sum('amount', output_field=DF), 0, output_field=DF)
        )['s']
 
        # Kunlik chiqimlar ro'yxati (note bilan)
        expense_list = list(
            daily_tx.filter(type='expense')
            .values('id', 'amount', 'note', 'created_at')
            .order_by('-created_at')
        )
        for e in expense_list:
            e['created_at'] = e['created_at'].strftime("%H:%M")
 
        # ── 7. OMBOR QIYMATI (tan narxi bo'yicha) ───────────────────────────
        inventory_value = AccessoryInventory.objects.filter(
            product__owner=actual_owner
        ).aggregate(
            total=Coalesce(
                Sum(F('quantity') * F('product__purchase_price'), output_field=DF),
                0, output_field=DF
            )
        )['total']
 
        top_products = list(
            StocLogItem.objects.filter(
                product__owner=actual_owner, stoc_log__created_at__date=filter_date     # Aynan tanlangan kundagilari
            )
            .values('product__id', 'product__name','product__category__name')         # ID va Nomi bo'yicha guruhlaymiz
            .annotate(total_quantity=Sum('quantity'))       # Sotilgan miqdorini yig'amiz
            .order_by('-total_quantity')[:5]                # Eng ko'p sotilgan 5 tasini olamiz
        )
        # ── 8. KUNLIK TRANSAKSIYALAR (paginated) ────────────────────────────
        paginated_tx = Transaction.objects.filter(
            owner=actual_owner,
            created_at__date=filter_date
        ).order_by('-created_at')
 
        paginator = PageNumberPagination()
        paginator.page_size = 10
        result_page = paginator.paginate_queryset(paginated_tx, request)
        tx_serializer = TransactionSerializer(result_page, many=True)
 
        # ── JAVOB ────────────────────────────────────────────────────────────
        return Response({
            "filter_date": filter_date,
            "stats": {
                # 1. Seyf — hamma vaqt naqd pul balansi
                "safe_balance": safe_balance,
 
                # 2. Kunlik jami savdo (naqd + nasiya)
                "daily_total_sales": daily_total_sales,
 
                # 3. Kunlik naqd kassa (naqd savdo + bugungi nasiya to'lovlar)
                "daily_cash_in": daily_cash_in,
                "daily_cash_sales": daily_cash_sales,          # faqat naqd savdo
                "daily_customer_payments": daily_customer_payments,  # nasiya to'lovlari
 
                # 4. Supplier (ta'minotchilar)
                "total_supplier_debt": total_supplier_debt,    # jami qarz
                "daily_supplier_new_debt": daily_supplier_new_debt,  # bugun nasiya olindi
                "daily_supplier_return": daily_supplier_return,
                "daily_supplier_pay": daily_supplier_pay,      # bugun to'landi
 
                # 5. Qarzdorlar (mijozlar)
                "total_customer_debt": total_customer_debt,    # jami nasiya
                "daily_new_debt": daily_new_debt,              # bugun yangi nasiya
                "daily_debt_collected": daily_debt_collected,  # bugun to'lovi
 
                # 6. Kunlik chiqimlar
                "daily_expenses": daily_expenses,
                "expense_list": expense_list,
 
                # 7. Ombor qiymati
                "inventory_value": inventory_value,

                "top_products": top_products,
            },
            "transactions": tx_serializer.data,
            "pagination": {
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "count": paginator.page.paginator.count,
                "total_pages": paginator.page.paginator.num_pages,
                "current_page": int(request.query_params.get('page', 1))
            }
        })
 
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)
    


@api_view(['GET'])
def get_business_analytics(request):
    user = request.user
    today = timezone.now().date()

    # 1. Tan narxi bo'yicha ombordagi tovarlar qiymati
    total_inventory_value = AccessoryInventory.objects.filter(
        product__owner=user
    ).aggregate(
        total=Sum(F('quantity') * F('product__purchase_price'))
    )['total'] or 0

    # 2. Bugungi savdo va sof foyda (StocLog orqali)
    sales_today = StocLog.objects.filter(product__owner=user, created_at__date=today)
    
    total_revenue = sum(s.quantity * s.price_at_time for s in sales_today)
    # Tan narxi (purchase_price_at_time ishlatish shart!)
    total_cost = sum(s.quantity * (s.purchase_price_at_time or 0) for s in sales_today)
    net_profit = total_revenue - total_cost

    # 3. Kassa holati (Transaction orqali)
    # Bugun kirgan jami naqd pul
    cash_in = Transaction.objects.filter(
        owner=user, 
        created_at__date=today, 
        type__in=['sale', 'customer_pay']
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    # 4. Qarzlar (Customer va Supplier modellaridagi maydonlardan olish osonroq)
    total_customer_debts = Customer.objects.filter(owner=user).aggregate(Sum('total_debt'))['total_debt__sum'] or 0

    return Response({
        "today": today,
        "inventory_value": total_inventory_value,
        "today_revenue": total_revenue,
        "today_net_profit": net_profit,
        "today_cash_collected": cash_in, # Bugun qo'lga tekkan naqd pul
        "total_customer_debts": total_customer_debts
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def export_full_report_excel(request):
    user = request.user
    wb = openpyxl.Workbook()
    
    # 1-Varaq: Ombor Qoldig'i
    ws1 = wb.active
    ws1.title = "Ombor Qoldig'i"
    headers1 = ['Mahsulot Nomi', 'Barkod', 'Kelgan Narxi', 'Sotuv Narxi', 'Qoldiq', 'Jami Tan Narxi']
    ws1.append(headers1)
    
    # Headerlarni qalin qilish
    for cell in ws1[1]:
        cell.font = Font(bold=True)

    products = Product.objects.filter(owner=user)
    for p in products:
        stock = getattr(p.accessoryinventory, 'quantity', 0)
        ws1.append([
            p.name, 
            p.barcode, 
            p.purchase_price, 
            p.sale_price, 
            stock,
            (p.purchase_price * stock) # Omborning umumiy qiymati
        ])

    # 2-Varaq: Bugungi Savdolar
    ws2 = wb.create_sheet(title="Bugungi Savdolar")
    headers2 = ['Vaqt', 'Mahsulot', 'Miqdor', 'Sotilgan Narx', 'To`lov Usuli']
    ws2.append(headers2)
    
    today_sales = StocLog.objects.filter(product__owner=user, created_at__date=timezone.now().date())
    for sale in today_sales:
        ws2.append([
            sale.created_at.strftime("%H:%M"),
            sale.product.name,
            sale.quantity,
            sale.price_at_time,
            sale.payment_method
        ])

    # Faylni javob sifatida yuborish
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="hisobot_{user.username}.xlsx"'
    wb.save(response)
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def customer_history(request, customer_id):
    try:
        customer = Customer.objects.get(id=customer_id, owner=request.user)
    except Customer.DoesNotExist:
        return Response({"error": "Mijoz topilmadi"}, status=404)

    # 1. Qarz olish va to'lash tarixi
    debts = DebtLog.objects.filter(customer=customer).order_by('-created_at')
    debt_serializer = DebtLogSerializer(debts, many=True)

    # 2. Vozvratlar tarixi (agar mijozga bog'langan bo'lsa)
    returns = ReturnLog.objects.filter(customer_id=customer_id).order_by('-created_at')
    return_serializer = ReturnLogSerializer(returns, many=True)

    # 3. Mijozning umumiy statistikasi
    stats = {
        "full_name": customer.full_name,
        "phone": customer.phone,
        "total_debt": customer.total_debt,
        "last_visit": debts.first().created_at if debts.exists() else None
    }

    return Response({
        "stats": stats,
        "debt_history": debt_serializer.data,
        "return_history": return_serializer.data
    })