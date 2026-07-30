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
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID', 1532376168173404170))
GUILD_ID = int(os.getenv('GUILD_ID', 0))

SUPPORT_ROLE_ID = int(os.getenv('SUPPORT_ROLE_ID', 0))
ADDITIONAL_SUPPORT_ROLE_IDS = [
    1529252048883810485,
    1529253808666841302,
    1529253952850366616,
    1529254103820275823
]
ALL_SUPPORT_ROLE_IDS = [SUPPORT_ROLE_ID] + ADDITIONAL_SUPPORT_ROLE_IDS if SUPPORT_ROLE_ID else ADDITIONAL_SUPPORT_ROLE_IDS

if not TOKEN or CATEGORY_ID == 0:
    print("❌ Ошибка: не заданы DISCORD_TOKEN и CATEGORY_ID")
    sys.exit(1)

# ---------- Счётчик ----------
COUNTER_FILE = "data/application_counter.txt"
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

# ---------- Логирование (файлы) ----------
LOG_DIR = "logs_applications"
if os.path.exists(LOG_DIR) and not os.path.isdir(LOG_DIR):
    os.remove(LOG_DIR)
os.makedirs(LOG_DIR, exist_ok=True)

log_lock = asyncio.Lock()

def get_log_path(app_number: int) -> str:
    return os.path.join(LOG_DIR, f"application-{app_number:05d}.log")

async def write_app_log(app_number: int, text: str):
    async with log_lock:
        path = get_log_path(app_number)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")

async def read_app_log(app_number: int) -> str:
    path = get_log_path(app_number)
    if not os.path.exists(path):
        return "Лог пуст."
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

async def delete_app_log(app_number: int):
    path = get_log_path(app_number)
    if os.path.exists(path):
        os.remove(path)

# ---------- Бот ----------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

bot.category = None
bot.log_channel = None
bot.app_open_time = {}

# ---------- Модальное окно с ОДНИМ полем ----------
class ApplicationModal(discord.ui.Modal, title='📝 Заявка в группировку'):
    group_name = discord.ui.TextInput(
        label='Название группировки',
        placeholder='Введите название группировки',
        required=True,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Мгновенный ответ (defer)
        await interaction.response.defer(ephemeral=True)
        asyncio.create_task(self._handle(interaction))

    async def _handle(self, interaction: discord.Interaction):
        global counter
        try:
            group = self.group_name.value.strip()
            if not group:
                await interaction.followup.send("❌ Название группировки не может быть пустым.", ephemeral=True)
                return

            guild = interaction.guild
            category = bot.category
            if not category:
                await interaction.followup.send("❌ Категория не найдена.", ephemeral=True)
                return

            # Проверка существующей заявки
            existing = discord.utils.get(category.channels, topic=str(interaction.user.id))
            if existing:
                await interaction.followup.send(f"⚠️ У вас уже есть заявка: {existing.mention}", ephemeral=True)
                return

            # Роли поддержки
            support_roles = []
            for role_id in ALL_SUPPORT_ROLE_IDS:
                role = guild.get_role(role_id)
                if role:
                    support_roles.append(role)
            if not support_roles:
                await interaction.followup.send("❌ Ни одна из ролей поддержки не найдена.", ephemeral=True)
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
            for role in support_roles:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=str(interaction.user.id)
            )

            bot.app_open_time[current_number] = datetime.now()

            # Логируем открытие
            await write_app_log(current_number, f"🟢 ЗАЯВКА ОТКРЫТА")
            await write_app_log(current_number, f"   Пользователь: {interaction.user}")
            await write_app_log(current_number, f"   Группировка: {group}")

            # Отправляем в канал информацию о группировке + просьбу дополнить
            embed = discord.Embed(
                title=f"📋 Заявка #{current_number}",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Группировка", value=group, inline=False)
            embed.set_footer(text=f"От: {interaction.user.display_name}")

            await channel.send(embed=embed)

            # Сообщение с просьбой написать остальные пункты
            instruction = (
                "**Теперь напишите в этом канале следующие пункты (каждый с новой строки):**\n"
                "1. Ваш реальный возраст\n"
                "2. SteamID64\n"
                "3. Опыт игры на RP-проектах по STALKER RP DayZ\n"
                "4. Сколько часов в DayZ\n"
                "5. Ваш средний онлайн в день\n"
                "6. За какие группировки играли? / впервые на таком проекте\n\n"
                "Просто напишите ответы по порядку."
            )
            await channel.send(instruction)

            # Кнопка закрытия
            close_view = discord.ui.View()
            close_view.add_item(CloseApplicationButton())
            await channel.send("🔒 Кнопка закрытия заявки (только для администрации):", view=close_view)

            # Уведомление в лог-канал
            log_channel = bot.log_channel
            if log_channel:
                log_embed = discord.Embed(
                    title="📩 Новая заявка",
                    color=discord.Color.gold()
                )
                log_embed.add_field(name="Номер", value=f"#{current_number}", inline=False)
                log_embed.add_field(name="Пользователь", value=interaction.user.mention, inline=False)
                log_embed.add_field(name="Канал", value=channel.mention, inline=False)
                log_embed.add_field(name="Группировка", value=group, inline=False)
                await log_channel.send(embed=log_embed)

            await interaction.followup.send(f"✅ Заявка отправлена! Перейдите в {channel.mention}", ephemeral=True)

        except Exception as e:
            await interaction.followup.send("❌ Ошибка при создании заявки.", ephemeral=True)
            print(f"Ошибка в _handle: {e}")

# ---------- Кнопка "Подать заявку" ----------
class ApplyButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="📝 Подать заявку", style=discord.ButtonStyle.primary, custom_id="apply_button")

    async def callback(self, interaction: discord.Interaction):
        modal = ApplicationModal()
        await interaction.response.send_modal(modal)

