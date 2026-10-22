import os
import random
import asyncio
import json
import logging
import time
import unicodedata
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import discord
from discord.ext import commands
from discord.ui import Button, View, Select, Modal, TextInput

# ---------------------------------------------------------
# 0. الإعدادات والروابط والتعريفات الأساسية
# ---------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="#", intents=intents, help_command=None)

TOURNAMENT_OWNER_ID = 941287405573509140
TOURNAMENT_OWNER_USERNAME = "sahlap_makar"
DEFAULT_SIGNUP_MINUTES = 15
MIN_SIGNUP_MINUTES = 1
MAX_SIGNUP_MINUTES = 48 * 60
MAX_DRAFT_SKIPS = 3
HIGH_RATING_THRESHOLD = 91
HIGH_RATING_DRAW_WEIGHT = 0.03
CAIRO_TZ = ZoneInfo("Africa/Cairo")

active_tournament = None
pending_tournament_setup = None
RECENTLY_USED_PLAYER_KEYS = []
active_versus_players = set()
logger = logging.getLogger("mokar_bot")

TROPHY_IMAGE_URL = "https://commons.wikimedia.org/wiki/Special:FilePath/Champions%20League%20Trophy%20(52736201132).jpg?width=640"
KNOCKOUT_BRACKET_IMAGE_URL = "https://cdn.discordapp.com/attachments/1562212365276024923/1562212569979027497/6872765b-2f50-4a7b-acd8-c3b4ca25deb2_1.png"
TABLE_DESIGN_IMAGE_URL = "https://cdn.discordapp.com/attachments/1562212365276024923/1562216821031964763/4f69f3cf-caa0-45b3-9ece-58739c2732dd.png"
SCORERS_DESIGN_IMAGE_URL = "https://cdn.discordapp.com/attachments/1562212365276024923/1562220769600208977/c15d8934-399b-47cd-ae9c-e65fca33849a.png"
RATINGS_DESIGN_IMAGE_URL = "https://cdn.discordapp.com/attachments/1562212365276024923/1562221675649695827/326670---.webp"

def reserve_versus_players(*members):
    pids = {m.id for m in members if m}
    if pids & active_versus_players:
        return False
    active_versus_players.update(pids)
    return True

def release_versus_players(*members):
    for m in members:
        if m:
            active_versus_players.discard(m.id)

async def send_ephemeral_notice(interaction, message):
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass

# ---------------------------------------------------------
# 1. قاعدة البيانات والبيانات المرجعية (البطاقات والخطط)
# ---------------------------------------------------------
user_profiles = {}
def get_profile(uid):
    if uid not in user_profiles:
        user_profiles[uid] = {
            "wins": 0, "losses": 0,
            "goals_for": 0, "goals_against": 0,
            "trophies": 0, "coins": 10000
        }
    return user_profiles[uid]

FORMATIONS = {
    "4-3-3": ["GK", "RB", "CB1", "CB2", "LB", "CM1", "CM2", "CAM", "RW", "ST", "LW"],
    "4-4-2": ["GK", "RB", "CB1", "CB2", "LB", "RM", "CM1", "CM2", "LM", "ST1", "ST2"],
    "3-5-2": ["GK", "CB1", "CB2", "CB3", "CDM1", "CDM2", "RM", "LM", "CAM", "ST1", "ST2"],
    "4-2-3-1": ["GK", "RB", "CB1", "CB2", "LB", "CDM1", "CDM2", "RW", "CAM", "LW", "ST"],
    "4-3-2-1": ["GK", "RB", "CB1", "CB2", "LB", "CM1", "CM2", "CM3", "CAM1", "CAM2", "ST"],
    "4-1-2-1-2": ["GK", "RB", "CB1", "CB2", "LB", "CDM", "CM1", "CM2", "CAM", "ST1", "ST2"],
    "3-4-3": ["GK", "CB1", "CB2", "CB3", "LM", "CM1", "CM2", "RM", "LW", "ST", "RW"],
    "5-3-2": ["GK", "RB", "CB1", "CB2", "CB3", "LB", "CM1", "CM2", "CM3", "ST1", "ST2"],
}

def _c(name, pid, ver, rating, img=None):
    return {"name": name, "player_id": pid, "ver": ver, "rating": rating, "image_title": img or name}

CARDS_DATABASE = {
    "GK": [
        _c("Manuel Neuer", "neuer", "TOTY", 95), _c("Manuel Neuer", "neuer", "Gold", 89), _c("Manuel Neuer", "neuer", "Flashback", 91),
        _c("Alisson Becker", "alisson", "Gold", 89), _c("Ederson", "ederson", "Gold", 88), _c("Mike Maignan", "maignan", "In-Form", 90),
        _c("Thibaut Courtois", "courtois", "TOTS", 94), _c("Thibaut Courtois", "courtois", "Gold", 89), _c("Gianluigi Buffon", "buffon", "Icon", 93),
        _c("Jan Oblak", "oblak", "Gold", 88), _c("Yassine Bounou", "bounou", "Hero", 88),
        _c("محمد الشناوي", "shenawy", "Gold", 84, "Mohamed El Shenawy"), _c("عصام الحضري", "hadary", "Icon", 82, "Essam El-Hadary"),
        _c("محمد أبو جبل", "abougabal", "Gold", 74, "Mohamed Abu Gabal"), _c("Kasper Schmeichel", "schmeichel", "Gold", 82),
        _c("Guillermo Ochoa", "ochoa", "Gold", 78), _c("Kepa Arrizabalaga", "kepa", "Gold", 76), _c("Sergio Romero", "romero_gk", "Silver", 66),
        _c("Dean Henderson", "dean_henderson", "Gold", 82), _c("Alex Meret", "alex_meret", "Gold", 81),
        _c("Caoimhín Kelleher", "kelleher", "Gold", 80), _c("Bart Verbruggen", "verbruggen", "Gold", 81),
        _c("Mike Maignan", "maignan", "Gold", 87)
    ],
    "CB": [
        _c("Virgil van Dijk", "vandijk", "TOTY", 96), _c("Virgil van Dijk", "vandijk", "Gold", 89), _c("Virgil van Dijk", "vandijk", "TOTS", 94),
        _c("Sergio Ramos", "ramos", "Icon", 95), _c("Paolo Maldini", "maldini", "Icon", 96), _c("Rúben Dias", "rubendias", "TOTS", 93),
        _c("William Saliba", "saliba", "Gold", 90), _c("Antonio Rüdiger", "rudiger", "Gold", 88), _c("Cristian Romero", "romero_cb", "Gold", 86),
        _c("Matthijs de Ligt", "deligt", "Gold", 85), _c("Ronald Araújo", "araujo", "In-Form", 87),
        _c("أحمد حجازي", "hegazi", "Gold", 79, "Ahmed Hegazi"), _c("رومان سايس", "saiss", "Gold", 81, "Romain Saiss"),
        _c("علي البليهي", "bulaihi", "Gold", 76, "Ali Al-Bulaihi"), _c("Harry Maguire", "maguire", "Gold", 73),
        _c("Thiago Silva", "thiagosilva", "Gold", 82), _c("John Stones", "stones", "Gold", 88), _c("José Giménez", "gimenez", "Gold", 84),
        _c("Marc Guéhi", "guehi", "Gold", 85), _c("Levi Colwill", "levicolwill", "Gold", 80),
        _c("Fikayo Tomori", "tomori", "Gold", 80), _c("Mohammed Salisu", "salisu", "Gold", 76),
        _c("Nayef Aguerd", "aguerd", "Gold", 80)
    ],
    "RB": [
        _c("Trent Alexander-Arnold", "trent", "TOTS", 92), _c("Trent Alexander-Arnold", "trent", "Gold", 86),
        _c("Achraf Hakimi", "hakimi", "TOTY", 92), _c("Achraf Hakimi", "hakimi", "Gold", 88), _c("Cafu", "cafu", "Icon", 93),
        _c("Kyle Walker", "walker", "FUT Birthday", 89), _c("Pedro Porro", "porro", "Gold", 85), _c("Jules Koundé", "kounde", "Gold", 87),
        _c("نصير مزراوي", "mazraoui", "Gold", 84, "Noussair Mazraoui"), _c("Reece James", "reecejames", "Gold", 85),
        _c("Diogo Dalot", "dalot", "Gold", 76), _c("Ben White", "benwhite", "Gold", 82),
        _c("Malo Gusto", "malogusto", "Gold", 79), _c("Vanderson", "vanderson", "Gold", 77),
        _c("Omar El Hilali", "elhilali", "Gold", 75)
    ],
    "LB": [
        _c("Alphonso Davies", "davies", "TOTS", 93), _c("Alphonso Davies", "davies", "Gold", 87),
        _c("Roberto Carlos", "robertocarlos", "Icon", 92), _c("Theo Hernández", "theo", "TOTY", 94),
        _c("Nuno Mendes", "nunomendes", "Gold", 88), _c("Alejandro Balde", "balde", "Gold", 84), _c("Andrew Robertson", "robertson", "Gold", 86),
        _c("ياسر الشهراني", "shahrani", "Gold", 78, "Yasser Al-Shahrani"), _c("محمد حمدي", "hamdy", "Gold", 74, "Mohamed Hamdy (footballer, born 1995)"),
        _c("Rayan Aït-Nouri", "aitnouri", "Gold", 82), _c("Ben Chilwell", "chilwell", "Gold", 79),
        _c("Miloš Kerkez", "kerkez", "Gold", 81), _c("Destiny Udogie", "udogie", "Gold", 79),
        _c("Theo Hernández", "theo", "Gold", 82)
    ],
    "CM": [
        _c("Luka Modrić", "modric", "TOTY", 96), _c("Luka Modrić", "modric", "Gold", 88),
        _c("Kevin De Bruyne", "debruyne", "Gold", 91), _c("Federico Valverde", "valverde", "Gold", 89),
        _c("Gavi", "gavi", "Gold", 85), _c("Alexis Mac Allister", "macallister", "Gold", 86),
        _c("Zinedine Zidane", "zidane", "Icon", 96), _c("Jude Bellingham", "bellingham", "TOTS", 95),
        _c("Pedri", "pedri", "Future Stars", 90), _c("إسماعيل بن ناصر", "bennacer", "Gold", 84, "Ismaël Bennacer"),
        _c("محمد النني", "elneny", "Gold", 77, "Mohamed Elneny"), _c("Enzo Fernández", "enzo", "Gold", 88), _c("N'Golo Kanté", "kante", "Gold", 85),
        _c("Kobbie Mainoo", "mainoo", "Gold", 81), _c("Azzedine Ounahi", "ounahi", "Gold", 79),
        _c("Mohammed Kanno", "kanno", "Gold", 74), _c("Khéphren Thuram", "thuram", "Gold", 81),
        _c("Youssouf Fofana", "youssouf_fofana", "Gold", 80),
        _c("Jude Bellingham", "bellingham", "Gold", 90), _c("Pedri", "pedri", "Gold", 90)
    ],
    "CAM": [
        _c("Lionel Messi", "messi", "Icon/TOTY", 98), _c("Lionel Messi", "messi", "Gold", 91),
        _c("Ronaldinho", "ronaldinho", "Icon", 95), _c("Kaká", "kaka", "Icon", 92),
        _c("Bruno Fernandes", "bruno", "Gold", 88), _c("Phil Foden", "foden", "Gold", 88), _c("Cole Palmer", "palmer", "Gold", 87),
        _c("محمد أبو تريكة", "aboutrika", "Icon", 89, "Mohamed Aboutrika"), _c("حكيم زياش", "ziyech", "Gold", 84, "Hakim Ziyech"),
        _c("سعيد بن رحمة", "benrahma", "Gold", 80, "Saïd Benrahma"), _c("Jamal Musiala", "musiala", "Gold", 90), _c("Martin Ødegaard", "odegaard", "Gold", 88),
        _c("Morgan Rogers", "morgan_rogers", "Gold", 84), _c("Eberechi Eze", "eberechi_eze", "Gold", 84)
    ],
    "CDM": [
        _c("Rodri", "rodri", "TOTY", 95), _c("Casemiro", "casemiro", "Gold", 89), _c("Patrick Vieira", "vieira", "Icon", 93),
        _c("سفيان أمرابط", "amrabat", "Gold", 82, "Sofyan Amrabat"), _c("محمد النني", "elneny", "Gold", 77, "Mohamed Elneny"),
        _c("Fabinho", "fabinho", "Gold", 83), _c("Declan Rice", "rice", "Gold", 89), _c("Sergio Busquets", "busquets", "Gold", 82),
        _c("Tyler Adams", "tyler_adams", "Gold", 79), _c("Idrissa Gueye", "idrissa_gueye", "Gold", 79),
        _c("Rodri", "rodri", "Gold", 90)
    ],
    "RM": [
        _c("Bukayo Saka", "saka", "TOTS", 92), _c("Bukayo Saka", "saka", "Gold", 87),
        _c("David Beckham", "beckham", "Icon", 91),
        _c("رياض محرز", "mahrez", "Gold", 89, "Riyad Mahrez"), _c("حكيم زياش", "ziyech", "Gold", 84, "Hakim Ziyech"),
        _c("Ousmane Dembélé", "dembele", "Gold", 87), _c("Adama Traoré", "adama", "Gold", 79), _c("Sadio Mané", "mane", "Gold", 86),
        _c("Arda Güler", "arda_guler", "Gold", 83), _c("Jarrod Bowen", "jarrod_bowen", "Gold", 83),
        _c("Bryan Mbeumo", "bryan_mbeumo", "Gold", 84), _c("Moussa Diaby", "moussa_diaby", "Gold", 82),
        _c("Samuel Chukwueze", "chukwueze", "Gold", 78), _c("Takefusa Kubo", "kubo", "Gold", 80)
    ],
    "LM": [
        _c("Vinícius Júnior", "vinicius", "TOTY", 95), _c("Son Heung-min", "son", "TOTS", 92),
        _c("سالم الدوسري", "dawsari", "Gold", 85, "Salem Al-Dawsari"), _c("محمود تريزيجيه", "trezeguet", "Gold", 80, "Mahmoud Trezeguet"),
        _c("Rafael Leão", "leao", "Gold", 90), _c("Alejandro Garnacho", "garnacho", "Gold", 80), _c("سفيان بوفال", "boufal", "Gold", 79, "Sofiane Boufal"),
        _c("Jack Grealish", "grealish", "Gold", 82), _c("Luis Díaz", "luis_diaz", "Gold", 88),
        _c("Matheus Cunha", "matheus_cunha", "Gold", 84)
    ],
    "RW": [
        _c("Lionel Messi", "messi", "TOTY", 98), _c("Lionel Messi", "messi", "Gold", 90), _c("Lionel Messi", "messi", "Flashback", 93),
        _c("Mohamed Salah", "salah", "TOTS", 95), _c("Mohamed Salah", "salah", "Gold", 89), _c("Mohamed Salah", "salah", "Record Breaker", 92),
        _c("رياض محرز", "mahrez", "Gold", 90, "Riyad Mahrez"), _c("Rodrygo", "rodrygo", "Gold", 87), _c("Lamine Yamal", "yamal", "Gold", 88),
        _c("Raphinha", "raphinha", "Gold", 86), _c("عبد الصمد الزلزولي", "ezzalzouli", "Gold", 78, "Abde Ezzalzouli"),
        _c("Ilias Akhomach", "akhomach", "Gold", 75), _c("Rayan Cherki", "cherki", "Gold", 86),
        _c("Noni Madueke", "madueke", "Gold", 80)
    ],
    "LW": [
        _c("Cristiano Ronaldo", "cr7", "Icon / Prime", 97), _c("Cristiano Ronaldo", "cr7", "Flashback", 92),
        _c("Neymar Jr", "neymar", "Flashback", 91), _c("Neymar Jr", "neymar", "Gold", 89),
        _c("Kylian Mbappé", "mbappe", "TOTS", 96), _c("Kylian Mbappé", "mbappe", "Gold", 91),
        _c("محمود تريزيجيه", "trezeguet", "Gold", 80, "Mahmoud Trezeguet"), _c("سالم الدوسري", "dawsari", "Gold", 85, "Salem Al-Dawsari"),
        _c("Khvicha Kvaratskhelia", "kvara", "Gold", 88), _c("Rafael Leão", "leao", "Gold", 89),
        _c("Nico Williams", "nico_williams", "Gold", 84), _c("Anthony Gordon", "anthony_gordon", "Gold", 82),
        _c("Vinícius Júnior", "vinicius", "Gold", 89)
    ],
    "ST": [
        _c("Cristiano Ronaldo", "cr7", "TOTY", 98), _c("Cristiano Ronaldo", "cr7", "Icon", 95), _c("Cristiano Ronaldo", "cr7", "Gold", 90),
        _c("Kylian Mbappé", "mbappe", "TOTY", 97), _c("Kylian Mbappé", "mbappe", "Gold", 91),
        _c("Erling Haaland", "haaland", "TOTS", 96), _c("Erling Haaland", "haaland", "Gold", 91),
        _c("Ronaldo Nazário (R9)", "r9", "Icon", 96, "Ronaldo (Brazilian footballer)"),
        _c("Harry Kane", "kane", "Gold", 90), _c("Victor Osimhen", "osimhen", "Gold", 87), _c("Karim Benzema", "benzema", "TOTY", 94),
        _c("عمر مرموش", "marmoush", "Gold", 86, "Omar Marmoush"), _c("يوسف النصيري", "nesyri", "Gold", 83, "Youssef En-Nesyri"),
        _c("أيوب الكعبي", "kaabi", "Gold", 80, "Ayoub El Kaabi"), _c("Romelu Lukaku", "lukaku", "Gold", 82), _c("Darwin Núñez", "nunez", "Gold", 82),
        _c("Evan Ferguson", "evan_ferguson", "Gold", 74), _c("Benjamin Šeško", "sesko", "Gold", 82),
        _c("Jhon Durán", "jhon_duran", "Gold", 78)
    ]
}

