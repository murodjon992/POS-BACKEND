from django.urls import path

from .views import get_product_by_barcode, sell_product, add_stock,product_search,inventory_view,nasiya_sale,get_debtors,pay_debt,daily_summary,generate_product_barcodes_pdf,register,login,select_plan,super_admin_excel_upload,get_all_users,delete_user,update_user,product_detail,product_list_create,category_list,category_detail,get_all_subscriptions,update_subscription_admin,my_subscription,get_plans,superadmin_dashboard_stats,dashboard_stats,return_product,get_business_analytics,update_profile,reset_password,request_password_reset

from django.views.decorators.csrf import csrf_exempt

urlpatterns = [

    path("product/search", product_search),
    path("product/<str:barcode>/", get_product_by_barcode),
    path("sale/", sell_product), #Sotuv API
    path('register/', register), # Ro'yxatdan o'tish
    path('login/', login), # Login
    path("stock/add/", add_stock), # Omborga Mahsulot qo'shish
    path("inventory/",inventory_view), # Ombor
    path("analytics/",get_business_analytics), # Statistika
    path("nasiya-sale/",nasiya_sale), # Nasiya Savdo
    path("return-product/",return_product), # Mahsulotni Qaytarib olish
    path("debtors/",get_debtors), # Qarzdorlar
    path('parol-unut/', request_password_reset),
    path('reset-parol/', reset_password),
    path('pay-debt/', pay_debt), # Qarz uzish
    path("daily-summary/", daily_summary), # Kunlik Savdo
    path("print-barcodes/", csrf_exempt(generate_product_barcodes_pdf)), # Barcode generatsiya qilish
    path("select-plan/", select_plan), # Tarif tanlash
    path("admin-excel-upload/", super_admin_excel_upload), # Excel orqali mahsulot yuklash
    path("users/all/", get_all_users), # Barcha Foydalanuvchilar
    path("users/update/<int:pk>/", update_user), # Foydalanuvchilar Tahrirlash
    path("update-profile/", update_profile), # Foydalanuvchi o'z malumotlarini Tahrirlash
    path("users/delete/<int:pk>/", delete_user), # Foydalanuvchini o'chirish
    path("products/", product_list_create), # Mahsulotlar
    path("products/<int:pk>/", product_detail), # Mahsulotlar haqida yoki tahrirlash va yangilash
    path("categories/", category_list), # Kategoriyalar
    path("categories/<int:pk>/", category_detail), # Categoriya tahrirlash va yangilash
    path("admin/subs/all/", get_all_subscriptions), # Obunalar ro'yxati
    path("admin/subs/<int:pk>/update/", update_subscription_admin), # Obunalar tahrr
    path("my-sub/", my_subscription), # mening planim
    path("plans/", get_plans), # Tariflar
    path("store-stats/", dashboard_stats), # Ega uchun Dashboard
    path("admin-store-stats/", superadmin_dashboard_stats), # ADMIN uchun Dashboard

]