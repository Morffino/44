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

# ---------- Конфигурация ----------
TOKEN = os.getenv('DISCORD_TOKEN')
CATEGORY_ID = int(os.getenv('CATEGORY_ID', 0))
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID', 0))
ADMIN_ROLE_ID = int(os.getenv('ADMIN_ROLE_ID', 0))

if not TOKEN or CATEGORY_ID == 0:
    print("❌ Ошибка: не заданы DISCORD_TOKEN и CATEGORY_ID")
    sys.exit(1)

# ---------- Счётчик заявок ----------
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

# ---------- Модальное окно для заявки ----------
class ApplicationModal(discord.ui.Modal, title='📝 Заявка в группировку'):
    age = discord.ui.TextInput(
        label='Ваш реальный возраст',
        placeholder='Например: 18',
        required=True,
        max_length=3
    )
    steam = discord.ui.TextInput(
        label='SteamID64',
        placeholder='Введите ваш SteamID64 (только цифры)',
        required=True
    )
    experience = discord.ui.TextInput(
        label='Опыт игры на RP-проектах по STALKER RP DayZ',
        placeholder='Опишите свой опыт',
        required=True,
        style=discord.TextStyle.paragraph
    )
    hours = discord.ui.TextInput(
        label='Сколько часов в DayZ',
        placeholder='Например: 500+',
        required=True
    )
    online = discord.ui.TextInput(
        label='Ваш средний онлайн в день',
        placeholder='Например: 4-6 часов',
        required=True
    )
    groups = discord.ui.TextInput(
        label='За какие группировки играли? / впервые на таком проекте',
        placeholder='Перечислите группировки или напишите "впервые"',
        required=True,
        style=discord.TextStyle.paragraph
    )

    async def on_submit(self, interaction: discord.Interaction):
        global counter
        guild = interaction.guild
        category = bot.get_channel(CATEGORY_ID)
        if not category:
            await interaction.response.send_message("❌ Категория не найдена. Обратитесь к администратору.", ephemeral=True)
            return

        # Проверка на существующий канал
        existing = discord.utils.get(category.channels, topic=str(interaction.user.id))
        if existing:
            await interaction.response.send_message(f"⚠️ У вас уже есть открытая заявка: {existing.mention}", ephemeral=True)
            return

        # Получаем номер заявки
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
        # Если есть роль администратора, добавляем её
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
        embed.add_field(name="1. Реальный возраст", value=self.age.value, inline=False)
        embed.add_field(name="2. SteamID64", value=self.steam.value, inline=False)
        embed.add_field(name="3. Опыт RP", value=self.experience.value, inline=False)
        embed.add_field(name="4. Часы в DayZ", value=self.hours.value, inline=False)
        embed.add_field(name="5. Средний онлайн", value=self.online.value, inline=False)
        embed.add_field(name="6. Группировки", value=self.groups.value, inline=False)
        embed.set_footer(text=f"От: {interaction.user.display_name}")

        await channel.send(embed=embed)

        # Кнопка закрытия заявки (только для админов)
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

        await interaction.response.send_message(f"✅ Заявка отправлена! Перейдите в {channel.mention}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await interaction.response.send_message("❌ Ошибка при отправке заявки.", ephemeral=True)
        print(f"Ошибка в модальном окне: {error}")

# ---------- Кнопка "Название группировок" ----------
class GroupButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="📝 Название группировок", style=discord.ButtonStyle.primary, custom_id="group_application")

    async def callback(self, interaction: discord.Interaction):
        modal = ApplicationModal()
        await interaction.response.send_modal(modal)

# ---------- Кнопка закрытия заявки (только админы) ----------
class CloseApplicationButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Закрыть заявку", style=discord.ButtonStyle.danger, custom_id="close_application")

    async def callback(self, interaction: discord.Interaction):
        # Проверка на админа
        if ADMIN_ROLE_ID != 0:
            role = interaction.guild.get_role(ADMIN_ROLE_ID)
            if not role or role not in interaction.user.roles:
                await interaction.response.send_message("⛔ У вас нет прав закрывать заявку.", ephemeral=True)
                return

        channel = interaction.channel
        if not channel.category or channel.category.id != CATEGORY_ID:
            await interaction.response.send_message("❌ Это не канал заявки.", ephemeral=True)
            return

        await interaction.response.send_message("⏳ Заявка закрывается...", ephemeral=True)

        # Логирование закрытия
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"🔒 Заявка #{channel.name} закрыта администратором {interaction.user.mention}")

        await channel.delete()

# ---------- Представление с одной кнопкой ----------
class ApplicationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GroupButton())

# ---------- Команда /setup ----------
@bot.tree.command(name="setup", description="Создать сообщение с кнопкой для подачи заявок")
@app_commands.default_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 Подача заявки в группировку",
        description=(
            "Нажмите на кнопку ниже, чтобы заполнить анкету.\n"
            "После отправки заявки будет создан отдельный канал для рассмотрения."
        ),
        color=discord.Color.blue()
    )
    view = ApplicationView()
    await interaction.response.send_message(embed=embed, view=view)

# ---------- Веб-сервер для health check ----------
async def health_check(request):
    return web.Response(text="OK", status=200)

async def start_web():
    app = web.Application()
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host='0.0.0.0', port=8080)
    await site.start()
    print("🌐 Health check на порту 8080")
    await asyncio.Event().wait()

# ---------- Событие готовности ----------
@bot.event
async def on_ready():
    global counter
    counter = load_counter()
    print(f'✅ Бот {bot.user} запущен! Счётчик заявок: {counter}')
    try:
        synced = await bot.tree.sync()
        print(f"🔄 Синхронизировано {len(synced)} команд.")
    except Exception as e:
        print(f"⚠️ Ошибка синхронизации: {e}")

# ---------- Запуск ----------
async def main():
    asyncio.create_task(start_web())
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
