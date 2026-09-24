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
        ],
        2: [
            "{u} — уцы, уверенности много. Теперь осталось найти основания.",
            "{u} — ты так молчишь, будто мнение ещё проходит согласование.",
        ],
        3: [
            "{u} — аргументы закончились, а хабар всё идёт.",
            "{u} — ты сейчас очень смело идёшь туда, где фактов уже нет.",
        ],
        4: [
            "{u} — ле, если бы уверенность считалась доказательством, спор уже закрыли бы.",
            "{u} — мысль закончилась раньше сообщения, но ты героически продолжил.",
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
    def __init__(self, api_key: str, model: str, enabled: bool = True):
        self.api_key = api_key
        self.model = model
        self.enabled = enabled and bool(api_key)

    @staticmethod
    def mention(user: dict[str, Any]) -> str:
        if user.get("username"):
            return "@" + user["username"]
        return user.get("display_name") or "участник"

    def fallback(self, user: dict[str, Any], mood: str = "playful", level: int = 2) -> str:
        if mood == "playful":
            pool = FALLBACKS["playful"].get(max(1, min(4, level)), FALLBACKS["playful"][2])
        else:
            pool = FALLBACKS.get(mood, FALLBACKS["playful"][2])
        return random.choice(pool).format(u=self.mention(user))

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
    def detect_intensity(context: list[dict[str, Any]], max_level: int = 4) -> int:
        """Определяет фактическую жёсткость 1..4 по текущему стилю группы.

        max_level — административный потолок. Алгоритм не поднимается выше него.
        Эмоциональные режимы supportive/calm/wise всё равно имеют приоритет над roast.
        """
        max_level = max(1, min(4, int(max_level)))
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
        else:
            level = 4

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
    ) -> str:
        mood = mood or self.detect_mood(context)
        if not self.enabled:
            return self.fallback(target, mood, level)

        mention = self.mention(target)
        profile = target.get("style_profile", "neutral")
        transcript = []
        for m in context[-30:]:
            who = "@" + m["username"] if m.get("username") else m.get("display_name", "участник")
            transcript.append(f"{who}: [{m['kind']}] {m.get('content','')}")
        transcript_text = "\n".join(transcript) or "(контекста почти нет)"
        personal_words = personal_words or []
        group_words = group_words or []
        personal_lexicon = ", ".join(x["token"] for x in personal_words[:12]) or "(ещё не накоплен)"
        group_lexicon = ", ".join(x["token"] for x in group_words[:14]) or "(ещё не накоплен)"

        mode_rules = {
            "supportive": "Человек или чат звучит грустно/тяжело. НЕ подкалывай. Поддержи коротко, тепло и без пафоса.",
            "calm": "Есть напряжение или злость. Не подливай масла в огонь. Коротко успокой и предложи сбавить тон.",
            "stern": "Есть явная грубость/конфликт. Ответь сурово и уверенно, осади хамство, но не унижай и не провоцируй драку.",
            "wise": "Тема серьёзная. Дай короткую умную, жизненную мысль по контексту без морализаторства.",
            "playful": "Обычный живой разговор. Можно уместно подколоть по теме разговора.",
        }

        intensity_rules = {
            1: "Очень мягкая ирония. Никаких резких формулировок.",
            2: "Обычный дружеский подкол, легко и без обиды.",
            3: "Заметно жёстче и колче, но всё ещё дружески и по теме.",
            4: "Максимально острый дружеский стёб: метко и дерзко, но без унижения и травли.",
        }

        prompt = f"""
Ты — Telegram-бот «Аксакал», наблюдательный, остроумный и иногда суровый участник дружеской группы.
Напиши ОДНУ короткую реплику на русском языке.

ЖЁСТКИЙ ФОРМАТ: ответ начинается ровно с "{mention} — " и дальше одна фраза.
Никаких вступлений, кавычек, списков, объяснений и подписи. Обычно 5–18 слов, максимум 25.

Текущий эмоциональный режим: {mood}.
Правило этого режима: {mode_rules[mood]}
Причина вмешательства: {reason}
Автоматически выбранная жёсткость сейчас: {level}/4.
Правило жёсткости: {intensity_rules[max(1, min(4, level))]}
Профиль стиля пользователя: {profile}.

Последние сообщения:
{transcript_text}

Память речи:
- Частые слова и выражения именно этого участника: {personal_lexicon}
- Частые слова и выражения этой группы: {group_lexicon}
- Можно иногда естественно вернуть человеку его же характерное словечко или локальный мем группы.
- Не копируй механически и не повторяй сленг в каждом ответе.
- Не используй выученные слова, если они относятся к оскорблениям по внешности, здоровью, происхождению, религии или другим чувствительным признакам.
- Для мужчин и женщин правило одинаковое: стиль определяется их реальной манерой переписки, а не стереотипами.

Дагестанская подача:
- Общайся как живой дагестанский аксакал/старший в компании: коротко, метко, с местным ритмом речи.
- Иногда, но не в каждом сообщении, естественно используй узнаваемые слова и обороты: «жи есть», «уцы», «вацок», «ле», «йо», «сабур», «ахча», «хабар», «чанда», «что стало?», «моросишь», «тормози», «оставь», «суету наводишь».
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
- Взрослые темы допустимы через намёк и контекст, без графических сексуальных описаний.
- Не используй слово «Аксакал» внутри самой реплики.
""".strip()

        payload = {"model": self.model, "input": prompt, "max_output_tokens": 90}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            timeout = aiohttp.ClientTimeout(total=25)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post("https://api.openai.com/v1/responses", json=payload, headers=headers) as resp:
                    if resp.status >= 300:
                        return self.fallback(target, mood, level)
                    data = await resp.json()
            text = self._extract_text(data).strip().replace("\n", " ")
            if not text:
                return self.fallback(target, mood, level)
            if not text.startswith(f"{mention} — "):
                text = f"{mention} — {text.lstrip('-—: ')}"
            return text[:500]
        except Exception:
            return self.fallback(target, mood, level)

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        parts: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    parts.append(content["text"])
        return " ".join(parts)
