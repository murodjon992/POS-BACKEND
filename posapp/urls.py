from django.urls import path,include
from rest_framework.routers import DefaultRouter
from .views import get_product_by_barcode, sell_product, stock_in,product_search,inventory_view,get_debtors,pay_debtor_debt,daily_summary,generate_product_barcodes_pdf,register,login,select_plan,super_admin_excel_upload,get_all_users,delete_user,update_user,product_detail,product_list_create,category_list,category_detail,get_all_subscriptions,update_subscription_admin,my_subscription,PlanViewSet,SellerViewSet,superadmin_dashboard_stats,dashboard_stats,return_product,get_business_analytics,update_profile,reset_password,request_password_reset,customer_debt_history,sales_history,suppliers_view,supplier_history,pay_supplier_debt,return_to_supplier,all_purchase_history,supplier_general_return,add_expense,customers_view,get_debtor_details,extend_subscription,get_my_sellers
router = DefaultRouter()
from django.views.decorators.csrf import csrf_exempt
router.register(r'plans', PlanViewSet, basename='plan')
router.register(r'sellers', SellerViewSet, basename='seller')
urlpatterns = [
    path('', include(router.urls)),
    path('register/', register), # Ro'yxatdan o'tish
    path('login/', login), # Login
    path("stock-in/", stock_in), # Omborga Mahsulot qo'shish
    path("inventory/",inventory_view), # Ombor
    path("customers/",customers_view), # Tovar beruvchilar ro'yxati
    # TOVARCHILAR ===========================================
    path("pay-supplier-debt/<int:supplier_id>/",pay_supplier_debt), # Tovar beruvchilar ro'yxati
    path("suppliers/",suppliers_view), # Tovar beruvchilar ro'yxati
    path("supplier-history/<int:supplier_id>/",supplier_history), # Tovar beruvchi tarixi
    path("suppliers/<int:supplier_id>/return/",return_to_supplier), # Mahsulotni yetkazib beruvchiga qaytarib berish uchun
    path("all-purchase-history/", all_purchase_history), #Sotuvlar tarixi
    path("supplier-general-return/",supplier_general_return), # Mahsulotni naqdga olib yetkazib beruvchiga qaytarib berish uchun
    # TOVARCHILAR TUGASHI======================================
    path("analytics/",get_business_analytics),
    path("sale/", sell_product), #Sotuv API
    path("my-sellers/", get_my_sellers), #Sotuv API
    path("sales-history/", sales_history), #Sotuvlar tarixi
    path("return-product/",return_product), # Mahsulotni Qaytarib olish
    path("debtors/",get_debtors), # Qarzdorlar
    path("debtor-sales/<int:customer_id>/",get_debtor_details), # Qarzdorlar
    path("customer-debt-history/<int:customer_id>/",customer_debt_history), # Qarzdorlar
    path('pay-customer-debt/<int:customer_id>/', pay_debtor_debt), # Qarz uzish
    path('parol-unut/', request_password_reset),
    path('reset-parol/', reset_password),
    path("daily-summary/", daily_summary), # Kunlik Savdo
    path("print-barcodes/", csrf_exempt(generate_product_barcodes_pdf)), # Barcode generatsiya qilish
    path("admin-excel-upload/", super_admin_excel_upload), # Excel orqali mahsulot yuklash
    path("users/all/", get_all_users), # Barcha Foydalanuvchilar
    path("users/update/<int:pk>/", update_user), # Foydalanuvchilar Tahrirlash
    path("update-profile/", update_profile), # Foydalanuvchi o'z malumotlarini Tahrirlash
    path("users/delete/<int:pk>/", delete_user), # Foydalanuvchini o'chirish
    # MAHSULOTLAR =================================================================================================
    path("product/<str:barcode>/", get_product_by_barcode),
    path("product/search", product_search),
    path("products/", product_list_create), # Mahsulotlar
    path("products/<int:pk>/", product_detail), # Mahsulotlar haqida yoki tahrirlash va yangilash
    # MAHSULOTLAR TUGASHI =========================================================================================
    path("categories/", category_list), # Kategoriyalar
    path("categories/<int:pk>/", category_detail), # Categoriya tahrirlash va yangilash
    path("admin/subs/all/", get_all_subscriptions), # Obunalar ro'yxati
    path("admin/subs/<int:pk>/update/", update_subscription_admin), # Obunalar tahrr
    # TARIFLAR ===============================================
    path("my-sub/", my_subscription), # mening planim  
    path("my-sub/select-plan/", select_plan),
    path("my-sub/extend/", extend_subscription),
    # TARIFLAR TUGASHI=========================================
    path("owner-dashboard/", dashboard_stats), # Ega uchun Dashboard
    path("expenses/add/", add_expense), # Ega uchun Dashboard
    path("admin-store-stats/", superadmin_dashboard_stats), # ADMIN uchun Dashboard

]