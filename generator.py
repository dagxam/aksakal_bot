from __future__ import annotations

import re
import time
from typing import Any
import aiohttp


class PhraseGenerator:
    def __init__(
        self,
        enabled: bool = True,
        *,
        groq_api_key: str = "",
        groq_models: str = "openai/gpt-oss-120b,qwen/qwen3.8-27b,openai/gpt-oss-20b",
        mistral_api_key: str = "",
        mistral_model: str = "mistral-small-latest",
    ):
        self.groq_api_key = groq_api_key
        self.groq_models = [x.strip() for x in groq_models.split(",") if x.strip()]
        if not self.groq_models:
            self.groq_models = [
                "openai/gpt-oss-120b",
                "qwen/qwen3.8-27b",
                "openai/gpt-oss-20b",
            ]
        self.groq_model = self.groq_models[0]
        self.mistral_api_key = mistral_api_key
        self.mistral_model = mistral_model
        self.enabled = enabled and bool(groq_api_key or mistral_api_key)
        self.last_provider = ""
        self.last_error = ""
        self.provider_cooldowns: dict[str, float] = {}

    def provider_status(self) -> str:
        providers = []
        if self.groq_api_key:
            providers.append("Groq[" + " → ".join(self.groq_models) + "]")
        if self.mistral_api_key:
            providers.append(f"Mistral/{self.mistral_model}")
        if not providers:
            return "AI НЕ НАСТРОЕН — автоматические ответы отключены"
        status = " → ".join(providers)
        if self.last_provider:
            status += f" | последний ответ: {self.last_provider}"
        if self.last_error:
            status += f" | ошибка: {self.last_error[:120]}"
        return status

    async def health_check(self) -> dict[str, str]:
        """Минимальный реальный inference-тест каждой модели рабочей цепочки."""
        results: dict[str, str] = {}
        timeout = aiohttp.ClientTimeout(total=20)

        async def post_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> tuple[int, dict[str, Any] | str]:
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, headers=headers, json=payload) as resp:
                        try:
                            data: dict[str, Any] | str = await resp.json()
                        except Exception:
                            data = (await resp.text())[:800]
                        return resp.status, data
            except Exception as exc:
                return 0, f"{type(exc).__name__}: {exc}"

        def failure(status: int, data: dict[str, Any] | str) -> str:
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, dict):
                    detail = str(err.get("message") or err.get("status") or "")
                else:
                    detail = str(err or data.get("message") or "")
            else:
                detail = str(data)
            detail = " ".join(detail.split())[:180]
            return f"❌ HTTP {status or 'ошибка'}" + (f": {detail}" if detail else "")

        if not self.enabled:
            return {"AI": "❌ AI_ENABLED выключен или рабочие ключи не загружены"}

        prompt = "Ответь одним словом: работает"

        if self.groq_api_key:
            for model_id in self.groq_models:
                payload: dict[str, Any] = {
                    "model": model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_completion_tokens": 32,
                    "temperature": 0.2,
                }
                if model_id.startswith("openai/gpt-oss-"):
                    payload["reasoning_effort"] = "low"
                    payload["include_reasoning"] = False
                elif model_id.startswith("qwen/"):
                    payload["reasoning_effort"] = "none"
                status, data = await post_json(
                    "https://api.groq.com/openai/v1/chat/completions",
                    {
                        "Authorization": f"Bearer {self.groq_api_key}",
                        "Content-Type": "application/json",
                    },
                    payload,
                )
                results[f"Groq/{model_id}"] = "✅ работает" if status == 200 else failure(status, data)

        if self.mistral_api_key:
            status, data = await post_json(
                "https://api.mistral.ai/v1/chat/completions",
                {
                    "Authorization": f"Bearer {self.mistral_api_key}",
                    "Content-Type": "application/json",
                },
                {
                    "model": self.mistral_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 32,
                    "temperature": 0.2,
                },
            )
            results[f"Mistral/{self.mistral_model}"] = "✅ работает" if status == 200 else failure(status, data)

        if not results:
            results["AI"] = "❌ ни один рабочий ключ не загружен"
        return results

    @staticmethod
    def mention(user: dict[str, Any]) -> str:
        display = (user.get("display_name") or "").strip()
        if display:
            # В реплике используем обычное имя, а не @username.
            return display.split()[0]
        if user.get("username"):
            return user["username"].lstrip("@")
        return "участник"

    @staticmethod
    def is_information_question(text: str) -> bool:
        """Отличает реальный вопрос по смыслу от риторического подкола с вопросительным знаком."""
        low = " ".join((text or "").lower().replace("ё", "е").split())
        if not low:
            return False
        starters = (
            "кто ", "что ", "что такое ", "как ", "почему ", "зачем ", "когда ", "где ",
            "куда ", "откуда ", "сколько ", "какой ", "какая ", "какие ", "какое ",
            "чем ", "можно ли ", "нужно ли ", "стоит ли ", "есть ли ", "правда ли ",
            "объясни", "расскажи", "подскажи", "помоги", "посоветуй",
        )
        if low.startswith(starters):
            return True
        knowledge_markers = (
            "как сделать", "как работает", "как найти", "как получить", "как настроить",
            "в чем разница", "в чём разница", "что лучше", "что означает", "что значит",
        )
        return any(x in low for x in knowledge_markers)


    @staticmethod
    def choose_humor_style(
        source_text: str,
        recent_styles: list[str] | None,
        *,
        mood: str,
        level: int,
        has_memory: bool,
        style_preferences: dict[str, float] | None = None,
    ) -> str:
        """Выбирает технику юмора, не повторяя последние приёмы подряд."""
        if mood in {"supportive", "wise"} or PhraseGenerator.is_information_question(source_text):
            return "none"

        styles = ["dry", "logic", "analogy", "hyperbole", "wordplay"]
        if has_memory:
            styles.append("callback")
        if level >= 5:
            styles.append("correction")

        recent = [x for x in (recent_styles or []) if x and x != "none"][:3]
        preferences = style_preferences or {}
        candidates = [x for x in styles if x not in recent] or list(styles)

        acceptable = [x for x in candidates if float(preferences.get(x, 0.0)) > -2.0]
        if acceptable:
            candidates = acceptable

        seed = sum(ord(ch) for ch in (source_text or "")) + len(recent) * 17 + level * 11
        ranked = sorted(
            candidates,
            key=lambda x: (
                -float(preferences.get(x, 0.0)),
                (styles.index(x) - (seed % len(styles))) % len(styles),
            ),
        )
        return ranked[0]


    @staticmethod
    def _recent_text(context: list[dict[str, Any]], count: int = 12) -> str:
        return " ".join(
            (m.get("content") or "")
            for m in context[-count:]
            if m.get("kind") in {"message", "sticker", "reaction"}
        ).lower()

    @staticmethod
    def detect_mood(context: list[dict[str, Any]]) -> str:
        # Главный приоритет — последнее сообщение пользователя. Старый контекст не должен
        # превращать обычную новую реплику в грусть/конфликт из-за прошлой темы.
        last = next(
            (
                (m.get("content") or "").lower()
                for m in reversed(context)
                if m.get("kind") in {"message", "sticker"} and (m.get("content") or "").strip()
            ),
            "",
        )
        if not last:
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

        if any(re.search(p, last) for p in supportive):
            return "supportive"
        hostile_hits = sum(bool(re.search(p, last)) for p in hostile)
        if hostile_hits >= 2:
            return "stern"
        if hostile_hits == 1:
            return "calm"
        if any(re.search(p, last) for p in serious):
            return "wise"
        return "playful"

    @staticmethod
    def detect_mode(
        context: list[dict[str, Any]],
        *,
        mood: str | None = None,
        source_text: str = "",
    ) -> int:
        """AUTO выбирает один из трёх режимов: 1=Нормальный, 3=Злой, 5=Супер злой."""
        mood = mood or PhraseGenerator.detect_mood(context)
        current = (source_text or "").lower()

        # Грусть, серьёзная тема и настоящий вопрос требуют содержательного ответа,
        # а не попытки обязательно пошутить.
        if mood in {"supportive", "wise"} or PhraseGenerator.is_information_question(source_text):
            return 1

        text = PhraseGenerator._recent_text(context, 10)
        combined = f"{text} {current}"

        rough = [
            r"\bнах\w*", r"\bхрен\w*", r"\bпизд\w*", r"\bеб\w*", r"\bёб\w*",
            r"\bсука\b", r"\bбля\w*", r"\bмраз\w*", r"\bдолбо\w*", r"\bидиот\w*",
        ]
        taunts = [
            r"\bтуп\w*", r"\bмозг\w*\s+нет", r"\bклоун\w*", r"\bбред\w*",
            r"\bзаткни\w*", r"\bобосрал\w*", r"\bслабак\w*", r"\bбессиль\w*",
            r"😂|🤣|ахах|хаха|лол|ору|ржу",
        ]

        rough_hits = sum(bool(re.search(p, combined)) for p in rough)
        taunt_hits = sum(bool(re.search(p, combined)) for p in taunts)

        if rough_hits >= 2 or (rough_hits >= 1 and taunt_hits >= 2) or taunt_hits >= 4:
            return 5
        if mood in {"stern", "calm"} or rough_hits >= 1 or taunt_hits >= 1:
            return 3
        return 1

    @staticmethod
    def address_profile_violation(text: str, profile: str, avoided_addresses: list[str] | None = None) -> str:
        """
        Жёсткий фильтр обращений. Даже если модель проигнорировала prompt, она не может
        назвать человека «брат/сестра» или другим гендерным обращением, пока профиль
        не подтверждён самим пользователем в переписке.
        """
        low = " ".join((text or "").lower().replace("ё", "е").split())
        if not low:
            return ""

        avoided = {x.lower().replace("ё", "е") for x in (avoided_addresses or []) if x}
        male_addresses = ("брат", "братан", "братец", "парень", "молодой", "джигит", "вацок", "уцы")
        female_addresses = ("сестра", "сестрёнка", "сестренка", "девушка", "молодая")

        # Ищем именно обращение, а не упоминание третьего лица вроде «твой брат пришёл».
        # Типичные формы обращения: в начале реплики, после запятой/тире или в конце после запятой.
        def used_as_address(token: str) -> bool:
            token_re = re.escape(token)
            patterns = (
                rf"^s*{token_re}(?:s|[,!?.:;—-]|$)",
                rf"[,;:—-]s*{token_re}(?:s|[,!?.:;—-]|$)",
                rf"(?:слушай|смотри|скажи|пойми|давай|эй)s*,?s*{token_re}",
                rf"{token_re}s*[!?.]?s*$",
            )
            return any(re.search(p, low, re.I) for p in patterns)

        for token in male_addresses + female_addresses:
            if token in avoided and re.search(rf"{re.escape(token)}", low):
                return f"запрещённое пользователем обращение: {token}"

        male_used = next((x for x in male_addresses if used_as_address(x)), "")
        female_used = next((x for x in female_addresses if used_as_address(x)), "")

        if profile == "neutral":
            if male_used or female_used:
                return "гендерное обращение до подтверждения профиля"
        elif profile == "male":
            if female_used:
                return "женское обращение к пользователю с мужским профилем"
        elif profile == "female":
            if male_used:
                return "мужское обращение к пользователю с женским профилем"
        return ""

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
        relevant_memory: list[dict[str, Any]] | None = None,
        user_profile: dict[str, Any] | None = None,
        thread_context: list[dict[str, Any]] | None = None,
        humor_style: str = "none",
        manual_feedback_examples: list[dict[str, Any]] | None = None,
    ) -> str:
        mood = mood or self.detect_mood(context)
        recent_bot_replies = recent_bot_replies or []
        relevant_memory = relevant_memory or []
        user_profile = user_profile or {}
        thread_context = thread_context or []
        manual_feedback_examples = manual_feedback_examples or []
        if not self.enabled:
            self.last_error = "нет настроенного AI-провайдера"
            return ""

        profile = target.get("style_profile", "neutral")
        target_display = self.mention(target)
        transcript = []
        recent_context = context[-30:]
        by_message_id = {
            int(m.get("telegram_message_id") or 0): m
            for m in recent_context
            if int(m.get("telegram_message_id") or 0)
        }
        for m in recent_context:
            who = m.get("display_name") or m.get("username") or "участник"
            relation = ""
            parent_id = int(m.get("reply_to_message_id") or 0)
            parent = by_message_id.get(parent_id)
            if parent:
                parent_name = parent.get("display_name") or parent.get("username") or "участник"
                relation = f" [ответ {parent_name}]"
            transcript.append(f"{who}{relation}: [{m['kind']}] {m.get('content','')}")
        transcript_text = "\n".join(transcript) or "(контекста почти нет)"
        memory_lines = []
        seen_memory = set()
        for m in relevant_memory[:8]:
            line = f"{m.get('display_name') or 'участник'}: {m.get('content','')}"
            if line not in seen_memory:
                seen_memory.add(line)
                memory_lines.append(line)
        memory_text = "\n".join(memory_lines) or "(релевантных старых сообщений не найдено)"

        thread_lines = []
        thread_by_id = {
            int(m.get("telegram_message_id") or 0): m
            for m in thread_context
            if int(m.get("telegram_message_id") or 0)
        }
        for m in thread_context:
            who = m.get("display_name") or m.get("username") or "участник"
            parent = thread_by_id.get(int(m.get("reply_to_message_id") or 0))
            relation = ""
            if parent:
                parent_name = parent.get("display_name") or parent.get("username") or "участник"
                relation = f" → ответ {parent_name}"
            thread_lines.append(f"{who}{relation}: {m.get('content','')}")
        thread_text = "\n".join(thread_lines) or "(отдельной reply-цепочки нет)"

        profile_phrases = ", ".join(
            f"{x.get('token')}×{x.get('count')}"
            for x in user_profile.get("frequent_phrases", [])[:10]
        ) or "(ещё не накоплены)"
        profile_targets = ", ".join(
            f"{x.get('display_name') or x.get('target_id')}×{x.get('cnt')}"
            for x in user_profile.get("frequent_reply_targets", [])[:3]
        ) or "(явных постоянных собеседников нет)"
        profile_recent = " | ".join(
            str(x.get("content") or "")
            for x in user_profile.get("recent_messages", [])[:4]
            if x.get("content")
        ) or "(нет)"
        user_profile_text = (
            f"сообщений={user_profile.get('message_count',0)}, "
            f"стикеров={user_profile.get('sticker_count',0)}, "
            f"реакций={user_profile.get('reaction_count',0)}; "
            f"повторяющиеся выражения: {profile_phrases}; "
            f"кому чаще отвечает: {profile_targets}; "
            f"недавние реплики: {profile_recent}"
        )

        good_examples = [
            (x.get("content") or "").strip()
            for x in manual_feedback_examples
            if int(x.get("score") or 0) > 0 and (x.get("content") or "").strip()
        ][:3]
        bad_examples = [
            (x.get("content") or "").strip()
            for x in manual_feedback_examples
            if int(x.get("score") or 0) < 0 and (x.get("content") or "").strip()
        ][:3]
        good_examples_text = "\n".join(f"+ {x}" for x in good_examples) or "(пока нет)"
        bad_examples_text = "\n".join(f"- {x}" for x in bad_examples) or "(пока нет)"

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
                "Это стикер. Реагируй именно на то, что человек заменил им обычную реплику. "
                "В Злом и Супер злом режимах замечание может быть колче; формулировку придумай самостоятельно."
            ),
            "reaction": "Это реакция/эмодзи. Подколи именно реакцию, не выдумывай новую тему.",
            "direct_attack": (
                "Человек обращается прямо к тебе и грубит/оскорбляет. Не читай ему лекцию про вежливость и не отвечай "
                "канцелярским «снизь тон». Верни реплику умно и колко в той же энергии: можно грубить, материться "
                "и высмеять его формулировку или логику. Не угрожай реальным насилием и не цепляй чувствительные признаки."
            ),
            "silence": (
                "Это режим тишины. Тут не нужно отвечать на конкретную тему: выбери живую провокацию, "
                "обратись к выбранному человеку по имени и попробуй расшевелить всю группу."
            ),
            "profile_correction": (
                "Пользователь поправил обращение к себе. Подшути коротко над самой поправкой, покажи что понял "
                "и не используй запрещённое обращение в этой реплике."
            ),
            "greeting_correction": (
                "Это обычное светское приветствие. Сделай короткое замечание именно о форме приветствия "
                "и предложи «Ассаламу алейкум». Формулировку придумай сам, не используй готовый шаблон. "
                "Не приписывай человеку национальность, религию или происхождение."
            ),
            "greeting_salam": (
                "Это салам. Начни содержательную часть с «Ва алейкум ассалам» и не ругай человека за приветствие."
            ),
        }.get(source_kind, "Отвечай строго на текущий смысл.")

        mode_rules = {
            "supportive": "Человек или чат звучит грустно/тяжело. НЕ подкалывай. Поддержи коротко, тепло и без пафоса.",
            "calm": "Есть напряжение. Не морализируй: ответь спокойно, но с характером и по существу.",
            "stern": "Есть явная грубость/конфликт. Ответь жёстко, умно и колко; можешь вернуть сарказмом или грубостью, если это уместно. Не переходи к реальным угрозам.",
            "wise": "Тема серьёзная. Дай короткую умную, жизненную мысль по контексту без морализаторства.",
            "playful": "Обычный живой разговор. Можно уместно подколоть по теме разговора.",
        }

        behavior_mode = "normal" if level <= 1 else "angry" if level <= 3 else "super_angry"
        behavior_rules = {
            "normal": (
                "НОРМАЛЬНЫЙ. Веди себя как умный живой собеседник и старший товарищ. "
                "Если задан вопрос — сначала реально ответь на него настолько полно, насколько нужно. "
                "Если тема жизненная, можно добавить меткую собственную мысль или известную цитату только если уверен в авторстве; "
                "иначе формулируй как свою мысль без автора. Если человеку грустно — поддержи конкретно по его ситуации. "
                "Юмор только ситуативный: не вставляй подкол ради самого подкола."
            ),
            "angry": (
                "ЗЛОЙ. Отвечай резко, умно и с характером. Цепляйся за конкретное противоречие, слабый аргумент, "
                "самоуверенную формулировку или смешную ошибку. Можно использовать мат, если он естественен. "
                "Не скатывайся в детские случайные обзывания: лучше одна точная колкость, чем три пустых оскорбления."
            ),
            "super_angry": (
                "СУПЕР ЗЛОЙ. Очень жёсткий взрослый разговорный стёб: мат, резкий сарказм, издёвка, двусмысленность и "
                "точечное унижение слабой логики или нелепой формулировки. Если есть явная ошибка — можешь исправить её так, "
                "чтобы само исправление стало частью подкола. Отвечай остроумно, а не просто набором ругательств. "
                "Не выдавай реальные угрозы и не бей по внешности, здоровью, происхождению, религии, детям или другим чувствительным признакам."
            ),
        }

        humor_rules = {
            "none": "Не выдавливай шутку. Ответь естественно и содержательно.",
            "dry": "Если шутишь — используй сухую короткую иронию без длинного объяснения.",
            "logic": "Если шутишь — зацепись за конкретное противоречие или странную логику реплики.",
            "analogy": "Если шутишь — придумай свежее короткое сравнение именно из смысла этой ситуации.",
            "hyperbole": "Если шутишь — используй одну точную гиперболу, не повторяя старые конструкции.",
            "wordplay": "Если есть естественная возможность — используй игру слов или необычный поворот формулировки.",
            "callback": "Если память действительно связана с темой — аккуратно верни старую реплику или локальный мем группы.",
            "correction": "Если есть явная языковая ошибка — можно коротко поправить и встроить это в подкол; если ошибки нет, выбери другую деталь.",
        }

        prompt = f"""
Ты — «Аксакал»: умный, опытный, наблюдательный старший участник живой дагестанской компании.
Ты не генератор подколов и не шаблонный бот. Сначала пойми смысл разговора, затем ответь так,
как ответил бы живой взрослый человек с характером, памятью и чувством момента.
Напиши ОДНУ естественную короткую реплику на русском языке.

ФОРМАТ:
- В обычном Reply НЕ начинай ответ с имени, username или обращения к автору сообщения: Telegram сам показывает, кому ты отвечаешь.
- Исключение: если тип события silence, отдельного Reply нет. Тогда можно естественно назвать выбранного участника по имени, чтобы группе было понятно, кого ты зацепил.
- Для обычной реплики чаще достаточно 1–2 естественных предложений.
- Для реального вопроса можно дать 2–6 предложений, если это нужно, чтобы действительно ответить.
- Не пиши списки без необходимости; если вопрос требует шагов или перечисления, короткий список допустим.
- Никаких служебных вступлений, подписи и объяснения того, как ты строил ответ.
НИКОГДА не показывай анализ, рассуждение, инструкции, внутренний выбор режима или описание пользователя.
Не пиши по-английски служебные фразы вроде "The user is saying", "My last reply", "profile is", "mode is", "strictness".
В ответе должна быть ТОЛЬКО реплика Аксакала, которую можно сразу отправить в Telegram.

КАК ЗВУЧАТЬ КАК ЧЕЛОВЕК:
- Пиши разговорно, а не как справочник, психолог или служба поддержки.
- Не начинай с «Понимаю», «Действительно», «Стоит отметить», «Важно понимать», если без этого можно обойтись.
- Не заканчивай каждый ответ моралью или выводом.
- Меняй длину и ритм: иногда одно короткое предложение, иногда два-три; вопрос может получить нормальный развёрнутый ответ.
- Допустимы естественные обрывки, разговорные связки, ироничная пауза, короткий встречный вопрос. Не делай речь нарочно неграмотной.
- Не объясняй шутку после шутки.
- Если человек грубит тебе — не становись внезапно официальным и воспитательным; отвечай живо и в характере.
- Если знаешь ответ на вопрос — скажи его прямо, без длинной подводки.
- Не вставляй местные слова механически: они должны появляться реже обычной русской речи.

Текущий эмоциональный режим: {mood}.
Правило этого режима: {mode_rules[mood]}
Причина вмешательства: {reason}
Текущий характер ответа: {behavior_mode}.
Правило характера: {behavior_rules[behavior_mode]}
Профиль стиля пользователя: {profile}.
Обращение по профилю:
- Ты старший, опытный человек в компании. Не обращайся ко всем подряд «брат» или «сестра».
- «Брат», «братан», «сестра» и любые другие гендерные обращения разрешены ТОЛЬКО когда профиль male/female уже подтверждён самим человеком в переписке.
- male: если обращение действительно нужно, говори как старший к молодому — иногда «молодой», «парень», «джигит», реже «вацок» или «уцы». «Брат» лучше не использовать даже здесь без особой необходимости.
- female: если обращение действительно нужно, естественно «девушка», «молодая». «Сестра» лучше не использовать без особой необходимости.
- neutral: профиль ещё не подтверждён — ЗАПРЕЩЕНЫ «брат», «сестра», «парень», «девушка», «молодой», «молодая», «джигит», «вацок», «уцы». Просто отвечай без обращения.
- В большинстве Reply обращение вообще не нужно: Telegram и так показывает адресата.
- Используй максимум одно обращение и только если оно звучит живо, а не как повторяющаяся кличка.
- Никогда не используй обращения, которые этот человек уже запретил: {avoided_text}.
Тип события: {source_kind}.
Выбранный участник для этого события: {target_display}
Правило события: {source_rule}

ТОЧНОЕ СООБЩЕНИЕ, НА КОТОРОЕ ТЫ ОБЯЗАН ОТВЕТИТЬ:
{exact_source}

Контекст группы — только фон, чтобы понять предыдущую мысль, людей и локальные шутки:
{transcript_text}

REPLY-ЦЕПОЧКА ТЕКУЩЕГО РАЗГОВОРА:
{thread_text}
Если сообщение является ответом на другое, эта цепочка важнее случайных соседних сообщений.

ПОВЕДЕНЧЕСКАЯ ПАМЯТЬ ОБ ЭТОМ УЧАСТНИКЕ:
{user_profile_text}
Это только наблюдения из самой группы. Не делай из них выводов о здоровье, происхождении, религии, личности или других чувствительных качествах.

РУЧНОЕ ОБУЧЕНИЕ АДМИНИСТРАТОРА:
Удачные прошлые ответы:
{good_examples_text}

Неудачные прошлые ответы:
{bad_examples_text}

Используй хорошие примеры только как ориентир по естественности, ритму и качеству. Не копируй их дословно и не переноси из них факты в новую тему.
Плохие примеры показывают, каких конструкций и манеры лучше избегать. Смысл текущего сообщения всегда важнее примеров.

ТЕКУЩИЙ ПРИЁМ ЮМОРА: {humor_style}
Правило приёма: {humor_rules.get(humor_style, humor_rules["none"])}
Не называй этот приём в ответе. Если он не подходит по смыслу, лучше не шутить вовсе.

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА СМЫСЛА:
- ТОЧНОЕ СООБЩЕНИЕ выше — главный и обязательный источник ответа. Сначала ответь именно на него, а уже потом используй контекст.
- Если точное сообщение само по себе понятно, игнорируй несвязанные соседние реплики, даже если они ярче, смешнее или проще для шутки.
- Если точное сообщение является Reply, используй цепочку только чтобы понять ссылку, местоимение, короткое «да/нет/ага» или недосказанную мысль. Не отвечай вместо текущего сообщения на его родителя.
- Твой ответ должен выглядеть так, будто живой человек нажал Reply именно на выбранную реплику и продолжил именно её.
- Твой ответ обязан продолжать именно эту тему или прямо реагировать на высказанную мысль.
- Нельзя брать случайную старую тему из контекста, если она не связана с текущим сообщением.
- Нельзя выдавать универсальный roast вроде «уверенности много» без связи с конкретной фразой пользователя.
- Если в сообщении есть объект/тема (машина, работа, деньги, отношения, игра, еда, человек, поездка и т.д.) — обязательно отрази её в ответе.
- Если это настоящий вопрос — ДАЙ ПОЛЕЗНЫЙ ОТВЕТ. Не заменяй ответ шуткой, уклонением или фразой в стиле «сам разберись».
- Можно отвечать на любые обычные темы, которые знает модель: бытовые вопросы, техника, история, игры, отношения, учёба, культура, объяснения терминов и советы.
- Если для точного ответа нужны свежие данные из интернета, которых у тебя нет, честно обозначь это и не выдумывай факты.
- После содержательного ответа можно добавить одну уместную шутку или аксакальскую мысль, только если она реально улучшает ответ.
- Если это утверждение — отреагируй именно на это утверждение.
- Если видишь очевидную опечатку/ошибку: в Нормальном режиме обычно игнорируй или мягко поправь только если это полезно; в Злом можно подколоть; в Супер злом можно коротко исправить слово и язвительно зацепиться за ошибку. Не придирайся к каждой мелочи подряд.
- Если это короткая реплика вроде «да», «нет», «ага», смайла или стикера — используй предыдущую связанную реплику как тему, но не придумывай новую.
- Не выдумывай факты, которых нет в текущем сообщении или предыдущем контексте.
- Ты ОБЯЗАН отвечать НА СМЫСЛ текущего сообщения, а не на отдельные слова из него.
- Если нет повода для подкола — нормально продолжи разговор, ответь на вопрос, уточни или дай уместную человеческую реакцию.
- НЕ цитируй и НЕ пересказывай сообщение пользователя обратно ему.
- Не строй ответ по шаблону «вот это “...” требует объяснений», «ты это серьёзно или...», «по теме “...”» и подобным конструкциям.
- Не пиши бессодержательные фразы вроде «раскрывай мысль», если из сообщения уже понятен смысл.
- Если сообщение короткое («с тобой что», «не хочу», «устал», «да ладно») — используй ближайшие 2–5 реплик контекста, чтобы понять, о чём речь.
- Никогда не подставляй случайную универсальную фразу вместо реакции на конкретное содержание.
- ЮМОР: не шути по одному и тому же шаблону. Ищи конкретную смешную деталь текущей реплики: противоречие, преувеличение, выбор слов, неожиданную логику, прошлую связанную реплику или реальную привычку человека в чате.
- Не пытайся сделать смешной каждую фразу. Иногда сухой точный ответ сильнее натянутой шутки.
- Избегай одинаковых конструкций вроде «ты так сказал, будто...», «ещё немного и...», «это уже...», если похожая конструкция недавно использовалась.
- Можно использовать сравнение, иронию, короткую гиперболу, игру слов или callback к недавнему разговору, но только когда это естественно.
- В Злом и Супер злом режимах можно сильнее цепляться за реально замеченные привычки в этой группе: повторяющиеся слова, споры, молчание, стикеры, реакции, самоуверенную манеру, противоречия и явные языковые ошибки. Не выдумывай личные факты.

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
- Не называй всех «брат». По роли ты старший, а не ровесник каждого участника.
- Гендерное обращение бери только из сохранённого профиля: male — иногда «молодой», «парень», «джигит», «вацок», «уцы»; female — «девушка», «молодая»; neutral — без гендерного обращения. Не смешивай их.
- Можно делать бытовые отсылки к чаю, хинкалу, чуду, свадьбам, горам, двору, соседям, родственникам, машине, работе и обычной жизни — только если это реально подходит к контексту.
- Не превращай речь в карикатуру: местные слова используй редко и только когда они реально звучат естественно.
- Не начинай каждую реплику с «ле», «йо», «вацок», «уцы». Большинство ответов должны обходиться без них.
- Аксакал может быть и серьёзным, и ироничным, и коротко мудрым; он не обязан подкалывать каждую реплику.
- Не приписывай человеку национальность, аул, тейп, религию или происхождение, если это не сказано в чате.
- Не высмеивай акцент, этничность или религиозность.

Общие правила:
- Всегда учитывай конкретную тему разговора, а не выдавай случайную заготовку.
- Тон выбранного режима должен ощущаться естественным продолжением разговора.
- В AUTO внутренний анализ эмоции помогает выбрать Нормальный, Злой или Супер злой; пользователю эти внутренние категории не показывай.
- В supportive не высмеивай грусть, боль, одиночество или уязвимость.
- В stern не морализируй. Если на тебя наехали — можешь ответить грубо и насмешливо, но цепляйся за сказанное, а не за чувствительные признаки человека.
- Не выдумывай факты о личной жизни.
- Если сообщение содержит реальную угрозу или обещание насилия, ответь строго по теме и не усиливай угрозу: можно осадить, высмеять браваду или предложить сбавить обороты, но не угрожай в ответ и не подталкивай к насилию.
- Не затрагивай трагедии, здоровье, внешность, детей, этничность, религию и другие болезненные признаки ради шутки.
- В Супер злом режиме допустим взрослый дерзкий юмор, крепкая лексика и двусмысленность по контексту, но без графических сексуальных описаний и реальных угроз.
- Не используй слово «Аксакал» внутри самой реплики.
""".strip()

        import difflib

        def normalize(value: str) -> str:
            return re.sub(r"\W+", " ", (value or "").lower()).strip()

        def validate_candidate(raw_text: str) -> tuple[str, str]:
            text = (raw_text or "").strip().replace("\n", " ")
            if not text:
                return "", "пустой ответ"

            # Имя пользователя в начале ответа не нужно: Telegram уже показывает reply.
            text = text.lstrip("—-: ").strip()
            normalized = normalize(text)
            source_norm = normalize(source_text or "")

            address_error = self.address_profile_violation(
                text,
                profile,
                avoided_addresses,
            )
            if address_error:
                return "", address_error

            for old in recent_bot_replies[:16]:
                old_norm = normalize(old)
                if old_norm and difflib.SequenceMatcher(None, normalized, old_norm).ratio() >= 0.72:
                    return "", "слишком похож на недавний ответ"

            answer_body = normalized

            if source_norm and len(source_norm) >= 8:
                similarity = difflib.SequenceMatcher(None, answer_body, source_norm).ratio()
                if similarity >= 0.68:
                    return "", "слишком близко повторяет сообщение пользователя"

            banned_templates = (
                "требует объяснений",
                "ты это сейчас серьезно или",
                "ты это сейчас серьёзно или",
                "раскрывай мысль",
                "по теме",
            )
            if any(x in answer_body for x in banned_templates):
                return "", "шаблонная формулировка"

            target_name = self.mention(target)
            target_name_norm = normalize(target_name)
            if (
                source_kind != "silence"
                and target_name_norm
                and re.match(rf"^{re.escape(target_name_norm)}(?:\s|—|-|:|,)", answer_body)
            ):
                return "", "модель лишний раз начала ответ с имени пользователя"

            meta_leaks = (
                "the user is saying",
                "the user says",
                "my last reply",
                "user profile",
                "profile is",
                "mode is",
                "strictness",
                "the mode",
                "i should respond",
                "i need to respond",
                "the conversation",
                "the user's profile",
                "system prompt",
                "developer message",
                "assistant analysis",
                "reasoning:",
                "analysis:",
                "current mode",
                "this message means",
                "the correct response",
                "i will respond",
                "i'll respond",
                "the appropriate response",
                "conversation context",
                "the user's message",
                "internal",
                "уровень жесткости",
                "уровень жёсткости",
                "профиль пользователя",
                "режим playful",
                "режим stern",
                "режим supportive",
            )
            low_raw = (raw_text or "").lower()
            if any(marker in low_raw for marker in meta_leaks):
                return "", "модель раскрыла служебное рассуждение"

            # Английское объяснение перед русской репликой тоже считаем утечкой.
            if re.match(r"^\s*(the user|user is|i should|i need|this is|my last)", low_raw):
                return "", "модель начала с внутреннего анализа"

            # Короткие человеческие ответы допустимы. Отбрасываем только совсем универсальные заглушки.
            generic_fillers = {
                "понятно", "ясно", "бывает", "окей", "ладно", "ну да", "ну понятно",
                "интересно", "согласен", "точно", "вот именно",
            }
            if (
                source_kind == "message"
                and not self.is_information_question(source_text or "")
                and answer_body in generic_fillers
            ):
                return "", "универсальная короткая заглушка"

            return text[:500], ""

        async def post_json(name: str, url: str, key: str, payload: dict[str, Any]) -> dict[str, Any]:
            now = time.time()
            cooldown_until = float(self.provider_cooldowns.get(name, 0.0) or 0.0)
            if cooldown_until > now:
                left = max(1, int(cooldown_until - now))
                raise RuntimeError(f"{name} временно на cooldown ещё {left} сек")

            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            timeout = aiohttp.ClientTimeout(total=25)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status >= 300:
                        body = await resp.text()
                        if resp.status == 429:
                            retry_after = 0
                            try:
                                retry_after = int(float(resp.headers.get("Retry-After", "0") or 0))
                            except (TypeError, ValueError):
                                retry_after = 0
                            if retry_after <= 0:
                                match = re.search(r"retry(?:\s+after)?[^0-9]{0,20}(\d+)", body, re.I)
                                retry_after = int(match.group(1)) if match else 60
                            retry_after = max(15, min(retry_after, 3600))
                            self.provider_cooldowns[name] = time.time() + retry_after
                        raise RuntimeError(f"{name} HTTP {resp.status}: {body[:700]}")
                    self.provider_cooldowns.pop(name, None)
                    return await resp.json()

        async def call_groq(
            model_id: str,
            input_prompt: str = prompt,
            max_tokens: int = 420,
            temperature: float = 0.75,
        ) -> tuple[str, str]:
            payload: dict[str, Any] = {
                "model": model_id,
                "messages": [{"role": "user", "content": input_prompt}],
                "max_completion_tokens": max_tokens,
                "temperature": temperature,
            }
            if model_id.startswith("openai/gpt-oss-"):
                payload["reasoning_effort"] = "low"
                payload["include_reasoning"] = False
            elif model_id.startswith("qwen/"):
                payload["reasoning_effort"] = "none"
            data = await post_json(
                f"Groq/{model_id}",
                "https://api.groq.com/openai/v1/chat/completions",
                self.groq_api_key,
                payload,
            )
            choices = data.get("choices") or []
            content = ((choices[0].get("message") or {}).get("content") or "") if choices else ""
            return content, str(data.get("model") or model_id)

        async def call_mistral(
            input_prompt: str = prompt,
            max_tokens: int = 420,
            temperature: float = 0.75,
        ) -> tuple[str, str]:
            payload = {
                "model": self.mistral_model,
                "messages": [{"role": "user", "content": input_prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            data = await post_json(
                f"Mistral/{self.mistral_model}",
                "https://api.mistral.ai/v1/chat/completions",
                self.mistral_api_key,
                payload,
            )
            choices = data.get("choices") or []
            content = ((choices[0].get("message") or {}).get("content") or "") if choices else ""
            return content, str(data.get("model") or self.mistral_model)

        attempts: list[tuple[str, Any]] = []
        if self.groq_api_key:
            for model_id in self.groq_models:
                async def try_groq(mid=model_id):
                    return await call_groq(mid)
                attempts.append((f"Groq/{model_id}", try_groq))
        if self.mistral_api_key:
            attempts.append((f"Mistral/{self.mistral_model}", call_mistral))

        errors: list[str] = []
        chosen = ""
        chosen_provider = ""
        chosen_model = ""

        for provider_name, attempt in attempts:
            try:
                raw, model_used = await attempt()
                candidate, quality_error = validate_candidate(raw)
                if candidate:
                    chosen = candidate
                    chosen_provider = provider_name
                    chosen_model = model_used
                    break
                errors.append(f"{provider_name}: {quality_error}")
                print(f"AI quality retry: {provider_name}: {quality_error}")
            except Exception as exc:
                errors.append(f"{provider_name}: {exc}")
                print(f"AI provider error: {provider_name}: {exc}")

        if not chosen:
            self.last_provider = ""
            self.last_error = " | ".join(errors)[-700:] if errors else "AI не вернул пригодный ответ"
            if errors:
                print("All AI attempts failed:", " | ".join(errors))
            return ""

        # Qwen проверяет черновик от GPT-OSS/Mistral. Если основной ответ уже от Qwen,
        # второй запрос не нужен.
        editor_used = False
        editor_model_id = (
            "qwen/qwen3.8-27b"
            if "qwen/qwen3.8-27b" in self.groq_models
            else (self.groq_models[0] if self.groq_models else "")
        )
        if self.groq_api_key and editor_model_id and chosen_provider != f"Groq/{editor_model_id}":
            review_prompt = f"""
Ты — строгий редактор одной Telegram-реплики. Ничего не объясняй.

Сообщение пользователя:
{exact_source}

Reply-цепочка:
{thread_text}

Режим ответа: {behavior_mode}
Выбранный приём юмора: {humor_style}

Черновик:
{chosen}

Проверь:
1) отвечает ли он именно на смысл сообщения и reply-цепочки;
2) если это вопрос — есть ли реальный полезный ответ;
3) если это шутка — привязана ли она к конкретной детали, а не универсальна;
4) не повторяет ли он сообщение пользователя и не звучит ли как шаблонный бот;
5) нет ли имени пользователя в начале;
6) нет ли служебного анализа или объяснения внутренних правил.

Если черновик по теме, естественный и не нарушает эти пункты — ответь ровно: OK. Не переписывай его просто ради более красивого текста.
Не делай реплику литературнее, вежливее или официальнее; сохраняй разговорность, сарказм, мат и ритм, если они уместны.
Переписывай только при явной проблеме. Тогда верни ТОЛЬКО улучшенную финальную реплику без комментариев и без имени пользователя.
Не добавляй новые факты, которых нет в черновике/контексте.
""".strip()
            try:
                edited_raw, editor_model = await call_groq(
                    editor_model_id,
                    review_prompt,
                    max_tokens=260,
                    temperature=0.25,
                )
                if edited_raw.strip().upper() != "OK":
                    edited, edit_error = validate_candidate(edited_raw)
                    if edited:
                        chosen = edited
                        editor_used = True
                    elif edit_error:
                        print(f"AI editor rejected its rewrite: {edit_error}")
                else:
                    editor_used = True
            except Exception as exc:
                print(f"AI editor error: {exc}")

        self.last_provider = f"{chosen_provider} → {chosen_model}" + (
            f" + editor/{editor_model_id}" if editor_used else ""
        )
        self.last_error = ""
        return chosen

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        parts: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    parts.append(content["text"])
        return " ".join(parts)
