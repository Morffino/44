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
GUILD_ID = int(os.getenv('GUILD_ID', 0))

CATEGORY_ID = 1529178033100165324
LOG_CHANNEL_ID = 1532376168173404170

# Роли поддержки (старые)
ALL_SUPPORT_ROLE_IDS = [
    1529252048883810485,
    1529253808666841302,
    1529253952850366616,
    1529254103820275823
]

# Сопоставление группировок и ID их ролей (для добавления в канал на чтение)
GROUP_ROLE_IDS = {
    "Свобода": 1529254394908905576,
    "Нейтралы": 1529254524584329286,
    "Наёмники": 1529254566988615901,
    "Братки": 1529254606843154442,
    "Военные": 1529254665768931460,
    "ОКСОП": 1529254686060839092,
    "Долг": 1529254754767605911,
    "Монолит": 1529254797851623535,
    "Грех": 1529254838804807791,
    "Учёные": 1529254886963937321,
    "Охрана Деревни": 1529255019969253427,
    "Охрана Бара": 1529255117918830773,
    "Ренегаты": 1529255157496545380,
    "Чистое Небо": 1529255242758230156,
    "Амбрелла": 1529256543164301432
}

VALID_GROUPS = list(GROUP_ROLE_IDS.keys())
VALID_GROUPS_LOWER = {g.lower(): g for g in VALID_GROUPS}

if not TOKEN:
    print("❌ Ошибка: не задан DISCORD_TOKEN в .env")
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

# ---------- Модальное окно подтверждения закрытия ----------
class ConfirmCloseModal(discord.ui.Modal, title='Подтверждение закрытия заявки'):
    reason = discord.ui.TextInput(
        label='Причина закрытия (необязательно)',
        placeholder='Укажите причину или оставьте пустым',
        required=False,
        max_length=200
    )

    async def on_submit(self, interaction: discord.Interaction):
        channel = interaction.channel
        if not channel.category or channel.category.id != CATEGORY_ID:
            await interaction.response.send_message("❌ Это не канал заявки.", ephemeral=True)
            return

        creator_id = channel.topic
        if creator_id is None:
            await interaction.response.send_message("❌ Не удалось определить создателя.", ephemeral=True)
            return
        creator_id = int(creator_id)

        # Проверка прав: только создатель или поддержка
        has_support_role = False
        for role_id in ALL_SUPPORT_ROLE_IDS:
            if interaction.user.get_role(role_id):
                has_support_role = True
                break

        if interaction.user.id != creator_id and not has_support_role:
            await interaction.response.send_message("⛔ У вас нет прав на закрытие этой заявки.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            app_number = int(channel.name.split('-')[-1])
        except:
            app_number = None

        if app_number:
            await write_app_log(app_number, f"🔴 ЗАЯВКА ЗАКРЫТА")
            await write_app_log(app_number, f"   Закрыл: {interaction.user}")
            if self.reason.value:
                await write_app_log(app_number, f"   Причина: {self.reason.value}")

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
        await interaction.followup.send("✅ Заявка закрыта.", ephemeral=True)

# ---------- Модальное окно заявки ----------
class ApplicationModal(discord.ui.Modal, title='📝 Заявка в группировку'):
    group_name = discord.ui.TextInput(
        label='Название группировки',
        placeholder='Введите точное название из списка',
        required=True,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        asyncio.create_task(self._handle(interaction))

    async def _handle(self, interaction: discord.Interaction):
        global counter
        try:
            group_raw = self.group_name.value.strip()
            if not group_raw:
                await interaction.followup.send("❌ Название группировки не может быть пустым.", ephemeral=True)
                return

            group_lower = group_raw.lower()
            if group_lower not in VALID_GROUPS_LOWER:
                groups_list = "\n".join(VALID_GROUPS)
                await interaction.followup.send(
                    f"❌ Группировка **{group_raw}** не найдена.\n\n"
                    f"Доступные группировки:\n{groups_list}",
                    ephemeral=True
                )
                return

            group = VALID_GROUPS_LOWER[group_lower]
            guild = interaction.guild
            category = bot.category

            if category is None or not isinstance(category, discord.CategoryChannel):
                await interaction.followup.send("❌ Категория не найдена или указан неверный ID.", ephemeral=True)
                return

            existing = discord.utils.get(category.channels, topic=str(interaction.user.id))
            if existing:
                await interaction.followup.send(f"⚠️ У вас уже есть заявка: {existing.mention}", ephemeral=True)
                return

            support_roles = []
            for role_id in ALL_SUPPORT_ROLE_IDS:
                role = guild.get_role(role_id)
                if role:
                    support_roles.append(role)
            if not support_roles:
                await interaction.followup.send("❌ Ни одна из ролей поддержки не найдена.", ephemeral=True)
                return

            async with counter_lock:
                current_number = counter
                counter += 1
                save_counter(counter)

            channel_name = f"заявка-{interaction.user.name.lower()}-{current_number}"

            # Настройка прав доступа
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            }

            # Роли поддержки – могут читать и писать
            for role in support_roles:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

            # Роль группировки – только чтение
            group_role_id = GROUP_ROLE_IDS.get(group)
            if group_role_id:
                group_role = guild.get_role(group_role_id)
                if group_role:
                    overwrites[group_role] = discord.PermissionOverwrite(view_channel=True, send_messages=False)

            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=str(interaction.user.id)
            )

            bot.app_open_time[current_number] = datetime.now()

            await write_app_log(current_number, f"🟢 ЗАЯВКА ОТКРЫТА")
            await write_app_log(current_number, f"   Пользователь: {interaction.user}")
            await write_app_log(current_number, f"   Группировка: {group}")

            embed = discord.Embed(
                title=f"📋 Заявка #{current_number}",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Группировка", value=group, inline=False)
            embed.set_footer(text=f"От: {interaction.user.display_name}")
            await channel.send(embed=embed)

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

            # --- Две кнопки закрытия ---
            close_view = discord.ui.View()
            close_view.add_item(CloseForCreatorButton())  # для создателя
            close_view.add_item(CloseForAdminButton())    # для админов
            await channel.send("🔒 Кнопки закрытия заявки:", view=close_view)

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

        except discord.Forbidden:
            await interaction.followup.send("❌ У бота недостаточно прав для создания канала. Проверьте права.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Ошибка Discord: {e.text if hasattr(e, 'text') else str(e)}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка: {type(e).__name__}: {str(e)}", ephemeral=True)
            print(f"Ошибка в _handle: {type(e).__name__}: {e}")

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        try:
            await interaction.response.send_message(
                f"❌ Критическая ошибка: {type(error).__name__}: {error}",
                ephemeral=True
            )
        except:
            try:
                await interaction.followup.send(
                    f"❌ Критическая ошибка: {type(error).__name__}: {error}",
                    ephemeral=True
                )
            except:
                pass
        print(f"Ошибка в on_error: {type(error).__name__}: {error}")

# ---------- Кнопка "Подать заявку" ----------
class ApplyButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="📝 Подать заявку", style=discord.ButtonStyle.primary, custom_id="apply_button")

    async def callback(self, interaction: discord.Interaction):
        modal = ApplicationModal()
        await interaction.response.send_modal(modal)

