import asyncio
import random
import re
import string
import logging
from typing import Tuple
from collections import defaultdict

# Библиотеки для работы
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from telethon import TelegramClient, functions, types as tg_types
from telethon.errors import FloodWaitError, ChannelsAdminPublicSegmentsTooManyError

# ═══════════════════════════════════════════════════════════════════════════
# ТВОИ ДАННЫЕ (УЖЕ ПОДСТАВЛЕНЫ)
# ═══════════════════════════════════════════════════════════════════════════
API_ID = 37550489
API_HASH = "4351af9b85689203f34bbcf9f3568deb"
BOT_TOKEN = "8679245171:AAFXKI5-nWJvr32gpTTVD0xK6auXur3_I7I"
PHONE_NUMBER = "+918453061473"

AUTO_CLAIM_THRESHOLD = 90  # Порог редкости для авто-захвата
BASE_CHECK_DELAY = 1.3     # Безопасная пауза
VOWELS = "aeiouy"
CONSONANTS = "bcdfghjklmnprstvwxz"

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s]: %(message)s')
logger = logging.getLogger(__name__)

class UsernameStates(StatesGroup):
    waiting_for_sniper_username = State()
    waiting_for_quick_check = State()

# ═══════════════════════════════════════════════════════════════════════════
# ЛОГИКА РАБОТЫ С ЮЗЕРНЕЙМАМИ
# ═══════════════════════════════════════════════════════════════════════════
class UsernameManager:
    def __init__(self, telethon_client: TelegramClient, bot: Bot):
        self.client = telethon_client
        self.bot = bot

    async def check_username_available(self, username: str) -> bool:
        try:
            await asyncio.sleep(BASE_CHECK_DELAY)
            return await self.client(functions.account.CheckUsernameRequest(username))
        except FloodWaitError as e:
            logger.warning(f"🚫 Флуд-фильтр: ждем {e.seconds} сек")
            await asyncio.sleep(e.seconds + 2)
            return False
        except Exception as e:
            logger.error(f"❌ Ошибка API: {e}")
            return False

    async def claim_via_group(self, username: str, user_id: int):
        """УМНЫЙ ЗАХВАТ: Группа -> Супергруппа -> Юзернейм"""
        try:
            logger.info(f"🚀 ПОПЫТКА ЗАХВАТА: @{username}")
            # Создаем чат
            created_chat = await self.client(functions.messages.CreateChatRequest(
                users=['me'], title=f"Reserved @{username}"
            ))
            chat_id = created_chat.chats[0].id
            # Делаем супергруппой
            upgrade = await self.client(functions.messages.MigrateChatRequest(chat_id=chat_id))
            supergroup = upgrade.chats[0]
            # Ставим юзернейм
            await self.client(functions.channels.UpdateUsernameRequest(
                channel=tg_types.InputChannel(supergroup.id, supergroup.access_hash),
                username=username
            ))
            await self.bot.send_message(user_id, f"🔥 **НИК ЗАБРОНИРОВАН!**\nЮзернейм @{username} теперь в твоем чате!")
            return True
        except ChannelsAdminPublicSegmentsTooManyError:
            await self.bot.send_message(user_id, "❌ Лимит публичных чатов (10) исчерпан!")
        except Exception as e:
            await self.bot.send_message(user_id, f"⚠️ Не удалось забрать @{username}: {e}")
        return False

    def calculate_ai_score(self, username: str) -> Tuple[int, str]:
        score = 50
        name = username.lower()
        if all((c in VOWELS) != (name[i-1] in VOWELS) for i, c in enumerate(name) if i > 0): score += 25
        if any(name.endswith(x) for x in ['7', '1', '0']): score += 15
        if name == name[::-1]: score += 10
        score = min(score, 100)
        emoji = "🔥 PREMIUM" if score >= 90 else "✨ RARE" if score >= 80 else "⭐ OK"
        return score, emoji

    def generate_readable(self, count=10):
        res = set()
        while len(res) < count:
            name = "".join(random.choice(CONSONANTS if i % 2 == 0 else VOWELS) for i in range(random.choice([5, 6])))
            res.add(name)
        return list(res)

