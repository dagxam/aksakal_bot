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

    async def delete(self, chat_id: int, message_id: int):
        return await self.call("deleteMessage", chat_id=chat_id, message_id=message_id)


class AksakalBot:
    STOP_WORDS = {
        "это","как","что","чтобы","когда","тогда","тут","там","где","кто","она","они","оно","его","ее","её",
        "для","про","под","над","или","если","уже","ещё","еще","вот","был","была","были","будет","есть","нет",
        "да","не","ни","ну","же","бы","ли","то","из","на","по","за","от","до","во","со","мы","вы","ты","я",
        "мне","тебе","ему","нам","вам","их","мой","твой","наш","ваш","свой","так","такой","такая","такие",
        "просто","очень","тоже","только","можно","надо","нужно","потом","сейчас","сегодня","вчера","завтра"
    }

    CROCODILE_WORDS: dict[str, tuple[str, str, str]] = {
        "арбуз": (
            "Большой круглый плод: снаружи зелёный, внутри красный и очень сочный.",
            "Его часто едят летом, а внутри много чёрных семечек.",
            "Начинается на «А».",
        ),
        "самолёт": (
            "Воздушный транспорт с крыльями, который перевозит людей между городами и странами.",
            "Перед поездкой на нём проходят регистрацию и садятся в салон через аэропорт.",
            "Начинается на «С».",
        ),
        "холодильник": (
            "Большой кухонный шкаф, внутри которого продукты долго остаются свежими.",
            "В нём обычно хранят молоко, мясо, сыр и напитки.",
            "Начинается на «Х».",
        ),
        "телефон": (
            "Небольшое устройство, которое почти всегда носишь с собой: звонки, сообщения, фото и интернет.",
            "Его регулярно заряжают, а экран часто разблокируют пальцем или лицом.",
            "Начинается на «Т».",
        ),
        "зонт": (
            "Эту вещь раскрывают над головой, когда с неба льётся вода.",
            "Она складывается и часто лежит в сумке на случай плохой погоды.",
            "Начинается на «З».",
        ),
        "жираф": (
            "Африканское животное, которое легко достаёт листья с очень высоких деревьев.",
            "У него пятнистая окраска и необычно длинная шея.",
            "Начинается на «Ж».",
        ),
        "пингвин": (
            "Птица, которая не поднимается в небо, зато отлично плавает и живёт в очень холодных местах.",
            "Чёрно-белая окраска делает его похожим на маленького человека во фраке.",
            "Начинается на «П».",
        ),
        "банан": (
            "Длинный жёлтый фрукт, который перед едой очищают руками.",
            "Растёт большими связками и внутри мягкий, без косточки.",
            "Начинается на «Б».",
        ),
        "шахматы": (
            "Игра на доске из 64 клеток, где есть король, ферзь, ладьи, слоны и кони.",
            "Главная цель — поставить мат королю соперника.",
            "Начинается на «Ш».",
        ),
        "будильник": (
            "Эта штука начинает шуметь именно тогда, когда утром больше всего хочется спать.",
            "В ней заранее выставляют время, чтобы не проспать работу или учёбу.",
            "Начинается на «Б».",
        ),
        "подушка": (
            "Мягкая вещь на кровати, на которую кладут голову во время сна.",
            "Обычно лежит рядом с одеялом и бывает в наволочке.",
            "Начинается на «П».",
        ),
        "пылесос": (
            "Домашний прибор, которым чистят ковры и пол, втягивая мелкий мусор внутрь.",
            "У него часто есть длинный шланг, труба и насадка.",
            "Начинается на «П».",
        ),
        "велосипед": (
            "Транспорт на двух колёсах, который движется, когда человек крутит педали.",
            "У него есть руль, цепь и седло, но обычно нет двигателя.",
            "Начинается на «В».",
        ),
        "футбол": (
            "Командная игра, где две стороны стараются отправить мяч в ворота соперника.",
            "На поле обычно одновременно находятся 22 игрока.",
            "Начинается на «Ф».",
        ),
        "морковь": (
            "Оранжевый овощ, который растёт в земле, а сверху видна зелёная ботва.",
            "Её кладут в суп, салат и часто дают грызть сырой.",
            "Начинается на «М».",
        ),
        "комар": (
            "Маленькое летающее насекомое, которое особенно надоедает летними ночами.",
            "После его укуса кожа часто зудит.",
            "Начинается на «К».",
        ),
        "свеча": (
            "Её зажигают спичкой или зажигалкой, и сверху появляется маленькое пламя.",
            "Она постепенно становится короче, пока горит.",
            "Начинается на «С».",
        ),
        "радуга": (
            "Разноцветная дуга, которую иногда видно в небе после дождя, когда выходит солнце.",
            "В ней принято выделять семь цветов.",
            "Начинается на «Р».",
        ),
        "черепаха": (
            "Медлительное животное, которое носит твёрдый защитный дом прямо на спине.",
            "При опасности может спрятать голову и лапы внутрь панциря.",
            "Начинается на «Ч».",
        ),
        "вертолёт": (
            "Воздушная машина с большим вращающимся винтом сверху.",
            "Может подниматься почти вертикально и зависать на месте.",
            "Начинается на «В».",
        ),
        "гитара": (
            "Музыкальный инструмент со струнами: одной рукой зажимают аккорды, другой извлекают звук.",
            "У неё обычно шесть струн и длинный гриф.",
            "Начинается на «Г».",
        ),
        "микроволновка": (
            "Кухонный прибор, куда ставят тарелку, чтобы очень быстро сделать еду горячей.",
            "После нажатия кнопки внутри обычно вращается стеклянный круг.",
            "Начинается на «М».",
        ),
        "рюкзак": (
            "Сумка, которую носят за спиной на двух лямках.",
            "В неё школьники кладут учебники, а туристы — вещи для дороги.",
            "Начинается на «Р».",
        ),
        "лифт": (
            "Небольшая кабина в многоэтажном доме, которая возит людей вверх и вниз.",
            "Внутри нажимают кнопку нужного этажа.",
            "Начинается на «Л».",
        ),
        "пицца": (
            "Круглое блюдо из теста с начинкой сверху, которое обычно режут треугольными кусками.",
            "Часто сверху расплавленный сыр, а привозят её в плоской квадратной коробке.",
            "Начинается на «П».",
        ),
        "очки": (
            "Их надевают на лицо перед глазами, чтобы лучше видеть или защищаться от яркого солнца.",
            "Две линзы соединены перемычкой и держатся за ушами дужками.",
            "Начинается на «О».",
        ),
        "ключ": (
            "Небольшая металлическая вещь, которую вставляют в замок, чтобы открыть дверь.",
            "Её очень неприятно обнаружить потерянной уже возле дома.",
            "Начинается на «К».",
        ),
        "чайник": (
            "Кухонная ёмкость, в которой нагревают воду для горячего напитка.",
            "Электрический вариант сам отключается после закипания.",
            "Начинается на «Ч».",
        ),
        "мороженое": (
            "Холодный сладкий десерт, который особенно любят летом.",
            "Бывает в стаканчике, рожке или на палочке и быстро тает на жаре.",
            "Начинается на «М».",
        ),
        "светофор": (
            "Устройство возле дороги с тремя цветами, которое регулирует движение.",
            "Красный требует остановиться, зелёный разрешает ехать.",
            "Начинается на «С».",
        ),
        "чемодан": (
            "В него складывают одежду и вещи перед дальней поездкой.",
            "У современных моделей часто есть колёсики и выдвижная ручка.",
            "Начинается на «Ч».",
        ),
        "магнит": (
            "Небольшой предмет, который способен притягивать некоторые металлы без клея и верёвки.",
            "Такие сувениры часто висят на дверце кухонной техники.",
            "Начинается на «М».",
        ),
        "кактус": (
            "Зелёное растение, которому нужно мало воды и которое неприятно хватать голыми руками.",
            "Вместо обычных листьев у него много колючек.",
            "Начинается на «К».",
        ),
        "парашют": (
            "Большой купол над человеком, который помогает безопасно опускаться с большой высоты.",
            "Его раскрывают после прыжка из воздушного транспорта.",
            "Начинается на «П».",
        ),
        "барабан": (
            "Музыкальный инструмент, по которому ударяют палочками или руками, создавая ритм.",
            "У него натянута мембрана, а звук получается от ударов.",
            "Начинается на «Б».",
        ),
        "фонарик": (
            "Небольшой переносной источник света, который помогает видеть в темноте.",
            "Работает от батареек или аккумулятора и включается кнопкой.",
            "Начинается на «Ф».",
        ),
    }

    def __init__(self):
        if not config.telegram_token:
            raise SystemExit("TELEGRAM_BOT_TOKEN не задан. Скопируйте .env.example в .env")
        self.db = Database(config.database_path)
        self.generator = PhraseGenerator(
            enabled=config.ai_enabled,
            groq_api_key=config.groq_api_key,
            groq_models=config.groq_models,
            mistral_api_key=config.mistral_api_key,
            mistral_model=config.mistral_model,
        )
        self.offset = 0
        self.tg: TelegramAPI | None = None
        self.pending_reply_tasks: dict[int, asyncio.Task] = {}
        self.game_tasks: dict[int, asyncio.Task] = {}
        self.bot_user_id: int = 0
        self.bot_username: str = ""

    def ai_diagnostics(self) -> str:
        providers = [
            ("Groq", bool(config.groq_api_key)),
            ("Mistral", bool(config.mistral_api_key)),
        ]
        loaded = ", ".join(name for name, ok in providers if ok) or "нет"
        missing = ", ".join(name for name, ok in providers if not ok) or "нет"
        return (
            f"AI_ENABLED: {'да' if config.ai_enabled else 'НЕТ'}\n"
            f".env найден: {'да' if config.env_file_exists else 'НЕТ'}\n"
            f"ожидаемый .env: {config.env_file_path}\n"
            f"загружены ключи: {loaded}\n"
            f"не загружены: {missing}"
        )


    async def ai_health_text(self) -> str:
        checks = await self.generator.health_check()
        return "\n".join(f"{name}: {status}" for name, status in checks.items())

    @staticmethod
    def reaction_feedback_score(reactions: list[str]) -> int:
        positive = {"😂", "🤣", "🔥", "❤️", "❤", "👍", "👏", "💯", "😁", "😆", "🥰", "🤝"}
        negative = {"👎", "🤡", "💩", "🙄", "😒", "🤦", "🤦‍♂️", "🤦‍♀️"}
        score = sum(1 for x in reactions if x in positive) - sum(1 for x in reactions if x in negative)
        return max(-2, min(2, score))

    @staticmethod
    def reply_feedback_score(text: str) -> int:
        low = " ".join((text or "").lower().replace("ё", "е").split())
        if not low:
            return 1
        negative = (
            "бред", "чушь", "не смешно", "несмешно", "скучно", "тупо",
            "неправильно", "не правильно", "неверно", "не верно", "что за бред",
            "глупо ответил", "опять одно и то же",
        )
        positive = (
            "ахах", "хаха", "точно", "верно", "красава", "хорош", "огонь",
            "нормально сказал", "правильно", "😂", "🤣", "🔥",
        )
        if any(x in low for x in negative):
            return -1
        if any(x in low for x in positive):
            return 2
        return 1

    @staticmethod
    def looks_like_attack(text: str) -> bool:
        import re
        low = " ".join((text or "").lower().replace("ё", "е").split())
        if not low:
            return False
        patterns = (
            r"\bмозг\w*\s+нет\b",
            r"\bтуп\w*\b",
            r"\bидиот\w*\b",
            r"\bдурак\w*\b",
            r"\bдебил\w*\b",
            r"\bбезмозг\w*\b",
            r"\bклоун\w*\b",
            r"\bлох\w*\b",
            r"\bзаткни\w*\b",
            r"\bбред\s+нес\w*\b",
            r"\bбесполез\w*\b",
            r"\bслаб\w*\b",
            r"\bпош[её]л\w*\b",
            r"\bнах\w*\b",
            r"\bсука\b",
            r"\bбля\w*\b",
            r"\bмраз\w*\b",
        )
        return any(re.search(p, low) for p in patterns)

    @classmethod
    def extract_learning_tokens(cls, text: str) -> list[str]:
        import re
        raw = re.findall(r"[A-Za-zА-Яа-яЁё0-9_+-]{2,}", (text or "").lower())
        clean_words = [
            w for w in raw
            if w not in cls.STOP_WORDS and not w.startswith("http") and not w.startswith("@")
        ]
        phrases: list[str] = []
        # Фразы строятся из реальных соседних слов, а не из слов после удаления стоп-слов.
        for size in (2, 3):
            for i in range(len(raw) - size + 1):
                chunk = raw[i:i + size]
                if all(w in cls.STOP_WORDS for w in chunk):
                    continue
                phrase = " ".join(chunk)
                if 5 <= len(phrase) <= 64:
                    phrases.append(phrase)
        result = clean_words + phrases
        # Сохраняем порядок и убираем дубли в одном сообщении.
        return list(dict.fromkeys(result))[:50]

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


    async def safe_delete_message(self, chat_id: int, message_id: int):
        if not self.tg or not message_id:
            return
        try:
            await self.tg.delete(chat_id, message_id)
        except Exception as exc:
            # В группе удаление пользовательской команды требует права delete_messages.
            print(f"delete message skipped {chat_id}/{message_id}: {exc}")

    async def delete_later(self, chat_id: int, message_id: int, delay: int = 12):
        try:
            await asyncio.sleep(max(1, delay))
            await self.safe_delete_message(chat_id, message_id)
        except asyncio.CancelledError:
            return

    async def send_command_notice(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
        reply_markup: dict[str, Any] | None = None,
        ttl: int = 12,
    ):
        assert self.tg
        sent = await self.tg.send(
            chat_id,
            text,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
        )
        if isinstance(sent, dict) and sent.get("message_id"):
            asyncio.create_task(self.delete_later(chat_id, int(sent["message_id"]), ttl))
        return sent

    async def run(self):
        async with TelegramAPI(config.telegram_token) as tg:
            self.tg = tg
            # Long polling не работает, пока у бота установлен webhook.
            await tg.call("deleteWebhook", drop_pending_updates=False)

            me = await tg.call("getMe")
            self.bot_user_id = int(me.get("id", 0) or 0)
            self.bot_username = (me.get("username") or "").lower()
            try:
                await self.configure_bot_profile()
            except Exception as e:
                # Настройка имени/описания/команд не должна мешать работе самого бота.
                print(f"bot profile sync warning: {e}")
            print(f"Аксакал запущен: @{me.get('username')}")
            print(self.ai_diagnostics())
            worker = asyncio.create_task(self.silence_worker())
            try:
                await self.poll()
            finally:
                worker.cancel()

    async def configure_bot_profile(self):
        """Синхронизирует профиль только при реальном изменении и никогда не роняет запуск."""
        assert self.tg

        private_commands = [
            {"command": "start", "description": "Как работает Аксакал"},
            {"command": "help", "description": "Что умеет бот"},
            {"command": "test", "description": "Проверить, что бот работает"},
        ]

        async def safe_sync(label: str, get_method: str, set_method: str, desired: Any, **payload):
            try:
                current = await self.tg.call(get_method)

                if isinstance(current, dict):
                    # getMyName -> {"name": ...}
                    # getMyDescription -> {"description": ...}
                    # getMyShortDescription -> {"short_description": ...}
                    if "name" in current:
                        current_value = current.get("name", "")
                    elif "description" in current:
                        current_value = current.get("description", "")
                    elif "short_description" in current:
                        current_value = current.get("short_description", "")
                    else:
                        current_value = current
                else:
                    current_value = current

                if current_value == desired:
                    return

                await self.tg.call(set_method, **payload)
                print(f"bot profile synced: {label}")
            except Exception as e:
                # В том числе Telegram 429 retry_after. Это не критично:
                # polling и вся логика бота должны продолжить работу.
                print(f"bot profile sync skipped ({label}): {e}")

        # Командное меню показываем только в личке. В группах оно специально пустое,
        # чтобы служебные команды не торчали рядом с обычным разговором.
        try:
            private_scope = {"type": "all_private_chats"}
            group_scope = {"type": "all_group_chats"}
            default_scope = {"type": "default"}

            current_private = await self.tg.call("getMyCommands", scope=private_scope)
            normalized_private = [
                {"command": x.get("command", ""), "description": x.get("description", "")}
                for x in (current_private or [])
            ]
            if normalized_private != private_commands:
                await self.tg.call("setMyCommands", commands=private_commands, scope=private_scope)
                print("bot profile synced: private commands")

            current_group = await self.tg.call("getMyCommands", scope=group_scope)
            if current_group:
                await self.tg.call("deleteMyCommands", scope=group_scope)
                print("bot profile synced: group commands hidden")

            # Убираем старое глобальное меню, которое могло остаться от прошлой версии.
            current_default = await self.tg.call("getMyCommands", scope=default_scope)
            if current_default:
                await self.tg.call("deleteMyCommands", scope=default_scope)
                print("bot profile synced: old default commands removed")
        except Exception as e:
            print(f"bot profile sync skipped (commands): {e}")

        try:
            await self.tg.call("setChatMenuButton", menu_button={"type": "commands"})
            print("bot profile synced: private menu button")
        except Exception as e:
            print(f"bot profile sync skipped (menu button): {e}")

        await safe_sync(
            "name",
            "getMyName",
            "setMyName",
            "Аксакал",
            name="Аксакал",
        )
        await safe_sync(
            "description",
            "getMyDescription",
            "setMyDescription",
            "Живой участник группы: понимает тему разговора, подкалывает, поддерживает, успокаивает и оживляет чат.",
            description="Живой участник группы: понимает тему разговора, подкалывает, поддерживает, успокаивает и оживляет чат.",
        )
        await safe_sync(
            "short_description",
            "getMyShortDescription",
            "setMyShortDescription",
            "Подколы, поддержка, мудрость и живой чат.",
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
        chat_id = int(chat["id"])

        if new_status not in {"member", "administrator"}:
            return

        self.db.ensure_chat(
            chat_id,
            chat.get("title"),
            config.default_roast_level,
            config.min_bot_interval_minutes,
            config.silence_trigger_minutes,
        )

        # Если бот только добавлен без админки — объясняем, что для полноценной работы
        # нужно повышение. Полную панель покажем именно после активации администратором.
        if old_status in {"left", "kicked"} and new_status == "member":
            await self.tg.send(
                chat_id,
                "Аксакал добавлен, но ещё не полностью активирован. Сделай меня администратором "
                "с правом удаления сообщений и оставь Privacy Mode = Disable. "
                "После повышения я покажу панель настроек.",
            )
            return

        # Срабатывает и при добавлении сразу администратором, и при member → administrator.
        if new_status == "administrator" and old_status != "administrator":
            current = self.db.get_chat(chat_id) or {}
            await self.tg.send(
                chat_id,
                "Аксакал полностью активирован.\n"
                f"AI: {self.generator.provider_status()}\n\n"
                "Выбери режим, скорость ответа и интервал самостоятельного оживления группы.",
                reply_markup=self.settings_keyboard(current),
            )

    async def handle_message(self, msg: dict[str, Any]):
        chat = msg.get("chat", {})
        if chat.get("type") not in {"group", "supergroup"}:
            text = (msg.get("text") or "").strip()
            command = text.split(maxsplit=1)[0].split("@")[0].lower() if text.startswith("/") else ""
            if command == "/start" and self.tg:
                await self.tg.send(
                    chat["id"],
                    "Я Аксакал для групповых чатов. Добавь меня в группу, назначь администратором "
                    "и отключи Privacy Mode: @BotFather → /setprivacy → Disable. "
                    "В группе настройки доступны через /settings.",
                )
            elif command == "/help" and self.tg:
                await self.tg.send(
                    chat["id"],
                    "В личке доступны /start, /help и /test. Основная работа Аксакала идёт внутри группы: "
                    "он поддерживает разговор, отвечает на вопросы, запоминает контекст, шутит и оживляет тишину.",
                )
            elif command == "/test" and self.tg:
                health = await self.ai_health_text()
                await self.tg.send(
                    chat["id"],
                    "Аксакал работает.\n"
                    f"AI: {self.generator.provider_status()}\n\n"
                    f"{self.ai_diagnostics()}\n\n"
                    "Проверка API:\n"
                    f"{health}",
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

        reply = msg.get("reply_to_message") or {}
        reply_to_message_id = int(reply.get("message_id", 0) or 0) or None
        reply_from = reply.get("from") or {}
        reply_to_user_id = int(reply_from.get("id", 0) or 0) or None

        if (
            reply_to_message_id
            and not (text or "").startswith("/")
            and self.db.get_bot_response(chat_id, reply_to_message_id)
        ):
            self.db.set_response_feedback(
                chat_id,
                reply_to_message_id,
                user_id,
                "reply",
                self.reply_feedback_score(text),
                detail=(text or "")[:80],
            )

        self.db.add_message(
            chat_id,
            msg["message_id"],
            user_id,
            username,
            display,
            kind,
            text,
            reply_to_message_id=reply_to_message_id,
            reply_to_user_id=reply_to_user_id,
        )

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
            # После выполнения убираем саму slash-команду из группы.
            await self.safe_delete_message(chat_id, int(msg.get("message_id", 0) or 0))
            return

        if await self.handle_crocodile_guess(chat_id, user_id, display, text, kind):
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
        for reaction in upd.get("new_reaction", []):
            reactions.append(reaction.get("emoji") or "custom_emoji")
        content = "реакция " + " ".join(reactions) if reactions else "реакция убрана"
        username = user.get("username") or ""
        display = " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x).strip() or username or str(user_id)
        message_id = int(upd.get("message_id", 0) or 0)
        self.db.add_message(chat_id, message_id, user_id, username, display, "reaction", content)

        if message_id and self.db.get_bot_response(chat_id, message_id):
            self.db.set_response_feedback(
                chat_id,
                message_id,
                user_id,
                "reaction",
                self.reaction_feedback_score(reactions),
                detail=" ".join(reactions),
            )
            return

        if reactions and random.random() < 0.08:
            await self.roast(
                chat_id,
                user_id,
                "пользователь поставил реакцию вместо сообщения",
                source_text=content,
                source_kind="reaction",
            )

    @staticmethod
    def normalize_crocodile_guess(text: str) -> str:
        import re
        low = (text or "").lower().replace("ё", "е")
        low = re.sub(r"[^a-zа-я0-9\s-]+", " ", low)
        return " ".join(low.split())

    @staticmethod
    def crocodile_keyboard() -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "💡 Подсказка", "callback_data": "set:croc:hint"},
                    {"text": "⏹ Завершить", "callback_data": "set:croc:stop"},
                ]
            ]
        }

    def crocodile_score_text(self, chat_id: int) -> str:
        top = self.db.crocodile_top(chat_id, 5)
        if not top:
            return "Счёт пока пуст."
        medals = ["🥇", "🥈", "🥉", "4.", "5."]
        rows = [
            f"{medals[i]} {item['display_name']} — {item['score']}"
            for i, item in enumerate(top)
        ]
        return "🏆 Счёт:\n" + "\n".join(rows)

    async def start_crocodile_game(self, chat_id: int):
        assert self.tg
        current = self.db.get_crocodile_game(chat_id)
        if current and current.get("active"):
            if current.get("word"):
                await self.tg.send(
                    chat_id,
                    "🐊 Крокодил уже идёт. Пишите варианты прямо в чат.",
                    reply_markup=self.crocodile_keyboard(),
                )
            return
        self.db.start_crocodile_game(chat_id)
        await self.tg.send(
            chat_id,
            "🐊 Начинаем «Крокодила»!\n\n"
            "Я объясняю слово, не называя его. Все участники пишут варианты прямо в чат. "
            "Кто первым угадает — получает +1 очко. После правильного ответа я сам начинаю следующий раунд.",
        )
        await self.start_crocodile_round(chat_id)

    async def start_crocodile_round(self, chat_id: int, delay: float = 0):
        assert self.tg
        if delay:
            await asyncio.sleep(delay)
        game = self.db.get_crocodile_game(chat_id)
        if not game or not game.get("active"):
            return

        previous = self.normalize_crocodile_guess(str(game.get("word") or ""))
        words = [word for word in self.CROCODILE_WORDS if self.normalize_crocodile_guess(word) != previous]
        word = random.choice(words or list(self.CROCODILE_WORDS))
        self.db.set_crocodile_round(chat_id, word)
        fresh = self.db.get_crocodile_game(chat_id) or {}
        round_number = int(fresh.get("round_number", 1) or 1)
        clue = self.CROCODILE_WORDS[word][0]
        sent = await self.tg.send(
            chat_id,
            f"🐊 КРОКОДИЛ · Раунд {round_number}\n\n"
            f"🗣 {clue}\n\n"
            "Пишите варианты прямо в чат. Первому угадавшему +1.",
            reply_markup=self.crocodile_keyboard(),
        )
        if isinstance(sent, dict) and sent.get("message_id"):
            self.db.add_bot_message(chat_id, int(sent["message_id"]), f"Крокодил: {clue}")

    async def send_crocodile_hint(self, chat_id: int, automatic: bool = False):
        assert self.tg
        game = self.db.get_crocodile_game(chat_id)
        if not game or not game.get("active") or not game.get("word"):
            return
        word = str(game["word"])
        clues = self.CROCODILE_WORDS.get(word)
        if not clues:
            return
        current_index = int(game.get("clue_index", 0) or 0)
        if current_index >= len(clues) - 1:
            if not automatic:
                await self.send_command_notice(chat_id, "Больше подсказок нет — думайте 😄")
            return
        new_index = self.db.advance_crocodile_clue(chat_id)
        new_index = min(new_index, len(clues) - 1)
        label = "Автоподсказка" if automatic else "Подсказка"
        await self.tg.send(
            chat_id,
            f"💡 {label}: {clues[new_index]}",
            reply_markup=self.crocodile_keyboard(),
        )

    async def stop_crocodile_game(self, chat_id: int, announce: bool = True):
        assert self.tg
        game = self.db.get_crocodile_game(chat_id)
        if not game or not game.get("active"):
            if announce:
                await self.send_command_notice(chat_id, "Сейчас «Крокодил» не запущен.")
            return
        word = str(game.get("word") or "")
        self.db.stop_crocodile_game(chat_id)
        task = self.game_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()
        if announce:
            reveal = f" Последнее слово было: {word}." if word else ""
            await self.tg.send(
                chat_id,
                f"🐊 Игра завершена.{reveal}\n\n{self.crocodile_score_text(chat_id)}",
            )

    async def handle_crocodile_guess(
        self,
        chat_id: int,
        user_id: int,
        display_name: str,
        text: str,
        kind: str,
    ) -> bool:
        game = self.db.get_crocodile_game(chat_id)
        if not game or not game.get("active"):
            return False

        # Пока идёт игра, обычные автоответы Аксакала не перебивают участников.
        if kind != "message" or not text.strip() or not game.get("word"):
            return True

        guess = self.normalize_crocodile_guess(text)
        answer = self.normalize_crocodile_guess(str(game["word"]))
        if not guess:
            return True

        import re
        correct = bool(re.search(rf"(?<![a-zа-я0-9]){re.escape(answer)}(?![a-zа-я0-9])", guess))
        if correct:
            word = str(game["word"])
            self.db.clear_crocodile_round(chat_id)
            total = self.db.add_crocodile_score(chat_id, user_id, display_name, 1)
            await self.tg.send(
                chat_id,
                f"🎉 {display_name} угадал! Слово: {word}.\n"
                f"Счёт игрока: {total}.\n\n"
                f"{self.crocodile_score_text(chat_id)}\n\n"
                "Следующий раунд через 3 секунды…",
            )
            old_task = self.game_tasks.pop(chat_id, None)
            if old_task and not old_task.done():
                old_task.cancel()
            task = asyncio.create_task(self.start_crocodile_round(chat_id, delay=3))
            self.game_tasks[chat_id] = task
            return True

        attempts = self.db.register_crocodile_attempt(chat_id)
        if attempts in {5, 10}:
            await self.send_crocodile_hint(chat_id, automatic=True)
        return True

    @staticmethod
    def settings_keyboard(chat: dict[str, Any]) -> dict[str, Any]:
        mode = chat.get("hardness_mode", "auto")
        fixed = int(chat.get("fixed_hardness", 3))
        delay = int(chat.get("response_delay_seconds", 20))
        silence = int(chat.get("silence_minutes", 180))
        enabled = bool(chat.get("enabled", 1))

        def mark(label: str, active: bool) -> str:
            return ("✅ " if active else "") + label

        return {
            "inline_keyboard": [
                [
                    {"text": mark("AUTO", mode == "auto"), "callback_data": "set:hard:auto"},
                    {"text": mark("🙂 Нормальный", mode == "fixed" and fixed <= 2), "callback_data": "set:hard:normal"},
                    {"text": mark("😠 Злой", mode == "fixed" and 3 <= fixed <= 4), "callback_data": "set:hard:angry"},
                    {"text": mark("🔥 Супер злой", mode == "fixed" and fixed >= 5), "callback_data": "set:hard:super"},
                ],
                [
                    {"text": mark("⚡ Сразу", delay == 0), "callback_data": "set:time:0"},
                    {"text": mark("3 сек", delay == 3), "callback_data": "set:time:3"},
                    {"text": mark("5 сек", delay == 5), "callback_data": "set:time:5"},
                    {"text": mark("20 сек", delay == 20), "callback_data": "set:time:20"},
                ],
                [
                    {"text": mark("40 сек", delay == 40), "callback_data": "set:time:40"},
                    {"text": mark("1 мин", delay == 60), "callback_data": "set:time:60"},
                    {"text": mark("3 мин", delay == 180), "callback_data": "set:time:180"},
                ],
                [
                    {"text": mark("💬 15м", silence == 15), "callback_data": "set:silence:15"},
                    {"text": mark("💬 30м", silence == 30), "callback_data": "set:silence:30"},
                    {"text": mark("💬 1ч", silence == 60), "callback_data": "set:silence:60"},
                    {"text": mark("💬 3ч", silence == 180), "callback_data": "set:silence:180"},
                ],
                [
                    {"text": "🐊 Играть в Крокодила", "callback_data": "set:game:croc"},
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
        fixed = int(chat.get("fixed_hardness", 3))
        hardness = (
            "AUTO"
            if mode == "auto"
            else ("Нормальный" if fixed <= 2 else "Злой" if fixed <= 4 else "Супер злой")
        )
        delay = int(chat.get("response_delay_seconds", 20))
        delay_label = {0: "сразу", 3: "3 сек", 5: "5 сек", 20: "20 сек", 40: "40 сек", 60: "1 мин", 180: "3 мин"}.get(delay, f"{delay} сек")
        silence = int(chat.get("silence_minutes", 180))
        return (
            "⚙️ Настройки Аксакала\n"
            f"Режим: {hardness}\n"
            f"Ответ после сообщения: {delay_label}\n"
            f"Оживление группы после тишины: {silence} мин\n"
            f"Состояние: {'включён' if chat.get('enabled', 1) else 'выключен'}\n\n"
            "После этого времени без новых сообщений отвечаю на последнее.\n"
            "Можно нажать кнопку или написать: /hardness auto, /time 0, /silence 30"
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

        if section == "game" and value == "croc":
            if callback_id:
                await self.tg.call("answerCallbackQuery", callback_query_id=callback_id, text="Запускаю Крокодила")
            await self.start_crocodile_game(chat_id)
            return
        if section == "croc" and value == "hint":
            if callback_id:
                await self.tg.call("answerCallbackQuery", callback_query_id=callback_id, text="Ещё подсказка")
            await self.send_crocodile_hint(chat_id)
            return
        if section == "croc" and value == "stop":
            if callback_id:
                await self.tg.call("answerCallbackQuery", callback_query_id=callback_id, text="Игра завершена")
            await self.stop_crocodile_game(chat_id)
            return

        if section == "hard":
            if value == "auto":
                self.db.update_chat(chat_id, hardness_mode="auto")
            elif value in {"normal", "angry", "super"}:
                mapped = {"normal": 1, "angry": 3, "super": 5}[value]
                self.db.update_chat(chat_id, hardness_mode="fixed", fixed_hardness=mapped)
        elif section == "time" and value in {"0", "3", "5", "20", "40", "60", "180"}:
            self.db.update_chat(chat_id, response_delay_seconds=int(value))
        elif section == "silence" and value in {"15", "30", "60", "180"}:
            self.db.update_chat(chat_id, silence_minutes=int(value))
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
            await self.send_command_notice(
                chat_id,
                "Команды Аксакала:\n"
                "/settings — выбрать режим и время кнопками\n"
                "/status — текущие настройки\n"
                "/roast — подколоть ответом на сообщение\n"
                "/good — ответом на реплику Аксакала: удачный ответ\n"
                "/bad — ответом на реплику Аксакала: неудачный ответ\n"
                "/test — проверить бота\n"
                "/crocodile — начать игру «Крокодил»\n"
                "/crocodile hint — дать подсказку\n"
                "/crocodile stop — закончить игру\n\n"
                "Быстро вручную: /hardness auto|normal|angry|super, /time 0|3|5|20|40|60|180, /silence 15|30|60|180",
            )
            return

        if cmd in {"/settings", "/aksakal"}:
            if not await self.is_admin(chat_id, user_id):
                await self.send_command_notice(chat_id, "Настройки может менять администратор группы.")
                return
            await self.show_settings(chat_id)
            return

        if cmd in {"/crocodile", "/croc", "/крокодил"}:
            if not await self.is_admin(chat_id, user_id):
                await self.send_command_notice(chat_id, "Запускать и останавливать игру может администратор группы.")
                return
            action = arg.lower().strip()
            if action in {"stop", "стоп", "off"}:
                await self.stop_crocodile_game(chat_id)
            elif action in {"hint", "подсказка", "help"}:
                await self.send_crocodile_hint(chat_id)
            else:
                await self.start_crocodile_game(chat_id)
            return

        if cmd == "/test":
            health = await self.ai_health_text()
            await self.send_command_notice(
                chat_id,
                "Аксакал жив.\n"
                f"AI: {self.generator.provider_status()}\n"
                f"{self.ai_diagnostics()}\n\n"
                "Проверка API:\n"
                f"{health}",
                ttl=30,
            )
            return

        if cmd in {"/status", "/aksakal"}:
            c = self.db.get_chat(chat_id) or {}
            await self.send_command_notice(
                chat_id,
                f"Аксакал включён: {'да' if c.get('enabled',1) else 'нет'}\n"
                f"AI: {self.generator.provider_status()}\n"
                f"Режим: {('AUTO — сам выбираю Нормальный / Злой / Супер злой') if c.get('hardness_mode','auto') == 'auto' else ('Нормальный' if int(c.get('fixed_hardness',3)) <= 2 else 'Злой' if int(c.get('fixed_hardness',3)) <= 4 else 'Супер злой')}\n"
                f"Таймер тишины: {c.get('response_delay_seconds',20)} сек\n"
                f"Молчание: {c.get('silence_minutes',180)} мин\n"
                f"Контекст: {len(self.db.recent_context(chat_id, config.context_message_limit))} сообщений\n"
                f"Обучение юмору: {self.db.feedback_stats(chat_id)['signals']} сигналов "
                f"(баланс {self.db.feedback_stats(chat_id)['score']:+d})",
            )
            return

        if cmd in {"/good", "/bad"}:
            if not await self.is_admin(chat_id, user_id):
                await self.send_command_notice(chat_id, "Обучать Аксакала вручную может только администратор группы.")
                return

            reply = msg.get("reply_to_message") or {}
            reply_message_id = int(reply.get("message_id", 0) or 0)
            response_meta = self.db.get_bot_response(chat_id, reply_message_id) if reply_message_id else None
            if not response_meta:
                await self.send_command_notice(
                    chat_id,
                    "Ответь /good или /bad именно на AI-реплику Аксакала, которую хочешь оценить.",
                )
                return

            score = 2 if cmd == "/good" else -2
            detail = "admin_good" if score > 0 else "admin_bad"
            self.db.set_response_feedback(
                chat_id,
                reply_message_id,
                user_id,
                "admin",
                score,
                detail=detail,
            )
            style = response_meta.get("humor_style") or "none"
            if cmd == "/good":
                await self.send_command_notice(
                    chat_id,
                    f"Запомнил: такой ответ удачный. Стиль «{style}» получил сильный плюс.",
                    reply_to_message_id=reply_message_id,
                )
            else:
                await self.send_command_notice(
                    chat_id,
                    f"Запомнил: так отвечать хуже. Стиль «{style}» получил сильный минус.",
                    reply_to_message_id=reply_message_id,
                )
            return

        if cmd == "/profile":
            value = arg.lower()
            aliases = {"male": "male", "м": "male", "муж": "male", "female": "female", "ж": "female", "жен": "female", "neutral": "neutral", "нейтр": "neutral"}
            profile = aliases.get(value)
            if not profile:
                await self.send_command_notice(chat_id, "Использование: /profile male | female | neutral")
                return
            self.db.set_profile(chat_id, user_id, profile)
            await self.send_command_notice(chat_id, "Профиль стиля сохранён.")
            return

        if cmd in {"/on", "/off", "/hardness", "/h", "/time", "/t", "/frequency", "/silence"}:
            if not await self.is_admin(chat_id, user_id):
                await self.send_command_notice(chat_id, "Эту настройку может менять администратор группы.")
                return
            if cmd == "/on":
                self.db.update_chat(chat_id, enabled=1)
                await self.send_command_notice(chat_id, "Аксакал проснулся.")
                await self.show_settings(chat_id)
            elif cmd == "/off":
                self.db.update_chat(chat_id, enabled=0)
                await self.send_command_notice(chat_id, "Аксакал пока помолчит.")
            elif cmd in {"/hardness", "/h"}:
                value = arg.lower()
                aliases = {
                    "auto": "auto",
                    "normal": "normal", "нормальный": "normal", "норма": "normal", "1": "normal",
                    "angry": "angry", "злой": "angry", "2": "angry", "3": "angry",
                    "super": "super", "супер": "super", "суперзлой": "super", "супер-злой": "super", "4": "super", "5": "super",
                }
                selected = aliases.get(value)
                if selected == "auto":
                    self.db.update_chat(chat_id, hardness_mode="auto")
                    await self.send_command_notice(chat_id, "Режим: AUTO. Аксакал сам выбирает Нормальный, Злой или Супер злой по разговору.")
                elif selected in {"normal", "angry", "super"}:
                    mapped = {"normal": 1, "angry": 3, "super": 5}[selected]
                    label = {"normal": "Нормальный", "angry": "Злой", "super": "Супер злой"}[selected]
                    self.db.update_chat(chat_id, hardness_mode="fixed", fixed_hardness=mapped)
                    await self.send_command_notice(chat_id, f"Режим зафиксирован: {label}")
                else:
                    await self.send_command_notice(chat_id, "Использование: /hardness auto | normal | angry | super")
                    return
            elif cmd in {"/time", "/t"}:
                try:
                    n = int(arg)
                except ValueError:
                    await self.send_command_notice(chat_id, "Использование: /time 0 | 3 | 5 | 20 | 40 | 60 | 180")
                    return
                if n not in {0, 3, 5, 20, 40, 60, 180}:
                    await self.send_command_notice(chat_id, "Выбери: 0, 3, 5, 20, 40, 60 или 180 секунд.")
                    return
                self.db.update_chat(chat_id, response_delay_seconds=n)
                await self.send_command_notice(chat_id, f"Задержка ответа: {n} сек.")
            elif cmd == "/frequency":
                # Старый скрытый алиас: значения трактуем как секунды только из нового набора.
                try:
                    n = int(arg)
                except ValueError:
                    await self.send_command_notice(chat_id, "Теперь используй /time 0|3|5|20|40|60|180")
                    return
                if n not in {0, 3, 5, 20, 40, 60, 180}:
                    await self.send_command_notice(chat_id, "Теперь используй /time 3|5|20|40|60|180")
                    return
                self.db.update_chat(chat_id, response_delay_seconds=n)
                await self.send_command_notice(chat_id, f"Задержка ответа: {n} сек.")
            elif cmd == "/silence":
                try:
                    n = max(15, min(1440, int(arg)))
                except ValueError:
                    await self.send_command_notice(chat_id, "Использование: /silence количество_минут (15–1440)")
                    return
                self.db.update_chat(chat_id, silence_minutes=n)
                await self.send_command_notice(chat_id, f"Начну тормошить чат после {n} мин тишины.")
            return

        if cmd == "/roast":
            reply = msg.get("reply_to_message")
            if reply and reply.get("from") and not reply["from"].get("is_bot"):
                target_id = self.db.touch_user(chat_id, reply["from"], "message")
                reply_text = (reply.get("text") or reply.get("caption") or "").strip()
                reply_kind = "sticker" if reply.get("sticker") else "message"
                if reply_kind == "sticker":
                    reply_text = (reply.get("sticker") or {}).get("emoji") or "стикер"
                await self.roast(
                    chat_id,
                    target_id,
                    "пользователь явно попросил подкол через /roast",
                    reply_to_message_id=reply.get("message_id"),
                    source_text=reply_text,
                    source_kind=reply_kind,
                )
            else:
                await self.send_command_notice(chat_id, "Ответь командой /roast на сообщение человека.")

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
            return False

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
            delay = delay if delay in {0, 3, 5, 20, 40, 60, 180} else 20
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                await asyncio.sleep(0)

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

            reply = msg.get("reply_to_message") or {}
            reply_message_id = int(reply.get("message_id", 0) or 0)
            reply_from = reply.get("from") or {}
            low_source = source_text.lower()
            addressed_by_name = "аксакал" in low_source or (
                self.bot_username and f"@{self.bot_username}" in low_source
            )
            direct_to_bot = bool(
                (reply_message_id and self.db.get_bot_response(chat_id, reply_message_id))
                or (self.bot_user_id and int(reply_from.get("id", 0) or 0) == self.bot_user_id)
                or addressed_by_name
            )
            direct_attack = direct_to_bot and self.looks_like_attack(source_text)

            if is_sticker:
                source_text = (msg.get("sticker") or {}).get("emoji") or "стикер"
                reason = (
                    "человек отправил стикер вместо слов. Ответь именно на это: подшути, что пора писать словами. "
                    "Тон формулировки должен соответствовать выбранному режиму."
                )
            else:
                feedback = self.detect_address_feedback(source_text)
                greeting = self.detect_greeting_style(source_text)
                if direct_attack:
                    mood = "stern"
                    source_kind = "direct_attack"
                    reason = (
                        "человек прямо наехал на Аксакала. Ответь ему обратно умно, жёстко и по его конкретным словам. "
                        "Не становись воспитателем и не проси просто «сбавить тон». Если грубость лёгкая — колко поддень; "
                        "если сильная — можешь ответить грубее и с матом. Реальными угрозами не отвечай."
                    )
                elif feedback:
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
                        "или происхождение. Тон замечания должен соответствовать текущему режиму."
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
                    reason = "ответь прямо на последнее сообщение по существу; если там грубость — осади её в соответствии с текущим режимом"
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

            sent_ok = await self.roast(
                chat_id,
                sender_id,
                reason,
                mood=mood,
                reply_to_message_id=msg.get("message_id"),
                source_text=source_text,
                source_kind=source_kind,
            )

            # Кратковременный сбой/лимит AI не должен навсегда съедать реплику.
            # Делаем только одну повторную попытку; новое сообщение отменит эту задачу.
            if not sent_ok and self.generator.enabled:
                await asyncio.sleep(15)
                await self.roast(
                    chat_id,
                    sender_id,
                    reason + " Это повторная попытка после временной ошибки AI; сформулируй свежо и без повторов.",
                    mood=mood,
                    reply_to_message_id=msg.get("message_id"),
                    source_text=source_text,
                    source_kind=source_kind,
                )
        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"delayed reply error in chat {chat_id}: {type(e).__name__}: {e}")
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
        forced_level: int | None = None,
    ):
        assert self.tg
        chat = self.db.get_chat(chat_id)
        if not chat or not chat["enabled"]:
            return
        users = self.db.active_users(chat_id, 30 * 86400)
        target = next((u for u in users if u["user_id"] == target_user_id), None)
        if not target:
            return False
        context = self.db.recent_context(chat_id, config.context_message_limit)
        if forced_level in {1, 3, 5}:
            auto_level = int(forced_level)
        elif chat.get("hardness_mode", "auto") == "fixed":
            fixed = int(chat.get("fixed_hardness", 3))
            auto_level = 1 if fixed <= 2 else 3 if fixed <= 4 else 5
        else:
            auto_level = self.generator.detect_mode(context, mood=mood, source_text=source_text or "")
        personal_words = self.db.top_learned_words(chat_id, target_user_id, 14)
        group_words = self.db.top_learned_words(chat_id, None, 18)
        avoided_addresses = self.db.avoided_addresses(chat_id, target_user_id)
        recent_bot_replies = self.db.recent_bot_replies(chat_id, 24)
        relevant_memory = self.db.relevant_messages(chat_id, source_text or "", 8, 800)
        user_profile = self.db.user_profile_summary(chat_id, target_user_id)
        thread_context = self.db.message_thread(chat_id, reply_to_message_id, 8)
        recent_humor_styles = self.db.recent_humor_styles(chat_id, target_user_id, 5)
        style_preferences = self.db.humor_style_preferences(chat_id, target_user_id)
        manual_feedback_examples = self.db.manual_feedback_examples(chat_id, target_user_id, 8)
        humor_style = self.generator.choose_humor_style(
            source_text or "",
            recent_humor_styles,
            mood=mood or "playful",
            level=auto_level,
            has_memory=bool(thread_context or relevant_memory),
            style_preferences=style_preferences,
        )
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
            recent_bot_replies=recent_bot_replies,
            relevant_memory=relevant_memory,
            user_profile=user_profile,
            thread_context=thread_context,
            humor_style=humor_style,
            manual_feedback_examples=manual_feedback_examples,
        )
        if not text or not text.strip():
            print(f"AI skipped reply in chat {chat_id}: {self.generator.last_error or 'empty response'}")
            return False
        sent = await self.tg.send(chat_id, text, reply_to_message_id=reply_to_message_id)
        if isinstance(sent, dict) and sent.get("message_id"):
            self.db.add_bot_message(
                chat_id,
                int(sent["message_id"]),
                text,
                reply_to_message_id=reply_to_message_id,
                reply_to_user_id=target_user_id,
            )
            self.db.record_humor_style(chat_id, target_user_id, humor_style)
            self.db.register_bot_response(
                chat_id,
                int(sent["message_id"]),
                target_user_id,
                humor_style,
                auto_level,
            )
        now = int(time.time())
        self.db.update_chat(chat_id, last_bot_message_at=now)
        self.db.mark_roasted(chat_id, target_user_id)
        return True

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
            game = self.db.get_crocodile_game(int(chat["chat_id"]))
            if game and game.get("active"):
                continue
            silence_age = now - int(chat["last_activity_at"])
            bot_age = now - int(chat["last_bot_message_at"])
            threshold = int(chat["silence_minutes"]) * 60
            if silence_age < threshold or bot_age < threshold:
                continue
            users = self.db.active_users(int(chat["chat_id"]), 30 * 86400)
            if not users:
                continue

            # Предпочитаем тех, кого не трогали последний час. Если таких нет —
            # всё равно выбираем кого-то: тишина больше не должна зависать на 6 часов.
            fresh_candidates = [
                u for u in users
                if now - int(u["last_roasted_at"] or 0) > 3600
            ]
            candidates = fresh_candidates or users
            target = random.choice(candidates[: min(20, len(candidates))])

            silence_level = None
            if chat.get("hardness_mode", "auto") == "auto":
                silence_level = random.choices([1, 3, 5], weights=[30, 50, 20], k=1)[0]

            await self.roast(
                int(chat["chat_id"]),
                int(target["user_id"]),
                "в группе давно тишина. Сам выбери живой способ расшевелить компанию: можешь мягко позвать "
                "выбранного человека, иронично зацепить его, устроить короткий жёсткий подкол или задать ему "
                "провокационный, но безопасный вопрос. Не повторяй фразы про саму «тишину» каждый раз; придумай "
                "конкретный повод, используя реальные привычки и память группы.",
                source_text="нужно оживить молчащую группу",
                source_kind="silence",
                forced_level=silence_level,
            )


if __name__ == "__main__":
    asyncio.run(AksakalBot().run())
