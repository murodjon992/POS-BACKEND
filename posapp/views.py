from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum,F,Count,DecimalField,ExpressionWrapper
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view,permission_classes,authentication_classes
from urllib3.filepost import writer
from rest_framework.pagination import PageNumberPagination
from .permissions import HasActiveSubscription
from django.db import transaction
from decimal import Decimal
from .models import Product, AccessoryInventory, StocLog, Customer,DebtLog,Subscription,Plan,Category,ReturnLog
from .serializers import ProductSerializer, InventorySerializer,NasiyaSaleSerializer,CustomerSerializer,DailySummarySerializer,UserSerializer,CategorySerializer,SubscriptionSerializer,PlanSerializer,StocLogSerializer,ReturnLogSerializer
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
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import io
import random
import os
import barcode
from django.conf import settings
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from telegram_bot.bot import send_telegram_otp

# Font fayllari yo'lini ko'rsatamiz
FONT_REG = os.path.join(settings.BASE_DIR, 'static', 'fonts', 'Montserrat-Regular.ttf')
FONT_BOLD = os.path.join(settings.BASE_DIR, 'static', 'fonts', 'Montserrat-Bold.ttf')

# Fontlarni ro'yxatdan o'tkazamiz
pdfmetrics.registerFont(TTFont('Montserrat', FONT_REG))
pdfmetrics.registerFont(TTFont('Montserrat-Bold', FONT_BOLD))




@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    username = request.data.get("username","").strip()
    phone = request.data.get("phone","").strip()
    password = request.data.get("password","")

    if not username or not password or not phone:
        return Response({"error": "Barcha maydonlarni to'ldiring"}, status=400)

    if User.objects.filter(username=username).exists():
        return Response({"error": "Bunday login mavjud"}, status=400)

    if Subscription.objects.filter(phone=phone).exists():
        return Response({"error": "Bu telefon raqami allaqachon ro'yxatdan o'tgan"}, status=400)
    try:
        with transaction.atomic():  # Hammasi bajariladi yoki hech biri bajarilmaydi
            user = User.objects.create_user(username=username, password=password)

            # 7 kunlik bepul sinov muddati bilan obuna yaratish
            trial_limit = timezone.now() + timedelta(days=7)
            Subscription.objects.create(
                user=user,
                phone=phone,
                trial_end=trial_limit,
                is_paid=False  # Dastlab to'lanmagan, lekin trial_end borligi uchun ishlaydi
            )

            token = Token.objects.create(user=user)

        return Response({
            "token": token.key,
            "username": user.username,
            'days_left': 7,
            "message": "Ro'yxatdan muvaffaqqiyatli o'tdingiz. 7 kunlik bepul sinov muddati faollashtirildi!"
        }, status=201)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(['POST'])
def login(request):
    username = request.data.get("username")
    password = request.data.get("password")

    # 1. Avvalo username bazada borligini tekshiramiz
    try:
        user_exists = User.objects.get(username=username)
    except User.DoesNotExist:
        return Response({"error": "Bunday foydalanuvchi nomi mavjud emas"}, status=404)

    # 2. Endi parolni tekshiramiz
    user = authenticate(username=username, password=password)

    if user is None:
        # Agar username bor bo'lsa-yu, authenticate None qaytarsa - demak parol xato
        return Response({"error": "Parol noto'g'ri kiritildi"}, status=400)

    # 3. Muvaffaqiyatli login
    token, _ = Token.objects.get_or_create(user=user)

    return Response({
        "token": token.key,
        "user": {
            "id": user.id,
            "username": user.username,
            "is_superuser": user.is_superuser,
        }
    })




