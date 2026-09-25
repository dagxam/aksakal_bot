from __future__ import annotations

import random
import re
from typing import Any
import aiohttp


FALLBACKS = {
    "playful": {
        1: [
            "{u} — сегодня ты подозрительно серьёзный, жи есть. Это временно?",
            "{u} — мысль хорошая, не испорть продолжением.",
            "{u} — спокойно, уцы, пока всё звучит разумно.",
            "{u} — вот сейчас нормально сказал, не сглазь.",
            "{u} — редкий случай: даже спорить пока не хочется.",
            "{u} — мысль понял. Продолжай, пока всё не испортил.",
            "{u} — сегодня без суеты идёшь, даже непривычно.",
            "{u} — нормально начал. Финал не подведи.",
        ],
        2: [
            "{u} — уцы, уверенности много. Теперь осталось найти основания.",
            "{u} — ты так молчишь, будто мнение ещё проходит согласование.",
            "{u} — хабар пошёл уверенный, факты догонят потом?",
            "{u} — ты опять начал так, будто уже всех переубедил.",
            "{u} — спокойно, вацок, мысль ещё можно спасти.",
            "{u} — ты сейчас мнение выдал или объявление сделал?",
            "{u} — всё красиво сказал, осталось понять зачем.",
            "{u} — ещё немного уверенности — и сам себе поверишь окончательно.",
        ],
        3: [
            "{u} — аргументы закончились, а хабар всё идёт.",
            "{u} — ты сейчас очень смело идёшь туда, где фактов уже нет.",
            "{u} — уцы, ты спор уже не ведёшь, ты его тащишь на характере.",
            "{u} — факты вышли, а ты всё ещё на сцене.",
            "{u} — ты сейчас не объясняешь, ты давишь уверенностью.",
            "{u} — ещё одно сообщение, и твоя версия станет семейной легендой.",
            "{u} — моросишь уже красиво, почти профессионально.",
            "{u} — ты как всегда: сначала уверенно, потом разберёмся.",
        ],
        4: [
            "{u} — ле, если бы уверенность считалась доказательством, спор уже закрыли бы.",
            "{u} — мысль закончилась раньше сообщения, но ты героически продолжил.",
            "{u} — уцы, ты сейчас не споришь, ты выживаешь на одной наглости.",
            "{u} — фактов ноль, подачи как на свадьбе.",
            "{u} — ты эту мысль так долго толкаешь, она уже сама устала.",
            "{u} — брат, тут даже твоя уверенность просит сделать паузу.",
            "{u} — ещё чуть-чуть и спор начнёт извиняться перед всеми.",
            "{u} — ты так уверенно несёшь это, будто возврат не предусмотрен.",
        ],
        5: [
            "{u} — ты сейчас так зашёл, будто стыд вообще в отпуск отправил.",
            "{u} — ещё чуть-чуть такой подачи, и группе понадобится возрастное ограничение.",
            "{u} — у тебя сегодня тормоза сняты, а здравый смысл даже не пристегнулся.",
            "{u} — ты это написал так уверенно, будто последствия читать не собираешься.",
            "{u} — мысль дерзкая. Ещё дерзче только то, что ты решил её отправить.",
            "{u} — сегодня ты явно выбрал режим: сначала сказать, потом уже жить с последствиями.",
            "{u} — тут уже не подкол нужен, тут свидетелей опрашивать пора.",
            "{u} — ещё одна такая фраза — и чат сам попросит поставить 18+.",
        ],
    },
    "supportive": [
        "{u} — сабур. Не держи всё в себе, иногда разговор реально помогает.",
        "{u} — тяжёлый день не означает тяжёлую жизнь. Держись.",
        "{u} — выдохни. Не всё нужно решить прямо сейчас.",
        "{u} — если тяжело, лучше сказать об этом, чем молча тащить всё одному.",
    ],
    "calm": [
        "{u} — сейчас лучше немного остыть, чем потом жалеть о словах.",
        "{u} — пауза иногда сильнее самого громкого ответа.",
        "{u} — не спеши отвечать на злости. Через десять минут мысль может звучать иначе.",
    ],
    "stern": [
        "{u} — тормози, да. Грубость аргумент сильнее не делает.",
        "{u} — если мысль хорошая, ей не нужен крик.",
        "{u} — тормози. Разговор ещё можно оставить разговором.",
        "{u} — злость громкая, а правота пока не доказана.",
    ],
    "wise": [
        "{u} — не каждый спор нужно выигрывать. Иногда важнее сохранить уважение.",
        "{u} — не мороси: половина ошибок начинается там, где вывод делают раньше фактов.",
        "{u} — слова быстро забываются, а отношение после них остаётся.",
        "{u} — спокойствие тоже сила, просто она не шумит.",
    ],
}


