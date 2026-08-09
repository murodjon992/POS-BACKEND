# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

# Avval FAQAT requirements faylini ko'chiramiz
COPY requirements.txt .

# --mount=type=cache: pip'ning o'z ichki yuklab olish keshini Docker qatlamidan
# ALOHIDA saqlaydi. Hatto Docker qatlam keshi negadir buzilib qolsa ham
# (masalan boshqa sabablarga ko'ra), pip paketlarni qaytadan internetdan emas,
# shu mahalliy keshdan oladi - build sezilarli tezlashadi.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# KEYIN qolgan hamma kodni ko'chiramiz
COPY . .

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]