# EA SPORTS FC 27 base-item overalls, checked against EA's official ratings database.
# Icons and campaign/special versions keep their separate item ratings.
FC27_BASE_RATINGS = {
    "Manuel Neuer": 81, "Alisson Becker": 87, "Ederson": 82, "Mike Maignan": 87,
    "Thibaut Courtois": 90, "Jan Oblak": 88, "Yassine Bounou": 82, "Kepa Arrizabalaga": 78,
    "Virgil van Dijk": 88, "Rúben Dias": 87, "William Saliba": 88, "Antonio Rüdiger": 83,
    "Cristian Romero": 82, "Matthijs de Ligt": 82, "Ronald Araújo": 80, "Harry Maguire": 82,
    "John Stones": 82, "José Giménez": 82, "Trent Alexander-Arnold": 84, "Achraf Hakimi": 88,
    "Kyle Walker": 76, "Pedro Porro": 83, "Jules Koundé": 85, "Noussair Mazraoui": 80,
    "Reece James": 84, "Diogo Dalot": 78, "Ben White": 81, "Alphonso Davies": 82,
    "Theo Hernández": 82, "Nuno Mendes": 89, "Alejandro Balde": 82, "Andrew Robertson": 80,
    "Rayan Aït-Nouri": 81, "Ben Chilwell": 77, "Luka Modrić": 85, "Kevin De Bruyne": 85,
    "Federico Valverde": 87, "Gavi": 83, "Alexis Mac Allister": 84, "Enzo Fernández": 86,
    "N'Golo Kanté": 83, "Jude Bellingham": 90, "Pedri": 90, "Casemiro": 83, "Rodri": 90,
    "Declan Rice": 88, "Fabinho": 82, "Bukayo Saka": 87, "Bruno Fernandes": 89,
    "Phil Foden": 84, "Cole Palmer": 85, "Saïd Benrahma": 77, "Jamal Musiala": 87,
    "Martin Ødegaard": 86, "Adama Traoré": 68, "Sadio Mané": 82, "Mohamed Salah": 87,
    "Rafael Leão": 83, "Alejandro Garnacho": 77, "Rodrygo": 84, "Lamine Yamal": 90,
    "Raphinha": 88, "Cristiano Ronaldo": 84, "Kylian Mbappé": 91,
    "Khvicha Kvaratskhelia": 89, "Erling Haaland": 91, "Harry Kane": 90,
    "Victor Osimhen": 85, "Karim Benzema": 82, "Omar Marmoush": 82,
    "Youssef En-Nesyri": 80, "Ayoub El Kaabi": 80, "Romelu Lukaku": 82, "Darwin Núñez": 77,
    "Dean Henderson": 82, "Alex Meret": 81, "Caoimhín Kelleher": 80, "Bart Verbruggen": 81,
    "Marc Guéhi": 85, "Levi Colwill": 80, "Fikayo Tomori": 80, "Mohammed Salisu": 76,
    "Nayef Aguerd": 80, "Malo Gusto": 79, "Vanderson": 77, "Omar El Hilali": 75,
    "Miloš Kerkez": 81, "Destiny Udogie": 79, "Kobbie Mainoo": 81, "Azzedine Ounahi": 79,
    "Mohammed Kanno": 74, "Khéphren Thuram": 81, "Youssouf Fofana": 80,
    "Morgan Rogers": 84, "Eberechi Eze": 84, "Tyler Adams": 79, "Idrissa Gueye": 79,
    "Arda Güler": 83, "Jarrod Bowen": 83, "Bryan Mbeumo": 84, "Moussa Diaby": 82,
    "Samuel Chukwueze": 78, "Takefusa Kubo": 80, "Jack Grealish": 82, "Luis Díaz": 88,
    "Matheus Cunha": 84, "Ilias Akhomach": 75, "Rayan Cherki": 86, "Noni Madueke": 80,
    "Nico Williams": 84, "Anthony Gordon": 82, "Evan Ferguson": 74,
    "Benjamin Šeško": 82, "Jhon Durán": 78,
}

for position_cards in CARDS_DATABASE.values():
    for card in position_cards:
        if card["ver"] == "Gold" and card["name"] in FC27_BASE_RATINGS:
            card["rating"] = FC27_BASE_RATINGS[card["name"]]

def player_key(card):
    if "player_id" in card and card["player_id"]:
        return card["player_id"].strip().casefold()
    identity = card.get("image_title", card["name"])
    return "".join(c for c in unicodedata.normalize("NFKD", identity).casefold() if c.isalnum())

def pull_random_card(position_code, seen_players=None):
    pos = "".join([c for c in position_code if not c.isdigit()])
    pool = CARDS_DATABASE.get(pos, CARDS_DATABASE["ST"])
    if seen_players is not None:
        pool = [card for card in pool if player_key(card) not in seen_players]
    if not pool:
        raise ValueError(f"No unused players remain for position {position_code}.")
    weights = []
    for card in pool:
        key = player_key(card)
        w = HIGH_RATING_DRAW_WEIGHT if card["rating"] >= HIGH_RATING_THRESHOLD else 1.0
        if key in RECENTLY_USED_PLAYER_KEYS:
            w *= 0.25
        weights.append(w)
    card = random.choices(pool, weights=weights, k=1)[0].copy()
    if seen_players is not None:
        seen_players.add(player_key(card))
    return card

def remember_player_use(card):
    key = player_key(card)
    if key in RECENTLY_USED_PLAYER_KEYS:
        RECENTLY_USED_PLAYER_KEYS.remove(key)
    RECENTLY_USED_PLAYER_KEYS.append(key)
    del RECENTLY_USED_PLAYER_KEYS[:-160]

PLAYER_IMAGE_CACHE = {}
PLAYER_IMAGE_PRELOAD_TASK = None
PLAYER_IMAGE_OVERRIDES = {
    "Ronaldo Nazário (R9)": "Ronaldo (Brazilian footballer)",
    "Neymar Jr": "Neymar",
    "Mohamed Abu Gabal": "Mohamed Abou Gabal",
    "Gianluigi Buffon": "Gianluigi Buffon",
    "Kaká": "Kaká",
    "Adama Traoré": "Adama Traoré (footballer, born 1996)",
    "Ben White": "Ben White (footballer)",
    "Ederson": "Ederson (footballer, born 1993)",
    "Fabinho": "Fabinho (footballer, born 1993)",
    "Gavi": "Gavi (footballer)",
    "Nuno Mendes": "Nuno Mendes (footballer, born 2002)",
    "Anthony Gordon": "Anthony Gordon (footballer)",
    "Luis Díaz": "Luis Díaz (footballer, born 1997)",
    "Vanderson": "Vanderson (footballer, born 2001)",
    "Youssouf Fofana": "Youssouf Fofana (footballer, born 1999)",
}
PLAYER_IMAGE_URL_OVERRIDES = {
    "trent alexander-arnold": "https://commons.wikimedia.org/wiki/Special:FilePath/Trent_Alexander-Arnold_2018_(cropped).jpg?width=512",
    "mohammed kanno": "https://commons.wikimedia.org/wiki/Special:FilePath/Mohamed_Kanno_Fifa_World_Cup_2026_(cropped).jpg?width=512",
}

def player_image_title(card):
    title = card.get("image_title", card["name"])
    return PLAYER_IMAGE_OVERRIDES.get(title, PLAYER_IMAGE_OVERRIDES.get(card["name"], title)).strip()

def fetch_player_images(titles):
    params = urlencode({"action": "query", "format": "json", "prop": "pageimages", "piprop": "thumbnail", "pithumbsize": 512, "redirects": 1, "titles": "|".join(titles)})
    request = Request(f"https://en.wikipedia.org/w/api.php?{params}", headers={"User-Agent": "MokarFootballBot/1.0 (Discord game bot)"})
    with urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))

async def load_player_images(cards):
    title_map = {player_image_title(c).casefold(): player_image_title(c) for c in cards}
    for title_key in title_map:
        if title_key in PLAYER_IMAGE_URL_OVERRIDES:
            PLAYER_IMAGE_CACHE[title_key] = PLAYER_IMAGE_URL_OVERRIDES[title_key]
    missing = [t for k, t in title_map.items() if k not in PLAYER_IMAGE_CACHE]
    for start in range(0, len(missing), 50):
        batch = missing[start:start + 50]
        data = None
        for attempt in range(3):
            try:
                data = await asyncio.to_thread(fetch_player_images, batch)
                break
            except HTTPError as e:
                if e.code == 429 and attempt < 2:
                    await asyncio.sleep(2)
                    continue
                logger.warning("Could not load player images (HTTP %s): %s", e.code, batch)
                break
            except Exception as e:
                logger.warning("Could not load player images: %s", e)
                break
        if not data:
            continue
        query = data.get("query", {})
        aliases = {a["from"].replace("_", " ").casefold(): a["to"].replace("_", " ").casefold() for a in query.get("normalized", []) + query.get("redirects", [])}
        images = {p.get("title", "").replace("_", " ").casefold(): p.get("thumbnail", {}).get("source") for p in query.get("pages", {}).values()}
        for title in batch:
            k = title.replace("_", " ").casefold()
            PLAYER_IMAGE_CACHE[k] = PLAYER_IMAGE_URL_OVERRIDES.get(k) or images.get(aliases.get(k, k))
        await asyncio.sleep(0.5)

async def ensure_player_image(card):
    title = player_image_title(card).casefold()
    if title not in PLAYER_IMAGE_CACHE:
        await load_player_images([card])

