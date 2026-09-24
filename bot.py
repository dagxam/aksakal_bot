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

    async def send(self, chat_id: int, text: str, reply_to_message_id: int | None = None):
        payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if reply_to_message_id:
            payload["reply_parameters"] = {"message_id": reply_to_message_id, "allow_sending_without_reply": True}
        return await self.call("sendMessage", **payload)


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

    @classmethod
    def extract_learning_tokens(cls, text: str) -> list[str]:
        import re
        words = re.findall(r"[A-Za-zА-Яа-яЁё0-9_+-]{3,}", (text or "").lower())
        words = [w for w in words if w not in cls.STOP_WORDS and not w.startswith("http") and not w.startswith("@")]
        # Плюс короткие устойчивые пары — именно они часто становятся локальными мемами.
        pairs = [f"{words[i]} {words[i+1]}" for i in range(len(words)-1) if len(words[i]) + len(words[i+1]) <= 40]
        return (words + pairs)[:40]

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
            {"command": "start", "description": "Как подключить Аксакала"},
            {"command": "help", "description": "Помощь и команды"},
            {"command": "test", "description": "Проверить, что бот отвечает"},
            {"command": "status", "description": "Состояние Аксакала в группе"},
            {"command": "aksakal", "description": "Настройки группы"},
            {"command": "roast", "description": "Подколоть участника ответом на его сообщение"},
            {"command": "hardness", "description": "Жёсткость: auto или 1–4 (админ)"},
            {"command": "level", "description": "Старый алиас жёсткости (админ)"},
            {"command": "frequency", "description": "Минимальная пауза в минутах (админ)"},
            {"command": "silence", "description": "Когда тормошить молчунов (админ)"},
            {"command": "on", "description": "Включить Аксакала (админ)"},
            {"command": "off", "description": "Выключить Аксакала (админ)"},
            {"command": "profile", "description": "Стиль: male / female / neutral"},
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
        allowed = ["message", "edited_message", "message_reaction", "my_chat_member", "chat_member"]
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
                    "Проверка: /test\nВ группе: /status, /aksakal, /roast. "
                    "Админ-настройки: /level, /frequency, /silence, /on, /off.",
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

        if text.startswith("/"):
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
            await self.roast(chat_id, user_id, "пользователь поставил реакцию вместо сообщения")

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
                "/test — мгновенная проверка\n"
                "/status — состояние в группе\n"
                "/aksakal — настройки\n"
                "/roast — ответь этой командой на сообщение участника\n"
                "/profile male|female|neutral — стиль обращения\n"
                "/hardness auto|1|2|3|4 — режим жёсткости (админ)\n"
                "/level 1..4 — старый алиас (админ)\n"
                "/frequency 10..360 — пауза между репликами (админ)\n"
                "/silence 30..1440 — через сколько минут тишины оживлять чат (админ)\n"
                "/on /off — включить или выключить (админ)",
            )
            return

        if cmd == "/test":
            await self.tg.send(chat_id, "Аксакал жив. Всё вижу, всё запоминаю. Теперь говорите осторожнее 😏")
            return

        if cmd in {"/status", "/aksakal"}:
            c = self.db.get_chat(chat_id) or {}
            await self.tg.send(
                chat_id,
                f"Аксакал включён: {'да' if c.get('enabled',1) else 'нет'}\n"
                f"AI: {'включён' if self.generator.enabled else 'fallback без AI'}\n"
                f"Жёсткость: {('авто до ' + str(c.get('roast_level',3)) + '/4') if c.get('hardness_mode','auto') == 'auto' else ('фиксированная ' + str(c.get('fixed_hardness',3)) + '/4')}\n"
                f"Пауза: {c.get('min_interval_minutes',10)} мин\n"
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

        if cmd in {"/on", "/off", "/level", "/hardness", "/frequency", "/silence"}:
            if not await self.is_admin(chat_id, user_id):
                await self.tg.send(chat_id, "Эту настройку может менять администратор группы.")
                return
            if cmd == "/on":
                self.db.update_chat(chat_id, enabled=1)
                await self.tg.send(chat_id, "Аксакал проснулся.")
            elif cmd == "/off":
                self.db.update_chat(chat_id, enabled=0)
                await self.tg.send(chat_id, "Аксакал пока помолчит.")
            elif cmd == "/hardness":
                value = arg.lower()
                if value == "auto":
                    self.db.update_chat(chat_id, hardness_mode="auto")
                    await self.tg.send(chat_id, "Жёсткость: AUTO. Аксакал сам выбирает уровень по тону переписки.")
                else:
                    try:
                        n = int(value)
                        if n not in {1, 2, 3, 4}:
                            raise ValueError
                    except ValueError:
                        await self.tg.send(chat_id, "Использование: /hardness auto или /hardness 1..4")
                        return
                    self.db.update_chat(chat_id, hardness_mode="fixed", fixed_hardness=n)
                    await self.tg.send(chat_id, f"Жёсткость зафиксирована: {n}/4")
            elif cmd == "/level":
                try:
                    n = int(arg)
                    if n not in {1, 2, 3, 4}:
                        raise ValueError
                except ValueError:
                    await self.tg.send(chat_id, "Использование: /level 1..4")
                    return
                self.db.update_chat(chat_id, hardness_mode="fixed", fixed_hardness=n)
                await self.tg.send(chat_id, f"Жёсткость зафиксирована: {n}/4")
            elif cmd == "/frequency":
                try:
                    n = max(10, min(360, int(arg)))
                except ValueError:
                    await self.tg.send(chat_id, "Использование: /frequency количество_минут (10–360)")
                    return
                self.db.update_chat(chat_id, min_interval_minutes=n)
                await self.tg.send(chat_id, f"Минимальная пауза: {n} мин.")
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
        """Автоматический ответ на каждое обычное сообщение пользователя."""
        chat = self.db.get_chat(chat_id)
        if not chat or not chat["enabled"]:
            return

        sender = msg.get("from", {})
        sender_id = int(sender.get("id", 0))
        if not sender_id:
            return

        context = self.db.recent_context(chat_id, config.context_message_limit)
        mood = self.generator.detect_mood(context)

        reasons = {
            "supportive": "ответь прямо на последнее сообщение: поддержи человека мягко и без шутки",
            "calm": "ответь прямо на последнее сообщение и спокойно снизь напряжение",
            "stern": "ответь прямо на последнее сообщение: сурово осади грубость, но не унижай человека",
            "wise": "ответь прямо на последнее сообщение короткой уместной мудрой мыслью по теме",
            "playful": "ответь прямо на последнее сообщение коротким контекстным подколом или ироничной репликой",
        }

        await self.roast(
            chat_id,
            sender_id,
            reasons[mood],
            mood=mood,
            reply_to_message_id=msg.get("message_id"),
            ignore_cooldown=True,
        )

    async def roast(
        self,
        chat_id: int,
        target_user_id: int,
        reason: str,
        mood: str | None = None,
        reply_to_message_id: int | None = None,
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
            auto_level = max(1, min(4, int(chat.get("fixed_hardness", 3))))
        else:
            auto_level = self.generator.detect_intensity(context, int(chat["roast_level"]))
        personal_words = self.db.top_learned_words(chat_id, target_user_id, 14)
        group_words = self.db.top_learned_words(chat_id, None, 18)
        text = await self.generator.generate(
            target=target,
            context=context,
            level=auto_level,
            reason=reason,
            mood=mood,
            personal_words=personal_words,
            group_words=group_words,
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
                if now - int(u["last_roasted_at"]) > 12 * 3600
                and now - int(u["last_spoken_at"] or 0) > threshold
            ]
            if not candidates:
                continue
            candidates.sort(key=lambda u: (u["last_spoken_at"] or 0, -u["reaction_count"]))
            target = random.choice(candidates[: min(5, len(candidates))])
            await self.roast(int(chat["chat_id"]), int(target["user_id"]), "в группе тишина; слегка жёстко зацепи молчуна и спровоцируй разговор")


if __name__ == "__main__":
    asyncio.run(AksakalBot().run())