# ---------- Кнопка закрытия ----------
class CloseApplicationButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Закрыть заявку", style=discord.ButtonStyle.danger, custom_id="close_application")

    async def callback(self, interaction: discord.Interaction):
        has_support_role = False
        for role_id in ALL_SUPPORT_ROLE_IDS:
            if interaction.user.get_role(role_id):
                has_support_role = True
                break
        if not has_support_role:
            await interaction.response.send_message("⛔ У вас нет прав на закрытие заявок.", ephemeral=True)
            return

        channel = interaction.channel
        if not channel.category or channel.category.id != CATEGORY_ID:
            await interaction.response.send_message("❌ Это не канал заявки.", ephemeral=True)
            return

        await interaction.response.send_message("⏳ Заявка закрывается...", ephemeral=True)

        try:
            app_number = int(channel.name.split('-')[-1])
        except:
            app_number = None

        if app_number:
            await write_app_log(app_number, f"🔴 ЗАЯВКА ЗАКРЫТА")
            await write_app_log(app_number, f"   Закрыл: {interaction.user}")

            log_channel = bot.log_channel
            if log_channel:
                log_content = await read_app_log(app_number)
                if log_content.strip():
                    temp_path = f"/tmp/application_{app_number:05d}.log"
                    with open(temp_path, "w", encoding="utf-8") as f:
                        f.write(log_content)
                    try:
                        await log_channel.send(
                            f"📄 Лог заявки #{app_number:05d} (ЗАКРЫТА)",
                            file=discord.File(temp_path, filename=f"application_{app_number:05d}.log")
                        )
                    except:
                        pass
                    os.remove(temp_path)
            await delete_app_log(app_number)
            if app_number in bot.app_open_time:
                del bot.app_open_time[app_number]

        await channel.delete()

# ---------- Представление с кнопкой ----------
class ApplicationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ApplyButton())

# ---------- Команды ----------
@bot.tree.command(name="setup", description="Создать сообщение с кнопкой для подачи заявок")
@app_commands.default_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 Подача заявки в группировку",
        description="Нажмите на кнопку ниже, чтобы заполнить анкету.",
        color=discord.Color.blue()
    )
    view = ApplicationView()
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="close", description="Закрыть текущий канал заявки")
async def close_application(interaction: discord.Interaction):
    channel = interaction.channel
    if not channel.category or channel.category.id != CATEGORY_ID:
        await interaction.response.send_message("❌ Это не канал заявки.", ephemeral=True)
        return

    has_support_role = False
    for role_id in ALL_SUPPORT_ROLE_IDS:
        if interaction.user.get_role(role_id):
            has_support_role = True
            break
    if not has_support_role:
        await interaction.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        return

    await interaction.response.send_message("⏳ Закрытие...", ephemeral=True)

    try:
        app_number = int(channel.name.split('-')[-1])
    except:
        app_number = None

    if app_number:
        await write_app_log(app_number, f"🔴 ЗАЯВКА ЗАКРЫТА")
        await write_app_log(app_number, f"   Закрыл: {interaction.user}")
        log_channel = bot.log_channel
        if log_channel:
            log_content = await read_app_log(app_number)
            if log_content.strip():
                temp_path = f"/tmp/application_{app_number:05d}.log"
                with open(temp_path, "w", encoding="utf-8") as f:
                    f.write(log_content)
                try:
                    await log_channel.send(
                        f"📄 Лог заявки #{app_number:05d} (ЗАКРЫТА)",
                        file=discord.File(temp_path, filename=f"application_{app_number:05d}.log")
                    )
                except:
                    pass
                os.remove(temp_path)
        await delete_app_log(app_number)
        if app_number in bot.app_open_time:
            del bot.app_open_time[app_number]

    await channel.delete()

# ---------- Обработчик сообщений (логирование переписки) ----------
@bot.event
async def on_message(message):
    if message.author.bot:
        await bot.process_commands(message)
        return

    if not message.channel.category or message.channel.category.id != CATEGORY_ID:
        await bot.process_commands(message)
        return

    channel_name = message.channel.name
    if not channel_name.startswith("заявка-"):
        await bot.process_commands(message)
        return

    try:
        app_number = int(channel_name.split('-')[-1])
    except:
        await bot.process_commands(message)
        return

    await write_app_log(app_number, f"💬 {message.author}: {message.content}")
    await bot.process_commands(message)

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
    print(f'✅ Бот {bot.user} запущен! Счётчик заявок: {counter}')
    guild = bot.guilds[0] if bot.guilds else None
    if not guild:
        print("⚠️ Бот не на сервере.")
        return
    bot.category = guild.get_channel(CATEGORY_ID)
    bot.log_channel = guild.get_channel(LOG_CHANNEL_ID)

    for role_id in ALL_SUPPORT_ROLE_IDS:
        role = guild.get_role(role_id)
        if role:
            print(f"✅ Роль {role.name} (ID: {role_id}) найдена.")
        else:
            print(f"⚠️ Роль с ID {role_id} не найдена.")

    if not bot.category: print(f"⚠️ Категория {CATEGORY_ID} не найдена.")
    if not bot.log_channel: print(f"⚠️ Лог-канал {LOG_CHANNEL_ID} не найден.")

    try:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            synced = await bot.tree.sync(guild=guild)
            print(f"🔄 Синхронизировано {len(synced)} команд для сервера {GUILD_ID}")
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