# ---------------------------------------------------------
# 2. الأحداث البرمجية والأوامر العامة
# ---------------------------------------------------------
@bot.event
async def on_ready():
    global PLAYER_IMAGE_PRELOAD_TASK
    print(f"✅ تم تشغيل البوت بنجاح باسم: {bot.user}")
    await bot.change_presence(activity=discord.Game(name="المدرب المكار ⚽ | #vs | #champ"))
    if PLAYER_IMAGE_PRELOAD_TASK is None or PLAYER_IMAGE_PRELOAD_TASK.done():
        cards = [card for position_cards in CARDS_DATABASE.values() for card in position_cards]
        PLAYER_IMAGE_PRELOAD_TASK = asyncio.create_task(load_player_images(cards))

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.BadArgument):
        if ctx.command and ctx.command.name == "champ":
            await ctx.send(
                f"❌ اكتب مدة التسجيل بالدقائق كرقم من {MIN_SIGNUP_MINUTES} إلى "
                f"{MAX_SIGNUP_MINUTES}. مثال: `#champ 15`."
            )
            return
        await ctx.send("❌ لم أتعرف على العضو أو صيغة الأمر. مثال: `#vs @عضو`.")
        return
    logger.error("Command error: %s", error)
    await ctx.send("⚠️ حصل خطأ أثناء تنفيذ الأمر. حاول ثانية بعد قليل.")

@bot.command(name="help", aliases=["مساعدة", "اوامر"])
async def help_command(ctx):
    embed = discord.Embed(title="⚽ قائمة أوامر المدرب المكار 👑", description="دليلك الكامل للمباريات الفردية، التحديات، والبطولة الكبرى!", color=discord.Color.gold())
    embed.add_field(name="🎮 التحدي والمباريات الفردية (#vs)", value="• `#vs`: لفتح تحدٍ عام في السيرفر لأي منافس.\n• `#vs @عضو`: لتحدي عضو محدد؛ **يصله زر قبول أو رفض** لمدة 3 دقائق قبل البدء.\n• بعد القبول يختار الطرفان الخطة ثم تبدأ قرعة سحب 11 لاعباً لكل فريق بالتناوب مع التخطي أو الشراء من المتجر.\n• بعد نهاية المباراة، تختفي الأحداث وتظهر لوحة إحصائيات OSM مقسمة لنصفين مع تقييمات اللاعبين ورجل المباراة.", inline=False)
    embed.add_field(name="🏆 بطولة المكار الكبرى (#champ) — خاص بصاحب البوت فقط", value=f"• `#champ [دقائق]`: صاحب البوت وحده يحدد مدة التسجيل من {MIN_SIGNUP_MINUTES} إلى {MAX_SIGNUP_MINUTES} دقيقة؛ الافتراضي {DEFAULT_SIGNUP_MINUTES} دقيقة.\n• تنتهي إمكانية الدخول تلقائياً عند انتهاء الوقت. إذا لم يكتمل 16 لاعباً، يستطيع صاحب البوت تمديد التسجيل بأمر `#champ [دقائق]`.\n• يفتح تسجيل البطولة مع زر **[دخول البطولة]** وزر **[بدء البطولة]** (للصاحب فقط).\n• حد أدنى 16 لاعباً وحد أقصى 32 لاعباً. قرعة لسحب أندية دوري الأبطال مع محاولتي تخطٍ.\n• إذا دخل 16 لاعباً تبدأ الأدوار الإقصائية مباشرة؛ وإذا زاد العدد تبدأ مرحلة دوري من 5 جولات يتأهل منها أفضل 16 نادياً.\n• إشعار المباراة يمنشن الطرفين قبل 10 دقائق (وقبل النهائي بـ 15 دقيقة) لضبط التشكيلة والمتجر والأسلوب والمتخصصين في رسالة موحدة.", inline=False)
    embed.add_field(name="📊 متابعة البطولة (#جدول و #دور)", value="• `#جدول`: جدول الترتيب والنقاط (18 نادياً في الصفحة) مع أزرار للتنقل بين الصفحتين وزر للهدافين وزر لتقييمات اللاعبين في نفس الرسالة.\n• `#دور`: يعرض مواجهات الأدوار الإقصائية المتبقية مع تصميم شجرة البطولة واسم مدرب كل فريق.", inline=False)
    embed.add_field(name="🚨 نظام الغيابات والإصابات في البطولة", value="• الكارت الأحمر: إيقاف وغياب لمدة **مباراة واحدة**.\n• الإصابة: غياب لمدة **مباراتين**.", inline=False)
    embed.add_field(name="🪙 مكافآت الكوينز والملف الشخصي (#profile)", value="• الفائز: 2,500 + 1,500 لكل هدف + 500 بونص شباك نظيفة.\n• الخاسر: 500 لكل هدف سجله.\n• التعادل الإيجابي: 1,500 لكل لاعب + 450 لكل هدف.\n• التعادل 0-0: 1,000 لكل لاعب. الانسحاب يمنح الخصم 3,000.\n• بطل البطولة يضاف كأس في ملفه الشخصي (`#profile`).", inline=False)
    embed.set_footer(text="صُنع بواسطة: سحلب مكار 👑 | sahlap_makar")
    await ctx.send(embed=embed)

@bot.command(name="profile", aliases=["بروفايل"])
async def profile_command(ctx, member: discord.Member = None):
    target = member or ctx.author
    p = get_profile(target.id)
    embed = discord.Embed(title=f"📋 الملف الشخصي - {target.display_name}", color=discord.Color.green())
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="💰 الكوينز", value=f"{p['coins']:,} K", inline=True)
    embed.add_field(name="🏆 البطولات", value=f"{p['trophies']}", inline=True)
    embed.add_field(name="📊 السجل", value=f"فوز: {p['wins']} | خسارة: {p['losses']}", inline=False)
    embed.add_field(name="⚽ الأهداف", value=f"له: {p['goals_for']} | عليه: {p['goals_against']}", inline=False)
    await ctx.send(embed=embed)

# ---------------------------------------------------------
# 3. محرك التحديات والدرافت (#vs)
# ---------------------------------------------------------
class MatchSession:
    def __init__(self, p1, p2, channel):
        self.p1 = p1
        self.p2 = p2
        self.channel = channel
        self.p1_form = None
        self.p2_form = None
        self.p1_squad = {}
        self.p2_squad = {}
        self.p1_skips = 3
        self.p2_skips = 3
        self.draft_message = None
        self.draft_turn = 0
        self.draft_total = 0
        self.seen_players = set()
        self.withdrawn_player = None
        self.active_draft_state = None
        self.tournament = None
        self.fixture = None
        self.p1_setup = {}
        self.p2_setup = {}

@bot.command(name="vs", aliases=["تحدي"])
async def vs_command(ctx, opponent: discord.Member = None):
    if ctx.guild is None:
        await ctx.send("❌ استخدم أمر `#vs` داخل سيرفر ديسكورد.")
        return
    if opponent and opponent.bot:
        await ctx.send("❌ لا يمكنك تحدي البوت!")
        return
    if opponent and opponent.id == ctx.author.id:
        await ctx.send("❌ لا يمكنك تحدي نفسك!")
        return

    p1 = ctx.author
    participants = (p1, opponent) if opponent else (p1,)
    if not reserve_versus_players(*participants):
        await ctx.send("⌛ أحد اللاعبين لديه تحدٍ أو مباراة جارية بالفعل.")
        return

    try:
        if opponent:
            embed = discord.Embed(
                title="⚔️ تحدي كروي مباشر!",
                description=f"{p1.mention} يتحدى {opponent.mention} في مباراة درافت كروية!\nعلى {opponent.mention} الضغط على **[قبول]** لبدء المباراة أو **[رفض]** خلال 3 دقائق.",
                color=discord.Color.red()
            )
            view = DirectChallengeView(p1, opponent, ctx.channel)
            view.challenge_message = await ctx.send(content=f"{opponent.mention}", embed=embed, view=view, allowed_mentions=discord.AllowedMentions(users=[opponent]))
        else:
            embed = discord.Embed(
                title="⚔️ تحدي مفتوح!",
                description=f"{p1.mention} يبحث عن منافس لمباراة درافت!\nاضغط على **[ قبول التحدي ]** بالأسفل للمواجهة.",
                color=discord.Color.orange()
            )
            view = AcceptChallengeView(p1, ctx.channel)
            view.challenge_message = await ctx.send(embed=embed, view=view)
    except discord.HTTPException:
        release_versus_players(*participants)
        raise

class AcceptChallengeView(View):
    def __init__(self, p1, channel):
        super().__init__(timeout=180)
        self.p1 = p1
        self.channel = channel
        self.challenge_message = None
        self.resolved = False

    async def on_timeout(self):
        if self.resolved:
            return
        self.resolved = True
        release_versus_players(self.p1)
        for item in self.children:
            item.disabled = True
        if self.challenge_message:
            try:
                await self.challenge_message.edit(embed=discord.Embed(title="⌛ انتهت صلاحية التحدي", description="لم يقبل أحد التحدي خلال 3 دقائق.", color=discord.Color.dark_grey()), view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="⚔️ قبول التحدي", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: Button):
        if self.resolved:
            return
        if interaction.user.id == self.p1.id or interaction.user.bot:
            await interaction.response.send_message("❌ لا يمكنك قبول تحدي نفسك أو بحساب بوت!", ephemeral=True)
            return
        p2 = interaction.user
        if not reserve_versus_players(p2):
            await interaction.response.send_message("⌛ لديك تحدٍ أو مباراة جارية بالفعل.", ephemeral=True)
            return
        self.resolved = True
        try:
            await interaction.response.edit_message(embed=discord.Embed(title="✅ تم قبول التحدي", description=f"قبل {p2.mention} تحدي {self.p1.mention}. اختارا تشكيلتيكما الآن.", color=discord.Color.green()), view=None)
        except discord.HTTPException:
            release_versus_players(self.p1, p2)
            self.stop()
            return
        self.stop()
        view = FormationSelectionView(self.p1, p2, self.channel)
        view.selection_message = await self.channel.send(embed=discord.Embed(title="📋 اختيار التشكيلة", description="على كل لاعب اختيار خطته للمباراة:", color=discord.Color.blue()), view=view)

