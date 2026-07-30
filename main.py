import discord
from discord import app_commands
from discord.ext import commands
import os
import sys
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from aiohttp import web

load_dotenv()

# ---------- Безопасное чтение переменных ----------
def get_int_env(var_name: str, default: int = 0) -> int:
    value = os.getenv(var_name)
    if value is None:
        return default
    value = value.strip()
    if value.isdigit():
        return int(value)
    return default

TOKEN = os.getenv('DISCORD_TOKEN')
CATEGORY_ID = get_int_env('CATEGORY_ID')
ADMIN_ROLE_ID = get_int_env('ADMIN_ROLE_ID')
LOG_CHANNEL_ID = 1532376168173404170

if not TOKEN or CATEGORY_ID == 0:
    print("❌ Ошибка: не заданы DISCORD_TOKEN и CATEGORY_ID")
    sys.exit(1)

# ---------- Счётчик ----------
COUNTER_FILE = "data/counter.txt"
os.makedirs("data", exist_ok=True)

def load_counter():
    if os.path.exists(COUNTER_FILE):
        with open(COUNTER_FILE, "r") as f:
            return int(f.read().strip())
    return 1

def save_counter(val):
    with open(COUNTER_FILE, "w") as f:
        f.write(str(val))

counter = load_counter()
counter_lock = asyncio.Lock()

# ---------- Бот ----------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ---------- Команда /apply (вместо модального окна) ----------
@bot.tree.command(name="apply", description="Подать заявку в группировку (заполните все поля)")
@app_commands.describe(
    age="Ваш реальный возраст",
    steamid="SteamID64 (только цифры)",
    experience="Опыт игры на RP-проектах по STALKER RP DayZ",
    hours="Сколько часов в DayZ",
    online="Ваш средний онлайн в день",
    groups="За какие группировки играли? / впервые"
)
async def apply(
    interaction: discord.Interaction,
    age: str,
    steamid: str,
    experience: str,
    hours: str,
    online: str,
    groups: str
):
    global counter

    # Быстрая проверка SteamID
    if not steamid.isdigit():
        await interaction.response.send_message("❌ SteamID должен содержать только цифры.", ephemeral=True)
        return

    guild = interaction.guild
    category = bot.get_channel(CATEGORY_ID)
    if not category:
        await interaction.response.send_message("❌ Категория не найдена.", ephemeral=True)
        return

    # Проверка на существующий канал
    existing = discord.utils.get(category.channels, topic=str(interaction.user.id))
    if existing:
        await interaction.response.send_message(f"⚠️ У вас уже есть заявка: {existing.mention}", ephemeral=True)
        return

    # Номер заявки
    async with counter_lock:
        current_number = counter
        counter += 1
        save_counter(counter)

    # Создаём канал
    channel_name = f"заявка-{interaction.user.name.lower()}-{current_number}"
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
    }
    if ADMIN_ROLE_ID != 0:
        role = guild.get_role(ADMIN_ROLE_ID)
        if role:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

    try:
        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=str(interaction.user.id)
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ Ошибка создания канала: {e}", ephemeral=True)
        return

    # Формируем embed с анкетой
    embed = discord.Embed(
        title=f"📋 Заявка #{current_number}",
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="1. Реальный возраст", value=age, inline=False)
    embed.add_field(name="2. SteamID64", value=steamid, inline=False)
    embed.add_field(name="3. Опыт RP", value=experience, inline=False)
    embed.add_field(name="4. Часы в DayZ", value=hours, inline=False)
    embed.add_field(name="5. Средний онлайн", value=online, inline=False)
    embed.add_field(name="6. Группировки", value=groups, inline=False)
    embed.set_footer(text=f"От: {interaction.user.display_name}")

    await channel.send(embed=embed)

    # Кнопка закрытия
    close_view = discord.ui.View()
    close_view.add_item(CloseApplicationButton())
    await channel.send("🔒 Кнопка закрытия заявки (только для администрации):", view=close_view)

    # Логирование
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        log_embed = discord.Embed(
            title="📩 Новая заявка",
            color=discord.Color.gold()
        )
        log_embed.add_field(name="Номер", value=f"#{current_number}", inline=False)
        log_embed.add_field(name="Пользователь", value=interaction.user.mention, inline=False)
        log_embed.add_field(name="Канал", value=channel.mention, inline=False)
        await log_channel.send(embed=log_embed)

    # Отвечаем пользователю (мгновенно)
    await interaction.response.send_message(f"✅ Заявка отправлена! Перейдите в {channel.mention}", ephemeral=True)

