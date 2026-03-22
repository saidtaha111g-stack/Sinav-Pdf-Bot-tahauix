"""
Telegram Sınav Notu Botu — Konu Bazlı PDF İşleme
=================================================
Gereksinimler:
    pip install python-telegram-bot anthropic pdfplumber pypdf

Ortam değişkenleri:
    TELEGRAM_TOKEN=<bot_token>
    ANTHROPIC_API_KEY=<anthropic_key>
"""

import os
import io
import re
import logging
import pdfplumber
from pypdf import PdfReader
from telegram import Update
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

# Konu başlığı regex desenleri
HEADING_PATTERNS = [
    r"^(BÖLÜM|CHAPTER|ÜNİTE|UNITE|KONU|PART|KISIM)\s*[\d\.\-]*\s*.+",
    r"^\d+[\.\)]\s+[A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜa-zçğışöüI\s]{3,}$",
    r"^[A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜ\s]{4,}$",
]


# ── PDF metin çıkarıcı ────────────────────────────────────────────────────────

def extract_text_from_pdf(file_bytes: bytes) -> str:
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception:
        pass

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


# ── Konu başlıklarına göre böl ────────────────────────────────────────────────

def split_by_headings(text: str) -> list:
    lines = text.split("\n")
    sections = []
    current_title = "Giriş"
    current_lines = []

    for line in lines:
        stripped = line.strip()
        is_heading = False

        if stripped:
            for pattern in HEADING_PATTERNS:
                if re.match(pattern, stripped, re.IGNORECASE):
                    is_heading = True
                    break

        if is_heading:
            if current_lines:
                content = "\n".join(current_lines).strip()
                if len(content) > 100:
                    sections.append({"title": current_title, "content": content})
            current_title = stripped
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        content = "\n".join(current_lines).strip()
        if len(content) > 100:
            sections.append({"title": current_title, "content": content})

    # Başlık bulunamadıysa kelime sayısına göre böl
    if len(sections) <= 1:
        sections = split_by_word_count(text, chunk_size=3000)

    return sections


def split_by_word_count(text: str, chunk_size: int = 3000) -> list:
    words = text.split()
    sections = []
    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i : i + chunk_size])
        part_num = (i // chunk_size) + 1
        sections.append({"title": f"Bölüm {part_num}", "content": chunk})
    return sections


# ── Claude ile not üretici ────────────────────────────────────────────────────

def generate_notes_for_section(title: str, content: str) -> str:
    system_prompt = """Sen akademik belgeleri özlü sınav notlarına dönüştüren bir asistansın.
Verilen bölüm için şu formatta Türkçe notlar hazırla:

## 🔑 Anahtar Kavramlar
## 📐 Formüller / Kurallar (varsa)
## ⚠️ Kritik Noktalar
## 📝 Kısa Özet (2-3 cümle)

Yanıt kısa ve öz olsun, sadece önemli bilgileri içersin."""

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": f"Bölüm: {title}\n\nİçerik:\n{content[:6000]}",
            }
        ],
    )
    return response.content[0].text


# ── Uzun mesaj gönderici ──────────────────────────────────────────────────────

async def send_long_message(update: Update, text: str) -> None:
    MAX_LEN = 4000
    if len(text) <= MAX_LEN:
        await update.message.reply_text(text, parse_mode="Markdown")
    else:
        chunks = [text[i : i + MAX_LEN] for i in range(0, len(text), MAX_LEN)]
        for chunk in chunks:
            await update.message.reply_text(chunk, parse_mode="Markdown")


# ── Komut handler'ları ────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_text(
        f"Merhaba {user.first_name}! 👋\n\n"
        "PDF gönder, konu başlıklarına göre sınav notlarına çevireyim!\n\n"
        "📌 Her konu için ayrı mesaj gelir.\n"
        "📄 100 sayfalık PDF'ler de desteklenir.\n\n"
        "/yardim — Komutlar"
    )


async def yardim(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📋 *Komutlar*\n\n"
        "/start — Botu başlat\n"
        "/yardim — Bu menü\n\n"
        "📄 *Kullanım:*\n"
        "PDF dosyası gönder → konu başlıklarına göre notlar gelir.",
        parse_mode="Markdown",
    )


# ── PDF handler ───────────────────────────────────────────────────────────────

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document = update.message.document

    if document.mime_type != "application/pdf":
        await update.message.reply_text("❌ Lütfen geçerli bir PDF dosyası gönderin.")
        return

    if document.file_size > 20 * 1024 * 1024:
        await update.message.reply_text("❌ PDF 20 MB'dan büyük olamaz.")
        return

    status = await update.message.reply_text("⏳ PDF yükleniyor...")

    try:
        file = await context.bot.get_file(document.file_id)
        file_bytes = await file.download_as_bytearray()

        await status.edit_text("🔍 Metin çıkarılıyor...")
        pdf_text = extract_text_from_pdf(bytes(file_bytes))

        if not pdf_text:
            await status.edit_text(
                "❌ PDF'den metin çıkarılamadı. Taranmış (görüntü) PDF olabilir."
            )
            return

        await status.edit_text("📂 Konu başlıkları tespit ediliyor...")
        sections = split_by_headings(pdf_text)

        await status.edit_text(
            f"✅ *{len(sections)} konu* tespit edildi.\n"
            f"📝 Sınav notları hazırlanıyor, biraz bekle...",
            parse_mode="Markdown",
        )

        # İçindekiler tablosu
        toc = "📚 *İçindekiler:*\n" + "\n".join(
            [f"{i+1}. {s['title']}" for i, s in enumerate(sections)]
        )
        await send_long_message(update, toc)

        # Her bölüm için not üret
        for i, section in enumerate(sections):
            await status.edit_text(
                f"🧠 İşleniyor: *{section['title']}* ({i+1}/{len(sections)})",
                parse_mode="Markdown",
            )
            notes = generate_notes_for_section(section["title"], section["content"])
            header = f"📖 *{i+1}. {section['title']}*\n\n"
            await send_long_message(update, header + notes)

        await status.edit_text(
            f"✅ *Tamamlandı!* {len(sections)} konu için notlar hazırlandı.",
            parse_mode="Markdown",
        )

    except anthropic.APIError as e:
        logger.error("Anthropic API hatası: %s", e)
        await status.edit_text("❌ AI servisi yanıt vermiyor. Tekrar dene.")
    except Exception as e:
        logger.error("Hata: %s", e)
        await status.edit_text("❌ Bir hata oluştu. Tekrar dene.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📎 Bana bir PDF gönder, konu başlıklarına göre sınav notlarına çevireyim!\n"
        "/yardim — Komutlar"
    )


# ── Başlat ────────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("yardim", yardim))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot başlatılıyor...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