@api_view(['POST'])
@permission_classes([IsAdminUser])  # Faqat superadmin uchun
def super_admin_excel_upload(request):
        file = request.FILES.get('file')
        # Qaysi do'kon (owner) uchun yuklanayotganini aniqlaymiz
        target_owner_id = request.data.get('owner_id')

        if not file or not target_owner_id:
            return Response({"error": "Fayl va Owner ID yuborilishi shart!"}, status=400)

        try:
            target_owner = User.objects.get(id=target_owner_id)
            df = pd.read_excel(file)

            # Tranzaksiyani boshlaymiz: Xato bo'lsa bazaga hech narsa yozilmaydi
            with transaction.atomic():
                for index, row in df.iterrows():
                    category_name = row.get('category')
                    category_obj = None

                    if category_name:
                        # MUHIM: Faqat shu ownerga tegishli kategoriyani qidiramiz yoki yaratamiz
                        category_obj, _ = Category.objects.get_or_create(
                            name=category_name,
                            owner=target_owner  # Bu yerda ownerni ham filtrga qo'shdik
                        )

                    # Product yaratish yoki yangilash
                    product, created = Product.objects.update_or_create(
                        owner=target_owner,
                        barcode=str(row['barcode']),
                        defaults={
                            'name': row['name'],
                            'category': category_obj,
                            'purchase_price': row['purchase_price'],
                            'sale_price': row['sale_price'],
                        }
                    )

                    # 3. Inventoryni yangilaymiz yoki yaratamiz
                    # Excelda 'quantity' ustuni bo'lishi kerak
                    inventory, _ = AccessoryInventory.objects.get_or_create(product=product)
                    inventory.quantity = row.get('quantity', 0)
                    inventory.save()

            return Response({"message": f"{len(df)} ta mahsulot muvaffaqiyatli yuklandi!"}, status=201)

        except User.DoesNotExist:
            return Response({"error": "Bunday foydalanuvchi (owner) topilmadi!"}, status=404)
        except Exception as e:
            return Response({"error": f"Xatolik yuz berdi: {str(e)}"}, status=500)

@api_view(["GET"])
@permission_classes([HasActiveSubscription])
def get_product_by_barcode(request, barcode):
    try:
        product = Product.objects.get(barcode=barcode,owner=request.user)

        data = {
            "id": product.id,
            "name": product.name,
            "price": product.sale_price,
        }

        return Response(data)

    except Product.DoesNotExist:
        return Response({"error": "Product not found"})

@api_view(["POST"])
@permission_classes([HasActiveSubscription])
def sell_product(request):
    items = request.data.get("items", [])
    method = request.data.get("payment_method", "cash")
    customer_id = request.data.get("customer_id")

    warnings = []

    try:
        with transaction.atomic():
            for item in items:
                product = Product.objects.get(
                    barcode=item['barcode'],
                    owner=request.user
                )

                qty = int(item['quantity'])
                inventory = AccessoryInventory.objects.get(product=product)

                if inventory.quantity < qty:
                    return Response(
                        {"error": f"{product.name} yetarli emas!"},
                        status=400
                    )

                inventory.quantity -= qty
                inventory.save()

                if inventory.quantity <= 0:
                    warnings.append(f"{product.name} TUGADI!")
                elif inventory.quantity <= 10:
                    warnings.append(f"{product.name} kam qoldi!")

                StocLog.objects.create(
                    product=product,
                    quantity=qty,
                    price_at_time=product.sale_price,
                    payment_method=method,
                    note="Oddiy sotuv"
                )

        return Response({
            "status": "success",
            "warnings": warnings
        })

    except Exception as e:
        return Response({"error": str(e)}, status=500)

@api_view(["POST"])
@permission_classes([IsAuthenticated,HasActiveSubscription])
def add_stock(request):
    barcode = request.data.get("barcode")
    quantity = int(request.data.get("quantity"))

    product = Product.objects.get(barcode=barcode, owner=request.user)

    inventory, created = AccessoryInventory.objects.get_or_create(
        product=product
    )

    inventory.quantity += quantity
    inventory.save()

    StocLog.objects.create(
        product=product,
        quantity=quantity,
    )

    return Response({"status": "success"})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def product_search(request):
    query = request.GET.get("q", "").strip()

    products = Product.objects.filter(
        Q(name__icontains=query) |
        Q(barcode__icontains=query),
        owner=request.user
    ).order_by('name')[:20]
    # Agar topilmasa, error emas, bo'sh list [] qaytaramiz
    serializer = ProductSerializer(products, many=True)
    return Response(serializer.data)

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20  # Har safar 20 tadan ma'lumot chiqadi
    page_size_query_param = 'page_size'
    max_page_size = 100


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