class PhraseGenerator:
    def __init__(
        self,
        api_key: str,
        model: str,
        enabled: bool = True,
        *,
        openrouter_api_key: str = "",
        openrouter_model: str = "openrouter/free",
    ):
        self.openai_api_key = api_key
        self.model = model
        self.openrouter_api_key = openrouter_api_key
        self.openrouter_model = openrouter_model
        self.enabled = enabled and bool(api_key or openrouter_api_key)

    def provider_status(self) -> str:
        providers = []
        if self.openai_api_key:
            providers.append("OpenAI")
        if self.openrouter_api_key:
            providers.append("OpenRouter Free")
        if not providers:
            return "fallback без AI"
        return " → ".join(providers) + " — контекстные ответы"

    @staticmethod
    def mention(user: dict[str, Any]) -> str:
        display = (user.get("display_name") or "").strip()
        if display:
            # В реплике используем обычное имя, а не @username.
            return display.split()[0]
        if user.get("username"):
            return user["username"].lstrip("@")
        return "участник"

    def fallback(
        self,
        user: dict[str, Any],
        mood: str = "playful",
        level: int = 2,
        source_text: str | None = None,
        source_kind: str = "message",
        avoided_addresses: list[str] | None = None,
        recent_bot_replies: list[str] | None = None,
        relevant_memory: list[dict[str, Any]] | None = None,
    ) -> str:
        mention = self.mention(user)
        recent_norm = {
            re.sub(r"\W+", " ", x.lower()).strip()
            for x in (recent_bot_replies or [])
            if x
        }

        def fresh_choice(options: list[str]) -> str:
            if not options:
                return f"{mention} — понял."
            fresh = [
                x for x in options
                if re.sub(r"\W+", " ", x.lower()).strip() not in recent_norm
            ]
            return random.choice(fresh or options)
        profile = user.get("style_profile", "neutral")
        avoided = {x.lower().replace("ё", "е") for x in (avoided_addresses or [])}
        choices = {
            "male": ["вацок", "уцы", "брат", "ле"],
            "female": ["тётка", "сестра", "йо", "ле"],
            "neutral": ["йо", "ле", ""],
        }.get(profile, ["йо", "ле", ""])
        choices = [x for x in choices if not x or x.lower().replace("ё", "е") not in avoided]
        address = random.choice(choices or [""])
        prefix = f"{address}, " if address else ""
        source = (source_text or "").strip()
        if source_kind == "profile_correction":
            correction_lines = [
                f"{mention} — понял, понял. Один раз ошибся — уже личное дело завели.",
                f"{mention} — принято. Поправил меня быстро, будто протокол составлял.",
                f"{mention} — всё, запомнил. Второй раз такой роскоши не будет.",
                f"{mention} — понял тебя. Видишь, даже старших иногда приходится обучать.",
            ]
            return fresh_choice(correction_lines)
        if source_kind == "greeting_correction":
            greeting_lines = {
                1: [
                    f"{mention} — привет принят, но у нас красивее: Ассаламу алейкум.",
                    f"{mention} — давай по-нормальному: Ассаламу алейкум.",
                ],
                2: [
                    f"{mention} — что за «привет»? Ассаламу алейкум говори, звучит как надо.",
                    f"{mention} — «здравствуйте» оставь для кабинета, тут Ассаламу алейкум.",
                ],
                3: [
                    f"{mention} — ле, это что за «привет»? Нормально здоровайся: Ассаламу алейкум.",
                    f"{mention} — ты как на приём пришёл. Ассаламу алейкум скажи нормально.",
                ],
                4: [
                    f"{mention} — что за официальный заход? Ассаламу алейкум говори, не мороси.",
                    f"{mention} — «привет» он написал. Ва государственное учреждение пришёл? Ассаламу алейкум.",
                ],
                5: [
                    f"{mention} — ты с этим «привет» как турист в чат зашёл. Ассаламу алейкум говори нормально.",
                    f"{mention} — {prefix}убери это сухое «здравствуйте». Ассаламу алейкум — и разговор пошёл.",
                ],
            }
            return fresh_choice(greeting_lines[max(1, min(5, level))])
        if source_kind == "greeting_salam":
            return fresh_choice([
                f"{mention} — Ва алейкум ассалам. Вот теперь нормально зашёл.",
                f"{mention} — Ва алейкум ассалам. Хабар теперь можно начинать.",
                f"{mention} — Ва алейкум ассалам. Проходи, рассказывай что стало.",
            ])
        if source_kind == "sticker":
            sticker_lines = [
                f"{mention} — {prefix}хватит картинки кидать, пиши словами, буквы ещё не закончились.",
                f"{mention} — {prefix}опять стикер? Ты писать разучился или клавиатура обиделась?",
                f"{mention} — {prefix}словами попробуй, мы тут не выставку стикеров открыли.",
                f"{mention} — {prefix}ещё один стикер и я решу, что буквы ты принципиально игнорируешь.",
            ]
            return fresh_choice(sticker_lines)
        if source_kind == "silence":
            silence_lines = [
                f"{mention} — {prefix}ты там живой? Разбуди остальных, группа уже пылью покрывается.",
                f"{mention} — {prefix}давай хоть ты начни хабар, остальные будто телефоны продали.",
                f"{mention} — {prefix}куда все пропали? Скажи что-нибудь спорное, сейчас народ соберётся.",
                f"{mention} — {prefix}группа молчит. Начинай суету, на тебя последняя надежда.",
            ]
            return fresh_choice(silence_lines)
        if source and mood == "playful":
            compact = re.sub(r"\s+", " ", source)
            if len(compact) > 70:
                compact = compact[:67].rstrip() + "..."
            topical = [
                f"{mention} — {prefix}по «{compact}» ты это сейчас серьёзно или суету наводишь?",
                f"{mention} — {prefix}вот это «{compact}» уже требует объяснений.",
                f"{mention} — {prefix}по теме «{compact}» ты уверенно зашёл, теперь раскрывай мысль.",
            ]
            return fresh_choice(topical)
        if mood == "playful":
            pool = FALLBACKS["playful"].get(max(1, min(5, level)), FALLBACKS["playful"][2])
        else:
            pool = FALLBACKS.get(mood, FALLBACKS["playful"][2])
        return fresh_choice([x.format(u=mention) for x in pool])

    @staticmethod
    def _recent_text(context: list[dict[str, Any]], count: int = 12) -> str:
        return " ".join(
            (m.get("content") or "")
            for m in context[-count:]
            if m.get("kind") in {"message", "sticker", "reaction"}
        ).lower()

    @staticmethod
    def detect_mood(context: list[dict[str, Any]]) -> str:
        text = PhraseGenerator._recent_text(context, 10)
        if not text.strip():
            return "playful"

        supportive = [
            r"\bгруст", r"\bтяжело\b", r"\bплохо\b", r"\bобид", r"\bустал", r"\bбольно\b",
            r"\bодинок", r"\bне могу\b", r"\bнет сил\b", r"\bпережива", r"\bслез", r"\bплачу\b",
        ]
        hostile = [
            r"\bзаткни", r"\bидиот", r"\bтупой\b", r"\bдурак", r"\bненавиж", r"\bбесишь",
            r"\bпош[её]л\b", r"\bсдох", r"\bурод", r"\bмраз", r"\bтвар",
        ]
        serious = [
            r"\bжизн", r"\bдовер", r"\bуважен", r"\bотношен", r"\bлюбов", r"\bсемь",
            r"\bдружб", r"\bпредател", r"\bошибк", r"\bвыбор\b", r"\bбудущее\b",
        ]

        if any(re.search(p, text) for p in supportive):
            return "supportive"
        hostile_hits = sum(bool(re.search(p, text)) for p in hostile)
        if hostile_hits >= 2:
            return "stern"
        if hostile_hits == 1:
            return "calm"
        if any(re.search(p, text) for p in serious):
            return "wise"
        return "playful"

    @staticmethod
    def detect_intensity(context: list[dict[str, Any]], max_level: int = 5) -> int:
        """Определяет фактическую жёсткость 1..5 по текущему стилю группы.

        max_level — административный потолок. Алгоритм не поднимается выше него.
        Эмоциональные режимы supportive/calm/wise всё равно имеют приоритет над roast.
        """
        max_level = max(1, min(5, int(max_level)))
        text = PhraseGenerator._recent_text(context, 16)
        if not text.strip():
            return min(2, max_level)

        score = 0

        if re.search(r"(?:😂|🤣|😄|😆|ахах|хаха|лол|ору|ржу)", text):
            score += 1

        teasing = [
            r"\bтормоз", r"\bклоун", r"\bгений\b", r"\bэксперт", r"\bсмешн", r"\bбред",
            r"\bчуш", r"\bфигн", r"\bприкол", r"\bподкол", r"\bдушн", r"\bзадел",
        ]
        score += min(2, sum(bool(re.search(p, text)) for p in teasing))

        rough = [
            r"\bблин\b", r"\bчерт\b", r"\bчёрт\b", r"\bкапец\b", r"\bжесть\b",
            r"\bнах\w*", r"\bхрен\w*", r"\bпипец\b",
        ]
        rough_hits = sum(bool(re.search(p, text)) for p in rough)
        if rough_hits >= 1:
            score += 1
        if rough_hits >= 2:
            score += 1
        if rough_hits >= 4:
            score += 1

        # Дополнительные сигналы текущей беседы: частота сообщений, капс, восклицания,
        # обращения друг к другу и повторяющиеся резкие ответы.
        recent = context[-12:]
        reactionish = sum(1 for m in recent if m.get("kind") in {"reaction", "sticker"})
        if reactionish >= 3:
            score += 1

        raw_recent = " ".join((m.get("content") or "") for m in recent if m.get("kind") == "message")
        if raw_recent.count("!") >= 4:
            score += 1
        caps_words = re.findall(r"\b[А-ЯЁA-Z]{4,}\b", raw_recent)
        if len(caps_words) >= 2:
            score += 1
        if len(recent) >= 8:
            score += 1

        if score <= 0:
            level = 1
        elif score <= 2:
            level = 2
        elif score <= 4:
            level = 3
        elif score <= 6:
            level = 4
        else:
            level = 5

        return min(level, max_level)

    async def generate(
        self,
        *,
        target: dict[str, Any],
        context: list[dict[str, Any]],
        level: int,
        reason: str,
        mood: str | None = None,
        personal_words: list[dict[str, Any]] | None = None,
        group_words: list[dict[str, Any]] | None = None,
        source_text: str | None = None,
        source_kind: str = "message",
        avoided_addresses: list[str] | None = None,
        recent_bot_replies: list[str] | None = None,
    ) -> str:
        mood = mood or self.detect_mood(context)
        recent_bot_replies = recent_bot_replies or []
        relevant_memory = relevant_memory or []
        if not self.enabled:
            return self.fallback(target, mood, level, source_text, source_kind, avoided_addresses, recent_bot_replies)

        mention = self.mention(target)
        profile = target.get("style_profile", "neutral")
        transcript = []
        for m in context[-30:]:
            who = m.get("display_name") or m.get("username") or "участник"
            transcript.append(f"{who}: [{m['kind']}] {m.get('content','')}")
        transcript_text = "\n".join(transcript) or "(контекста почти нет)"
        memory_lines = []
        seen_memory = set()
        for m in relevant_memory[:8]:
            line = f"{m.get('display_name') or 'участник'}: {m.get('content','')}"
            if line not in seen_memory:
                seen_memory.add(line)
                memory_lines.append(line)
        memory_text = "\n".join(memory_lines) or "(релевантных старых сообщений не найдено)"
        recent_reply_text = "\n".join(f"- {x}" for x in recent_bot_replies[:16]) or "(ещё нет)"
        exact_source = (source_text or "").strip()
        if not exact_source:
            for m in reversed(context):
                if (m.get("content") or "").strip():
                    exact_source = (m.get("content") or "").strip()
                    break
        exact_source = exact_source or "(нет содержимого сообщения)"
        personal_words = personal_words or []
        group_words = group_words or []
        personal_lexicon = ", ".join(x["token"] for x in personal_words[:12]) or "(ещё не накоплен)"
        group_lexicon = ", ".join(x["token"] for x in group_words[:14]) or "(ещё не накоплен)"
        avoided_addresses = [x.lower() for x in (avoided_addresses or [])]
        avoided_text = ", ".join(avoided_addresses) or "(нет)"
        source_rule = {
            "message": "Это обычное сообщение. Отвечай строго на его смысл.",
            "sticker": (
                "Это СТИКЕР. Не придумывай тему, которой нет. Подколи именно факт, что человек вместо слов шлёт стикер. "
                "На жёсткости 4–5 можно колко сказать, что пора писать словами, что буквы не закончились и т.п."
            ),
            "reaction": "Это реакция/эмодзи. Подколи именно реакцию, не выдумывай новую тему.",
            "silence": (
                "Это режим тишины. Тут не нужно отвечать на конкретную тему: выбери живую провокацию, "
                "обратись к выбранному человеку по имени и попробуй расшевелить всю группу."
            ),
            "profile_correction": (
                "Пользователь поправил обращение к себе. Подшути коротко над самой поправкой, покажи что понял "
                "и не используй запрещённое обращение в этой реплике."
            ),
            "greeting_correction": (
                "Это обычное приветствие вроде «привет», «здравствуйте» или «здорово». "
                "Сделай замечание именно про приветствие и предложи здороваться «Ассаламу алейкум». "
                "Можно пошутить в духе «что за привет, нормально здоровайся», но не приписывай человеку "
                "национальность, религию или происхождение."
            ),
            "greeting_salam": (
                "Это салам. Начни содержательную часть с «Ва алейкум ассалам» и не ругай человека за приветствие."
            ),
        }.get(source_kind, "Отвечай строго на текущий смысл.")

        mode_rules = {
            "supportive": "Человек или чат звучит грустно/тяжело. НЕ подкалывай. Поддержи коротко, тепло и без пафоса.",
            "calm": "Есть напряжение или злость. Не подливай масла в огонь. Коротко успокой и предложи сбавить тон.",
            "stern": "Есть явная грубость/конфликт. Ответь сурово и уверенно, осади хамство, но не унижай и не провоцируй драку.",
            "wise": "Тема серьёзная. Дай короткую умную, жизненную мысль по контексту без морализаторства.",
            "playful": "Обычный живой разговор. Можно уместно подколоть по теме разговора.",
        }

        intensity_rules = {
            1: "Мягко и доброжелательно. Если подкалываешь — только лёгкая ирония.",
            2: "Дружеский подкол заметнее, но без грубости.",
            3: "Колко и уверенно, можно ощутимо задеть привычку или конкретную реплику, оставаясь по теме.",
            4: "Очень жёсткий персональный стёб по конкретной реплике и реально замеченным привычкам; можно крепкую лексику, если чат так говорит.",
            5: (
                "Самый жёсткий взрослый режим. Допустимы резкие формулировки, крепкая лексика и "
                "двусмысленные взрослые намёки, если сама беседа к этому ведёт. Можно почти 18+, "
                "но без графических сексуальных описаний, угроз, травли и выпадов по чувствительным признакам."
            ),
        }

        prompt = f"""
Ты — Telegram-бот «Аксакал», наблюдательный, остроумный и иногда суровый участник дружеской группы.
Напиши ОДНУ короткую реплику на русском языке.

ЖЁСТКИЙ ФОРМАТ: ответ начинается ровно с "{mention} — " и дальше одна фраза.
Никаких вступлений, кавычек, списков, объяснений и подписи. Обычно 5–18 слов, максимум 25.

Текущий эмоциональный режим: {mood}.
Правило этого режима: {mode_rules[mood]}
Причина вмешательства: {reason}
Автоматически выбранная жёсткость сейчас: {level}/5.
Правило жёсткости: {intensity_rules[max(1, min(5, level))]}
Профиль стиля пользователя: {profile}.
Обращение по профилю:
- male: можно естественно использовать «вацок», «уцы», «брат», «ле».
- female: можно естественно использовать «тётка», «сестра», «йо», «ле».
- neutral: не используй гендерное обращение; допускаются нейтральные «йо» или «ле».
- Используй максимум одно такое обращение в реплике и только если оно звучит естественно.
- Никогда не используй обращения, которые этот человек уже запретил: {avoided_text}.
Тип события: {source_kind}.
Правило события: {source_rule}

ТОЧНОЕ СООБЩЕНИЕ, НА КОТОРОЕ ТЫ ОБЯЗАН ОТВЕТИТЬ:
{exact_source}

Контекст группы — только фон, чтобы понять предыдущую мысль, людей и локальные шутки:
{transcript_text}

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА СМЫСЛА:
- Сначала пойми, О ЧЁМ ИМЕННО говорит точное сообщение выше.
- Твой ответ обязан продолжать именно эту тему или прямо реагировать на высказанную мысль.
- Нельзя брать случайную старую тему из контекста, если она не связана с текущим сообщением.
- Нельзя выдавать универсальный roast вроде «уверенности много» без связи с конкретной фразой пользователя.
- Если в сообщении есть объект/тема (машина, работа, деньги, отношения, игра, еда, человек, поездка и т.д.) — обязательно отрази её в ответе.
- Если это вопрос — ответь по сути вопроса и только потом можешь добавить подкол.
- Если это утверждение — отреагируй именно на это утверждение.
- Если это короткая реплика вроде «да», «нет», «ага», смайла или стикера — используй предыдущую связанную реплику как тему, но не придумывай новую.
- Не выдумывай факты, которых нет в текущем сообщении или предыдущем контексте.
- Ты ОБЯЗАН ответить на текущее сообщение после таймера. Если нет повода для подкола — дай короткую естественную реакцию по существу.
- Никогда не подставляй случайную универсальную фразу вместо реакции на конкретное содержание.
- На жёсткости 4–5 можно сильнее задевать человека, но только через реально замеченные привычки в этой группе: его повторяющиеся слова, споры, молчание, стикеры, реакции, самоуверенную манеру и т.п. Не выдумывай личные факты.

ДОЛГОВРЕМЕННАЯ ПАМЯТЬ ПО ТЕКУЩЕЙ ТЕМЕ:
{memory_text}
Используй её только если она реально связана с текущим сообщением. Не вытаскивай старые темы случайно.

ПОСЛЕДНИЕ ОТВЕТЫ АКСАКАЛА — НЕ ПОВТОРЯЙ ИХ И НЕ ПЕРЕФРАЗИРУЙ СЛИШКОМ БЛИЗКО:
{recent_reply_text}
Меняй лексику, ритм, конструкцию и тип шутки. Не начинай несколько ответов подряд одинаково.

Память речи:
- Частые слова и выражения именно этого участника: {personal_lexicon}
- Частые слова и выражения этой группы: {group_lexicon}
- Можно иногда естественно вернуть человеку его же характерное словечко или локальный мем группы.
- Не копируй механически и не повторяй сленг в каждом ответе.
- Не используй выученные слова, если они относятся к оскорблениям по внешности, здоровью, происхождению, религии или другим чувствительным признакам.
- Для мужчин и женщин правило одинаковое: стиль определяется их реальной манерой переписки, а не стереотипами.

Дагестанская подача:
- Общайся как живой дагестанский аксакал/старший в компании: коротко, метко, с местным ритмом речи.
- Иногда, но не в каждом сообщении, естественно используй узнаваемые слова и обороты: «жи есть», «ле», «йо», «сабур», «ахча», «хабар», «чанда», «что стало?», «моросишь», «тормози», «оставь», «суету наводишь».
- Гендерные обращения бери только из профиля выше: для male допустимы «вацок», «уцы», «брат»; для female — «тётка», «сестра». Не смешивай их.
- Можно делать бытовые отсылки к чаю, хинкалу, чуду, свадьбам, горам, двору, соседям, родственникам, машине, работе и обычной жизни — только если это реально подходит к контексту.
- Не превращай речь в карикатуру: 1 местный маркер на реплику максимум, а часто лучше вообще без него.
- Не приписывай человеку национальность, аул, тейп, религию или происхождение, если это не сказано в чате.
- Не высмеивай акцент, этничность или религиозность.

Общие правила:
- Всегда учитывай конкретную тему разговора, а не выдавай случайную заготовку.
- Жёсткость должна ощущаться естественным продолжением тона группы.
- Если режим supportive/calm/wise/stern — он важнее roast и обычной жёсткости.
- В supportive не высмеивай грусть, боль, одиночество или уязвимость.
- В stern осуждай поведение/тон, а не личность человека.
- Не выдумывай факты о личной жизни.
- Не затрагивай трагедии, здоровье, внешность, детей, этничность, религию и другие болезненные признаки ради шутки.
- На уровне 5 допустим более взрослый, дерзкий, двусмысленный юмор и крепкая лексика по контексту, но без графических сексуальных описаний.
- Не используй слово «Аксакал» внутри самой реплики.
""".strip()

        base_payload = {
            "input": prompt,
            "max_output_tokens": 140,
        }

        async def call_provider(name: str, url: str, key: str, model: str) -> str:
            payload = dict(base_payload)
            payload["model"] = model
            if name == "OpenAI":
                payload["reasoning"] = {"effort": "low"}
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            timeout = aiohttp.ClientTimeout(total=25)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status >= 300:
                        body = await resp.text()
                        raise RuntimeError(f"{name} HTTP {resp.status}: {body[:700]}")
                    data = await resp.json()
            return self._extract_text(data).strip().replace("\n", " ")

        providers = []
        if self.openai_api_key:
            providers.append(("OpenAI", "https://api.openai.com/v1/responses", self.openai_api_key, self.model))
        if self.openrouter_api_key:
            providers.append(("OpenRouter", "https://openrouter.ai/api/v1/responses", self.openrouter_api_key, self.openrouter_model))

        errors = []
        text = ""
        for provider in providers:
            try:
                text = await call_provider(*provider)
                if text:
                    break
            except Exception as exc:
                errors.append(str(exc))
                print(f"AI provider error: {exc}")

        if not text:
            if errors:
                print("All AI providers failed:", " | ".join(errors))
            return self.fallback(target, mood, level, source_text, source_kind, avoided_addresses, recent_bot_replies)

        if not text.startswith(f"{mention} — "):
            text = f"{mention} — {text.lstrip('-—: ')}"

        # Защита от почти дословных повторов. При сильном совпадении используем
        # контекстный локальный fallback вместо очередной одинаковой реплики.
        import difflib
        normalized = re.sub(r"\W+", " ", text.lower()).strip()
        for old in recent_bot_replies[:12]:
            old_norm = re.sub(r"\W+", " ", old.lower()).strip()
            if old_norm and difflib.SequenceMatcher(None, normalized, old_norm).ratio() >= 0.78:
                return self.fallback(
                    target, mood, level, source_text, source_kind,
                    avoided_addresses, recent_bot_replies
                )
        return text[:500]

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        parts: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    parts.append(content["text"])
        return " ".join(parts)
