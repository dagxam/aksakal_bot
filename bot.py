from __future__ import annotations

import asyncio
import html
import random
import time
from typing import Any

import aiohttp

from config import config
from db import Database
from generator import PhraseGenerator


class TelegramAPI:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}"
        self.session: aiohttp.ClientSession | None = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
        return self

    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()

    async def call(self, method: str, **payload):
        assert self.session
        async with self.session.post(f"{self.base}/{method}", json=payload) as r:
            data = await r.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram {method}: {data}")
            return data["result"]

    async def send(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
        reply_markup: dict[str, Any] | None = None,
    ):
        payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if reply_to_message_id:
            payload["reply_parameters"] = {"message_id": reply_to_message_id, "allow_sending_without_reply": True}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self.call("sendMessage", **payload)

    async def edit(self, chat_id: int, message_id: int, text: str, reply_markup: dict[str, Any] | None = None):
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "disable_web_page_preview": True}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self.call("editMessageText", **payload)


class AksakalBot:
    STOP_WORDS = {
        "это","как","что","чтобы","когда","тогда","тут","там","где","кто","она","они","оно","его","ее","её",
        "для","про","под","над","или","если","уже","ещё","еще","вот","был","была","были","будет","есть","нет",
        "да","не","ни","ну","же","бы","ли","то","из","на","по","за","от","до","во","со","мы","вы","ты","я",
        "мне","тебе","ему","нам","вам","их","мой","твой","наш","ваш","свой","так","такой","такая","такие",
        "просто","очень","тоже","только","можно","надо","нужно","потом","сейчас","сегодня","вчера","завтра"
    }

    def __init__(self):
        if not config.telegram_token:
            raise SystemExit("TELEGRAM_BOT_TOKEN не задан. Скопируйте .env.example в .env")
        self.db = Database(config.database_path)
        self.generator = PhraseGenerator(config.openai_api_key, config.openai_model, config.ai_enabled)
        self.offset = 0
        self.tg: TelegramAPI | None = None
        self.pending_reply_tasks: dict[int, asyncio.Task] = {}

    @classmethod
    def extract_learning_tokens(cls, text: str) -> list[str]:
        import re
        words = re.findall(r"[A-Za-zА-Яа-яЁё0-9_+-]{3,}", (text or "").lower())
        words = [w for w in words if w not in cls.STOP_WORDS and not w.startswith("http") and not w.startswith("@")]
        # Плюс короткие устойчивые пары — именно они часто становятся локальными мемами.
        pairs = [f"{words[i]} {words[i+1]}" for i in range(len(words)-1) if len(words[i]) + len(words[i+1]) <= 40]
        return (words + pairs)[:40]

    @staticmethod
    def detect_address_feedback(text: str) -> dict[str, Any] | None:
        import re
        low = " ".join((text or "").lower().replace("ё", "е").split())
        if not low:
            return None

        explicit_female = [
            r"\bя\s+(?:девушка|женщина)\b",
        ]
        explicit_male = [
            r"\bя\s+(?:парень|мужчина)\b",
        ]
        if any(re.search(p, low) for p in explicit_female):
            return {"profile": "female", "avoid": [], "explicit": True}
        if any(re.search(p, low) for p in explicit_male):
            return {"profile": "male", "avoid": [], "explicit": True}

        address_tokens = {
            "вацок": "male", "уцы": "male", "брат": "male",
            "тетка": "female", "теткой": "female", "сестра": "female",
            "ле": "neutral", "йо": "neutral",
        }
        denied = []
        for token in address_tokens:
            patterns = [
                rf"\bя\s+не\s+{re.escape(token)}\b",
                rf"\bне\s+называй\s+меня\s+{re.escape(token)}\b",
                rf"\bне\s+зови\s+меня\s+{re.escape(token)}\b",
            ]
            if any(re.search(p, low) for p in patterns):
                denied.append(token)

        if denied:
            # Одно отрицание не используем для скрытого вывода о поле.
            return {"profile": None, "avoid": denied, "explicit": False}
        return None


    @staticmethod
    def detect_greeting_style(text: str) -> str | None:
        import re
        low = " ".join((text or "").lower().replace("ё", "е").split())
        if not low:
            return None

        # Нормальные для стиля Аксакала варианты салама.
        salam_patterns = [
            r"\bасс?ал(?:а|я)м[у]?[\s-]+алейкум\b",
            r"\bас[\s-]*сал(?:а|я)м[у]?[\s-]+алейкум\b",
            r"\bсал(?:а|я)м[у]?[\s-]+алейкум\b",
            r"\bасс?аляму[\s-]+алейкум\b",
        ]
        if any(re.search(p, low) for p in salam_patterns):
            return "salam"
        if re.search(r"^\s*(?:асс?алам|салам)(?:\s|[!,.?]|$)", low):
            return "salam"

        generic_patterns = [
            r"^\s*привет(?:ик|ики)?\b",
            r"^\s*здравствуй(?:те)?\b",
            r"^\s*здоров(?:а|о|еньки)?\b",
            r"^\s*доброе\s+(?:утро|утречко)\b",
            r"^\s*добрый\s+(?:день|вечер)\b",
            r"^\s*салют\b",
            r"^\s*хай\b",
            r"^\s*hello\b",
            r"^\s*hi\b",
        ]
        if any(re.search(p, low) for p in generic_patterns):
            return "generic"
        return None


    async def run(self):
        async with TelegramAPI(config.telegram_token) as tg:
            self.tg = tg
            # Long polling не работает, пока у бота установлен webhook.
            await tg.call("deleteWebhook", drop_pending_updates=False)

            me = await tg.call("getMe")
            await self.configure_bot_profile()
            print(f"Аксакал запущен: @{me.get('username')}")
            worker = asyncio.create_task(self.silence_worker())
            try:
                await self.poll()
            finally:
                worker.cancel()

    async def configure_bot_profile(self):
        assert self.tg
        commands = [
            {"command": "start", "description": "Как работает Аксакал"},
            {"command": "settings", "description": "Настройки кнопками"},
            {"command": "status", "description": "Текущие настройки"},
            {"command": "roast", "description": "Подколоть ответом на сообщение"},
            {"command": "test", "description": "Проверить бота"},
        ]
        await self.tg.call("setMyCommands", commands=commands)
        await self.tg.call("setMyName", name="Аксакал")
        await self.tg.call(
            "setMyDescription",
            description="Живой участник группы: понимает тему разговора, подкалывает, поддерживает, успокаивает и оживляет чат.",
        )
        await self.tg.call(
            "setMyShortDescription",
            short_description="Подколы, поддержка, мудрость и живой чат.",
        )

    async def poll(self):
        assert self.tg
        allowed = ["message", "edited_message", "message_reaction", "my_chat_member", "chat_member", "callback_query"]
        while True:
            try:
                updates = await self.tg.call(
                    "getUpdates",
                    offset=self.offset,
                    timeout=45,
                    allowed_updates=allowed,
                )
                for update in updates:
                    self.offset = update["update_id"] + 1
                    await self.handle_update(update)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print("poll error:", e)
                await asyncio.sleep(3)

    async def handle_update(self, update: dict[str, Any]):
        if "message" in update:
            await self.handle_message(update["message"])
        elif "callback_query" in update:
            await self.handle_callback(update["callback_query"])
        elif "message_reaction" in update:
            await self.handle_reaction(update["message_reaction"])
        elif "my_chat_member" in update:
            await self.handle_my_chat_member(update["my_chat_member"])

    async def handle_my_chat_member(self, upd: dict[str, Any]):
        if not self.tg:
            return
        chat = upd.get("chat", {})
        if chat.get("type") not in {"group", "supergroup"}:
            return
        old_status = (upd.get("old_chat_member") or {}).get("status")
        new_status = (upd.get("new_chat_member") or {}).get("status")
        if old_status in {"left", "kicked"} and new_status in {"member", "administrator"}:
            chat_id = int(chat["id"])
            self.db.ensure_chat(
                chat_id,
                chat.get("title"),
                config.default_roast_level,
                config.min_bot_interval_minutes,
                config.silence_trigger_minutes,
            )
            await self.tg.send(
                chat_id,
                "Аксакал на месте. Для проверки напиши /test. "
                "Чтобы я видел обычные сообщения и реакции, сделай меня администратором "
                "и отключи Privacy Mode через @BotFather → /setprivacy → Disable.",
            )

    async def handle_message(self, msg: dict[str, Any]):
        chat = msg.get("chat", {})
        if chat.get("type") not in {"group", "supergroup"}:
            text = msg.get("text", "")
            if text.startswith("/start") and self.tg:
                await self.tg.send(
                    chat["id"],
                    "Добавь меня в группу, назначь администратором и отключи Privacy Mode: "
                    "@BotFather → /setprivacy → выбери бота → Disable. "
                    "После этого в группе напиши /test.",
                )
            elif text.startswith("/help") and self.tg:
                await self.tg.send(
                    chat["id"],
                    "Основное: /settings — настройки кнопками, /status — состояние, /test — проверка.",
                )
            return

        chat_id = int(chat["id"])
        self.db.ensure_chat(chat_id, chat.get("title"), config.default_roast_level, config.min_bot_interval_minutes, config.silence_trigger_minutes)

        sender = msg.get("from")
        if not sender or sender.get("is_bot"):
            return

        text = msg.get("text") or msg.get("caption") or ""
        sticker = msg.get("sticker")
        kind = "sticker" if sticker else "message"
        if sticker:
            text = sticker.get("emoji") or "стикер"

        user_id = self.db.touch_user(chat_id, sender, kind)
        username = sender.get("username") or ""
        display = " ".join(x for x in [sender.get("first_name"), sender.get("last_name")] if x).strip() or username or str(user_id)
        self.db.add_message(chat_id, msg["message_id"], user_id, username, display, kind, text)

        if kind == "message" and text and not text.startswith("/"):
            self.db.learn_tokens(chat_id, user_id, self.extract_learning_tokens(text))
            feedback = self.detect_address_feedback(text)
            if feedback:
                if feedback["profile"]:
                    self.db.set_profile(chat_id, user_id, feedback["profile"])
                for token in feedback["avoid"]:
                    self.db.avoid_address(chat_id, user_id, token)

        if text.startswith("/"):
            old_task = self.pending_reply_tasks.pop(chat_id, None)
            if old_task and not old_task.done():
                old_task.cancel()
            await self.handle_command(msg, text)
            return

        await self.maybe_emotional_response(chat_id, msg)

    async def handle_reaction(self, upd: dict[str, Any]):
        chat = upd.get("chat", {})
        if chat.get("type") not in {"group", "supergroup"}:
            return
        user = upd.get("user")
        if not user or user.get("is_bot"):
            return
        chat_id = int(chat["id"])
        self.db.ensure_chat(chat_id, chat.get("title"), config.default_roast_level, config.min_bot_interval_minutes, config.silence_trigger_minutes)
        user_id = self.db.touch_user(chat_id, user, "reaction")
        reactions = []
        for r in upd.get("new_reaction", []):
            reactions.append(r.get("emoji") or "custom_emoji")
        content = "реакция " + " ".join(reactions) if reactions else "реакция убрана"
        username = user.get("username") or ""
        display = " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x).strip() or username or str(user_id)
        self.db.add_message(chat_id, upd.get("message_id", 0), user_id, username, display, "reaction", content)

        if reactions and random.random() < 0.08:
            await self.roast(
                chat_id,
                user_id,
                "пользователь поставил реакцию вместо сообщения",
                source_text=content,
                source_kind="reaction",
            )

    @staticmethod
    def settings_keyboard(chat: dict[str, Any]) -> dict[str, Any]:
        mode = chat.get("hardness_mode", "auto")
        fixed = int(chat.get("fixed_hardness", 3))
        delay = int(chat.get("response_delay_seconds", 20))
        enabled = bool(chat.get("enabled", 1))

        def mark(label: str, active: bool) -> str:
            return ("✅ " if active else "") + label

        return {
            "inline_keyboard": [
                [
                    {"text": mark("AUTO", mode == "auto"), "callback_data": "set:hard:auto"},
                    {"text": mark("1", mode == "fixed" and fixed == 1), "callback_data": "set:hard:1"},
                    {"text": mark("2", mode == "fixed" and fixed == 2), "callback_data": "set:hard:2"},
                    {"text": mark("3", mode == "fixed" and fixed == 3), "callback_data": "set:hard:3"},
                    {"text": mark("4", mode == "fixed" and fixed == 4), "callback_data": "set:hard:4"},
                    {"text": mark("🔥 5", mode == "fixed" and fixed == 5), "callback_data": "set:hard:5"},
                ],
                [
                    {"text": mark("3 сек", delay == 3), "callback_data": "set:time:3"},
                    {"text": mark("5 сек", delay == 5), "callback_data": "set:time:5"},
                    {"text": mark("20 сек", delay == 20), "callback_data": "set:time:20"},
                    {"text": mark("40 сек", delay == 40), "callback_data": "set:time:40"},
                ],
                [
                    {"text": mark("1 мин", delay == 60), "callback_data": "set:time:60"},
                    {"text": mark("3 мин", delay == 180), "callback_data": "set:time:180"},
                ],
                [
                    {"text": mark("🟢 Включён", enabled), "callback_data": "set:bot:on"},
                    {"text": mark("🔴 Выключен", not enabled), "callback_data": "set:bot:off"},
                ],
            ]
        }

    @staticmethod
    def settings_text(chat: dict[str, Any]) -> str:
        mode = chat.get("hardness_mode", "auto")
        hardness = "AUTO" if mode == "auto" else f"{int(chat.get('fixed_hardness', 3))}/5"
        delay = int(chat.get("response_delay_seconds", 20))
        delay_label = {3: "3 сек", 5: "5 сек", 20: "20 сек", 40: "40 сек", 60: "1 мин", 180: "3 мин"}.get(delay, f"{delay} сек")
        return (
            "⚙️ Настройки Аксакала\n"
            f"Жёсткость: {hardness}\n"
            f"Таймер тишины: {delay_label}\n"
            f"Состояние: {'включён' if chat.get('enabled', 1) else 'выключен'}\n\n"
            "После этого времени без новых сообщений отвечаю на последнее.\n"
            "Можно нажать кнопку или написать: /hardness 5, /hardness auto, /time 3"
        )

    async def show_settings(self, chat_id: int):
        assert self.tg
        chat = self.db.get_chat(chat_id) or {}
        await self.tg.send(chat_id, self.settings_text(chat), reply_markup=self.settings_keyboard(chat))

    async def handle_callback(self, query: dict[str, Any]):
        assert self.tg
        data = query.get("data") or ""
        msg = query.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = int(chat.get("id", 0) or 0)
        user_id = int((query.get("from") or {}).get("id", 0) or 0)
        callback_id = query.get("id")
        if not chat_id or not user_id or not data.startswith("set:"):
            if callback_id:
                await self.tg.call("answerCallbackQuery", callback_query_id=callback_id)
            return

        if not await self.is_admin(chat_id, user_id):
            if callback_id:
                await self.tg.call("answerCallbackQuery", callback_query_id=callback_id, text="Только администратор.", show_alert=True)
            return

        parts = data.split(":")
        if len(parts) != 3:
            return
        section, value = parts[1], parts[2]

        if section == "hard":
            if value == "auto":
                self.db.update_chat(chat_id, hardness_mode="auto")
            elif value in {"1", "2", "3", "4", "5"}:
                self.db.update_chat(chat_id, hardness_mode="fixed", fixed_hardness=int(value))
        elif section == "time" and value in {"3", "5", "20", "40", "60", "180"}:
            self.db.update_chat(chat_id, response_delay_seconds=int(value))
        elif section == "bot":
            self.db.update_chat(chat_id, enabled=1 if value == "on" else 0)

        if callback_id:
            await self.tg.call("answerCallbackQuery", callback_query_id=callback_id, text="Сохранено")
        fresh = self.db.get_chat(chat_id) or {}
        try:
            await self.tg.edit(chat_id, int(msg.get("message_id", 0)), self.settings_text(fresh), self.settings_keyboard(fresh))
        except Exception:
            await self.show_settings(chat_id)

    async def handle_command(self, msg: dict[str, Any], text: str):
        assert self.tg
        chat_id = int(msg["chat"]["id"])
        user_id = int(msg["from"]["id"])
        cmd, *rest = text.split(maxsplit=1)
        cmd = cmd.split("@")[0].lower()
        arg = rest[0].strip() if rest else ""

        if cmd in {"/help", "/start"}:
            await self.tg.send(
                chat_id,
                "Команды Аксакала:\n"
                "/settings — выбрать жёсткость и время кнопками\n"
                "/status — текущие настройки\n"
                "/roast — подколоть ответом на сообщение\n"
                "/test — проверить бота\n\n"
                "Быстро вручную: /hardness auto|1|2|3|4|5 и /time 3|5|20|40|60|180",
            )
            return

        if cmd in {"/settings", "/aksakal"}:
            if not await self.is_admin(chat_id, user_id):
                await self.tg.send(chat_id, "Настройки может менять администратор группы.")
                return
            await self.show_settings(chat_id)
            return

        if cmd == "/test":
            await self.tg.send(chat_id, "Аксакал жив. Всё вижу, всё запоминаю. Теперь говорите осторожнее 😏")
            return

        if cmd in {"/status", "/aksakal"}:
            c = self.db.get_chat(chat_id) or {}
            await self.tg.send(
                chat_id,
                f"Аксакал включён: {'да' if c.get('enabled',1) else 'нет'}\n"
                f"AI: {'включён — ответы генерируются по контексту' if self.generator.enabled else 'НЕ ВКЛЮЧЁН — сейчас используются готовые fallback-фразы'}\n"
                f"Жёсткость: {('AUTO — сам выбираю 1–5 по беседе') if c.get('hardness_mode','auto') == 'auto' else ('фиксированная ' + str(c.get('fixed_hardness',3)) + '/5')}\n"
                f"Таймер тишины: {c.get('response_delay_seconds',20)} сек\n"
                f"Молчание: {c.get('silence_minutes',180)} мин\n"
                f"Контекст: {len(self.db.recent_context(chat_id, config.context_message_limit))} сообщений",
            )
            return

        if cmd == "/profile":
            value = arg.lower()
            aliases = {"male": "male", "м": "male", "муж": "male", "female": "female", "ж": "female", "жен": "female", "neutral": "neutral", "нейтр": "neutral"}
            profile = aliases.get(value)
            if not profile:
                await self.tg.send(chat_id, "Использование: /profile male | female | neutral")
                return
            self.db.set_profile(chat_id, user_id, profile)
            await self.tg.send(chat_id, "Профиль стиля сохранён.")
            return

        if cmd in {"/on", "/off", "/hardness", "/h", "/time", "/t", "/frequency", "/silence"}:
            if not await self.is_admin(chat_id, user_id):
                await self.tg.send(chat_id, "Эту настройку может менять администратор группы.")
                return
            if cmd == "/on":
                self.db.update_chat(chat_id, enabled=1)
                await self.tg.send(chat_id, "Аксакал проснулся.")
            elif cmd == "/off":
                self.db.update_chat(chat_id, enabled=0)
                await self.tg.send(chat_id, "Аксакал пока помолчит.")
            elif cmd in {"/hardness", "/h"}:
                value = arg.lower()
                if value == "auto":
                    self.db.update_chat(chat_id, hardness_mode="auto")
                    await self.tg.send(chat_id, "Жёсткость: AUTO. Аксакал сам выбирает уровень по тону переписки.")
                else:
                    try:
                        n = int(value)
                        if n not in {1, 2, 3, 4, 5}:
                            raise ValueError
                    except ValueError:
                        await self.tg.send(chat_id, "Использование: /hardness auto или /hardness 1..5")
                        return
                    self.db.update_chat(chat_id, hardness_mode="fixed", fixed_hardness=n)
                    await self.tg.send(chat_id, f"Жёсткость зафиксирована: {n}/5")
            elif cmd in {"/time", "/t"}:
                try:
                    n = int(arg)
                except ValueError:
                    await self.tg.send(chat_id, "Использование: /time 3 | 5 | 20 | 40 | 60 | 180")
                    return
                if n not in {3, 5, 20, 40, 60, 180}:
                    await self.tg.send(chat_id, "Выбери: 3, 5, 20, 40, 60 или 180 секунд.")
                    return
                self.db.update_chat(chat_id, response_delay_seconds=n)
                await self.tg.send(chat_id, f"Задержка ответа: {n} сек.")
            elif cmd == "/frequency":
                # Старый скрытый алиас: значения трактуем как секунды только из нового набора.
                try:
                    n = int(arg)
                except ValueError:
                    await self.tg.send(chat_id, "Теперь используй /time 3|5|20|40|60|180")
                    return
                if n not in {3, 5, 20, 40, 60, 180}:
                    await self.tg.send(chat_id, "Теперь используй /time 3|5|20|40|60|180")
                    return
                self.db.update_chat(chat_id, response_delay_seconds=n)
                await self.tg.send(chat_id, f"Задержка ответа: {n} сек.")
            elif cmd == "/silence":
                try:
                    n = max(30, min(1440, int(arg)))
                except ValueError:
                    await self.tg.send(chat_id, "Использование: /silence количество_минут (30–1440)")
                    return
                self.db.update_chat(chat_id, silence_minutes=n)
                await self.tg.send(chat_id, f"Начну тормошить чат после {n} мин тишины.")
            return

        if cmd == "/roast":
            reply = msg.get("reply_to_message")
            if reply and reply.get("from") and not reply["from"].get("is_bot"):
                target_id = self.db.touch_user(chat_id, reply["from"], "message")
                await self.roast(chat_id, target_id, "пользователь явно попросил подкол через /roast")
            else:
                await self.tg.send(chat_id, "Ответь командой /roast на сообщение человека.")

    async def is_admin(self, chat_id: int, user_id: int) -> bool:
        assert self.tg
        try:
            member = await self.tg.call("getChatMember", chat_id=chat_id, user_id=user_id)
            return member.get("status") in {"creator", "administrator"}
        except Exception:
            return False

    async def maybe_emotional_response(self, chat_id: int, msg: dict[str, Any]):
        """Сбрасывает таймер на каждом новом сообщении и оценивает только последнее после паузы."""
        chat = self.db.get_chat(chat_id)
        if not chat or not chat["enabled"]:
            return

        sender = msg.get("from", {})
        if not int(sender.get("id", 0) or 0):
            return

        old_task = self.pending_reply_tasks.get(chat_id)
        if old_task and not old_task.done():
            old_task.cancel()

        task = asyncio.create_task(self.delayed_consider(chat_id, dict(msg)))
        self.pending_reply_tasks[chat_id] = task

    async def delayed_consider(self, chat_id: int, msg: dict[str, Any]):
        current = asyncio.current_task()
        try:
            chat = self.db.get_chat(chat_id) or {}
            delay = int(chat.get("response_delay_seconds", 20))
            delay = delay if delay in {3, 5, 20, 40, 60, 180} else 20
            await asyncio.sleep(delay)

            # Если за время ожидания пришло новое сообщение, старая задача уже отменена.
            chat = self.db.get_chat(chat_id)
            if not chat or not chat.get("enabled", 1):
                return

            sender = msg.get("from", {})
            sender_id = int(sender.get("id", 0) or 0)
            if not sender_id:
                return

            context = self.db.recent_context(chat_id, config.context_message_limit)
            mood = self.generator.detect_mood(context)
            source_text = (msg.get("text") or msg.get("caption") or "").strip()
            is_sticker = bool(msg.get("sticker"))
            source_kind = "sticker" if is_sticker else "message"

            if is_sticker:
                source_text = (msg.get("sticker") or {}).get("emoji") or "стикер"
                reason = (
                    "человек отправил стикер вместо слов. Ответь именно на это: подшути, что пора писать словами. "
                    "Жёсткость формулировки должна точно соответствовать выбранному уровню."
                )
            else:
                feedback = self.detect_address_feedback(source_text)
                greeting = self.detect_greeting_style(source_text)
                if feedback:
                    mood = "playful"
                    source_kind = "profile_correction"
                    reason = (
                        "пользователь поправил обращение к себе. Ответь только на эту поправку: коротко подшути, "
                        "покажи, что понял, и не используй обращение, которое он только что отверг."
                    )
                elif greeting == "generic":
                    mood = "playful"
                    source_kind = "greeting_correction"
                    reason = (
                        "человек поздоровался обычным «привет/здравствуйте/здорово» вместо салама. "
                        "Сделай короткое дагестанско-кавказское замечание по теме приветствия: в духе "
                        "«что за привет, нормально здоровайся — Ассаламу алейкум». Не утверждай его национальность "
                        "или происхождение. Жёсткость замечания должна соответствовать текущему уровню."
                    )
                elif greeting == "salam":
                    mood = "playful"
                    source_kind = "greeting_salam"
                    reason = (
                        "человек нормально поздоровался саламом. Ответь «Ва алейкум ассалам» и при желании "
                        "добавь очень короткую уместную реплику в стиле Аксакала."
                    )
                elif mood == "supportive":
                    reason = "ответь прямо на последнее сообщение по его смыслу; если человеку тяжело — поддержи без случайной шутки"
                elif mood == "stern":
                    reason = "ответь прямо на последнее сообщение по существу; если там грубость — осади её в соответствии с жёсткостью"
                elif mood == "calm":
                    reason = "ответь именно на последнее сообщение и по возможности снизь напряжение"
                elif mood == "wise":
                    reason = "ответь по существу последнего сообщения короткой уместной мыслью"
                else:
                    reason = (
                        "это последнее сообщение после выбранной паузы. ОБЯЗАТЕЛЬНО ответь на него. "
                        "Если есть повод — подколи; если повода нет — просто дай живую короткую реакцию строго по его теме. "
                        "Не используй случайную универсальную фразу."
                    )

            await self.roast(
                chat_id,
                sender_id,
                reason,
                mood=mood,
                reply_to_message_id=msg.get("message_id"),
                source_text=source_text,
                source_kind=source_kind,
            )
        except asyncio.CancelledError:
            return
        finally:
            if self.pending_reply_tasks.get(chat_id) is current:
                self.pending_reply_tasks.pop(chat_id, None)

    async def roast(
        self,
        chat_id: int,
        target_user_id: int,
        reason: str,
        mood: str | None = None,
        reply_to_message_id: int | None = None,
        source_text: str | None = None,
        source_kind: str = "message",
        ignore_cooldown: bool = False,
    ):
        assert self.tg
        chat = self.db.get_chat(chat_id)
        if not chat or not chat["enabled"]:
            return
        users = self.db.active_users(chat_id, 30 * 86400)
        target = next((u for u in users if u["user_id"] == target_user_id), None)
        if not target:
            return
        context = self.db.recent_context(chat_id, config.context_message_limit)
        if chat.get("hardness_mode", "auto") == "fixed":
            auto_level = max(1, min(5, int(chat.get("fixed_hardness", 3))))
        else:
            auto_level = self.generator.detect_intensity(context, 5)
        personal_words = self.db.top_learned_words(chat_id, target_user_id, 14)
        group_words = self.db.top_learned_words(chat_id, None, 18)
        avoided_addresses = self.db.avoided_addresses(chat_id, target_user_id)
        text = await self.generator.generate(
            target=target,
            context=context,
            level=auto_level,
            reason=reason,
            mood=mood,
            personal_words=personal_words,
            group_words=group_words,
            source_text=source_text,
            source_kind=source_kind,
            avoided_addresses=avoided_addresses,
        )
        await self.tg.send(chat_id, text, reply_to_message_id=reply_to_message_id)
        now = int(time.time())
        self.db.update_chat(chat_id, last_bot_message_at=now)
        self.db.mark_roasted(chat_id, target_user_id)

    async def silence_worker(self):
        while True:
            try:
                await asyncio.sleep(60)
                await self.check_silent_chats()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print("silence worker:", e)

    async def check_silent_chats(self):
        now = int(time.time())
        with self.db.connect() as conn:
            chats = [dict(r) for r in conn.execute("SELECT * FROM chats WHERE enabled=1").fetchall()]
        for chat in chats:
            silence_age = now - int(chat["last_activity_at"])
            bot_age = now - int(chat["last_bot_message_at"])
            threshold = int(chat["silence_minutes"]) * 60
            if silence_age < threshold or bot_age < threshold:
                continue
            users = self.db.active_users(int(chat["chat_id"]), 14 * 86400)
            candidates = [
                u for u in users
                if now - int(u["last_roasted_at"] or 0) > 6 * 3600
            ]
            if not candidates:
                continue
            # При тишине выбираем любого знакомого участника, а не обязательно самого молчаливого.
            target = random.choice(candidates[: min(12, len(candidates))])
            await self.roast(
                int(chat["chat_id"]),
                int(target["user_id"]),
                "в группе давно тишина. Зацепи выбранного человека короткой смешной фразой и попробуй "
                "вызвать остальных на разговор. Можно спросить, куда все пропали, или подколоть выбранного "
                "участника так, чтобы другим захотелось ответить.",
                source_text="группа давно молчит",
                source_kind="silence",
            )


if __name__ == "__main__":
    asyncio.run(AksakalBot().run())