@api_view(['GET'])
@permission_classes([IsAdminUser]) # Faqat Superadmin ko'ra oladi
def get_all_users(request):
    users = User.objects.all().order_by('-date_joined')
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


@api_view(["POST"])
@permission_classes([IsAuthenticated,HasActiveSubscription])
def nasiya_sale(request):
    serializer = NasiyaSaleSerializer(data=request.data)
    if serializer.is_valid():
        data = serializer.validated_data
        customer_name = data["customer_name"]
        customer_phone = data["customer_phone"]
        items = data["items"]
        total_bill = Decimal('0')
        purchased_items_list = []
        customer, _ = Customer.objects.get_or_create(
            owner=request.user,
            name=customer_name,
            phone=customer_phone
        )
        for item in items:
            product = Product.objects.get(
                barcode=item['barcode'],
                owner=request.user
            )
            qty = int(item['quantity'])
            inventory = AccessoryInventory.objects.get(product=product)

            if inventory.quantity < qty:
                return Response({"error": f"Kechirasiz {inventory.product.name} Yetarli emas"}, status=400)
            inventory.quantity -= qty
            inventory.save()


            total_bill += product.sale_price * qty
            purchased_items_list.append(f"{product.name} - {qty}ta")

            StocLog.objects.create(
                product=product,
                quantity=qty,
                price_at_time=product.sale_price,
                payment_method="debt"
            )

        note_text = ", ".join(purchased_items_list)

        customer.total_debt += total_bill
        customer.save()

        DebtLog.objects.create(
            customer=customer,
            amount=total_bill,
            type='borrow',
            note=note_text
        )
        return Response({"status": "ok"})

@api_view(["POST"])
@permission_classes([IsAuthenticated,HasActiveSubscription])
@transaction.atomic
def return_product(request):
    items = request.data.get('items', [])
    method = request.data.get('payment_method') # 'cash' yoki 'debt'
    customer_id = request.data.get('customer_id', None) # Nasiya bo'lsa kerak bo'ladi

    if not items or not method:
        return Response({"error": "Ma'lumotlar to'liq emas"}, status=400)

    for item in items:
        product = Product.objects.get(barcode=item['barcode'], owner=request.user)
        qty = int(item['quantity'])
        return_amount = product.sale_price * qty # Yoki oxirgi sotuv narxi

        # 1. Omborga qaytarish
        inv = AccessoryInventory.objects.get(product=product)
        inv.quantity += qty
        inv.save()

        # 2. ReturnLog yaratish
        ReturnLog.objects.create(
            product=product,
            quantity=qty,
            amount_returned=return_amount,
            payment_method=method, # Foydalanuvchi tanlagan metod
            original_sale=None # Endi bunga bog'lash shart emas
        )

        # 3. Agar Nasiya tanlangan bo'lsa, mijoz qarzini kamaytirish
        if method == 'debt' and customer_id:
            customer = Customer.objects.get(id=customer_id)
            customer.total_debt -= return_amount
            customer.save()

            # Tarixda qolishi uchun
            DebtLog.objects.create(
                customer=customer,
                amount=return_amount,
                type='pay',
                note=f"VOZVRAT: {product.name} ({qty} ta)"
            )

    return Response({"status": "ok", "message": "Qaytarish muvaffaqiyatli yakunlandi"})

