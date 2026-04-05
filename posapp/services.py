from django.db import transaction
from .models import Product, AccessoryInventory, StocLog


@transaction.atomic
def sell_product(barcode, quantity):

    product = Product.objects.get(barcode=barcode)

    inventory = AccessoryInventory.objects.get(product=product)

    if inventory.quantity < quantity:
        raise Exception("Not enough stock")

    inventory.quantity -= quantity
    inventory.save()

    StocLog.objects.create(
        product=product,
        quantity=quantity,
        action="sale"
    )

    return product


@transaction.atomic
def add_stock(barcode, quantity):

    product = Product.objects.get(barcode=barcode)

    inventory, created = AccessoryInventory.objects.get_or_create(
        product=product
    )

    inventory.quantity += quantity
    inventory.save()

    StocLog.objects.create(
        product=product,
        quantity=quantity,
        action="add"
    )

    return inventory