# ---------- Кнопка закрытия для создателя ----------
class CloseForCreatorButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🔒 Закрыть (создатель)", style=discord.ButtonStyle.secondary, custom_id="close_creator")

    async def callback(self, interaction: discord.Interaction):
        # Проверяем, что пользователь – создатель канала
        channel = interaction.channel
        creator_id = channel.topic
        if creator_id is None:
            await interaction.response.send_message("❌ Не удалось определить создателя.", ephemeral=True)
            return
        creator_id = int(creator_id)
        if interaction.user.id != creator_id:
            await interaction.response.send_message("❌ Эта кнопка только для создателя заявки.", ephemeral=True)
            return
        modal = ConfirmCloseModal()
        await interaction.response.send_modal(modal)

# ---------- Кнопка закрытия для админов ----------
class CloseForAdminButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🔒 Закрыть (админ)", style=discord.ButtonStyle.danger, custom_id="close_admin")

    async def callback(self, interaction: discord.Interaction):
        # Проверяем, есть ли у пользователя роль поддержки
        has_support_role = False
        for role_id in ALL_SUPPORT_ROLE_IDS:
            if interaction.user.get_role(role_id):
                has_support_role = True
                break
        if not has_support_role:
            await interaction.response.send_message("⛔ У вас нет прав администратора.", ephemeral=True)
            return
        modal = ConfirmCloseModal()
        await interaction.response.send_modal(modal)

# ---------- Представление с кнопкой ----------
class ApplicationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ApplyButton())

# ---------- Команды ----------
@bot.tree.command(name="setup", description="Создать сообщение с кнопкой для подачи заявок")
@app_commands.default_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    groups_text = "\n".join(VALID_GROUPS)
    embed = discord.Embed(
        title="📋 Подача заявки в группировку",
        description=(
            "Нажмите на кнопку ниже, чтобы заполнить анкету.\n\n"
            "**Доступные группировки:**\n" + groups_text
        ),
        color=discord.Color.blue()
    )
    view = ApplicationView()
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="close", description="Быстро закрыть текущий канал заявки (без подтверждения)")
async def close_application(interaction: discord.Interaction):
    channel = interaction.channel
    if not channel.category or channel.category.id != CATEGORY_ID:
        await interaction.response.send_message("❌ Это не канал заявки.", ephemeral=True)
        return

    creator_id = channel.topic
    if creator_id is None:
        await interaction.response.send_message("❌ Не удалось определить создателя.", ephemeral=True)
        return
    creator_id = int(creator_id)

    has_support_role = False
    for role_id in ALL_SUPPORT_ROLE_IDS:
        if interaction.user.get_role(role_id):
            has_support_role = True
            break

    if interaction.user.id != creator_id and not has_support_role:
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

# ---------- Обработчик сообщений ----------
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

# ---------- Веб-сервер ----------
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

    category_obj = guild.get_channel(CATEGORY_ID)
    if category_obj is None or not isinstance(category_obj, discord.CategoryChannel):
        print(f"❌ Категория {CATEGORY_ID} не найдена или не является категорией.")
        bot.category = None
    else:
        bot.category = category_obj
        print(f"✅ Категория {category_obj.name} (ID: {CATEGORY_ID}) найдена.")

    bot.log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if not bot.log_channel:
        print(f"⚠️ Лог-канал {LOG_CHANNEL_ID} не найден.")

    for role_id in ALL_SUPPORT_ROLE_IDS:
        role = guild.get_role(role_id)
        if role:
            print(f"✅ Роль поддержки {role.name} (ID: {role_id}) найдена.")
        else:
            print(f"⚠️ Роль поддержки с ID {role_id} не найдена.")

    for group, role_id in GROUP_ROLE_IDS.items():
        role = guild.get_role(role_id)
        if role:
            print(f"✅ Роль {group} (ID: {role_id}) найдена.")
        else:
            print(f"⚠️ Роль {group} с ID {role_id} не найдена.")

    if bot.category is None:
        print("⚠️ Бот запущен, но заявки не будут работать до исправления CATEGORY_ID.")

    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=GUILD_ID)
            synced = await bot.tree.sync(guild=guild_obj)
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