@api_view(["GET"])
@permission_classes([HasActiveSubscription,IsAuthenticated])
def get_debtors(request):
    # Faqat qarzi bor mijozlarni chiqaramiz
    debtors = Customer.objects.filter(owner=request.user, total_debt__gt=0).order_by('-total_debt')
    # Bu yerda CustomerSerializer ishlatiladi
    serializer = CustomerSerializer(debtors, many=True)
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([HasActiveSubscription,IsAuthenticated])
def pay_debt(request):
    customer_id = request.data.get("customer_id")
    try:
        amount = Decimal(str(request.data.get("amount", 0)))
    except (ValueError, TypeError):
        return Response({"error": "Summa noto'g'ri kiritildi"}, status=400)

    if not customer_id or amount <= 0:
        return Response({"error": "Noto'g'ri ma'lumot yuborildi"}, status=400)

    try:
        with transaction.atomic():
            customer = Customer.objects.get(id=customer_id,owner=request.user)

            # Qarzni kamaytiramiz
            customer.total_debt -= amount
            customer.save()

            # Tarixda qolishi uchun DebtLog yaratamiz
            DebtLog.objects.create(
                customer=customer,
                amount=amount,
                type='pay',
                note="Qarz qaytarildi (to'lov)"
            )

            return Response({
                "message": "To'lov qabul qilindi",
                "remaining_debt": customer.total_debt
            })
    except Customer.DoesNotExist:
        return Response({"error": "Mijoz topilmadi"}, status=404)



@api_view(['GET'])
@permission_classes([IsAuthenticated])
def daily_summary(request):
    today = timezone.now().date()
    owner = request.user

    # 1. Bugungi barcha sotuvlar (Naqd va Nasiya)
    sales_qs = StocLog.objects.filter(product__owner=owner, created_at__date=today)
    total_sales_qty = sales_qs.aggregate(Sum('quantity'))['quantity__sum'] or 0
    total_sales_types = sales_qs.aggregate(Count('product', distinct=True))['product__count'] or 0

    # Bugungi naqd sotuv (Vozvrat ayirilmagan hali)
    cash_sales_total = sum(float(s.quantity * s.price_at_time) for s in sales_qs.filter(payment_method='cash'))
    # Bugungi nasiya sotuv (Vozvrat ayirilmagan)
    debt_sales_total = sum(float(s.quantity * s.price_at_time) for s in sales_qs.filter(payment_method='debt'))

    # 2. Bugungi qaytarilgan tovarlar (Refunds)
    returns_qs = ReturnLog.objects.filter(product__owner=owner, created_at__date=today)
    cash_returns = float(
        returns_qs.filter(payment_method='cash').aggregate(Sum('amount_returned'))['amount_returned__sum'] or 0)
    debt_returns = float(
        returns_qs.filter(payment_method='debt').aggregate(Sum('amount_returned'))['amount_returned__sum'] or 0)

    total_returned_qty = returns_qs.aggregate(Sum('quantity'))['quantity__sum'] or 0
    total_returned_types = returns_qs.aggregate(Count('product', distinct=True))['product__count'] or 0

    # 3. Bugun mijozlar olib kelgan REAL NAQD PUL (Qarz to'lovi)
    # MUHIM: Faqat "VOZVRAT" bo'lmagan to'lovlarni olamiz
    real_payments = float(DebtLog.objects.filter(
        customer__owner=owner,
        type='pay',
        created_at__date=today
    ).exclude(note__icontains="VOZVRAT").aggregate(Sum('amount'))['amount__sum'] or 0)

    # --- HISOB-KITOB ---

    # KASSADAGI NAQD PUL: (Bugungi naqd savdo - qaytarilgan naqd tovar) + Mijoz olib kelgan qarz puli
    final_cash = (cash_sales_total - cash_returns) + real_payments

    # NASIYA BALANSI: (Bugun berilgan qarz - Bugun qaytarilgan nasiya tovar) - Mijoz olib kelgan qarz puli
    final_debt = (debt_sales_total - debt_returns) - real_payments

    # UMUMIY SAVDO (Aylanma): Jami sotuv - Jami qaytarish
    grand_total = (cash_sales_total + debt_sales_total) - (cash_returns + debt_returns)

    # Necha turdagi mahsulot sotildi (masalan: Olma, Non, Choy = 3 tur)
    items_types_count = total_sales_types - total_returned_types
    # Necha turdagi mahsulotdan qancha dona sotildi (masalan: Olma 2ta, Non 3ta, Choy 4ta = 9 ta)
    total_items_quantity = total_sales_qty - total_returned_qty

    return Response({
        "date": today,
        "grand_total": grand_total,
        "items_types_count": items_types_count,
        "total_items_quantity": total_items_quantity,
        "details": {
            "cash": final_cash,
            "debt": final_debt,
            "cash_sales": cash_sales_total - cash_returns,
            "debt_sales": debt_sales_total - debt_returns,
            "received_payments": real_payments
        }
    })

