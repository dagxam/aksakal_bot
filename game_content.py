from __future__ import annotations

import asyncio
import random
import re
import time
from typing import Any

import aiohttp

from db import Database


class GameContentUpdater:
    """
    Фоновое обновление игровых баз из Wikidata.

    Важный принцип: сеть никогда не используется в момент ответа игрока.
    Здесь мы только заранее наполняем локальный SQLite-кэш; игровые обработчики
    читают уже готовые строки из БД и поэтому остаются быстрыми даже при плохом интернете.
    """

    ENDPOINT = "https://query.wikidata.org/sparql"
    SOURCE = "Wikidata"
    REFRESH_SECONDS = 12 * 3600
    MIN_RETRY_SECONDS = 30 * 60
    USER_AGENT = "AksakalTelegramBot/1.0 (game-content refresh; github.com/dagxam/aksakal_bot)"

    COUNTRY_QUERY = """
    SELECT ?country ?countryLabel ?capital ?capitalLabel ?continentLabel ?currencyLabel ?languageLabel WHERE {
      VALUES ?countryClass { wd:Q6256 wd:Q3624078 }
      ?country wdt:P31 ?countryClass.
      OPTIONAL { ?country wdt:P36 ?capital. }
      OPTIONAL { ?country wdt:P30 ?continent. }
      OPTIONAL { ?country wdt:P38 ?currency. }
      OPTIONAL { ?country wdt:P37 ?language. }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "ru,en". }
    }
    LIMIT 260
    """

    ELEMENT_QUERY = """
    SELECT ?element ?elementLabel ?symbol ?atomicNumber WHERE {
      ?element wdt:P31 wd:Q11344;
               wdt:P246 ?symbol;
               wdt:P1086 ?atomicNumber.
      SERVICE wikibase:label { bd:serviceParam wikibase:language "ru,en". }
    }
    ORDER BY ?atomicNumber
    LIMIT 140
    """

    PEOPLE_QUERY = """
    SELECT ?person ?personLabel ?occupationLabel ?countryLabel ?birth ?sitelinks WHERE {
      ?person wdt:P31 wd:Q5;
              wdt:P106 ?occupation;
              wikibase:sitelinks ?sitelinks.
      FILTER(?sitelinks >= 20)
      OPTIONAL { ?person wdt:P27 ?country. }
      OPTIONAL { ?person wdt:P569 ?birth. }
      ?article schema:about ?person;
               schema:isPartOf <https://ru.wikipedia.org/>.
      SERVICE wikibase:label { bd:serviceParam wikibase:language "ru,en". }
    }
    ORDER BY DESC(?sitelinks)
    LIMIT 450
    """

    CITY_QUERY = """
    SELECT ?city ?cityLabel ?countryLabel ?population WHERE {
      ?city wdt:P31 wd:Q515;
            wdt:P17 ?country;
            wdt:P1082 ?population.
      FILTER(?population >= 50000)
      ?article schema:about ?city;
               schema:isPartOf <https://ru.wikipedia.org/>.
      SERVICE wikibase:label { bd:serviceParam wikibase:language "ru,en". }
    }
    ORDER BY DESC(?population)
    LIMIT 700
    """

    def __init__(self, db: Database):
        self.db = db
        self.last_error = ""

    @staticmethod
    def _value(row: dict[str, Any], name: str) -> str:
        node = row.get(name) or {}
        return str(node.get("value") or "").strip()

    @staticmethod
    def _qid(uri: str) -> str:
        return (uri or "").rstrip("/").rsplit("/", 1)[-1]

    @staticmethod
    def _clean_label(value: str) -> str:
        value = " ".join((value or "").split()).strip()
        if not value or re.fullmatch(r"Q\d+", value):
            return ""
        return value

    @staticmethod
    def _birth_year(value: str) -> str:
        match = re.match(r"^(-?\d{1,4})-", value or "")
        if not match:
            return ""
        year = match.group(1)
        if year.startswith("-"):
            return ""
        return year

    @staticmethod
    def _answer_level(answer: str) -> int:
        compact = re.sub(r"[^а-яёa-z]", "", (answer or "").lower())
        length = len(compact)
        if length <= 7:
            return 1
        if length <= 11:
            return 2
        return 3

    async def _sparql(self, session: aiohttp.ClientSession, query: str) -> list[dict[str, Any]]:
        headers = {
            "Accept": "application/sparql-results+json",
            "User-Agent": self.USER_AGENT,
        }
        timeout = aiohttp.ClientTimeout(total=35, connect=10)
        async with session.get(
            self.ENDPOINT,
            params={"query": query, "format": "json"},
            headers=headers,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            data = await response.json(content_type=None)
        return list(((data.get("results") or {}).get("bindings") or []))

    @staticmethod
    def _dedupe_rows(rows: list[dict[str, Any]], key_name: str) -> list[dict[str, Any]]:
        result = []
        seen = set()
        for row in rows:
            raw = GameContentUpdater._value(row, key_name)
            if not raw or raw in seen:
                continue
            seen.add(raw)
            result.append(row)
        return result

    @staticmethod
    def _options(answer: str, pool: list[str], count: int = 4) -> str:
        candidates = [x for x in dict.fromkeys(pool) if x and x != answer]
        random.shuffle(candidates)
        selected = [answer] + candidates[: max(0, count - 1)]
        random.shuffle(selected)
        return "\n".join(selected)

    def _country_content(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = self._dedupe_rows(rows, "country")
        countries = [self._clean_label(self._value(x, "countryLabel")) for x in rows]
        capitals = [self._clean_label(self._value(x, "capitalLabel")) for x in rows]
        continents = [self._clean_label(self._value(x, "continentLabel")) for x in rows]
        currencies = [self._clean_label(self._value(x, "currencyLabel")) for x in rows]
        languages = [self._clean_label(self._value(x, "languageLabel")) for x in rows]

        items: list[dict[str, Any]] = []
        for row in rows:
            uri = self._value(row, "country")
            country = self._clean_label(self._value(row, "countryLabel"))
            capital = self._clean_label(self._value(row, "capitalLabel"))
            continent = self._clean_label(self._value(row, "continentLabel"))
            currency = self._clean_label(self._value(row, "currencyLabel"))
            language = self._clean_label(self._value(row, "languageLabel"))
            qid = self._qid(uri)
            source_url = f"https://www.wikidata.org/wiki/{qid}" if qid else ""

            if country and capital:
                items.extend([
                    {
                        "content_type": "quiz",
                        "content_key": f"capital:{qid}",
                        "difficulty": 1,
                        "title": f"Столица какого государства — {capital}?",
                        "answer": country,
                        "options": self._options(country, countries),
                        "category": "география · столицы",
                        "source": self.SOURCE,
                        "source_url": source_url,
                    },
                    {
                        "content_type": "quiz",
                        "content_key": f"capital-of:{qid}",
                        "difficulty": 1,
                        "title": f"Какой город является столицей государства {country}?",
                        "answer": capital,
                        "options": self._options(capital, capitals),
                        "category": "география · столицы",
                        "source": self.SOURCE,
                        "source_url": source_url,
                    },
                    {
                        "content_type": "crocodile",
                        "content_key": f"country:{qid}",
                        "difficulty": self._answer_level(country),
                        "answer": country.lower(),
                        "clue1": f"Это государство. Его столица — {capital}.",
                        "clue2": f"Оно находится на континенте {continent}." if continent else "Это название страны.",
                        "clue3": f"Начинается на «{country[0].upper()}».",
                        "category": "страны",
                        "source": self.SOURCE,
                        "source_url": source_url,
                    },
                    {
                        "content_type": "hangman",
                        "content_key": f"country:{qid}",
                        "difficulty": self._answer_level(country),
                        "answer": country.lower(),
                        "clue1": f"Страна; столица — {capital}.",
                        "category": "страны",
                        "source": self.SOURCE,
                        "source_url": source_url,
                    },
                ])

            if country and continent:
                items.append({
                    "content_type": "quiz",
                    "content_key": f"continent:{qid}",
                    "difficulty": 1,
                    "title": f"На каком континенте находится государство {country}?",
                    "answer": continent,
                    "options": self._options(continent, continents),
                    "category": "география · континенты",
                    "source": self.SOURCE,
                    "source_url": source_url,
                })

            if country and currency:
                items.append({
                    "content_type": "quiz",
                    "content_key": f"currency:{qid}",
                    "difficulty": 2,
                    "title": f"Какая валюта используется в государстве {country}?",
                    "answer": currency,
                    "options": self._options(currency, currencies),
                    "category": "география · валюты",
                    "source": self.SOURCE,
                    "source_url": source_url,
                })

            if country and language:
                items.append({
                    "content_type": "quiz",
                    "content_key": f"language:{qid}",
                    "difficulty": 2,
                    "title": f"Какой язык имеет официальный статус в государстве {country}?",
                    "answer": language,
                    "options": self._options(language, languages),
                    "category": "география · языки",
                    "source": self.SOURCE,
                    "source_url": source_url,
                })

            if capital:
                capital_level = self._answer_level(capital)
                items.extend([
                    {
                        "content_type": "crocodile",
                        "content_key": f"capital:{qid}",
                        "difficulty": capital_level,
                        "answer": capital.lower(),
                        "clue1": f"Это город — столица государства {country}.",
                        "clue2": "Нужно назвать именно город.",
                        "clue3": f"Начинается на «{capital[0].upper()}».",
                        "category": "столицы",
                        "source": self.SOURCE,
                        "source_url": source_url,
                    },
                    {
                        "content_type": "hangman",
                        "content_key": f"capital:{qid}",
                        "difficulty": capital_level,
                        "answer": capital.lower(),
                        "clue1": f"Столица государства {country}.",
                        "category": "столицы",
                        "source": self.SOURCE,
                        "source_url": source_url,
                    },
                ])
        return items

    def _element_content(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = self._dedupe_rows(rows, "element")
        names = [self._clean_label(self._value(x, "elementLabel")) for x in rows]
        symbols = [self._clean_label(self._value(x, "symbol")) for x in rows]
        atomic_numbers = [self._clean_label(self._value(x, "atomicNumber")) for x in rows]
        items: list[dict[str, Any]] = []
        for row in rows:
            uri = self._value(row, "element")
            name = self._clean_label(self._value(row, "elementLabel"))
            symbol = self._clean_label(self._value(row, "symbol"))
            atomic = self._clean_label(self._value(row, "atomicNumber"))
            if not (name and symbol and atomic):
                continue
            qid = self._qid(uri)
            source_url = f"https://www.wikidata.org/wiki/{qid}" if qid else ""
            level = self._answer_level(name)
            items.extend([
                {
                    "content_type": "quiz",
                    "content_key": f"element-symbol:{qid}",
                    "difficulty": 2,
                    "title": f"Какой химический элемент обозначается символом {symbol}?",
                    "answer": name,
                    "options": self._options(name, names),
                    "category": "наука · химия",
                    "source": self.SOURCE,
                    "source_url": source_url,
                },
                {
                    "content_type": "quiz",
                    "content_key": f"element-number:{qid}",
                    "difficulty": 3,
                    "title": f"Какой атомный номер у химического элемента {name}?",
                    "answer": atomic,
                    "options": self._options(atomic, atomic_numbers),
                    "category": "наука · химия",
                    "source": self.SOURCE,
                    "source_url": source_url,
                },
                {
                    "content_type": "crocodile",
                    "content_key": f"element:{qid}",
                    "difficulty": level,
                    "answer": name.lower(),
                    "clue1": f"Это химический элемент с символом {symbol}.",
                    "clue2": f"Его атомный номер — {atomic}.",
                    "clue3": f"Начинается на «{name[0].upper()}».",
                    "category": "химические элементы",
                    "source": self.SOURCE,
                    "source_url": source_url,
                },
                {
                    "content_type": "hangman",
                    "content_key": f"element:{qid}",
                    "difficulty": level,
                    "answer": name.lower(),
                    "clue1": f"Химический элемент; символ {symbol}, атомный номер {atomic}.",
                    "category": "химия",
                    "source": self.SOURCE,
                    "source_url": source_url,
                },
            ])
        return items

    def _people_content(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: list[dict[str, Any]] = []
        seen = set()
        for row in rows:
            uri = self._value(row, "person")
            if not uri or uri in seen:
                continue
            seen.add(uri)
            name = self._clean_label(self._value(row, "personLabel"))
            occupation = self._clean_label(self._value(row, "occupationLabel"))
            if name and len(name.split()) >= 2 and occupation:
                unique.append(row)

        occupations = [
            self._clean_label(self._value(row, "occupationLabel"))
            for row in unique
            if self._clean_label(self._value(row, "occupationLabel"))
        ]
        countries = [
            self._clean_label(self._value(row, "countryLabel"))
            for row in unique
            if self._clean_label(self._value(row, "countryLabel"))
        ]

        items: list[dict[str, Any]] = []
        for row in unique:
            uri = self._value(row, "person")
            name = self._clean_label(self._value(row, "personLabel"))
            occupation = self._clean_label(self._value(row, "occupationLabel"))
            country = self._clean_label(self._value(row, "countryLabel"))
            year = self._birth_year(self._value(row, "birth"))
            try:
                sitelinks = int(float(self._value(row, "sitelinks") or "20"))
            except ValueError:
                sitelinks = 20
            difficulty = 1 if sitelinks >= 100 else 2 if sitelinks >= 50 else 3
            qid = self._qid(uri)
            source_url = f"https://www.wikidata.org/wiki/{qid}" if qid else ""
            clues = [
                f"Этот человек известен как {occupation.lower()}.",
                f"Связан с государством {country}." if country else "Это известный человек.",
                f"Год рождения — {year}." if year else f"Имя начинается на «{name[0].upper()}».",
            ]
            items.append({
                "content_type": "whoami",
                "content_key": qid or name,
                "difficulty": difficulty,
                "answer": name,
                "clue1": clues[0],
                "clue2": clues[1],
                "clue3": clues[2],
                "category": "известные люди",
                "source": self.SOURCE,
                "source_url": source_url,
            })

            items.append({
                "content_type": "quiz",
                "content_key": f"person-job:{qid}",
                "difficulty": 2,
                "title": f"Кем известен {name}?",
                "answer": occupation,
                "options": self._options(occupation, occupations),
                "category": "личности · профессии",
                "source": self.SOURCE,
                "source_url": source_url,
            })

            if country:
                items.append({
                    "content_type": "quiz",
                    "content_key": f"person-country:{qid}",
                    "difficulty": 2,
                    "title": f"С каким государством связан {name} по гражданству?",
                    "answer": country,
                    "options": self._options(country, countries),
                    "category": "личности · страны",
                    "source": self.SOURCE,
                    "source_url": source_url,
                })

            if year and year.isdigit():
                year_num = int(year)
                year_options = [
                    str(year_num),
                    str(year_num - 1),
                    str(year_num + 1),
                    str(year_num + 5),
                    str(year_num - 5),
                    str(year_num + 10),
                    str(year_num - 10),
                ]
                items.append({
                    "content_type": "quiz",
                    "content_key": f"person-birth:{qid}",
                    "difficulty": 3,
                    "title": f"В каком году родился {name}?",
                    "answer": year,
                    "options": self._options(year, year_options),
                    "category": "личности · даты",
                    "source": self.SOURCE,
                    "source_url": source_url,
                })
        return items

    def _city_content(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen_names = set()
        for row in rows:
            uri = self._value(row, "city")
            city = self._clean_label(self._value(row, "cityLabel"))
            country = self._clean_label(self._value(row, "countryLabel"))
            population_raw = self._value(row, "population")
            normalized = city.lower().replace("ё", "е")
            if not city or normalized in seen_names or len(city) > 48:
                continue
            if not re.fullmatch(r"[А-Яа-яЁёA-Za-z\- .]+", city):
                continue
            seen_names.add(normalized)
            qid = self._qid(uri)
            items.append({
                "content_type": "city",
                "content_key": qid or normalized,
                "difficulty": 0,
                "answer": city,
                "clue1": country,
                "clue2": population_raw,
                "category": "города",
                "source": self.SOURCE,
                "source_url": f"https://www.wikidata.org/wiki/{qid}" if qid else "",
            })
        return items

    def _city_quiz_content(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cities = self._city_content(rows)
        countries = [x["clue1"] for x in cities if x.get("clue1")]
        items: list[dict[str, Any]] = []
        for city in cities:
            country = str(city.get("clue1") or "")
            name = str(city.get("answer") or "")
            if not country or not name:
                continue
            items.append({
                "content_type": "quiz",
                "content_key": f"city-country:{city['content_key']}",
                "difficulty": 2,
                "title": f"В какой стране находится город {name}?",
                "answer": country,
                "options": self._options(country, countries),
                "category": "география · города",
                "source": self.SOURCE,
                "source_url": city.get("source_url", ""),
            })
        return items

    async def refresh(self, session: aiohttp.ClientSession, force: bool = False) -> dict[str, int]:
        now = int(time.time())
        last_success = int(self.db.get_game_content_meta("refresh_success_at", "0") or 0)
        last_attempt = int(self.db.get_game_content_meta("refresh_attempt_at", "0") or 0)
        if not force:
            if last_success and now - last_success < self.REFRESH_SECONDS:
                return {"skipped": 1}
            if last_attempt and now - last_attempt < self.MIN_RETRY_SECONDS:
                return {"retry_later": 1}

        self.db.set_game_content_meta("refresh_attempt_at", str(now))
        counts: dict[str, int] = {}
        all_items: list[dict[str, Any]] = []
        try:
            countries = await self._sparql(session, self.COUNTRY_QUERY)
            all_items.extend(self._country_content(countries))
            await asyncio.sleep(1)

            elements = await self._sparql(session, self.ELEMENT_QUERY)
            all_items.extend(self._element_content(elements))
            await asyncio.sleep(1)

            people = await self._sparql(session, self.PEOPLE_QUERY)
            all_items.extend(self._people_content(people))
            await asyncio.sleep(1)

            cities = await self._sparql(session, self.CITY_QUERY)
            all_items.extend(self._city_content(cities))
            all_items.extend(self._city_quiz_content(cities))

            written = self.db.upsert_game_content(all_items)
            for kind in ("quiz", "crocodile", "hangman", "whoami", "city"):
                counts[kind] = self.db.game_content_count(kind)
            counts["written"] = written
            self.db.set_game_content_meta("refresh_success_at", str(int(time.time())))
            self.db.set_game_content_meta("refresh_last_error", "")
            self.last_error = ""
            return counts
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.db.set_game_content_meta("refresh_last_error", self.last_error[:1000])
            return {"error": 1}

    async def worker(self, session: aiohttp.ClientSession):
        while True:
            try:
                result = await self.refresh(session)
                if result.get("error"):
                    print(f"game content refresh warning: {self.last_error}")
                elif not result.get("skipped") and not result.get("retry_later"):
                    print(f"game content refreshed: {result}")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"game content worker warning: {exc}")
            await asyncio.sleep(30 * 60)
