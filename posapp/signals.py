from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import F
from .models import (StocLogItem, Product, AccessoryInventory, StocLog, Transaction, DebtLog, SupplierLog, ReturnLog, Supplier, Subscription)

# --- YORDAMCHI FUNKSIYA (Real-time xabar yuborish) ---
def broadcast_data(action_type, payload):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "pos_updates",
        {
            "type": "pos_message",
            "action": action_type,
            "payload": payload
        }
    )

# --- SIGNALLAR ---

@receiver(post_save, sender=Subscription)
def subscription_updated(sender, instance, created, **kwargs):
    # OLDIN: bu yerda ikkinchi, noto'g'ri formatlangan group_send chaqiruvi bor edi
    # ("data" ichiga o'ralgan action/payload), u consumer tomonidan tushunilmay,
    # action=null xabar yuborilib, konsolda "Noma'lum action" chiqishiga sabab bo'lgan.
    # Endi hammasi bitta to'g'ri chaqiruvga birlashtirildi:
    broadcast_data("SUBSCRIPTION_UPDATE", {
        "user_id": instance.user.id,
        "is_active": instance.is_active_status,
        "is_paid": instance.is_paid,
        "plan_name": instance.plan.name if instance.plan else "Reja tanlanmagan"
    })


@receiver(post_save, sender=StocLogItem)
def update_inventory_on_sale(sender, instance, created, **kwargs):
    if created:
        inv, _ = AccessoryInventory.objects.get_or_create(product=instance.product)
        inv.quantity -= instance.quantity
        inv.save()
        broadcast_data("STOCK_UPDATE", {"product_name": instance.product.name})

@receiver(post_save, sender=Product)
def create_product_inventory(sender, instance, created, **kwargs):
    if created:
        AccessoryInventory.objects.get_or_create(product=instance, quantity=0)

@receiver(post_save, sender=StocLog)
def auto_transaction_on_total_sale(sender, instance, created, **kwargs):
    if created:
        Transaction.objects.create(
            owner=instance.owner,
            amount=instance.total_amount,
            type='sale',
            payment_method=instance.payment_method
        )
        if instance.payment_method == 'debt' and instance.customer:
            customer = instance.customer
            customer.total_debt += instance.total_amount
            customer.save()
            DebtLog.objects.create(
                customer=customer,
                amount=instance.total_amount,
                type='borrow',
                note=f"Savdo #{instance.daily_id} dan qarz"
            )
        broadcast_data("NEW_SALE", {"amount": float(instance.total_amount)})

@receiver(post_save, sender=DebtLog)
def auto_transaction_on_debt_pay(sender, instance, created, **kwargs):
    if created and instance.type == 'pay':
        Transaction.objects.create(
            owner=instance.customer.owner,
            amount=instance.amount,
            type='customer_pay',
            payment_method='cash'
        )
        broadcast_data("DEBT_PAY", {"customer": instance.customer.name, "amount": float(instance.amount)})

@receiver(post_save, sender=SupplierLog)
def update_supplier_balance(sender, instance, created, **kwargs):
    if created:
        supplier = instance.supplier
        if instance.type == 'take':
            supplier.total_debt_to_them = F('total_debt_to_them') + instance.amount
        elif instance.type == 'pay' or instance.type == 'return':
            supplier.total_debt_to_them = F('total_debt_to_them') - instance.amount

        supplier.save()
        supplier.refresh_from_db()

        if instance.type == 'pay':
            from django.contrib.contenttypes.models import ContentType
            Transaction.objects.create(
                owner=supplier.owner,
                amount=instance.amount,
                type='supplier_pay',
                payment_method='cash',
                content_type=ContentType.objects.get_for_model(Supplier),
                object_id=supplier.id
            )

@receiver(post_save, sender=ReturnLog)
def handle_return_log(sender, instance, created, **kwargs):
    if created:
        inventory, _ = AccessoryInventory.objects.get_or_create(product=instance.product)
        inventory.quantity += instance.quantity
        inventory.save()

        broadcast_data("STOCK_UPDATE", {"product_id": instance.product.id, "new_quantity": inventory.quantity})

        Transaction.objects.create(owner=instance.product.owner,
                                   amount=instance.amount_returned,
                                   type='return_sale',
                                   payment_method=instance.payment_method,
                                   note=f"vozvrat ({instance.payment_method}): {instance.product.name} - {instance.quantity}ta")

        if instance.payment_method == 'debt' and instance.customer:
            customer = instance.customer
            new_debt = float(customer.total_debt) - float(instance.amount_returned)

            DebtLog.objects.create(customer=instance.customer,
                                   amount=instance.amount_returned,
                                   type="return",
                                   note=f"vozvrat {instance.product.name} ({instance.quantity}ta)")

            new_debt = float(customer.total_debt) - float(instance.amount_returned)
            customer.total_debt = max(0, new_debt)
            customer.save()