# ═══════════════════════════════════════════════════════════════════════════
# СНАЙПЕР И БОТ
# ═══════════════════════════════════════════════════════════════════════════
class SnipeManager:
    def __init__(self, bot: Bot, manager: UsernameManager):
        self.bot = bot
        self.manager = manager
        self.monitored = defaultdict(list)
        self.tasks = {}

    async def _loop(self, user_id):
        while True:
            for username in list(self.monitored[user_id]):
                if await self.manager.check_username_available(username):
                    score, _ = self.manager.calculate_ai_score(username)
                    if score >= AUTO_CLAIM_THRESHOLD:
                        await self.manager.claim_via_group(username, user_id)
                    else:
                        await self.bot.send_message(user_id, f"🔔 @{username} свободен!")
                    self.monitored[user_id].remove(username)
                await asyncio.sleep(15)
            await asyncio.sleep(5)

async def main():
    client = TelegramClient('vildan_session', API_ID, API_HASH)
    await client.start(phone=PHONE_NUMBER)
    bot = Bot(token=BOT_TOKEN); dp = Dispatcher()
    mgr = UsernameManager(client, bot); sniper = SnipeManager(bot, mgr)

    @dp.message(Command("start"))
    async def cmd_start(m: types.Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Поиск 5-6 букв", callback_data="gen_read")],
            [InlineKeyboardButton(text="🎯 Снайпер (Слежка)", callback_data="snipe_menu")],
            [InlineKeyboardButton(text="🔍 Проверить один", callback_data="check_one")]
        ])
        await m.answer("👋 Бот-снайпер запущен!\nИщу ники и забираю редкие (90+) в чаты автоматически.", reply_markup=kb)

    @dp.callback_query(F.data == "gen_read")
    async def gen_read(call: types.CallbackQuery):
        await call.answer("Проверяю пачку ников...")
        for n in mgr.generate_readable(8):
            if await mgr.check_username_available(n):
                score, _ = mgr.calculate_ai_score(n)
                if score >= AUTO_CLAIM_THRESHOLD: await mgr.claim_via_group(n, call.from_user.id)
                else: await call.message.answer(f"✅ Свободен: @{n} (Score: {score})")
        await call.message.answer("Пачка проверена.")

    @dp.callback_query(F.data == "snipe_menu")
    async def snipe_menu(call: types.CallbackQuery, state: FSMContext):
        await call.message.answer("Введи юзернейм для слежки:")
        await state.set_state(UsernameStates.waiting_for_sniper_username)

    @dp.message(UsernameStates.waiting_for_sniper_username)
    async def add_snipe(m: types.Message, state: FSMContext):
        name = m.text.strip().lower().replace("@", "")
        sniper.monitored[m.from_user.id].append(name)
        if m.from_user.id not in sniper.tasks: sniper.tasks[m.from_user.id] = asyncio.create_task(sniper._loop(m.from_user.id))
        await m.answer(f"📍 Добавил @{name} в мониторинг."); await state.clear()

    @dp.callback_query(F.data == "check_one")
    async def check_one(call: types.CallbackQuery, state: FSMContext):
        await call.message.answer("Введи ник для проверки:"); await state.set_state(UsernameStates.waiting_for_quick_check)

    @dp.message(UsernameStates.waiting_for_quick_check)
    async def quick_check(m: types.Message, state: FSMContext):
        name = m.text.strip().lower().replace("@", "")
        if await mgr.check_username_available(name):
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚡️ ЗАБРАТЬ В ЧАТ", callback_data=f"claim_now_{name}")]])
            await m.answer(f"✅ @{name} свободен!", reply_markup=kb)
        else: await m.answer(f"❌ @{name} занят."); await state.clear()

    @dp.callback_query(F.data.startswith("claim_now_"))
    async def manual_claim(call: types.CallbackQuery):
        await mgr.claim_via_group(call.data.replace("claim_now_", ""), call.from_user.id)

    print("🤖 БОТ ЗАПУЩЕН. Команды принимаются в Telegram!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
