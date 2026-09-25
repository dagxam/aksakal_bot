from __future__ import annotations

import re
from typing import Any
import aiohttp


class PhraseGenerator:
    def __init__(
        self,
        api_key: str,
        model: str,
        enabled: bool = True,
        *,
        openrouter_api_key: str = "",
        openrouter_model: str = "openrouter/free",
        openrouter_models: str = "",
        groq_api_key: str = "",
        groq_model: str = "qwen/qwen3.8-27b",
    ):
        self.openai_api_key = api_key
        self.model = model
        self.openrouter_api_key = openrouter_api_key
        self.openrouter_model = openrouter_model
        self.openrouter_models = [
            x.strip()
            for x in (openrouter_models or openrouter_model or "openrouter/free").split(",")
            if x.strip()
        ]
        if not self.openrouter_models:
            self.openrouter_models = ["openrouter/free"]
        self.groq_api_key = groq_api_key
        self.groq_model = groq_model
        self.enabled = enabled and bool(api_key or openrouter_api_key or groq_api_key)
        self.last_provider = ""
        self.last_error = ""

    def provider_status(self) -> str:
        providers = []
        if self.openai_api_key:
            providers.append("OpenAI")
        if self.groq_api_key:
            providers.append(f"Groq/{self.groq_model}")
        if self.openrouter_api_key:
            providers.append("OpenRouter[" + " → ".join(self.openrouter_models) + "]")
        if not providers:
            return "AI НЕ НАСТРОЕН — автоматические ответы отключены"
        status = " → ".join(providers)
        if self.last_provider:
            status += f" | последний ответ: {self.last_provider}"
        if self.last_error:
            status += f" | ошибка: {self.last_error[:120]}"
        return status

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

        # Грусть, серьёзный вопрос и уязвимость всегда тянут в нормальный режим:
        # здесь важнее умно ответить или поддержать, чем издеваться.
        if mood in {"supportive", "wise"}:
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
    ) -> str:
        mood = mood or self.detect_mood(context)
        recent_bot_replies = recent_bot_replies or []
        relevant_memory = relevant_memory or []
        if not self.enabled:
            self.last_error = "нет настроенного AI-провайдера"
            return ""

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
                "Это стикер. Реагируй именно на то, что человек заменил им обычную реплику. "
                "Чем выше жёсткость, тем колче замечание, но придумай формулировку самостоятельно."
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
            "calm": "Есть напряжение или злость. Не подливай масла в огонь. Коротко успокой и предложи сбавить тон.",
            "stern": "Есть явная грубость/конфликт. Ответь сурово и уверенно, осади хамство, но не унижай и не провоцируй драку.",
            "wise": "Тема серьёзная. Дай короткую умную, жизненную мысль по контексту без морализаторства.",
            "playful": "Обычный живой разговор. Можно уместно подколоть по теме разговора.",
        }

        behavior_mode = "normal" if level <= 1 else "angry" if level <= 3 else "super_angry"
        behavior_rules = {
            "normal": (
                "НОРМАЛЬНЫЙ. Главная задача — поддерживать разговор умно и по теме. "
                "На вопрос отвечай по существу; если уместна мудрая мысль, используй короткий афоризм или жизненную формулировку, "
                "но не выдумывай авторство цитат. Если человеку грустно — поддержи конкретно по его ситуации. "
                "Можно слегка пошутить, но не превращай всё в подкол."
            ),
            "angry": (
                "ЗЛОЙ. Отвечай резко, колко и уверенно, цепляйся за противоречия, слабые аргументы и неудачные формулировки. "
                "Можно использовать умеренный мат, если он естественен для текущего разговора. "
                "Не уходи в случайные оскорбления: каждый укол должен быть связан с конкретными словами человека."
            ),
            "super_angry": (
                "СУПЕР ЗЛОЙ. Максимально жёсткий взрослый стёб по теме: резкая лексика, мат, сарказм, "
                "двусмысленные взрослые намёки, издёвка над противоречиями, нелепой формулировкой или очевидной опечаткой. "
                "Если пользователь ошибся в слове или грамматике и ошибка заметна, можешь сначала коротко поправить, затем подколоть. "
                "Не выдавай реальные угрозы, не призывай к насилию, не трави по внешности, здоровью, происхождению, религии, детям "
                "или другим чувствительным признакам. Жёсткость направляй на сказанное и поведение в чате."
            ),
        }

        prompt = f"""
Ты — «Аксакал»: умный, опытный, наблюдательный старший участник живой дагестанской компании.
Ты не генератор подколов и не шаблонный бот. Сначала пойми смысл разговора, затем ответь так,
как ответил бы живой взрослый человек с характером, памятью и чувством момента.
Напиши ОДНУ естественную короткую реплику на русском языке.

ЖЁСТКИЙ ФОРМАТ: ответ начинается ровно с "{mention} — " и дальше одна фраза.
Никаких вступлений, кавычек, списков, объяснений и подписи. Обычно 5–18 слов, максимум 25.
НИКОГДА не показывай анализ, рассуждение, инструкции, внутренний выбор режима или описание пользователя.
Не пиши по-английски служебные фразы вроде "The user is saying", "My last reply", "profile is", "mode is", "strictness".
В ответе должна быть ТОЛЬКО реплика Аксакала, которую можно сразу отправить в Telegram.

Текущий эмоциональный режим: {mood}.
Правило этого режима: {mode_rules[mood]}
Причина вмешательства: {reason}
Текущий характер ответа: {behavior_mode}.
Правило характера: {behavior_rules[behavior_mode]}
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
- Гендерные обращения бери только из профиля выше: для male допустимы «вацок», «уцы», «брат»; для female — «тётка», «сестра». Не смешивай их.
- Можно делать бытовые отсылки к чаю, хинкалу, чуду, свадьбам, горам, двору, соседям, родственникам, машине, работе и обычной жизни — только если это реально подходит к контексту.
- Не превращай речь в карикатуру: местные слова используй редко и только когда они реально звучат естественно.
- Не начинай каждую реплику с «ле», «йо», «вацок», «уцы». Большинство ответов должны обходиться без них.
- Аксакал может быть и серьёзным, и ироничным, и коротко мудрым; он не обязан подкалывать каждую реплику.
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

            if not text.startswith(f"{mention} — "):
                text = f"{mention} — {text.lstrip('-—: ')}"

            normalized = normalize(text)
            source_norm = normalize(source_text or "")

            for old in recent_bot_replies[:16]:
                old_norm = normalize(old)
                if old_norm and difflib.SequenceMatcher(None, normalized, old_norm).ratio() >= 0.72:
                    return "", "слишком похож на недавний ответ"

            answer_body = normalized
            mention_norm = normalize(mention)
            if mention_norm and answer_body.startswith(mention_norm):
                answer_body = answer_body[len(mention_norm):].strip()

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

            # Бессодержательные ответы из одного-двух слов для обычного сообщения тоже не отправляем.
            if source_kind == "message" and len(answer_body.split()) < 3:
                return "", "слишком короткий бессодержательный ответ"

            return text[:500], ""

        async def post_json(name: str, url: str, key: str, payload: dict[str, Any]) -> dict[str, Any]:
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            timeout = aiohttp.ClientTimeout(total=25)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status >= 300:
                        body = await resp.text()
                        raise RuntimeError(f"{name} HTTP {resp.status}: {body[:700]}")
                    return await resp.json()

        async def call_openai() -> tuple[str, str]:
            payload = {
                "model": self.model,
                "input": prompt,
                "max_output_tokens": 160,
                "reasoning": {"effort": "low"},
            }
            data = await post_json(
                "OpenAI",
                "https://api.openai.com/v1/responses",
                self.openai_api_key,
                payload,
            )
            return self._extract_text(data), str(data.get("model") or self.model)

        async def call_groq() -> tuple[str, str]:
            payload = {
                "model": self.groq_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_completion_tokens": 180,
                "temperature": 0.75,
                "reasoning_effort": "none",
            }
            data = await post_json(
                "Groq",
                "https://api.groq.com/openai/v1/chat/completions",
                self.groq_api_key,
                payload,
            )
            choices = data.get("choices") or []
            content = ((choices[0].get("message") or {}).get("content") or "") if choices else ""
            return content, str(data.get("model") or self.groq_model)

        async def call_openrouter(model_id: str) -> tuple[str, str]:
            # OpenRouter's documented fallback-compatible OpenAI endpoint.
            # We iterate models ourselves so a low-quality-but-successful answer can also
            # fall through to the next model, not only HTTP/rate-limit failures.
            payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 180,
                "temperature": 0.8,
            }
            data = await post_json(
                f"OpenRouter/{model_id}",
                "https://openrouter.ai/api/v1/chat/completions",
                self.openrouter_api_key,
                payload,
            )
            choices = data.get("choices") or []
            content = ((choices[0].get("message") or {}).get("content") or "") if choices else ""
            return content, str(data.get("model") or model_id)

        attempts: list[tuple[str, Any]] = []
        if self.openai_api_key:
            attempts.append(("OpenAI", call_openai))
        if self.groq_api_key:
            attempts.append((f"Groq/{self.groq_model}", call_groq))
        if self.openrouter_api_key:
            for model_id in self.openrouter_models:
                async def try_model(mid=model_id):
                    return await call_openrouter(mid)
                attempts.append((f"OpenRouter/{model_id}", try_model))

        errors: list[str] = []

        for provider_name, attempt in attempts:
            try:
                raw, model_used = await attempt()
                candidate, quality_error = validate_candidate(raw)
                if candidate:
                    self.last_provider = f"{provider_name} → {model_used}"
                    self.last_error = ""
                    return candidate
                errors.append(f"{provider_name}: {quality_error}")
                print(f"AI quality retry: {provider_name}: {quality_error}")
            except Exception as exc:
                errors.append(f"{provider_name}: {exc}")
                print(f"AI provider error: {provider_name}: {exc}")

        self.last_provider = ""
        self.last_error = " | ".join(errors)[-700:] if errors else "AI не вернул пригодный ответ"
        if errors:
            print("All AI attempts failed:", " | ".join(errors))
        return ""

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        parts: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    parts.append(content["text"])
        return " ".join(parts)
