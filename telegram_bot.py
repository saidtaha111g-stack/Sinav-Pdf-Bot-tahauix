"""
Telegram Sınav Notu Botu
========================
Gereksinimler:
    pip install python-telegram-bot anthropic pdfplumber pypdf

Kurulum:
    1. BotFather'dan bot token alın: https://t.me/BotFather
    2. Anthropic API key alın: https://console.anthropic.com
    3. Aşağıdaki ortam değişkenlerini ayarlayın:
       - TELEGRAM_TOKEN=<bot_token>
       - ANTHROPIC_API_KEY=<anthropic_key>
    4. python telegram_bot.py
"""

import os
import io
import logging
import asyncio
import pdfplumber
from pypdf import PdfReader
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import anthropic

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Sabitler ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

if not TELEGRAM_TOKEN or not ANTHROPIC_API_KEY:
    raise EnvironmentError(
        "Lütfen TELEGRAM_TOKEN ve ANTHROPIC_API_KEY ortam değişkenlerini ayarlayın."
    )

anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── PDF metin çıkarıcı ────────────────────────────────────────────────────────

def extract_text_from_pdf(file_bytes: bytes) -> str:
    """PDF baytlarından metin çıkarır; önce pdfplumber, sonra pypdf dener."""
    text = ""

    # pdfplumber denemesi
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception:
        pass

    # Yeterli metin yoksa pypdf ile dene
    if len(text.strip()) < 50:
        try:
            reader = PdfReader(io.BytesIO(file_bytes))
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        except Exception as e:
            logger.error("PDF okuma hatası: %s", e)

    return text.strip()


# ── Claude ile sınav notu üretici ─────────────────────────────────────────────

def generate_exam_notes(pdf_text: str) -> str:
    """Claude'a PDF metnini gönderir, yapılandırılmış sınav notu döndürür."""
    system_prompt = """Sen, akademik belgeleri özlü ve etkili sınav notlarına dönüştüren
uzman bir eğitim asistanısın.

Görevin:
1. Ana kavramları ve tanımları belirle
2. Önemli formül, kural veya süreçleri listele
3. Sınav açısından kritik noktaları vurgula
4. Karşılaştırma veya ilişkileri tabloya dök (gerekirse)
5. Hızlı tekrar için kısa bir özet ekle

Çıktı formatı (Markdown kullan):
## 📚 Ana Kavramlar
## 🔑 Anahtar Tanımlar
## 📐 Formüller / Kurallar  (varsa)
## ⚠️ Kritik Sınav Noktaları
## 📝 Özet

Yanıtı Türkçe ver."""

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": f"Aşağıdaki PDF içeriğinden kapsamlı sınav notları hazırla:\n\n{pdf_text[:12000]}",
            }
        ],
    )
    return response.content[0].text


# ── Komut handler'ları ────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Karşılama mesajı gönder."""
    user = update.effective_user
    await update.message.reply_text(
        f"Merhaba {user.first_name}! 👋\n\n"
        "Ben sınav notu botuyum. Bana bir PDF gönder, sana:\n"
        "✅ Ana kavramları\n"
        "✅ Anahtar tanımları\n"
        "✅ Formül ve kuralları\n"
        "✅ Kritik sınav noktalarını\n"
        "çıkarayım!\n\n"
        "Komutlar için /yardim yazabilirsin."
    )


async def yardim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📋 *Komutlar*\n\n"
        "/start — Botu başlat\n"
        "/yardim — Bu menüyü göster\n"
        "/hakkinda — Bot hakkında bilgi\n\n"
        "📄 *PDF göndermek için:*\n"
        "Doğrudan bir PDF dosyası gönder, "
        "otomatik olarak sınav notlarına çeviririm.",
        parse_mode="Markdown",
    )


async def hakkinda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 *Sınav Notu Botu*\n\n"
        "Claude (Anthropic) destekli bu bot, PDF belgelerini analiz ederek "
        "sınava hazırlık için yapılandırılmış notlar üretir.\n\n"
        "Herhangi bir PDF dosyası gönder, gerisini ben hallederim! 📚",
        parse_mode="Markdown",
    )


# ── PDF mesaj handler'ı ───────────────────────────────────────────────────────

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gelen PDF'yi işle ve sınav notlarını gönder."""
    document = update.message.document

    # Dosya türü kontrolü
    if document.mime_type != "application/pdf":
        await update.message.reply_text("❌ Lütfen geçerli bir PDF dosyası gönderin.")
        return

    # Boyut kontrolü (20 MB)
    if document.file_size > 20 * 1024 * 1024:
        await update.message.reply_text("❌ PDF dosyası 20 MB'dan büyük olamaz.")
        return

    processing_msg = await update.message.reply_text(
        "⏳ PDF işleniyor, lütfen bekleyin..."
    )

    try:
        # Dosyayı indir
        file = await context.bot.get_file(document.file_id)
        file_bytes = await file.download_as_bytearray()

        await processing_msg.edit_text("🔍 PDF metni çıkarılıyor...")

        # Metin çıkar
        pdf_text = extract_text_from_pdf(bytes(file_bytes))

        if not pdf_text:
            await processing_msg.edit_text(
                "❌ PDF'den metin çıkarılamadı. "
                "Taranmış (görüntü tabanlı) bir PDF olabilir."
            )
            return

        await processing_msg.edit_text("🧠 Sınav notları oluşturuluyor...")

        # Claude ile not üret
        notes = generate_exam_notes(pdf_text)

        # Notları gönder (Telegram 4096 karakter sınırı)
        await processing_msg.delete()

        header = f"📄 *{document.file_name}* için sınav notları:\n\n"
        full_message = header + notes

        # Uzun mesajları böl
        MAX_LEN = 4000
        if len(full_message) <= MAX_LEN:
            await update.message.reply_text(full_message, parse_mode="Markdown")
        else:
            chunks = [full_message[i : i + MAX_LEN] for i in range(0, len(full_message), MAX_LEN)]
            for i, chunk in enumerate(chunks):
                prefix = f"*[{i+1}/{len(chunks)}]*\n" if len(chunks) > 1 else ""
                await update.message.reply_text(prefix + chunk, parse_mode="Markdown")

        logger.info("Sınav notları başarıyla gönderildi: %s", document.file_name)

    except anthropic.APIError as e:
        logger.error("Anthropic API hatası: %s", e)
        await processing_msg.edit_text(
            "❌ AI servisi şu an yanıt vermiyor. Lütfen tekrar deneyin."
        )
    except Exception as e:
        logger.error("Beklenmedik hata: %s", e)
        await processing_msg.edit_text(
            "❌ Bir hata oluştu. Lütfen tekrar deneyin."
        )


# ── Genel metin mesajı handler'ı ──────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Metin mesajlarını yanıtla."""
    await update.message.reply_text(
        "📎 Bana bir PDF dosyası gönder, sınav notlarına çevireyim!\n"
        "Yardım için /yardim komutunu kullanabilirsin."
    )


# ── Bildirim yardımcı fonksiyonu ──────────────────────────────────────────────

async def send_notification(bot: Bot, chat_id: int, message: str) -> None:
    """
    Belirli bir chat_id'ye programatik bildirim gönder.

    Kullanım örneği (bot dışında):
        asyncio.run(send_notification(bot, CHAT_ID, "Hatırlatma: Sınav yaklaşıyor!"))
    """
    await bot.send_message(chat_id=chat_id, text=message)


# ── Uygulama başlangıcı ───────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Komutlar
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("yardim", yardim))
    app.add_handler(CommandHandler("hakkinda", hakkinda))

    # PDF handler
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))

    # Metin handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot başlatılıyor...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