@api_view(["POST"])
@permission_classes([AllowAny])
def select_plan(request):
    user = request.user
    plan_id = request.data.get("plan_id")  # Mobile'dan plan_id bo'lib keladi

    if not plan_id:
        return Response({"error": "Plan ID yuborilmadi"}, status=400)
    try:
        plan_obj = Plan.objects.get(id=plan_id)
        # Foydalanuvchining obunasini olamiz (yoki yaratamiz)
        sub, created = Subscription.objects.get_or_create(user=user)

        sub.plan = plan_obj

        # Agar obuna muddati tugagan bo'lsa yoki yangi bo'lsa is_paid ni False qilamiz
        if not sub.is_active():
            sub.is_paid = False

        sub.save()
        return Response({
            "message": "Tarif muvaffaqiyatli tanlandi. To'lovni amalga oshiring, so'ng admin tasdiqlaydi",
            "plan_name": plan_obj.name
        }, status=200)
    except Plan.DoesNotExist:
        return Response({"error": "Tarif topilmadi"}, status=404)
    except Exception as e:
        return Response({"error": str(e)}, status=500)

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


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def product_list_create(request):
    if request.method == 'GET':
        # 1. Querysetni olish (select_related tezlik uchun)
        products = Product.objects.select_related('category', 'owner').all().order_by('-id')

        # User filtratsiyasi
        if not request.user.is_superuser:
            products = products.filter(owner=request.user)

        # Qidiruv
        search = request.query_params.get('search', None)
        if search:
            products = products.filter(name__icontains=search) | products.filter(barcode__icontains=search)

        category_id = request.query_params.get('category', None)
        if category_id:
            products = products.filter(category_id=category_id)

        # 2. PAGINATIONNI QAT'IY ISHLATISH
        paginator = PageNumberPagination()
        paginator.page_size = 20  # settings.py ga ishonmasdan, shu yerda belgilaymiz
        
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
            serializer.save(owner=request.user)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


        
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


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def category_list(request):
    if request.method == 'GET':
        if request.user.is_superuser:
            categories = Category.objects.all()
        else:
            categories = Category.objects.filter(owner=request.user)
        serializer = CategorySerializer(categories, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = CategorySerializer(data=request.data)
        if serializer.is_valid():
            # 1. Default holatda egasi - hozirgi user
            owner = request.user

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



@api_view(['PUT','PATCH', 'DELETE'])
def category_detail(request, pk):
    try:
        category = Category.objects.get(pk=pk)
    except Category.DoesNotExist:
        return Response(status=404)

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
    try:
        sub = Subscription.objects.get(pk=pk)
    except Subscription.DoesNotExist:
        return Response({"error": "Obuna topilmadi"}, status=404)

    # Kelayotgan yangi status
    new_is_paid = request.data.get('is_paid')

    # FAQAT STATUS O'ZGARSA ISHLAYDI
    if new_is_paid is not None and new_is_paid != sub.is_paid:
        if new_is_paid is True:
            # 1. To'lov yoqilganda: Hozirgi vaqtdan boshlab Plan kunini qo'shamiz
            days = sub.plan.duration_days if sub.plan else 30
            sub.trial_end = timezone.now() + timedelta(days=days)
            sub.is_paid = True
        else:
            # 2. To'lov o'chirilganda: Uni yana Trial holatiga qaytaramiz
            # Masalan, ro'yxatdan o'tgan kundan boshlab 14 kunlik muddat beramiz
            sub.trial_end = sub.start_date + timedelta(days=7)
            sub.is_paid = False

        sub.save()

    # Boshqa maydonlarni ham yangilash (masalan, plan o'zgarsa)
    serializer = SubscriptionSerializer(sub, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)

    return Response(serializer.errors, status=400)

@api_view(['GET'])
@permission_classes([AllowAny])
def get_plans(request):
    plans = Plan.objects.all()
    serializer = PlanSerializer(plans, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_subscription(request):
    sub, created = Subscription.objects.get_or_create(
        user=request.user,
        defaults={
            'trial_end': timezone.now() + timedelta(days=7), # Trial muddati
            'is_paid': False,
            'phone':'Nomalum'
        }
    )

    data = SubscriptionSerializer(sub).data
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAdminUser]) # Faqat superadmin va staff kiradi
def superadmin_dashboard_stats(request):
    # 1. Vaqt oralig'ini belgilaymiz (masalan, oxirgi 30 kun)
    last_30_days = timezone.now() - timedelta(days=30)

    # 2. Umumiy foydalanuvchilar (Do'konlar)
    total_stores = User.objects.filter(is_superuser=False).count()
    new_stores_30d = User.objects.filter(is_superuser=False, date_joined__gte=last_30_days).count()

    # 3. Obunalar statistikasi
    active_subscriptions = Subscription.objects.filter(trial_end__gt=timezone.now()).count()
    total_paid_amount = Subscription.objects.filter(is_paid=True).aggregate(
        total=Sum('plan__price') # Agar planda price bo'lsa
    )['total'] or 0

    # 4. Tizimdagi jami savdo (Barcha do'konlar bo'yicha StocLog orqali)
    total_system_sales = StocLog.objects.filter().aggregate(
        total=Sum(F('quantity') * F('price_at_time'))
    )['total'] or 0

    # 5. Jami mahsulotlar soni
    total_products = Product.objects.count()

    # 6. Oxirgi 5 ta qo'shilgan do'kon
    recent_stores = User.objects.filter(is_superuser=False).order_by('-date_joined')[:5].values(
        'id', 'username', 'email', 'date_joined'
    )

    return Response({
        "main_stats": [
            {
                "label": "Jami Do'konlar",
                "value": total_stores,
                "subValue": f"+{new_stores_30d} yangi (30 kun)",
                "icon": "users",
                "color": "blue"
            },
            {
                "label": "Faol Obunalar",
                "value": active_subscriptions,
                "subValue": f"Tushum: {total_paid_amount:,} so'm",
                "icon": "credit-card",
                "color": "green"
            },
            {
                "label": "Umumiy Savdo (GMV)",
                "value": f"{total_system_sales:,.0f} so'm",
                "subValue": "Barcha do'konlar bo'yicha",
                "icon": "trending-up",
                "color": "purple"
            },
            {
                "label": "Tizimdagi Tovar",
                "value": total_products,
                "subValue": "Jami SKU soni",
                "icon": "package",
                "color": "orange"
            }
        ],
        "recent_stores": list(recent_stores)
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated,HasActiveSubscription])
def dashboard_stats(request):
    user = request.user
    today = timezone.now().date()

    # --- SUPERADMIN ---
    if user.is_superuser:
        total_stores = User.objects.filter(is_superuser=False).count()
        total_products = Product.objects.count()
        # Jami tizimdagi barcha savdolar summasi
        total_revenue = StocLog.objects.filter().aggregate(
            total=Sum(F('quantity') * F('price_at_time'))
        )['total'] or 0

        return Response({
            "role": "superadmin",
            "stats": [
                {"label": "Jami Do'konlar", "value": total_stores, "icon": "users"},
                {"label": "Jami Mahsulotlar", "value": total_products, "icon": "package"},
                {"label": "Umumiy Tushum", "value": f"{total_revenue:,.0f} so'm", "icon": "dollar"},
            ]
        })

    # --- OWNER (DO'KON EGASI) ---
    else:
        # 1. O'z mahsulotlari soni
        my_products_count = Product.objects.filter(owner=user).count()

        # 2. Bugungi savdo summasi (StocLog orqali)
        # MUHIM: product__owner ishlatamiz, chunki StocLog-da owner maydoni yo'q
        my_today_sales = StocLog.objects.filter(
            product__owner=user,
            created_at__date=today
        ).aggregate(
            total=Sum(F('quantity') * F('price_at_time'))
        )['total'] or 0

        # 3. Kam qolgan tovarlar (AccessoryInventory orqali)
        low_stock = Product.objects.filter(
            owner=user,
            accessoryinventory__quantity__lt=5
        ).count()

        return Response({
            "role": "owner",
            "stats": [
                {"label": "Mahsulotlarim", "value": my_products_count, "icon": "package"},
                {"label": "Bugungi Savdo", "value": f"{my_today_sales:,.0f} so'm", "icon": "trending-up"},
                {"label": "Kam qolgan tovarlar", "value": low_stock, "icon": "alert"},
            ]
        })