class DirectChallengeView(View):
    def __init__(self, challenger, target, channel):
        super().__init__(timeout=180)
        self.challenger = challenger
        self.target = target
        self.channel = channel
        self.challenge_message = None
        self.resolved = False

    async def on_timeout(self):
        if self.resolved:
            return
        self.resolved = True
        release_versus_players(self.challenger, self.target)
        for item in self.children:
            item.disabled = True
        if self.challenge_message:
            try:
                await self.challenge_message.edit(embed=discord.Embed(title="⌛ انتهت صلاحية التحدي", description=f"لم يرد {self.target.mention} خلال 3 دقائق.", color=discord.Color.dark_grey()), view=self)
            except discord.HTTPException:
                pass

    async def interaction_is_target(self, interaction):
        if self.resolved:
            return False
        if interaction.user.id != self.target.id:
            await interaction.response.send_message(f"❌ هذا التحدي موجّه إلى {self.target.mention} فقط.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="قبول التحدي", emoji="✅", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: Button):
        if not await self.interaction_is_target(interaction):
            return
        self.resolved = True
        try:
            await interaction.response.edit_message(embed=discord.Embed(title="✅ تم قبول التحدي", description=f"قبل {self.target.mention} تحدي {self.challenger.mention}!\nاختارا تشكيلتيكما الآن.", color=discord.Color.green()), view=None)
        except discord.HTTPException:
            release_versus_players(self.challenger, self.target)
            self.stop()
            return
        self.stop()
        view = FormationSelectionView(self.challenger, self.target, self.channel)
        view.selection_message = await self.channel.send(embed=discord.Embed(title="📋 اختيار التشكيلة", description="على كل لاعب اختيار خطته للمباراة:", color=discord.Color.blue()), view=view)

    @discord.ui.button(label="رفض التحدي", emoji="✖️", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: Button):
        if not await self.interaction_is_target(interaction):
            return
        self.resolved = True
        release_versus_players(self.challenger, self.target)
        try:
            await interaction.response.edit_message(embed=discord.Embed(title="❌ تم رفض التحدي", description=f"رفض {self.target.mention} تحدي {self.challenger.mention}.", color=discord.Color.dark_grey()), view=None)
        except discord.HTTPException:
            pass
        self.stop()

class FormationSelectionView(View):
    def __init__(self, p1, p2, channel):
        super().__init__(timeout=120)
        self.session = MatchSession(p1, p2, channel)
        self.selection_message = None
        self.resolved = False
        for f in FORMATIONS:
            btn = Button(label=f, style=discord.ButtonStyle.primary)
            btn.callback = self.make_callback(f)
            self.add_item(btn)

    def make_callback(self, form_name):
        async def cb(interaction: discord.Interaction):
            await self.handle_choice(interaction, form_name)
        return cb

    async def on_timeout(self):
        if self.resolved:
            return
        self.resolved = True
        release_versus_players(self.session.p1, self.session.p2)
        if self.selection_message:
            try:
                await self.selection_message.edit(embed=discord.Embed(title="⌛ انتهى وقت اختيار التشكيلة", description="تم إلغاء التحدي لعدم اكتمال اختيار الخطتين.", color=discord.Color.dark_grey()), view=None)
            except discord.HTTPException:
                pass

    async def handle_choice(self, interaction: discord.Interaction, form_name):
        if self.resolved:
            return
        user = interaction.user
        if user.id not in [self.session.p1.id, self.session.p2.id]:
            await interaction.response.send_message("❌ أنت لست طرفاً في هذا التحدي!", ephemeral=True)
            return
        if user.id == self.session.p1.id and not self.session.p1_form:
            self.session.p1_form = form_name
            await interaction.response.send_message(f"✅ اخترت تشكيلة **{form_name}** يا {user.display_name}!", ephemeral=True)
        elif user.id == self.session.p2.id and not self.session.p2_form:
            self.session.p2_form = form_name
            await interaction.response.send_message(f"✅ اخترت تشكيلة **{form_name}** يا {user.display_name}!", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ لقد اخترت تشكيلتك بالفعل!", ephemeral=True)
            return

        if self.session.p1_form and self.session.p2_form:
            self.resolved = True
            self.stop()
            await self.session.channel.send("✨ تم اختيار التشكيلات! تبدأ الآن مرحلة سحب بطاقات اللاعبين (Draft)...")
            try:
                await start_draft_phase(self.session)
            except Exception as e:
                logger.error("Match draft error: %s", e)
                await self.session.channel.send("⚠️ حصل خطأ أثناء السحب. يمكن للاعبين بدء تحدٍ جديد.")
            finally:
                release_versus_players(self.session.p1, self.session.p2)

# ---------------------------------------------------------
# 4. مرحلة سحب بطاقات الدرافت
# ---------------------------------------------------------
async def start_draft_phase(session):
    p1_pos = FORMATIONS[session.p1_form]
    p2_pos = FORMATIONS[session.p2_form]
    session.draft_total = len(p1_pos) + len(p2_pos)
    session.draft_message = await session.channel.send(embed=discord.Embed(title="🎴 سحب اللاعبين", description="جارٍ تجهيز السحب...", color=discord.Color.gold()))
    
    for i in range(max(len(p1_pos), len(p2_pos))):
        if i < len(p1_pos):
            if not await run_single_draft(session, session.p1, p1_pos[i], True):
                await finish_forfeit(session, session.p1)
                return
        if i < len(p2_pos):
            if not await run_single_draft(session, session.p2, p2_pos[i], False):
                await finish_forfeit(session, session.p2)
                return

    embed = discord.Embed(title="✅ اكتمل اختيار التشكيلتين", description="اكتمل السحب بالتناوب. تبدأ المباراة الحية الآن!", color=discord.Color.green())
    embed.add_field(name=f"🔵 تشكيلة {session.p1.display_name}", value=format_squad(session.p1_squad), inline=True)
    embed.add_field(name=f"🔴 تشكيلة {session.p2.display_name}", value=format_squad(session.p2_squad), inline=True)
    await session.draft_message.edit(content=None, embed=embed, view=None)
    await start_live_match(session)

def format_squad(squad):
    return "\n".join(f"`{pos}` {card['name']} — ⭐ {card['rating']}" for pos, card in squad.items()) or "لم يتم اختيار لاعبين."

class DraftTurnState:
    def __init__(self, session, player, pos_code, is_p1):
        self.session = session
        self.player = player
        self.pos_code = pos_code
        self.is_p1 = is_p1
        self.turn_number = session.draft_turn + 1
        self.deadline = time.monotonic() + 120
        self.done_event = asyncio.Event()
        self.lock = asyncio.Lock()
        self.completed = False
        self.active = True
        self.card_revision = 0
        self.card = None
        self.turn_view = None

def shop_price(card):
    r = card["rating"]
    if r < 60: return 10000
    if r <= 76: return int(10000 + (r - 60) * 312.5)
    if r <= 83: return int(17000 + (r - 77) * 833.3)
    if r <= 87: return int(23000 + (r - 84) * 1666.6)
    if r <= 92: return int(30000 + (r - 88) * 2500)
    if r <= 95: return int(45000 + (r - 93) * 5000)
    return 70000 + (r - 96) * 5000

def make_draft_embed(session, player, pos_code, card, is_p1, turn_number, selected=False, price=None):
    squad = session.p1_squad if is_p1 else session.p2_squad
    skips = session.p1_skips if is_p1 else session.p2_skips
    count = len(squad)
    rem = max(0, 11 - count)
    bal = get_profile(player.id)["coins"]
    color = discord.Color.blue() if is_p1 else discord.Color.red()
    if card:
        embed = discord.Embed(title=f"⭐ {card['rating']} | {card['name']}", description=f"**المركز المطلوب:** `{pos_code}`\n**النسخة:** {card['ver']}", color=color)
        embed.add_field(name="مرات التخطي", value=f"**{MAX_DRAFT_SKIPS - skips}/{MAX_DRAFT_SKIPS}**", inline=True)
        img_url = PLAYER_IMAGE_CACHE.get(player_image_title(card).casefold())
        if img_url:
            embed.set_image(url=img_url)
    else:
        embed = discord.Embed(title=f"🎴 سحب بطاقة مركز {pos_code}", description="اضغط **سحب** لكشف بطاقة اللاعب، أو افتح المتجر للشراء بالكوينز.", color=color)
        embed.add_field(name="الوقت", value="دقيقتان لهذا الدور", inline=True)

    embed.set_author(name=f"دور {player.display_name} — المركز {pos_code}")
    embed.add_field(name="تقدم التشكيلة", value=f"**{count}/11** (متبقي {rem})", inline=True)
    embed.add_field(name="رصيدك", value=f"🪙 **{bal:,}**", inline=True)
    if selected:
        embed.description += f"\n\n✅ تم اختيار **{card['name']}**."
        if price:
            embed.description += f"\n🛒 سعر الشراء: **{price:,} كوينز**."
    return embed

def shop_cards_for_turn(state):
    pos = "".join(c for c in state.pos_code if not c.isdigit())
    return [c.copy() for c in CARDS_DATABASE.get(pos, CARDS_DATABASE["ST"]) if player_key(c) not in state.session.seen_players]

class PlayerShopSelect(Select):
    def __init__(self, state, cards):
        self.state = state
        self.cards = cards
        opts = [discord.SelectOption(label=f"{c['name']} — {c['ver']}"[:100], description=f"⭐ {c['rating']} | السعر {shop_price(c):,} كوينز", value=str(i)) for i, c in enumerate(cards[:25])]
        super().__init__(placeholder="اختر لاعباً لشرائه للمركز الحالي", options=opts)

    async def callback(self, interaction: discord.Interaction):
        st = self.state
        if interaction.user.id != st.player.id:
            await send_ephemeral_notice(interaction, "❌ هذا المتجر خاص بصاحب الدور الحالي.")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with st.lock:
            if not st.active or st.completed or st.card is not None:
                await interaction.edit_original_response(content="⌛ انتهى هذا الدور أو تم كشف بطاقة بالفعل.")
                return
            card = self.cards[int(self.values[0])]
            key = player_key(card)
            if key in st.session.seen_players:
                await interaction.edit_original_response(content="❌ تم استخدام هذا اللاعب بالفعل في المباراة.")
                return
            prof = get_profile(st.player.id)
            pr = shop_price(card)
            if prof["coins"] < pr:
                await interaction.edit_original_response(content=f"رصيدك {prof['coins']:,} كوينز وسعره {pr:,}.")
                return
            prof["coins"] -= pr
            st.session.seen_players.add(key)
            remember_player_use(card)
            squad = st.session.p1_squad if st.is_p1 else st.session.p2_squad
            squad[st.pos_code] = card
            st.card = card
            st.card_revision += 1
            st.completed = True
            try:
                await ensure_player_image(card)
                await st.session.draft_message.edit(content=None, embed=make_draft_embed(st.session, st.player, st.pos_code, card, st.is_p1, st.turn_number, selected=True, price=pr), view=None)
                await interaction.edit_original_response(content=f"✅ اشتريت **{card['name']}** مقابل **{pr:,} كوينز**.")
            finally:
                st.active = False
                st.done_event.set()
                if st.turn_view:
                    st.turn_view.stop()

class DraftTurnView(View):
    def __init__(self, state):
        super().__init__(timeout=max(1, state.deadline - time.monotonic()))
        self.state = state
        state.turn_view = self

    @discord.ui.button(label="سحب", emoji="🎴", style=discord.ButtonStyle.primary)
    async def draw_card(self, interaction: discord.Interaction, button: Button):
        st = self.state
        if interaction.user.id != st.player.id:
            await send_ephemeral_notice(interaction, "❌ هذا الدور مخصص للاعب الآخر.")
            return
        await interaction.response.defer()
        async with st.lock:
            if not st.active or st.completed:
                await interaction.followup.send("⌛ انتهى هذا الدور.", ephemeral=True)
                return
            if st.card is not None:
                await interaction.followup.send("⚠️ تم كشف بطاقة بالفعل. اخترها أو تخطّها.", ephemeral=True)
                return
            try:
                st.card = pull_random_card(st.pos_code, st.session.seen_players)
            except ValueError:
                await interaction.followup.send("❌ لا توجد بطاقات متاحة دون تكرار.", ephemeral=True)
                return
            st.card_revision += 1
            try:
                await ensure_player_image(st.card)
            except Exception as e:
                logger.warning("Could not prepare draft card image: %s", e)
            if not st.active:
                await interaction.followup.send("⌛ انتهى هذا الدور.", ephemeral=True)
                return
            view = DraftCardView(st)
            await interaction.edit_original_response(embed=make_draft_embed(st.session, st.player, st.pos_code, st.card, st.is_p1, st.turn_number), view=view)
            self.stop()

    @discord.ui.button(label="المتجر", emoji="🛒", style=discord.ButtonStyle.secondary)
    async def open_shop(self, interaction: discord.Interaction, button: Button):
        st = self.state
        if interaction.user.id != st.player.id:
            await interaction.response.send_message("❌ هذا المتجر خاص بصاحب الدور الحالي.", ephemeral=True)
            return
        async with st.lock:
            if not st.active or st.completed or st.card is not None:
                await interaction.response.send_message("⌛ انتهى هذا الدور أو تم كشف بطاقة بالفعل.", ephemeral=True)
                return
            cards = shop_cards_for_turn(st)
            if not cards:
                await interaction.response.send_message("لا توجد بطاقات متاحة في المتجر لهذا المركز.", ephemeral=True)
                return
        view = View()
        view.add_item(PlayerShopSelect(st, cards))
        await interaction.response.send_message(embed=discord.Embed(title=f"🛒 متجر المركز {st.pos_code}", description=f"رصيدك: **{get_profile(st.player.id)['coins']:,}** كوينز", color=discord.Color.gold()), view=view, ephemeral=True)

class DraftCardView(View):
    def __init__(self, state):
        super().__init__(timeout=max(1, state.deadline - time.monotonic()))
        self.state = state
        self.revision = state.card_revision
        skips_left = state.session.p1_skips if state.is_p1 else state.session.p2_skips
        skip_button = next(item for item in self.children if item.label == "تخطي")
        skip_button.label = f"تخطي {MAX_DRAFT_SKIPS - skips_left}/{MAX_DRAFT_SKIPS}"
        skip_button.disabled = skips_left <= 0

    @discord.ui.button(label="اختيار اللاعب", emoji="✅", style=discord.ButtonStyle.success)
    async def select_player(self, interaction: discord.Interaction, button: Button):
        st = self.state
        if interaction.user.id != st.player.id:
            await send_ephemeral_notice(interaction, "❌ هذا الدور مخصص للاعب الآخر.")
            return
        async with st.lock:
            if not st.active or st.completed or st.card is None or self.revision != st.card_revision:
                await send_ephemeral_notice(interaction, "⌛ هذه البطاقة لم تعد نشطة. استخدم أزرار الدور الحالي.")
                return
            squad = st.session.p1_squad if st.is_p1 else st.session.p2_squad
            squad[st.pos_code] = st.card
            remember_player_use(st.card)
            st.completed = True
            try:
                await interaction.response.edit_message(content=None, embed=make_draft_embed(st.session, st.player, st.pos_code, st.card, st.is_p1, st.turn_number, selected=True), view=None)
            finally:
                st.active = False
                st.done_event.set()
                self.stop()

    @discord.ui.button(label="تخطي", emoji="🔄", style=discord.ButtonStyle.danger)
    async def skip_card(self, interaction: discord.Interaction, button: Button):
        st = self.state
        if interaction.user.id != st.player.id:
            await send_ephemeral_notice(interaction, "❌ هذا الدور مخصص للاعب الآخر.")
            return
        await interaction.response.defer()
        async with st.lock:
            if not st.active or st.completed or st.card is None or self.revision != st.card_revision:
                await interaction.followup.send("⌛ هذه البطاقة لم تعد نشطة. استخدم أزرار الدور الحالي.", ephemeral=True)
                return
            skips = st.session.p1_skips if st.is_p1 else st.session.p2_skips
            if skips <= 0:
                await interaction.followup.send("❌ استنفدت محاولات التخطي.", ephemeral=True)
                return
            try:
                card = pull_random_card(st.pos_code, st.session.seen_players)
            except ValueError:
                await interaction.followup.send("❌ لا توجد بطاقات أخرى متاحة لهذا المركز.", ephemeral=True)
                return
            if st.is_p1:
                st.session.p1_skips -= 1
            else:
                st.session.p2_skips -= 1
            st.card = card
            st.card_revision += 1
            try:
                await ensure_player_image(st.card)
            except Exception as e:
                logger.warning("Could not prepare skipped draft card image: %s", e)
            if not st.active:
                await interaction.followup.send("⌛ انتهى هذا الدور.", ephemeral=True)
                return
            view = DraftCardView(st)
            await interaction.edit_original_response(embed=make_draft_embed(st.session, st.player, st.pos_code, st.card, st.is_p1, st.turn_number), view=view)
            self.stop()

async def finish_forfeit(session, withdrawn):
    winner = session.p2 if withdrawn.id == session.p1.id else session.p1
    get_profile(winner.id)["wins"] += 1
    get_profile(winner.id)["coins"] += 3000
    get_profile(withdrawn.id)["losses"] += 1
    await session.draft_message.edit(content=None, embed=discord.Embed(title="🏳️ انتهت المباراة بالانسحاب", description=f"لم يختر {withdrawn.mention} لاعبه في الوقت المحدد.\n🏆 فاز {winner.mention} بالانسحاب ونال **3,000 كوينز**.", color=discord.Color.gold()), view=None)

async def run_single_draft(session, player, pos_code, is_p1):
    st = DraftTurnState(session, player, pos_code, is_p1)
    session.active_draft_state = st
    previous_message = session.draft_message
    turn_view = DraftTurnView(st)
    turn_content = f"🎮 {player.mention} حان دورك للسحب — اختر لاعبك أو افتح المتجر. أمامك دقيقتان."
    turn_embed = make_draft_embed(session, player, pos_code, None, is_p1, st.turn_number)
    try:
        current_message = await session.channel.send(
            content=turn_content,
            embed=turn_embed,
            view=turn_view,
            allowed_mentions=discord.AllowedMentions(users=[player]),
        )
    except discord.HTTPException as send_error:
        logger.warning("Could not post a new draft turn; reusing the current message: %s", send_error)
        if previous_message is None:
            raise
        try:
            await previous_message.edit(
                content=turn_content,
                embed=turn_embed,
                view=turn_view,
                allowed_mentions=discord.AllowedMentions(users=[player]),
            )
            current_message = previous_message
        except discord.HTTPException:
            raise send_error
    session.draft_message = current_message
    if previous_message is not None and previous_message is not current_message:
        try:
            await previous_message.delete()
        except discord.NotFound:
            pass
        except discord.HTTPException as e:
            logger.warning("Could not remove previous draft message: %s", e)
            try:
                await previous_message.edit(view=None)
            except discord.HTTPException as edit_error:
                logger.warning("Could not remove controls from the previous draft message: %s", edit_error)
    try:
        await asyncio.wait_for(st.done_event.wait(), timeout=120)
    except asyncio.TimeoutError:
        async with st.lock:
            if not st.completed:
                st.active = False
    if not st.completed:
        st.active = False
        if st.turn_view:
            st.turn_view.stop()
        if session.active_draft_state is st:
            session.active_draft_state = None
        session.withdrawn_player = player
        return False
    st.active = False
    if st.turn_view:
        st.turn_view.stop()
    if session.active_draft_state is st:
        session.active_draft_state = None
    session.draft_turn += 1
    return True

# ---------------------------------------------------------
# 5. محاكي المباراة وإحصائيات OSM
# ---------------------------------------------------------
class MatchDetailsToggleView(View):
    def __init__(self, stats_embed, ratings_embed):
        super().__init__(timeout=1800)
        self.stats_embed = stats_embed
        self.ratings_embed = ratings_embed

    @discord.ui.button(label="📊 إحصائيات المباراة (OSM)", style=discord.ButtonStyle.primary)
    async def show_stats(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(embed=self.stats_embed, view=self)

    @discord.ui.button(label="⭐ تقييمات اللاعبين", style=discord.ButtonStyle.secondary)
    async def show_ratings(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(embed=self.ratings_embed, view=self)

def add_osm_comparison_fields(embed, session, stats):
    field_specs = [
        ("📊 الاستحواذ", lambda values: f"{values['possession']}%"),
        ("🎯 التسديدات", lambda values: f"{values['shots']} — على المرمى {values['shots_on_target']}"),
        ("✅ دقة التسديد", lambda values: f"{values['accuracy']}%"),
        ("🚩 الركنيات", lambda values: str(values["corners"])),
        (
            "🧱 الأخطاء والبطاقات",
            lambda values: f"{values['fouls']} أخطاء • 🟨 {values['yellow_cards']} • 🟥 {values['red_cards']}",
        ),
        ("🚑 الإصابات", lambda values: str(values["injuries"])),
    ]
    teams = ((session.p1, stats[0], "🔵"), (session.p2, stats[1], "🔴"))
    for field_name, format_value in field_specs:
        value = "\n".join(
            f"{marker} **{member.display_name}:** `{format_value(team_stats)}`"
            for member, team_stats, marker in teams
        )
        embed.add_field(name=field_name, value=value, inline=True)

def build_match_timeline(session):
    scores = [0, 0]
    events = []
    teams = [session.p1_squad, session.p2_squad]
    stats = []
    for squad in teams:
        stats.append({
            "possession": 0, "shots": 0, "shots_on_target": 0, "fouls": 0, "corners": 0,
            "yellow_cards": 0, "red_cards": 0, "injuries": 0,
            "player_events": {c["name"]: {"rating": 6.0, "goals": 0, "assists": 0, "yellow": 0, "red": 0, "injured": False} for c in squad.values()},
            "penalties": []
        })
    pos = random.randint(43, 57)
    stats[0]["possession"] = pos
    stats[1]["possession"] = 100 - pos

    for minute in [8, 16, 24, 33, 42, 45, 55, 64, 73, 82, 88, 90]:
        if minute == 45:
            events.append({"minute": 45, "text": "⏸️ **صافرة نهاية الشوط الأول.**", "p1": scores[0], "p2": scores[1]})
            continue
        side = random.randrange(2)
        opp = 1 - side
        team = session.p1 if side == 0 else session.p2
        squad = teams[side]
        cards = list(squad.values())
        if not cards:
            continue
        atk = random.choice(cards)
        p_stat = stats[side]["player_events"][atk["name"]]
        act = random.choices(["shot", "foul", "corner", "card", "injury"], weights=[55, 20, 12, 8, 5], k=1)[0]

        if act == "shot":
            stats[side]["shots"] += 1
            if random.random() < 0.6:
                stats[side]["shots_on_target"] += 1
                if random.random() < 0.35:
                    scores[side] += 1
                    p_stat["goals"] += 1
                    p_stat["rating"] += 1.3
                    ev = f"⚽ **د `{minute}'` هدف لـ {team.display_name}!** {atk['name']} يسكنها الشباك!"
                else:
                    ev = f"🧤 **د `{minute}'` تصدٍ رائع!** تسديدة {atk['name']} يبعدها الحارس."
            else:
                ev = f"🥅 **د `{minute}'` فرصة ضائعة لـ {team.display_name}:** تسديدة {atk['name']} خارج المرمى."
        elif act == "foul":
            stats[opp]["fouls"] += 1
            ev = f"⚠️ **د `{minute}'` خطأ واحتكاك قوي** من مدافع الخصم على {atk['name']}."
        elif act == "corner":
            stats[side]["corners"] += 1
            ev = f"🚩 **د `{minute}'` ركنية لـ {team.display_name}** ينفذها {atk['name']}."
        elif act == "card":
            stats[side]["fouls"] += 1
            if random.random() < 0.15:
                stats[side]["red_cards"] += 1
                p_stat["red"] += 1
                p_stat["rating"] -= 2.5
                stats[side]["penalties"].append({"type": "red", "player": atk})
                ev = f"🟥 **د `{minute}'` بطاقة حمراء مباشرة!** الحكم يطرد {atk['name']}!"
            else:
                stats[side]["yellow_cards"] += 1
                p_stat["yellow"] += 1
                p_stat["rating"] -= 0.4
                ev = f"🟨 **د `{minute}'` بطاقة صفراء** للاعب {atk['name']} بعد تدخل خشن."
        else:
            stats[side]["injuries"] += 1
            p_stat["injured"] = True
            p_stat["rating"] -= 0.8
            stats[side]["penalties"].append({"type": "injury", "player": atk})
            ev = f"🚑 **د `{minute}'` إصابة مؤلمة لـ {atk['name']}** ويغادر الملعب لتلقي الإسعافات."

        events.append({"minute": minute, "text": ev, "p1": scores[0], "p2": scores[1]})

    for s in stats:
        s["accuracy"] = round(s["shots_on_target"] * 100 / s["shots"]) if s["shots"] else 0
    return events, scores[0], scores[1], stats

def calculate_coin_rewards(s1, s2):
    if s1 > s2: return 2500 + 1500 * s1 + (500 if s2 == 0 else 0), 500 * s2
    if s2 > s1: return 500 * s1, 2500 + 1500 * s2 + (500 if s1 == 0 else 0)
    if s1 == 0: return 1000, 1000
    return 1500 + 450 * s1, 1500 + 450 * s2

def build_final_match_embeds(session, s1, s2, stats, rewards):
    motm = None
    r_lines = []
    for side, squad in enumerate([session.p1_squad, session.p2_squad]):
        for c in squad.values():
            pe = stats[side]["player_events"].get(c["name"], {"rating": 6.0})
            rt = max(1.0, min(10.0, pe["rating"]))
            ex = []
            if pe.get("goals"): ex.append(f"⚽ {pe['goals']}")
            if pe.get("yellow"): ex.append("🟨")
            if pe.get("red"): ex.append("🟥")
            if pe.get("injured"): ex.append("🚑")
            lbl = f"{c['name']} — **{rt:.1f}/10**" + (f" ({' '.join(ex)})" if ex else "")
            r_lines.append((side, lbl, rt, c["name"]))
            if not motm or rt > motm[0]:
                motm = (rt, c["name"], session.p1 if side == 0 else session.p2)

    res_txt = f"🏆 **الفائز: {session.p1.display_name}**" if s1 > s2 else (f"🏆 **الفائز: {session.p2.display_name}**" if s2 > s1 else "🤝 **انتهت المباراة بالتعادل العادل**")
    stats_embed = discord.Embed(
        title="🏁 صافرة النهاية — إحصائيات المباراة",
        description=f"🔵 **{session.p1.display_name}** `{s1}` — `{s2}` **{session.p2.display_name}** 🔴\n{res_txt}",
        color=discord.Color.gold()
    )
    add_osm_comparison_fields(stats_embed, session, stats)
    stats_embed.add_field(
        name="🌟 رجل المباراة",
        value=f"**{motm[1]}** — {motm[2].display_name}\nالتقييم: **{motm[0]:.1f}/10**",
        inline=False,
    )
    stats_embed.add_field(
        name="🪙 المكافآت",
        value=f"🔵 {session.p1.display_name}: `+{rewards[0]:,}`\n🔴 {session.p2.display_name}: `+{rewards[1]:,}`",
        inline=False,
    )
    ratings_embed = discord.Embed(
        title="⭐ تقييمات لاعبي الفريقين (OSM Rating)",
        description=f"**النتيجة النهائية:** 🔵 {session.p1.display_name} `{s1}` - `{s2}` {session.p2.display_name} 🔴\n🌟 رجل المباراة: **{motm[1]}** ({motm[0]:.1f}/10)\nالرموز: ⚽ أهداف | 🟨 إنذار | 🟥 طرد | 🚑 إصابة",
        color=discord.Color.purple()
    )
    ratings_embed.add_field(name=f"🔵 تشكيلة {session.p1.display_name}", value="\n".join(l for sd, l, _, _ in r_lines if sd == 0)[:1024] or "—", inline=True)
    ratings_embed.add_field(name=f"🔴 تشكيلة {session.p2.display_name}", value="\n".join(l for sd, l, _, _ in r_lines if sd == 1)[:1024] or "—", inline=True)
    motm_squad = session.p1_squad if motm[2].id == session.p1.id else session.p2_squad
    motm_card = next((card for card in motm_squad.values() if card["name"] == motm[1]), None)
    if motm_card:
        motm_image = PLAYER_IMAGE_CACHE.get(player_image_title(motm_card).casefold())
        if motm_image:
            ratings_embed.set_image(url=motm_image)
    return stats_embed, ratings_embed, motm

async def start_live_match(session):
    p1_rat = sum(c["rating"] for c in session.p1_squad.values()) // max(1, len(session.p1_squad))
    p2_rat = sum(c["rating"] for c in session.p2_squad.values()) // max(1, len(session.p2_squad))
    timeline, s1, s2, stats = build_match_timeline(session)
    rewards = calculate_coin_rewards(s1, s2)
    stats_embed, ratings_embed, motm = build_final_match_embeds(session, s1, s2, stats, rewards)

    msg = await session.channel.send(embed=discord.Embed(title=f"🏟️ {session.p1.display_name} ({p1_rat}) 🆚 {session.p2.display_name} ({p2_rat})", description="🏁 **صافرة البداية! انطلقت المباراة الآن...**", color=discord.Color.blue()))
    events_log = []
    for ev in timeline:
        await asyncio.sleep(6)
        events_log.insert(0, ev["text"])
        await msg.edit(embed=discord.Embed(title=f"🏟️ {session.p1.display_name} `{ev['p1']}` - `{ev['p2']}` {session.p2.display_name}", description=f"⏱️ **الدقيقة:** `{ev['minute']}'`\n\n" + "\n".join(events_log[:6]), color=discord.Color.blue()))

    p1_prof = get_profile(session.p1.id)
    p2_prof = get_profile(session.p2.id)
    p1_prof["goals_for"] += s1; p1_prof["goals_against"] += s2; p1_prof["coins"] += rewards[0]
    p2_prof["goals_for"] += s2; p2_prof["goals_against"] += s1; p2_prof["coins"] += rewards[1]
    if s1 > s2: p1_prof["wins"] += 1; p2_prof["losses"] += 1
    elif s2 > s1: p2_prof["wins"] += 1; p1_prof["losses"] += 1

    await msg.edit(content=None, embed=stats_embed, view=MatchDetailsToggleView(stats_embed, ratings_embed))
    if session.tournament and session.fixture:
        await finalize_tournament_match(session, session.fixture, s1, s2, stats, motm)

# ---------------------------------------------------------
# 6. نظام بطولة المكار الكبرى (#champ)
# ---------------------------------------------------------
CHAMPIONS_LEAGUE_CLUBS = [
    ("Real Madrid", "Spain", 93), ("Manchester City", "England", 93), ("Bayern München", "Germany", 92),
    ("Liverpool", "England", 92), ("Arsenal", "England", 91), ("Paris Saint-Germain", "France", 91),
    ("Barcelona", "Spain", 91), ("Inter", "Italy", 90), ("Bayer Leverkusen", "Germany", 89),
    ("Atlético de Madrid", "Spain", 88), ("Borussia Dortmund", "Germany", 88), ("Juventus", "Italy", 87),
    ("AC Milan", "Italy", 87), ("Chelsea", "England", 87), ("Manchester United", "England", 87),
    ("Sporting CP", "Portugal", 87), ("Napoli", "Italy", 88), ("Tottenham Hotspur", "England", 86),
    ("Aston Villa", "England", 86), ("Newcastle United", "England", 86), ("Porto", "Portugal", 86),
    ("Benfica", "Portugal", 86), ("PSV", "Netherlands", 86), ("Atalanta", "Italy", 86),
    ("RB Leipzig", "Germany", 85), ("Roma", "Italy", 85), ("Villarreal", "Spain", 85),
    ("Galatasaray", "Türkiye", 85), ("Fenerbahçe", "Türkiye", 84), ("Ajax", "Netherlands", 83),
    ("Al Hilal", "Saudi Arabia", 84), ("Al Nassr", "Saudi Arabia", 83), ("Al Ahly", "Egypt", 81), ("Zamalek", "Egypt", 78)
]

TOURNAMENT_CLUBS = [{"name": n, "country": c, "rating": r} for n, c, r in CHAMPIONS_LEAGUE_CLUBS]
TOURNAMENT_SLOTS = list(dict.fromkeys(pos for f in FORMATIONS.values() for pos in f))

class TournamentState:
    def __init__(self, owner_id, channel, mins):
        self.owner_id = owner_id
        self.channel = channel
        self.signup_minutes = mins
        self.signup_deadline = time.monotonic() + mins * 60
        self.signup_timer_task = None
        self.signup_timer_version = 0
        self.signup_view = None
        self.phase = "signup"
        self.entry_closed = False
        self.message = None
        self.entrant_ids = []
        self.participants = {}
        self.available_clubs = [c.copy() for c in TOURNAMENT_CLUBS]
        self.current_fixtures = []
        self.all_fixtures = []
        self.stage_label = "التسجيل"
        self.league_round = 0
        self.league_rounds = 5
        self.knockout_round = 0
        self.stage_advancing = False
        self.scorers = {}
        self.player_ratings = {}
        self.pairings_played = set()
        self.tasks = []

    def add_member(self, member):
        if member.id in self.participants or len(self.entrant_ids) >= 32:
            return False
        self.entrant_ids.append(member.id)
        self.participants[member.id] = {
            "member": member, "club": None, "roster": {}, "lineup": {}, "formation": "4-3-3",
            "setup": {"style": "متوازن", "tactic": "تمريرات", "specialists": {}, "pending_role": "قائد الفريق"},
            "suspensions": {},
            "table": {"played": 0, "won": 0, "drawn": 0, "lost": 0, "goals_for": 0, "goals_against": 0, "points": 0},
            "wins": 0
        }
        return True

def create_club_roster(club):
    roster = {}
    used = set()
    for slot in TOURNAMENT_SLOTS:
        pos = "".join(c for c in slot if not c.isdigit())
        pool = CARDS_DATABASE.get(pos, CARDS_DATABASE["CM"])
        cand = [c for c in pool if player_key(c) not in used] or pool
        card = random.choice(cand).copy()
        used.add(player_key(card))
        card["club_player_id"] = f"{club['name']}:{slot}:{player_key(card)}"
        roster[slot] = card
    return roster

def tournament_table_rows(state):
    return sorted(state.participants.values(), key=lambda p: (p["table"]["points"], p["table"]["goals_for"] - p["table"]["goals_against"], p["table"]["goals_for"]), reverse=True)

def tournament_signup_embed(state):
    ent = len(state.entrant_ids)
    rem = max(0, 32 - ent)
    close_ts = int(datetime.now(CAIRO_TZ).timestamp() + max(0, state.signup_deadline - time.monotonic()))
    lines = [f"**{i}.** {state.participants[uid]['member'].mention}" for i, uid in enumerate(state.entrant_ids[:16], 1)]
    return discord.Embed(
        title="🏆 ⚽ بطولة المكار الكبرى — دوري أبطال أوروبا ⚽ 🏆",
        description=(
            "📋 **المختصر المفيد عن نظام وقواعد البطولة:**\n"
            "• **العدد المطلوب:** من 16 إلى 32 لاعباً كحد أقصى.\n"
            "• **قرعة الأندية:** يختار كل لاعب نادياً عشوائياً بالترتيب وله محاولتا تخطٍ (2 Skips).\n"
            "• **طريقة البطولة:** إذا اكتمل **16 لاعباً فقط** تبدأ الأدوار الإقصائية مباشرة (خروج المغلوب). وإذا زاد العدد تبدأ مرحلة دوري من 5 جولات ويتأهل أفضل 16 نادياً للأدوار الإقصائية.\n"
            "• **قبل المباراة:** يمنشن البوت الطرفين قبل 10 دقائق (وقبل النهائي بـ 15 دقيقة) لفتح التشكيلة والمتجر والتكتيك والمتخصصين.\n"
            "• **نظام الغيابات:** الكارت الأحمر غياب **مباراة واحدة**، والإصابة غياب **مباراتين**.\n"
            "• **الجوائز:** كأس البطولة يضاف لبروفايل البطل، ومكافآت كوينز لكل مباراة!\n\n"
            f"👥 **المسجلون الآن:** `{ent}/32` لاعب | **الأماكن الشاغرة:** `{rem}`\n"
            f"⏳ **مدة التسجيل:** `{state.signup_minutes}` دقيقة\n"
            f"🔒 **حالة التسجيل:** `{'مغلق' if state.entry_closed else 'مفتوح'}`\n"
            f"⏳ **موعد إغلاق التسجيل:** <t:{close_ts}:R>\n\n"
            "**قائمة اللاعبين المسجلين:**\n" + ("\n".join(lines) or "لم يسجل أحد بعد.")
        ),
        color=discord.Color.gold()
    )

async def close_tournament_signup(state, notify=True, expected_version=None):
    if expected_version is not None and state.signup_timer_version != expected_version:
        return False
    if state.phase != "signup" or state.entry_closed:
        return False
    if time.monotonic() < state.signup_deadline:
        return False

    state.entry_closed = True
    if state.signup_view:
        state.signup_view.join_btn.disabled = True

    try:
        if state.message:
            await state.message.edit(
                embed=tournament_signup_embed(state),
                view=state.signup_view,
            )
    except discord.HTTPException:
        logger.exception("Could not update the tournament signup message after its deadline.")

    if notify:
        if len(state.entrant_ids) < 16:
            message = (
                f"انتهت مدة التسجيل ({state.signup_minutes} دقيقة) ولم يصل العدد إلى 16 لاعباً. "
                f"يمكن لصاحب البوت تمديد التسجيل باستخدام `#champ [دقائق]`."
            )
        else:
            message = (
                f"انتهت مدة التسجيل ({state.signup_minutes} دقيقة). "
                "يمكن لصاحب البوت بدء البطولة من زر **بدء البطولة**."
            )
        try:
            await state.channel.send(message)
        except discord.HTTPException:
            logger.exception("Could not announce that tournament signup has closed.")
    return True

def schedule_tournament_signup_close(state):
    state.signup_timer_version += 1
    version = state.signup_timer_version
    previous_task = state.signup_timer_task
    if previous_task and not previous_task.done():
        previous_task.cancel()

    async def wait_for_deadline():
        try:
            await asyncio.sleep(max(0, state.signup_deadline - time.monotonic()))
        except asyncio.CancelledError:
            return
        await close_tournament_signup(state, expected_version=version)

    state.signup_timer_task = asyncio.create_task(wait_for_deadline())

class TournamentSignupView(View):
    def __init__(self, state):
        # Keep the buttons active slightly beyond the maximum signup period so
        # the signup timer can close the join button first.
        super().__init__(timeout=MAX_SIGNUP_MINUTES * 60 + 60)
        self.state = state

    @discord.ui.button(label="دخول البطولة", emoji="⚽", style=discord.ButtonStyle.primary)
    async def join_btn(self, interaction: discord.Interaction, button: Button):
        st = self.state
        if st.phase != "signup" or st.entry_closed:
            await interaction.response.send_message("انتهى التسجيل في هذه البطولة.", ephemeral=True)
            return
        if time.monotonic() >= st.signup_deadline:
            await close_tournament_signup(st, notify=False)
            await interaction.response.send_message("انتهت مدة التسجيل في هذه البطولة.", ephemeral=True)
            return
        if interaction.user.bot or interaction.user.id in st.participants:
            await interaction.response.send_message("❌ أنت مسجل بالفعل أو الحساب بوت.", ephemeral=True)
            return
        if not st.add_member(interaction.user):
            await interaction.response.send_message("اكتمل الحد الأقصى (32 لاعباً).", ephemeral=True)
            return
        await interaction.response.edit_message(embed=tournament_signup_embed(st), view=self)

    @discord.ui.button(label="بدء البطولة", emoji="🏁", style=discord.ButtonStyle.success)
    async def start_btn(self, interaction: discord.Interaction, button: Button):
        st = self.state
        if interaction.user.id != st.owner_id:
            await interaction.response.send_message("❌ زر بدء البطولة مخصص لصاحب البوت فقط.", ephemeral=True)
            return
        if len(st.entrant_ids) < 16:
            await interaction.response.send_message(f"تحتاج البطولة 16 لاعباً على الأقل. المسجلون حالياً: {len(st.entrant_ids)}.", ephemeral=True)
            return
        st.phase = "club_draft"
        st.message = interaction.message
        await interaction.response.edit_message(embed=discord.Embed(title="🎲 سحب أندية البطولة", description=f"اكتمل التسجيل بـ **{len(st.entrant_ids)} لاعباً**. تبدأ الآن قرعة اختيار الأندية بالترتيب...", color=discord.Color.gold()), view=None)
        asyncio.create_task(run_tournament_club_draft(st))

class ClubDraftTurn:
    def __init__(self, tournament, member):
        self.tournament = tournament
        self.member = member
        self.deadline = time.monotonic() + 120
        self.done = asyncio.Event()
        self.candidate = None
        self.skips_left = 2

class ClubDrawView(View):
    def __init__(self, turn):
        super().__init__(timeout=120)
        self.turn = turn

    @discord.ui.button(label="سحب نادٍ", emoji="🎲", style=discord.ButtonStyle.primary)
    async def draw(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.turn.member.id:
            return
        self.turn.candidate = random.choice(self.turn.tournament.available_clubs)
        view = View(timeout=120)
        choose_btn = Button(label="اختيار النادي", emoji="✅", style=discord.ButtonStyle.success)
        choose_btn.callback = self.make_choose_cb(view)
        view.add_item(choose_btn)
        skip_btn = Button(label=f"تخطي ({self.turn.skips_left})", emoji="🔄", style=discord.ButtonStyle.secondary)
        skip_btn.callback = self.make_skip_cb(view)
        view.add_item(skip_btn)
        await interaction.response.edit_message(embed=discord.Embed(title=f"🏟️ ناديك المقترح: {self.turn.candidate['name']}", description=f"الدولة: {self.turn.candidate['country']} | القوة: ⭐ {self.turn.candidate['rating']}/100\nالتخطي المتبقي: {self.turn.skips_left}", color=discord.Color.blue()), view=view)
        self.stop()

    def make_choose_cb(self, parent_view):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.turn.member.id:
                return
            self.turn.done.set()
            parent_view.stop()
            await interaction.response.edit_message(content=None, embed=discord.Embed(title=f"✅ تم اختيار {self.turn.candidate['name']}!", color=discord.Color.green()), view=None)
        return cb

    def make_skip_cb(self, parent_view):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.turn.member.id:
                return
            if self.turn.skips_left <= 0:
                await interaction.response.send_message("استنفدت محاولتي التخطي.", ephemeral=True)
                return
            self.turn.skips_left -= 1
            pool = [c for c in self.turn.tournament.available_clubs if c['name'] != self.turn.candidate['name']]
            self.turn.candidate = random.choice(pool or self.turn.tournament.available_clubs)
            parent_view.children[1].label = f"تخطي ({self.turn.skips_left})"
            await interaction.response.edit_message(embed=discord.Embed(title=f"🏟️ ناديك المقترح: {self.turn.candidate['name']}", description=f"الدولة: {self.turn.candidate['country']} | القوة: ⭐ {self.turn.candidate['rating']}/100\nالتخطي المتبقي: {self.turn.skips_left}", color=discord.Color.blue()), view=parent_view)
        return cb

async def run_tournament_club_draft(state):
    try:
        draft_msg = await state.channel.send("🎲 تبدأ قرعة توزيع الأندية الآن...")
        for uid in state.entrant_ids:
            part = state.participants[uid]
            turn = ClubDraftTurn(state, part["member"])
            await draft_msg.edit(content=f"🎮 دور المدرب {part['member'].mention}", embed=discord.Embed(title="🎲 قرعة الأندية — حان دورك!", description=f"النوادي المتبقية: **{len(state.available_clubs)}**", color=discord.Color.gold()), view=ClubDrawView(turn), allowed_mentions=discord.AllowedMentions(users=[part["member"]]))
            try:
                await asyncio.wait_for(turn.done.wait(), timeout=120)
            except asyncio.TimeoutError:
                pass
            if not turn.candidate:
                turn.candidate = random.choice(state.available_clubs)
            club = turn.candidate
            state.available_clubs.remove(club)
            part["club"] = club
            part["roster"] = create_club_roster(club)
            part["lineup"] = {slot: part["roster"][slot] for slot in FORMATIONS[part["formation"]]}
            await draft_msg.edit(content=None, embed=discord.Embed(title=f"✅ {part['member'].display_name} يقود نادي {club['name']}!", description=f"القوة: ⭐ {club['rating']}/100", color=discord.Color.green()), view=None)
            await asyncio.sleep(2)

        await draft_msg.edit(content=None, embed=discord.Embed(title="✅ اكتملت قرعة الأندية بنجاح!", description=f"حصل جميع المشاركين الـ **{len(state.entrant_ids)}** على أنديتهم.", color=discord.Color.green()), view=None)
        if len(state.entrant_ids) == 16:
            state.phase = "knockout"
            await state.channel.send("⚡ **اكتمل 16 لاعباً بالضبط! تبدأ الأدوار الإقصائية فوراً (خروج المغلوب).**")
            await create_knockout_stage(state, random.sample(state.entrant_ids, len(state.entrant_ids)), first=True)
        else:
            state.phase = "league"
            state.league_round = 1
            await state.channel.send(f"⚽ **عدد المشاركين {len(state.entrant_ids)} لاعباً! تبدأ مرحلة دوري الأبطال (5 جولات).**")
            await create_league_round(state)
    except Exception as e:
        logger.error("Club draft failed: %s", e)

def new_tournament_fixture(state, p1_id, p2_id, stage, round_label, index):
    notice = 15 if round_label == "النهائي" else 10
    kickoff = datetime.now(CAIRO_TZ) + timedelta(minutes=notice + (index * 15))
    return {"id": len(state.all_fixtures) + 1, "p1_id": p1_id, "p2_id": p2_id, "stage": stage, "round_label": round_label, "kickoff": kickoff, "status": "scheduled", "score": None, "winner_id": None}

def start_fixture_tasks(state, fixtures):
    state.current_fixtures = fixtures
    state.all_fixtures.extend(fixtures)
    state.stage_advancing = False
    for fix in fixtures:
        t = asyncio.create_task(run_tournament_fixture(state, fix))
        state.tasks.append(t)

async def create_league_round(state):
    state.phase = "league"
    state.stage_label = f"مرحلة الدوري — الجولة {state.league_round}/{state.league_rounds}"
    parts = tournament_table_rows(state)
    ids = [p["member"].id for p in parts]
    unpaired = ids[:]
    random.shuffle(unpaired)
    if len(unpaired) % 2:
        bye = unpaired.pop()
        state.participants[bye]["table"]["points"] += 3
        state.participants[bye]["table"]["won"] += 1
        state.participants[bye]["table"]["played"] += 1
    pairs = []
    while unpaired:
        p1 = unpaired.pop(0)
        p2 = unpaired.pop(0)
        pairs.append((p1, p2))
    fixtures = [new_tournament_fixture(state, p1, p2, "league", state.stage_label, i) for i, (p1, p2) in enumerate(pairs)]
    start_fixture_tasks(state, fixtures)
    await state.channel.send(embed=discord.Embed(title=f"📅 {state.stage_label}", description=f"تم تحديد **{len(fixtures)} مباراة**. إشعار كل مباراة يبدأ قبلها بـ 10 دقائق.", color=discord.Color.blue()))

async def create_knockout_stage(state, participant_ids, first=False):
    ids = list(participant_ids)
    if first:
        random.shuffle(ids)
    if len(ids) <= 1:
        await finish_tournament(state, ids[0] if ids else None)
        return
    lbls = {32: "دور 32", 16: "دور 16", 8: "ربع النهائي", 4: "نصف النهائي", 2: "النهائي"}
    rlbl = lbls.get(len(ids), f"دور {len(ids)}")
    state.phase = "knockout"
    state.knockout_round += 1
    state.stage_label = rlbl
    fixtures = [new_tournament_fixture(state, ids[i], ids[i+1], "knockout", rlbl, i//2) for i in range(0, len(ids)-1, 2)]
    start_fixture_tasks(state, fixtures)
    await state.channel.send(embed=discord.Embed(title=f"🏆 بدأت مواجهات {rlbl}", description=f"تم تحديد **{len(fixtures)} مباراة إقصائية**. استخدم `#دور` لمتابعة الشجرة والمباريات.", color=discord.Color.gold()))

def make_match_reminder_embed(state, fixture):
    p1 = state.participants[fixture["p1_id"]]
    p2 = state.participants[fixture["p2_id"]]
    ktxt = fixture["kickoff"].strftime("%A %d %B — %I:%M %p")
    if fixture["round_label"] == "النهائي":
        embed = discord.Embed(title="🏆 ⚽ نهائي المكار — مواجهة حسم اللقب ⚽ 🏆", description=f"**موعد انطلاق النهائي:** {ktxt} بتوقيت القاهرة.\nالمباراة الكبرى لحسم اللقب! فُتحت الآن التشكيلات والتكتيكات والمتجر للطرفين.", color=discord.Color.gold())
        embed.add_field(name=f"🔵 {p1['club']['name']}", value=f"المدرب: {p1['member'].mention}\nقوة الفريق: ⭐ {p1['club']['rating']}", inline=True)
        embed.add_field(name="⚔️ VS ⚔️", value="🏆 **نهائي المكار** 🏆", inline=True)
        embed.add_field(name=f"🔴 {p2['club']['name']}", value=f"المدرب: {p2['member'].mention}\nقوة الفريق: ⭐ {p2['club']['rating']}", inline=True)
        embed.set_image(url=TROPHY_IMAGE_URL)
        return embed
    embed = discord.Embed(
        title=f"⚽ {fixture['round_label']} — موعد مباراتك القادمة",
        description=f"**{p1['club']['name']}** ({p1['member'].display_name})\n**ضد**\n**{p2['club']['name']}** ({p2['member'].display_name})\n\n⏱️ **موعد الانطلاق:** {ktxt} بتوقيت القاهرة.\nاضغط على **[🧩 التشكيلة والمتجر والتكتيك]** بالأسفل لضبط خطتك واختيار المتخصصين والتبديل من المتجر.",
        color=discord.Color.blue()
    )
    return embed

async def run_tournament_fixture(state, fixture):
    notice = 15 if fixture["round_label"] == "النهائي" else 10
    delay = max(0, (fixture["kickoff"] - timedelta(minutes=notice) - datetime.now(CAIRO_TZ)).total_seconds())
    await asyncio.sleep(delay)
    p1 = state.participants[fixture["p1_id"]]["member"]
    p2 = state.participants[fixture["p2_id"]]["member"]
    setup_view = View(timeout=max(60, notice * 60))
    setup_btn = Button(label="🧩 التشكيلة والمتجر والتكتيك", emoji="⚙️", style=discord.ButtonStyle.primary)
    async def open_setup_cb(interaction):
        if interaction.user.id not in (fixture["p1_id"], fixture["p2_id"]):
            await interaction.response.send_message("إعداد المباراة متاح للمدربين فقط.", ephemeral=True)
            return
        await interaction.response.send_message(embed=make_tournament_setup_embed(state, interaction.user.id), view=PlayerMatchSetupView(state, interaction.user.id), ephemeral=True)
    setup_btn.callback = open_setup_cb
    setup_view.add_item(setup_btn)
    await state.channel.send(content=f"{p1.mention} {p2.mention}", embed=make_match_reminder_embed(state, fixture), view=setup_view, allowed_mentions=discord.AllowedMentions(users=[p1, p2]))
    rem = max(0, (fixture["kickoff"] - datetime.now(CAIRO_TZ)).total_seconds())
    await asyncio.sleep(rem)
    fixture["status"] = "live"
    session = build_tournament_match_session(state, fixture)
    await start_live_match(session)

def build_tournament_match_session(state, fixture):
    p1 = state.participants[fixture["p1_id"]]
    p2 = state.participants[fixture["p2_id"]]
    session = MatchSession(p1["member"], p2["member"], state.channel)
    session.tournament = state
    session.fixture = fixture
    session.p1_form = p1["formation"]
    session.p2_form = p2["formation"]
    session.p1_setup = p1["setup"]
    session.p2_setup = p2["setup"]
    for part, target in [(p1, session.p1_squad), (p2, session.p2_squad)]:
        active_slots = FORMATIONS[part["formation"]]
        bench = [c for c in part["roster"].values() if c not in part["lineup"].values()]
        for slot in active_slots:
            card = part["lineup"].get(slot, part["roster"][slot])
            ckey = player_key(card)
            if part["suspensions"].get(ckey, 0) > 0:
                sub = next((b for b in bench if "".join(x for x in b.get("slot", "") if not x.isdigit()) == "".join(x for x in slot if not x.isdigit()) and part["suspensions"].get(player_key(b), 0) == 0), None)
                if sub: card = sub
            target[slot] = card
    return session

async def advance_tournament_if_ready(state):
    if state.stage_advancing or not state.current_fixtures:
        return
    if not all(f["status"] == "completed" for f in state.current_fixtures):
        return
    state.stage_advancing = True
    if state.phase == "league":
        if state.league_round < state.league_rounds:
            state.league_round += 1
            state.stage_advancing = False
            await create_league_round(state)
            return
        qual = [p["member"].id for p in tournament_table_rows(state)[:16]]
        state.stage_advancing = False
        await state.channel.send("✅ انتهت مرحلة الدوري! تأهل أفضل 16 نادياً للأدوار الإقصائية.")
        await create_knockout_stage(state, qual, first=True)
        return
    winners = [f["winner_id"] for f in state.current_fixtures]
    if len(winners) <= 1:
        await finish_tournament(state, winners[0] if winners else None)
        return
    state.stage_advancing = False
    await create_knockout_stage(state, winners, first=False)

async def finalize_tournament_match(session, fixture, s1, s2, stats, motm):
    state = session.tournament
    fixture["status"] = "completed"
    fixture["score"] = (s1, s2)
    p1_id, p2_id = fixture["p1_id"], fixture["p2_id"]
    for side, uid in enumerate([p1_id, p2_id]):
        part = state.participants[uid]
        for sk in list(part["suspensions"]):
            part["suspensions"][sk] = max(0, part["suspensions"][sk] - 1)
            if part["suspensions"][sk] == 0:
                del part["suspensions"][sk]
        for pen in stats[side]["penalties"]:
            ckey = player_key(pen["player"])
            part["suspensions"][ckey] = 1 if pen["type"] == "red" else 2
        for c in (session.p1_squad.values() if side == 0 else session.p2_squad.values()):
            pe = stats[side]["player_events"].get(c["name"], {})
            pk = f"{uid}:{player_key(c)}"
            rec = state.player_ratings.setdefault(pk, {"name": c["name"], "club": part["club"]["name"], "owner_id": uid, "sum": 0.0, "matches": 0})
            rec["sum"] += pe.get("rating", 6.0)
            rec["matches"] += 1
            if pe.get("goals"):
                sc = state.scorers.setdefault(pk, {"name": c["name"], "club": part["club"]["name"], "owner_id": uid, "goals": 0, "card": c})
                sc["goals"] += pe["goals"]

    if fixture["stage"] == "league":
        for uid, scored, conceded in [(p1_id, s1, s2), (p2_id, s2, s1)]:
            tbl = state.participants[uid]["table"]
            tbl["played"] += 1; tbl["goals_for"] += scored; tbl["goals_against"] += conceded
            if scored > conceded: tbl["won"] += 1; tbl["points"] += 3
            elif scored == conceded: tbl["drawn"] += 1; tbl["points"] += 1
            else: tbl["lost"] += 1
        fixture["winner_id"] = p1_id if s1 > s2 else (p2_id if s2 > s1 else None)
    else:
        fixture["winner_id"] = p1_id if s1 > s2 else (p2_id if s2 > s1 else random.choice([p1_id, p2_id]))
        state.participants[fixture["winner_id"]]["wins"] += 1
    await advance_tournament_if_ready(state)

async def finish_tournament(state, winner_id):
    state.phase = "complete"
    state.stage_advancing = True
    if not winner_id:
        return
    state.champion_id = winner_id
    win = state.participants[winner_id]
    prof = get_profile(winner_id)
    prof["trophies"] += 1
    embed = discord.Embed(title="🏆 👑 بطل بطولة المكار الكبرى 👑 🏆", description=f"ألف مبروك للمدرب البطل **{win['member'].mention}**!\nقاد نادي **{win['club']['name']}** للتتويج بلقب دوري أبطال المكار!\n\n🏆 **عدد بطولاته الرسمية:** `{prof['trophies']}` بطولات.", color=discord.Color.gold())
    embed.set_thumbnail(url=win["member"].display_avatar.url)
    embed.set_image(url=TROPHY_IMAGE_URL)
    await state.channel.send(embed=embed)

def make_tournament_setup_embed(state, uid):
    part = state.participants[uid]
    setup = part["setup"]
    specs = setup["specialists"]
    spec_txt = "\n".join(f"• {r}: **{specs.get(r, 'لم يحدد')}**" for r in ["قائد الفريق", "ضربات الجزاء", "الركلات الحرة", "الركنيات"])
    susp_txt = "\n".join(f"• {k}: موقوف لـ **{v}** مباراة" for k, v in part["suspensions"].items()) or "لا توجد غيابات"
    embed = discord.Embed(title=f"🧩 إعدادات {part['club']['name']}", description=f"**الخطة:** {part['formation']} | **الأسلوب:** {setup['style']} | **التكتيك:** {setup['tactic']}\n\n**المتخصصون:**\n{spec_txt}\n\n🚨 **الغيابات الحالية:**\n{susp_txt}\n\n💰 **رصيدك:** {get_profile(uid)['coins']:,} كوينز", color=discord.Color.blue())
    return embed

class PlayerMatchSetupView(View):
    def __init__(self, state, uid):
        super().__init__(timeout=600)
        self.state = state
        self.uid = uid
        part = state.participants[uid]
        f_opts = [discord.SelectOption(label=f, value=f, default=f == part["formation"]) for f in FORMATIONS]
        f_sel = Select(placeholder="اختر الخطة", options=f_opts, row=0)
        f_sel.callback = self.make_form_cb()
        self.add_item(f_sel)
        strat_opts = []
        for sty in ["دفاعي", "متوازن", "هجومي"]:
            for tac in ["هجوم الأطراف", "تسديد عن بعد", "تمريرات", "مرتدة"]:
                strat_opts.append(discord.SelectOption(label=f"{sty} — {tac}", value=f"{sty}|{tac}", default=(sty == part["setup"]["style"] and tac == part["setup"]["tactic"])))
        strat_sel = Select(placeholder="اختر أسلوب اللعب والتكتيك", options=strat_opts[:25], row=1)
        strat_sel.callback = self.make_strat_cb()
        self.add_item(strat_sel)
        role_sel = Select(placeholder="اختر دور المتخصص", options=[discord.SelectOption(label=r, value=r) for r in ["قائد الفريق", "ضربات الجزاء", "الركلات الحرة", "الركنيات"]], row=2)
        role_sel.callback = self.make_role_cb()
        self.add_item(role_sel)
        slots = FORMATIONS[part["formation"]]
        p_opts = [discord.SelectOption(label=part["lineup"][s]["name"][:100], value=s, description=f"{s} | تقييم {part['lineup'][s]['rating']}") for s in slots]
        p_sel = Select(placeholder="عيّن لاعباً للدور المحدد", options=p_opts[:25], row=3)
        p_sel.callback = self.make_spec_player_cb()
        self.add_item(p_sel)

    def make_form_cb(self):
        async def cb(interaction: discord.Interaction):
            part = self.state.participants[self.uid]
            part["formation"] = interaction.data["values"][0]
            part["lineup"] = {s: part["lineup"].get(s, part["roster"][s]) for s in FORMATIONS[part["formation"]]}
            await interaction.response.edit_message(embed=make_tournament_setup_embed(self.state, self.uid), view=PlayerMatchSetupView(self.state, self.uid))
        return cb

    def make_strat_cb(self):
        async def cb(interaction: discord.Interaction):
            sty, tac = interaction.data["values"][0].split("|", 1)
            self.state.participants[self.uid]["setup"]["style"] = sty
            self.state.participants[self.uid]["setup"]["tactic"] = tac
            await interaction.response.edit_message(embed=make_tournament_setup_embed(self.state, self.uid), view=self)
        return cb

    def make_role_cb(self):
        async def cb(interaction: discord.Interaction):
            self.state.participants[self.uid]["setup"]["pending_role"] = interaction.data["values"][0]
            await interaction.response.send_message(f"تم اختيار **{interaction.data['values'][0]}**. اختر الآن اللاعب من القائمة التالية.", ephemeral=True)
        return cb

    def make_spec_player_cb(self):
        async def cb(interaction: discord.Interaction):
            part = self.state.participants[self.uid]
            role = part["setup"].get("pending_role", "قائد الفريق")
            slot = interaction.data["values"][0]
            part["setup"]["specialists"][role] = part["lineup"][slot]["name"]
            await interaction.response.edit_message(embed=make_tournament_setup_embed(self.state, self.uid), view=self)
        return cb

    @discord.ui.button(label="فتح متجر البطولة", emoji="🛒", style=discord.ButtonStyle.success, row=4)
    async def open_shop(self, interaction: discord.Interaction, button: Button):
        part = self.state.participants[self.uid]
        used = {player_key(c) for c in part["lineup"].values()}
        options = []
        for slot in FORMATIONS[part["formation"]]:
            pos = "".join(c for c in slot if not c.isdigit())
            for card in CARDS_DATABASE.get(pos, []):
                if player_key(card) not in used:
                    options.append((slot, card, shop_price(card)))
        options.sort(key=lambda x: (x[2], -x[1]["rating"]))
        if not options:
            await interaction.response.send_message("لا توجد بطاقات بديلة متاحة حالياً.", ephemeral=True)
            return
        shop_view = View(timeout=300)
        sel_opts = [discord.SelectOption(label=f"{card['name']} ← {slot}"[:100], description=f"⭐ {card['rating']} | السعر {pr:,} كوينز", value=str(i)) for i, (slot, card, pr) in enumerate(options[:25])]
        s_sel = Select(placeholder="اختر لاعباً لشرائه واستبداله بالمركز", options=sel_opts)
        async def buy_cb(i_act):
            s_idx = int(i_act.data["values"][0])
            sl, c, pr = options[s_idx]
            prof = get_profile(self.uid)
            if prof["coins"] < pr:
                await i_act.response.send_message(f"رصيدك {prof['coins']:,} كوينز وسعر اللاعب {pr:,}.", ephemeral=True)
                return
            prof["coins"] -= pr
            part["lineup"][sl] = c.copy()
            await i_act.response.edit_message(content=f"✅ اشتريت **{c['name']}** واستبدلته في مركز `{sl}` مقابل **{pr:,} كوينز**.", embed=None, view=None)
        s_sel.callback = buy_cb
        shop_view.add_item(s_sel)
        await interaction.response.send_message(embed=discord.Embed(title="🛒 متجر البطولة", description=f"رصيدك: **{get_profile(self.uid)['coins']:,} كوينز**.\nاختر لاعباً لشرائه بالكوينز واستبداله بلاعب في تشكيلتك:", color=discord.Color.gold()), view=shop_view, ephemeral=True)

# ---------------------------------------------------------
# 7. أوامر المتابعة: #جدول و #دور
# ---------------------------------------------------------
def make_tournament_table_embed(state, mode="table", page=0):
    if mode == "table":
        rows = tournament_table_rows(state)
        first = page * 18
        vis = rows[first:first+18]
        lines = ["```text", f" #  {'النادي':<16} لعب  ف  ت  خ   له:عليه  نقاط", "───────────────────────────────────────────────"]
        for idx, p in enumerate(vis, start=first+1):
            tbl = p["table"]
            cn = (p["club"]["name"] if p["club"] else "—")[:15]
            lines.append(f"{idx:>2}. {cn:<16} {tbl['played']:>2} {tbl['won']:>2} {tbl['drawn']:>2} {tbl['lost']:>2}  {tbl['goals_for']:>2}:{tbl['goals_against']:<2}  {tbl['points']:>3}")
        lines.append("```")
        embed = discord.Embed(title=f"📊 جدول ترتيب دوري أبطال المكار — {state.stage_label}", description=f"مرحلة البطولة: **{state.phase}** | إجمالي الأندية: **{len(rows)}**", color=discord.Color.blue())
        embed.add_field(name="قائمة الترتيب", value="\n".join(lines), inline=False)
        embed.set_image(url=TABLE_DESIGN_IMAGE_URL)
        embed.set_footer(text=f"الصفحة {page+1}/2 • استخدم الأزرار بالأسفل للتنقل بين الصفحات والهدافين والتقييمات")
        return embed

    if mode == "scorers":
        scorers = sorted(state.scorers.values(), key=lambda s: (s["goals"], s["name"]), reverse=True)
        embed = discord.Embed(title="⚽ قائمة هدافي بطولة المكار", color=discord.Color.gold())
        if scorers:
            feat = scorers[0]
            embed.description = f"# 🥇 المتصدر: {feat['name']}\n🏟️ **النادي:** {feat['club']}\n⚽ **الأهداف:** `{feat['goals']}` أهداف"
            img_url = PLAYER_IMAGE_CACHE.get(player_image_title(feat["card"]).casefold())
            if img_url:
                embed.set_image(url=img_url)
            else:
                embed.set_image(url=SCORERS_DESIGN_IMAGE_URL)
            lines = [f"**{r}.** {s['name']} — {s['club']} ➔ ⚽ **{s['goals']}**" for r, s in enumerate(scorers[1:10], 2)]
            embed.add_field(name="بقية قائمة الهدافين", value="\n".join(lines) or "لا يوجد هدافون آخرون.", inline=False)
        else:
            embed.description = "لم تُسجل أي أهداف في البطولة حتى الآن."
            embed.set_image(url=SCORERS_DESIGN_IMAGE_URL)
        return embed

    ratings = sorted(state.player_ratings.values(), key=lambda r: (r["sum"]/max(1, r["matches"]), r["matches"]), reverse=True)
    embed = discord.Embed(title="⭐ أفضل تقييمات لاعبي البطولة (OSM Rating)", description="متوسط تقييم كل لاعب من 10 في المباريات:", color=discord.Color.purple())
    lines = [f"**{rk:>2}.** {r['name']} — {r['club']} ➔ ⭐ **{r['sum']/max(1, r['matches']):.1f}/10** ({r['matches']} م)" for rk, r in enumerate(ratings[:18], 1)]
    embed.add_field(name="أعلى التقييمات", value="\n".join(lines) or "لا توجد تقييمات حتى الآن.", inline=False)
    embed.set_image(url=RATINGS_DESIGN_IMAGE_URL)
    return embed

class TournamentTableView(View):
    def __init__(self, state):
        super().__init__(timeout=1800)
        self.state = state
        self.mode = "table"
        self.page = 0

    async def update(self, interaction, mode=None, page=None):
        if mode:
            self.mode = mode
        if page is not None:
            self.page = page
        await interaction.response.edit_message(embed=make_tournament_table_embed(self.state, self.mode, self.page), view=self)

    @discord.ui.button(label="📊 الترتيب (1–18)", style=discord.ButtonStyle.primary, row=0)
    async def p1(self, interaction: discord.Interaction, button: Button):
        await self.update(interaction, "table", 0)

    @discord.ui.button(label="📊 الترتيب (19–36)", style=discord.ButtonStyle.primary, row=0)
    async def p2(self, interaction: discord.Interaction, button: Button):
        await self.update(interaction, "table", 1)

    @discord.ui.button(label="⚽ قائمة الهدافين", style=discord.ButtonStyle.secondary, row=1)
    async def sc(self, interaction: discord.Interaction, button: Button):
        await self.update(interaction, "scorers")

    @discord.ui.button(label="⭐ تقييمات اللاعبين", style=discord.ButtonStyle.secondary, row=1)
    async def rt(self, interaction: discord.Interaction, button: Button):
        await self.update(interaction, "ratings")

def make_bracket_embed(state):
    embed = discord.Embed(title=f"🏆 الأدوار الإقصائية لبطولة المكار — {state.stage_label}", description=f"المرحلة الحالية: **{state.phase}**", color=discord.Color.gold())
    if state.phase == "complete":
        champ = state.participants.get(getattr(state, "champion_id", None))
        if champ:
            embed.description = f"👑 **بطل البطولة المتوج:** {champ['member'].mention} — نادي **{champ['club']['name']}**!"
        embed.set_image(url=TROPHY_IMAGE_URL)
        return embed
    if not state.current_fixtures:
        embed.description += "\nلا توجد مواجهات إقصائية محددة حالياً."
        embed.set_image(url=KNOCKOUT_BRACKET_IMAGE_URL)
        return embed
    lines = []
    for f in state.current_fixtures:
        p1 = state.participants[f["p1_id"]]
        p2 = state.participants[f["p2_id"]]
        sc = f" — `{f['score'][0]}` : `{f['score'][1]}`" if f["score"] else ""
        st = f"✅ تأهل: **{state.participants[f['winner_id']]['club']['name']}**" if f["status"] == "completed" else f"⏱️ موعد المباراة: {f['kickoff'].strftime('%I:%M %p')}"
        lines.append(f"⚽ **{p1['club']['name']}** ({p1['member'].display_name}) 🆚 **{p2['club']['name']}** ({p2['member'].display_name}){sc}\n   *{st}*")
    embed.description += "\n\n" + "\n\n".join(lines)
    embed.set_image(url=KNOCKOUT_BRACKET_IMAGE_URL)
    return embed

@bot.command(name="champ")
async def champ_command(ctx, signup_minutes: int = DEFAULT_SIGNUP_MINUTES):
    global active_tournament
    if ctx.author.id != TOURNAMENT_OWNER_ID:
        await ctx.send("❌ الأمر `#champ` مخصص حصرياً لصاحب البوت (`sahlap_makar`).")
        return
    if not MIN_SIGNUP_MINUTES <= signup_minutes <= MAX_SIGNUP_MINUTES:
        await ctx.send(
            f"❌ مدة التسجيل يجب أن تكون من {MIN_SIGNUP_MINUTES} إلى "
            f"{MAX_SIGNUP_MINUTES} دقيقة. مثال: `#champ 15`."
        )
        return

    if active_tournament and active_tournament.phase == "signup":
        state = active_tournament
        state.signup_minutes = signup_minutes
        state.signup_deadline = time.monotonic() + signup_minutes * 60
        state.entry_closed = False
        state.signup_view = TournamentSignupView(state)
        try:
            if state.message:
                await state.message.edit(
                    embed=tournament_signup_embed(state),
                    view=state.signup_view,
                )
            else:
                state.message = await ctx.send(
                    embed=tournament_signup_embed(state),
                    view=state.signup_view,
                )
        except discord.HTTPException:
            logger.exception("Could not update the tournament signup message.")
            await ctx.send("⚠️ تعذر تحديث رسالة التسجيل. حاول مرة أخرى.")
            return
        schedule_tournament_signup_close(state)
        await ctx.send(
            f"✅ تم ضبط مدة التسجيل إلى **{signup_minutes} دقيقة**. "
            "يمكنك استخدام الأمر نفسه لتغييرها مرة أخرى."
        )
        return

    if active_tournament and active_tournament.phase not in ("complete", "error"):
        await ctx.send("⚠️ هناك بطولة قائمة بالفعل! استخدم `#جدول` أو `#دور` لمتابعتها.")
        return
    state = TournamentState(ctx.author.id, ctx.channel, signup_minutes)
    view = TournamentSignupView(state)
    state.signup_view = view
    state.message = await ctx.send(embed=tournament_signup_embed(state), view=view)
    active_tournament = state
    schedule_tournament_signup_close(state)

@bot.command(name="جدول", aliases=["table", "ترتيب"])
async def tournament_table_command(ctx):
    if not active_tournament:
        await ctx.send("❌ لا توجد بطولة حالية. يبدأها صاحب البوت باستخدام الأمر `#champ`.")
        return
    await ctx.send(embed=make_tournament_table_embed(active_tournament), view=TournamentTableView(active_tournament))

@bot.command(name="دور", aliases=["bracket", "الادوار"])
async def tournament_round_command(ctx):
    if not active_tournament:
        await ctx.send("❌ لا توجد بطولة حالية لعرض أدوارها.")
        return
    await ctx.send(embed=make_bracket_embed(active_tournament))

# ---------------------------------------------------------
# 8. تشغيل البوت
# ---------------------------------------------------------
def main():
    token = os.environ.get("DISCORD_BOT_TOKEN") or os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN is missing. Please set your bot token.")
    bot.run(token)

if __name__ == "__main__":
    main()