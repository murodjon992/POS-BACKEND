FROM python:3.11-slim

# 1. Ishchi katalogni yaratish
WORKDIR /app

# 2. Avval FAQAT requirements faylini ko'chiramiz
COPY requirements.txt .

# 3. Kutubxonalarni o'rnatamiz (Bu qatlam keshda qoladi)
# Agar requirements.txt o'zgarmasa, Docker bu bosqichni sakrab o'tadi
RUN pip install --no-cache-dir -r requirements.txt

# 4. KEYIN qolgan hamma kodni ko'chiramiz
# Endi views.py o'zgarsa, faqat mana shu qatlam ishlaydi
COPY . .

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]