# ---------- Кнопка закрытия заявки ----------
class CloseApplicationButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Закрыть заявку", style=discord.ButtonStyle.danger, custom_id="close_application")
    async def callback(self, interaction: discord.Interaction):
        if ADMIN_ROLE_ID != 0:
            role = interaction.guild.get_role(ADMIN_ROLE_ID)
            if not role or role not in interaction.user.roles:
                await interaction.response.send_message("⛔ У вас нет прав.", ephemeral=True)
                return
        channel = interaction.channel
        if not channel.category or channel.category.id != CATEGORY_ID:
            await interaction.response.send_message("❌ Не канал заявки.", ephemeral=True)
            return
        await interaction.response.send_message("⏳ Закрытие...", ephemeral=True)
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"🔒 Заявка #{channel.name} закрыта {interaction.user.mention}")
        await channel.delete()

# ---------- Дополнительные команды ----------
@bot.tree.command(name="close", description="Закрыть текущий канал заявки")
async def close_application(interaction: discord.Interaction):
    channel = interaction.channel
    if not channel.category or channel.category.id != CATEGORY_ID:
        await interaction.response.send_message("❌ Это не канал заявки.", ephemeral=True)
        return
    if ADMIN_ROLE_ID != 0:
        role = interaction.guild.get_role(ADMIN_ROLE_ID)
        if not role or role not in interaction.user.roles:
            await interaction.response.send_message("⛔ У вас нет прав.", ephemeral=True)
            return
    await interaction.response.send_message("⏳ Закрытие...", ephemeral=True)
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"🔒 Заявка #{channel.name} закрыта {interaction.user.mention}")
    await channel.delete()

@bot.tree.command(name="list_applications", description="Показать все открытые заявки")
@app_commands.default_permissions(administrator=True)
async def list_applications(interaction: discord.Interaction):
    category = bot.get_channel(CATEGORY_ID)
    if not category:
        await interaction.response.send_message("❌ Категория не найдена.", ephemeral=True)
        return
    channels = [ch for ch in category.channels if isinstance(ch, discord.TextChannel) and ch.name.startswith("заявка-")]
    if not channels:
        await interaction.response.send_message("📭 Открытых заявок нет.", ephemeral=True)
        return
    embed = discord.Embed(title=f"📋 Открытые заявки ({len(channels)})", color=discord.Color.blue())
    for ch in channels:
        creator_id = ch.topic
        if creator_id and creator_id.isdigit():
            user = interaction.guild.get_member(int(creator_id))
            user_mention = user.mention if user else f"ID:{creator_id}"
        else:
            user_mention = "Неизвестно"
        embed.add_field(name=ch.name, value=f"Канал: {ch.mention}\nСоздатель: {user_mention}", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="stats", description="Показать статистику по заявкам")
@app_commands.default_permissions(administrator=True)
async def stats(interaction: discord.Interaction):
    category = bot.get_channel(CATEGORY_ID)
    if not category:
        await interaction.response.send_message("❌ Категория не найдена.", ephemeral=True)
        return
    total = counter - 1
    channels = [ch for ch in category.channels if isinstance(ch, discord.TextChannel) and ch.name.startswith("заявка-")]
    open_count = len(channels)
    closed_count = total - open_count
    embed = discord.Embed(title="📊 Статистика заявок", color=discord.Color.gold())
    embed.add_field(name="Всего подано", value=str(total), inline=True)
    embed.add_field(name="Открыто", value=str(open_count), inline=True)
    embed.add_field(name="Закрыто", value=str(closed_count), inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ---------- Команда /setup (создать сообщение с кнопкой-напоминанием) ----------
@bot.tree.command(name="setup", description="Создать сообщение с инструкцией по подаче заявки")
@app_commands.default_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 Подача заявки в группировку",
        description=(
            "Для подачи заявки используйте команду:\n"
            "`/apply age: <возраст> steamid: <SteamID64> experience: <опыт> hours: <часы> online: <онлайн> groups: <группировки>`\n\n"
            "Все поля обязательны для заполнения."
        ),
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed)

# ---------- Веб-сервер для health check ----------
async def health_check(request):
    return web.Response(text="OK", status=200)

async def start_web():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host='0.0.0.0', port=8080)
    await site.start()
    print("🌐 Health check на порту 8080")
    await asyncio.Event().wait()

@bot.event
async def on_ready():
    global counter
    counter = load_counter()
    print(f'✅ Бот {bot.user} запущен! Счётчик: {counter}')
    # Синхронизация на конкретный сервер (если задан GUILD_ID)
    guild_id = int(os.getenv('GUILD_ID', 0))
    try:
        if guild_id:
            guild = discord.Object(id=guild_id)
            synced = await bot.tree.sync(guild=guild)
            print(f"🔄 Синхронизировано {len(synced)} команд для сервера {guild_id}")
        else:
            synced = await bot.tree.sync()
            print(f"🔄 Синхронизировано {len(synced)} глобальных команд")
    except Exception as e:
        print(f"⚠️ Ошибка синхронизации: {e}")

async def main():
    asyncio.create_task(start_web())
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