@api_view(['GET'])
def get_business_analytics(request):
    user = request.user
    today = timezone.now().date()

    # 1. OMBORDAGI TOVARLARNING HOZIRGI QIYMATI (Kelgan narxida)
    # Bu doimiy qoldiqni ko'rsatadi (700.000 - 100.000 - 50.000 = 550.000 kabi)
    total_inventory_value = AccessoryInventory.objects.filter(
        product__owner=user
    ).aggregate(
        total=Sum(F('quantity') * F('product__purchase_price'), output_field=DecimalField())
    )['total'] or 0

    # 2. BUGUNGI SAVDOLAR (StocLog)
    sales_today = StocLog.objects.filter(product__owner=user, created_at__date=today)

    # JAMI TUSHUM: Sotilgan narxlari yig'indisi (150.000 + 70.000 = 220.000)
    grand_total_revenue = sales_today.aggregate(
        total=Sum(F('quantity') * F('price_at_time'), output_field=DecimalField())
    )['total'] or 0

    # SOTILGAN TOVARLARNING TAN NARXI (Ombordan ayirilishi kerak bo'lgan summa: 100.000 + 50.000 = 150.000)
    total_cost_of_sales = sales_today.aggregate(
        total=Sum(F('quantity') * F('product__purchase_price'), output_field=DecimalField())
    )['total'] or 0

    # 3. SOF FOYDA (Tushum - Sotilgan tovarning kelgan narxi)
    # (220.000 - 150.000 = 70.000)
    net_profit = grand_total_revenue - total_cost_of_sales

    # 4. JAMI QARZLAR (DebtLog)
    # Faqat mijozlarning qaytarilmagan qarzlarini hisoblaymiz
    debt_data = DebtLog.objects.filter(customer__owner=user).aggregate(
        total_borrow=Sum('amount', filter=Q(type='borrow')),  # Berilgan qarz
        total_pay=Sum('amount', filter=Q(type='pay'))  # Qaytarilgan pul
    )

    total_debts = (debt_data['total_borrow'] or 0) - (debt_data['total_pay'] or 0)

    return Response({
        "date": today,
        "total_inventory_value": float(total_inventory_value),  # Ombordagi qoldiq (Kelgan narxda)
        "total_revenue": float(grand_total_revenue),  # Jami tushum (Sotilgan narxda)
        "net_profit": float(net_profit),  # Sof foyda
        "total_debts": float(total_debts),  # Jami qarzlar
    })


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


# Vaqtincha kodlarni saqlash uchun (Katta loyihalarda Redis ishlatiladi)
temp_otp_store = {}



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


@api_view(['POST'])
@permission_classes([AllowAny])
def request_password_reset(request):
    phone = request.data.get('phone', '').replace('+', '').strip()
    print(phone)
    # Telefon raqami bo'yicha subscriptionni qidiramiz
    sub = Subscription.objects.filter(phone=phone).first()
    print(sub)
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