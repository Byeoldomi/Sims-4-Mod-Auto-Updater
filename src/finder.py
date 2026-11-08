"""심즈 4 모드 파일(.package, .ts4script) 내부의 바이너리/아카이브 메타데이터(LlamaLogic 매니페스트,
XML Tuning 식별자, Python 바이트코드 내장 URL, 제작자 태그 등)를 직접 추출하고,
스마트 파일명/폴더명 분석 및 웹 검색 스니펫 랭킹을 결합하여 실제 공식 배포 페이지를 찾는 엔진입니다.
"""

import html
import re
import struct
import urllib.parse
import zipfile
import zlib
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
import requests
from bs4 import BeautifulSoup

# ==============================================================================
# 1. 핵심 코어 모드 카탈로그 (전용 업데이터 및 대표 통합 모드)
# ==============================================================================
KNOWN_CATALOG = [
    {
        "keywords": ["mc_woohoo", "mcwoohoo", "mc woohoo"],
        "name": "MC Woohoo (MCCC Module)",
        "creator": "Deaderpool",
        "mod_title": "MC Woohoo",
        "links": [
            ("공식 다운로드 페이지 (MC Woohoo MediaFire)", "Deaderpool MCCC Downloads (MC Woohoo)", "https://deaderpool-mccc.com/downloads.html"),
            ("Patreon", "Deaderpool Patreon", "https://www.patreon.com/mccc_deaderpool")
        ]
    },
    {
        "keywords": [
            "mccc", "mc command center", "mc_cmd_center", "deaderpool",
            "mc_career", "mc_cas", "mc_cheats", "mc_cleaner", "mc_clubs",
            "mc_control", "mc_dresser", "mc_gedcom", "mc_occult",
            "mc_population", "mc_pregnancy", "mc_settings", "mc_tuner",
        ],
        "name": "MC Command Center (MCCC)",
        "creator": "Deaderpool",
        "mod_title": "MC Command Center (MCCC)",
        "links": [
            ("공식 다운로드 페이지", "Deaderpool MCCC Downloads", "https://deaderpool-mccc.com/downloads.html"),
            ("Patreon", "Deaderpool Patreon", "https://www.patreon.com/mccc_deaderpool")
        ]
    },
    {
        "keywords": ["turbodriver_wickedwhims", "wickedwhims_scripts", "wickedwhims_tuning"],
        "name": "WickedWhims",
        "creator": "TURBODRIVER",
        "mod_title": "WickedWhims",
        "links": [
            ("Wicked.cc (공식)", "WickedWhims - WickedCC | TURBODRIVER", "https://wicked.cc/mods/TURBODRIVER/wickedwhims"),
            ("Itch.io", "TURBODRIVER Itch.io", "https://turbodriver.itch.io/wickedwhims")
        ]
    },
    {
        "keywords": ["wonderfulwhims", "turbodriver_wonderfulwhims"],
        "name": "WonderfulWhims",
        "links": [
            ("공식 웹사이트", "WonderfulWhims Official", "https://wonderfulwhims.com/"),
            ("Itch.io", "TURBODRIVER Itch.io", "https://turbodriver.itch.io/wonderfulwhims")
        ]
    },
    {
        "keywords": ["more_cas_columns", "more columns in cas"],
        "name": "More Columns in CAS",
        "creator": "Weerbesu",
        "mod_title": "More Columns in CAS",
        "links": [
            ("Patreon (공식)", "More Columns in CAS | Weerbesu", "https://www.patreon.com/weerbesu/posts/more-columns-in-27751117"),
            ("Patreon 채널", "Weerbesu Official Patreon", "https://www.patreon.com/weerbesu")
        ]
    },
    {
        "keywords": ["ui_cheats_extension", "ui cheats extension"],
        "name": "UI Cheats Extension",
        "creator": "Weerbesu",
        "mod_title": "UI Cheats Extension",
        "links": [
            ("Patreon (공식)", "UI Cheats Extension | Weerbesu", "https://www.patreon.com/weerbesu/posts/ui-cheats-v1-59-26240068"),
            ("Patreon 채널", "Weerbesu Official Patreon", "https://www.patreon.com/weerbesu")
        ]
    },
    {
        "keywords": ["xoox", "icon cas organizer", "xoox_studio"],
        "name": "[XOOX] Icon CAS Organizer",
        "creator": "XOOX",
        "mod_title": "Icon CAS Organizer",
        "links": [
            ("Patreon (공식)", "[XOOX] Icon CAS Organizer v1.1", "https://www.patreon.com/XOOX_studio/posts/icon-cas-v1-1-171172167"),
            ("Patreon 채널", "XOOX Studio Patreon", "https://www.patreon.com/XOOX_studio")
        ]
    },
    {
        "keywords": ["kiss-n-grind", "kiss_n_grind", "kiss n grind"],
        "name": "[UTOPYA] Kiss-n-Grind Mod",
        "creator": "UTOPYA",
        "mod_title": "Kiss-n-Grind Mod",
        "links": [
            ("Patreon (공식)", "Kiss-n-Grind 1.9.9 | Provocative Grind | UTOPYA", "https://www.patreon.com/UTOPYA_cc/posts/kiss-n-grind-1-9-131081267"),
            ("Patreon 채널", "UTOPYA Official Patreon", "https://www.patreon.com/UTOPYA_cc")
        ]
    },
    {
        "keywords": ["passionate gifts", "passionate_gifts", "passionategifts", "passionate gift"],
        "name": "[UTOPYA] Passionate Gifts MOD",
        "creator": "UTOPYA",
        "mod_title": "Passionate Gifts MOD",
        "version": "0.8",
        "links": [
            ("Patreon (공식)", "Passionate Gift 0.8 | UTOPYA", "https://www.patreon.com/UTOPYA_cc/posts/passionate-gift-151330104"),
            ("Patreon 채널", "UTOPYA Official Patreon", "https://www.patreon.com/UTOPYA_cc")
        ]
    },
    {
        "keywords": ["sims4_aichat_byok_addon", "aichat_byok", "byok_addon", "sims 4 ai chat byok addon"],
        "name": "Sims 4 AI Chat BYOK Addon",
        "creator": "익명",
        "mod_title": "Sims 4 AI Chat BYOK Addon",
        "links": [
            ("디시인사이드", "(26.11.01업뎃) AI Chat 애드온 BYOK 배포", "https://gall.dcinside.com/mgallery/board/view/?id=sims&no=281508")
        ]
    },
    {
        "keywords": ["sims4_ai_chat", "sims 4 ai chat", "sims4aichat"],
        "name": "Sims 4 AI Chat",
        "creator": "VirtualConsciousnessLabs",
        "mod_title": "Sims 4 AI Chat",
        "links": [
            ("Patreon (공식)", "Sims 4 AI Chat v2.3.4 | Virtual Consciousness Labs", "https://www.patreon.com/VirtualConsciousnessLabs/posts/sims-4-ai-chat-4-174642480"),
            ("Patreon 채널", "Virtual Consciousness Labs Official Patreon", "https://www.patreon.com/VirtualConsciousnessLabs")
        ]
    },
    {
        "keywords": ["cumshine", "spent_cumshine"],
        "name": "Cumshine",
        "creator": "Spent",
        "mod_title": "Cumshine",
        "links": [
            ("Wicked.cc (공식)", "Cumshine - WickedCC | Spent", "https://wicked.cc/mods/spent/cumshine/"),
            ("Patreon 채널", "Spent Official Patreon", "https://www.patreon.com/Spent")
        ]
    },
    {
        "keywords": ["fitnesscontrols", "fitness controls"],
        "name": "Fitness Controls",
        "creator": "roBurky",
        "mod_title": "Fitness Controls",
        "version": "2.0.12.0",
        "links": [
            ("Itch.io (공식)", "Fitness Controls | roBurky", "https://roburky.itch.io/sims4-fitness")
        ]
    },
    {
        "keywords": ["xmlinjector", "xml_injector", "scumbumbo"],
        "name": "XML Injector",
        "links": [
            ("공식 웹사이트", "Scumbumbo Mods XML Injector", "https://scumbumbomods.com/xml-injector"),
            ("CurseForge", "CurseForge XML Injector", "https://www.curseforge.com/sims4/mods/xml-injector")
        ]
    },
    {
        "keywords": ["lumpinou_rpo_collection", "rpo_collection_m"],
        "name": "Relationship & Pregnancy Overhaul (RPO Collection)",
        "creator": "Lumpinou",
        "mod_title": "Relationship & Pregnancy Overhaul (RPO Collection)",
        "links": [
            ("Patreon (공식)", "[Mod] Relationship & Pregnancy Overhaul, ALL-FILES-IN-ONE-CLICK - Sims 4", "https://www.patreon.com/lumpinou/posts/mod-relationship-75983577")
        ]
    },
    {
        "keywords": ["lumpinou_toolbox", "lumpinous_toolbox", "lumpinou's toolbox"],
        "name": "Lumpinou's Toolbox",
        "creator": "Lumpinou",
        "mod_title": "Lumpinou's Toolbox (Script Library)",
        "links": [
            ("Patreon (공식)", "[Mod] Lumpinou's Toolbox - Script Library-Mod - Sims 4", "https://www.patreon.com/lumpinou/posts/mod-lumpinous-4-86658397")
        ]
    },
    {
        "keywords": ["contextualsocialinteractions", "contextual_social_interactions", "lumpinou_contextualsocialinteractions"],
        "name": "Lumpinou_ContextualSocialInteractions",
        "creator": "Lumpinou",
        "mod_title": "Contextual Social Interactions",
        "links": [
            ("Patreon (공식)", "[Mod] Contextual Social Interactions - Sims 4", "https://www.patreon.com/lumpinou/posts/mod-contextual-4-40485793")
        ]
    },
    {
        "keywords": ["talentsweaknesses", "talents_weaknesses", "talentsandweaknesses"],
        "name": "Lumpinou Talents & Weaknesses",
        "creator": "Lumpinou",
        "mod_title": "Talents & Weaknesses",
        "links": [
            ("Patreon (공식)", "[Mod] Talents & Weaknesses | Lumpinou", "https://www.patreon.com/lumpinou/posts/mod-talents-51561971")
        ]
    },
    {
        "keywords": ["lumpinou_moodpackmod", "moodpackmod", "mood pack mod"],
        "name": "Lumpinou_MoodPackMod",
        "creator": "Lumpinou",
        "mod_title": "Mood Pack Mod",
        "links": [
            ("Patreon (공식)", "[Mod] Lumpinou's Mood Pack Mod | Lumpinou", "https://www.patreon.com/lumpinou/posts/mod-lumpinous-43759541"),
            ("CurseForge", "Mood Pack : New Moods for your Sims - The Sims 4 Mods", "https://www.curseforge.com/sims4/mods/mood-pack")
        ]
    },
    {
        "keywords": ["lumpinou_roadtoromance", "roadtoromance", "road to romance"],
        "name": "Lumpinou_RoadToRomance",
        "creator": "Lumpinou",
        "mod_title": "Road To Romance",
        "links": [
            ("Patreon (공식)", "[Mod] Road to Romance - Lovestruck Edition - OR - BG Ver | Lumpinou", "https://www.patreon.com/lumpinou/posts/mod-road-to-or-4-39785932")
        ]
    },
    {
        "keywords": ["restrictedromance_bypolarbearsims", "restrictedromance"],
        "name": "RestrictedRomance By Polarbearsims",
        "creator": "Polarbearsims",
        "mod_title": "RestrictedRomance By Polarbearsims",
        "links": [
            ("ModTheSims", "Have Some Personality Please! | Polarbearsims", "https://modthesims.info/d/594573/have-some-personality-please.html")
        ]
    },
    {
        "keywords": ["sims_learninfo_bypolarbearsims", "sims_learninfo"],
        "name": "Sims LearnInfo By Polarbearsims",
        "creator": "Polarbearsims",
        "mod_title": "Sims LearnInfo By Polarbearsims",
        "links": [
            ("ModTheSims", "Have Some Personality Please! | Polarbearsims", "https://modthesims.info/d/594573/have-some-personality-please.html")
        ]
    },
    {
        "keywords": ["personality_please", "personalityplease"],
        "name": "Personality Please! By Polarbearsims",
        "creator": "Polarbearsims",
        "mod_title": "Personality Please! By Polarbearsims",
        "links": [
            ("ModTheSims", "Have Some Personality Please! | Polarbearsims", "https://modthesims.info/d/594573/have-some-personality-please.html")
        ]
    },
    {
        "keywords": ["disl_to_nooutfitchangepromoted", "nooutfitchangepromoted", "no outfit change when promoted"],
        "name": "Townies & Outfits - No Outfit Change When Promoted",
        "creator": "Down-In-Simsland",
        "mod_title": "Townies & Outfits - No Outfit Change When Promoted",
        "links": [
            ("SimFileShare", "DISL_TO_NoOutfitChangePromoted | Down-In-Simsland", "https://www.simfileshare.net/download/5174540/")
        ]
    },
    {
        "keywords": ["kallixer_removesimsfromconversation", "removesimsfromconversation"],
        "name": "Remove Sims From Conversation",
        "creator": "Kallixer",
        "mod_title": "Remove Sims From Conversation",
        "links": [
            ("CurseForge (공식)", "Remove Sims from Conversation | Kallixer", "https://www.curseforge.com/sims4/mods/remove-sims-from-conversation")
        ]
    },
    {
        "keywords": ["lotharihoe_simspawnoverhaul", "simspawnoverhaul"],
        "name": "Sim Spawn Overhaul",
        "creator": "lotharihoe",
        "mod_title": "Sim Spawn Overhaul",
        "version": "3.0.3",
        "links": [
            ("CurseForge (공식)", "Sim Spawn Overhaul | lotharihoe", "https://www.curseforge.com/sims4/mods/sim-spawn-overhaul")
        ]
    },
    {
        "keywords": ["cas tuning add-on", "cas tuning base", "controlled position mod"],
        "name": "Controlled Position Mod (CAS Tuning)",
        "creator": "NORTHERN SIBERIA WINDS",
        "mod_title": "",
        "links": [
            ("Patreon (공식)", "CONTROLLED POSITION MOD | NORTHERN SIBERIA WINDS", "https://www.patreon.com/northernsiberiawinds/posts/controlled-mod-103628223")
        ]
    },
    {
        "keywords": ["simmattically_family_loadingscreen", "family_loadingscreen"],
        "name": "Family Loading Screen",
        "creator": "SimMattically",
        "mod_title": "Family Loading Screen",
        "links": [
            ("Patreon (공식)", "Family Loading Screen | The Sims 4 | SimMattically", "https://www.patreon.com/SimMattically/posts/family-loading-4-150916961")
        ]
    },
    {
        "keywords": ["simmattically_refreshedmainmenu_standalone_homeview", "refreshedmainmenu_standalone_homeview"],
        "name": "Refreshed Main Menu: Homeview",
        "creator": "SimMattically",
        "mod_title": "Refreshed Main Menu: Homeview",
        "links": [
            ("Patreon (공식)", "Refreshed Main Menu: Homeview | SimMattically", "https://www.patreon.com/SimMattically/posts/refreshed-main-126640866")
        ]
    },
    {
        "keywords": ["nv_sm_ui_mood", "nv_sm_ui_mood_01_adult_all", "nv_sm_ui_mood_01_children_all"],
        "name": "NV_SM_UI_Mood",
        "creator": "NV Games",
        "mod_title": "",
        "links": [
            ("Patreon (공식)", "SMALL MODS | NV . Games", "https://www.patreon.com/nv_games/posts/small-mods-69121597")
        ]
    },
    {
        "keywords": ["sims4me_lessfacialoveraction", "lessfacialoveraction", "less facial overaction"],
        "name": "Less Facial Overaction",
        "creator": "Bienchen (sims4me)",
        "mod_title": "Less Facial Overaction",
        "links": [
            ("CurseForge (공식)", "Less Facial Overaction | Bienchen (sims4me)", "https://www.curseforge.com/sims4/mods/less-facial-overaction")
        ]
    },
    {
        "keywords": ["friedgil", "friedgil_random_name", "random_name_korean_translation"],
        "name": "FriedGil_Random_Name_Korean_Translation_Compilation",
        "creator": "FriedGil",
        "mod_title": "Random Name Korean Translation Compilation",
        "release_notes": "네이버 블로그 참고 (무료)",
        "links": [
            ("네이버 블로그 참고 (무료)", "FriedGil 랜덤 이름 한글화 배포 포스트", "https://blog.naver.com/friedg/221810746795")
        ]
    },
    {
        "keywords": ["wamtik", "바람별", "바람별한글화"],
        "name": "바람별 한글화 모드",
        "links": [
            ("Patreon (선배포)", "바람별 ZIMS 통합 한글화 (Patreon)", "https://www.patreon.com/cw/wwindystarZIMS"),
            ("Postype", "바람별의 포스타입 (Postype)", "https://www.postype.com/@wwwindystar"),
            ("네이버 블로그", "바람별의 심즈 4 네이버 블로그", "https://blog.naver.com/wwwindystar")
        ]
    },
]

# 신뢰할 수 있는 심즈 4 배포 도메인 목록
RELIABLE_DOMAINS = [
    ("curseforge.com", "CurseForge"),
    ("patreon.com", "Patreon"),
    ("itch.io", "Itch.io"),
    ("modthesims.info", "ModTheSims"),
    ("simfileshare.net", "SimFileShare"),
    ("tumblr.com", "Tumblr"),
    ("postype.com", "포스타입 (Postype)"),
    ("blog.naver.com", "네이버 블로그 참고 (무료)"),
    ("dcinside.com", "디시인사이드"),
    ("drive.google.com", "Google Drive"),
    ("scumbumbomods.com", "Scumbumbo Mods"),
    ("wicked.cc", "Wicked.cc"),
    ("loverslab.com", "LoversLab"),
    ("deaderpool-mccc.com", "Deaderpool MCCC"),
    ("sims4ai.virtualconscious.com", "Sims 4 AI Official"),
    ("github.com", "GitHub"),
    ("sims4studio.com", "Sims 4 Studio"),
    ("seebee.de", "ichschaf Sims 4 Mods"),
]

# 제외할 최상위/일반 루트 URL
IGNORED_ROOT_URLS = {
    "https://www.patreon.com",
    "https://patreon.com",
    "https://www.curseforge.com",
    "https://curseforge.com",
    "https://www.curseforge.com/sims4",
    "https://www.curseforge.com/sims4/mods",
    "https://postype.com",
    "https://www.postype.com",
    "https://github.com",
    "https://www.github.com",
    "https://www.tumblr.com",
    "https://tumblr.com",
    "https://modthesims.info",
    "https://www.modthesims.info",
    "https://db.modthesims.info",
    "https://itch.io",
    "https://www.loverslab.com",
    "https://loverslab.com",
    "https://www.dcinside.com",
    "https://dcinside.com",
    "https://gall.dcinside.com",
    "https://search.dcinside.com",
}

# 파일 바이너리 내부에서 무시할 비배포처 URL 프리픽스 (XML 스키마, API 엔드포인트, 에러 리포트 등)
IGNORED_INTERNAL_URL_PREFIXES = (
    "http://www.w3.org",
    "https://www.w3.org",
    "http://purl.org",
    "https://purl.org",
    "http://adobe.com",
    "https://adobe.com",
    "http://ns.adobe.com",
    "https://ns.adobe.com",
    "https://integrate.api.nvidia.com",
    "https://generativelanguage.googleapis.com",
    "https://api.openai.com",
    "https://api.cloudflare.com",
    "https://router.huggingface.co",
    "http://127.0.0.1",
    "http://localhost",
    "https://simsafterdark.com",
    "https://discord.gg",
    "https://discord.com",
    "https://www.lovense.com",
    "http://wonderf.cluster026.hosting.ovh.net",
)

# 무시할 일반 파이썬/심즈 기본 모듈명 및 튜닝 속성명
GENERIC_INTERNAL_NAMES = {
    "__init__", "injector", "config", "enums", "commands", "reload", "utils",
    "version", "patches", "snippets", "main", "core", "common", "settings",
    "tuning", "helpers", "elements", "ctypes", "services", "sims4", "llamalogic",
    "modfilemanifest", "xml_injector", "_do_not_unzip_", "test", "tests",
}


def extract_version_from_filename(filename: str) -> str:
    """파일명에 버전(예: v1, v2, v4, v1.1, 0.1, 0.1.0, v2.986, v2a, ChatPackv2_... 등)이 명시되어 있으면
    'v버전' 형태로 반환하고, 버전이 적혀 있지 않으면 빈 문자열('')을 반환합니다.
    """
    if not filename:
        return ""
    stem = re.sub(r"\.(?:package|ts4script|zip|rar|7z)$", "", filename, flags=re.IGNORECASE)
    # 1) 명시적 v / ver / version 접두사가 있는 버전 (예: v4, v1.1, v2.986, v2a, V2.3, ChatPackv2_BabiesFamily)
    # 파이썬 정규식에서 언더바(_)는 단어 문자(\w)이므로 \b 대신 (?=$|[^a-zA-Z0-9.]) 경계를 사용합니다.
    m_v = re.search(
        r"(?:^|[\s_\-\[\(]|(?<=[a-zA-Z]))(?:v|ver|version)\.?\s*([0-9]+(?:\.[0-9]+)*[a-z]?)(?=$|[^a-zA-Z0-9.])",
        stem,
        flags=re.IGNORECASE,
    )
    if m_v:
        raw_v = m_v.group(1).lstrip("vV")
        return f"v{raw_v}"
    # 1-b) 바람별 통합한글화모음 스타일 버전 (예: V98G8, V97G5 등)
    m_vg = re.search(r"(?:^|[\s_\-\[\(])(V[0-9]+G[0-9]+)(?=$|[^a-zA-Z0-9.])", stem, flags=re.IGNORECASE)
    if m_vg:
        return m_vg.group(1).upper()
    # 2) 점이 포함된 버전 숫자 (예: 0.1, 0.1.0, 1.8 - 단 배수 표기 1.75x 및 날짜 표기 26.11.01 등은 제외)
    m_dot = re.search(r"(?:^|[\s_\-\[\(])([0-9]+\.[0-9]+(?:\.[0-9]+)*[a-wyz]?)(?=$|[^a-zA-Z0-9.xX가-힣])", stem)
    if m_dot:
        raw_dot = m_dot.group(1)
        if not re.match(r"^(?:20)?2[0-9]\.[01][0-9]\.[0-3][0-9]$", raw_dot):
            return f"v{raw_dot}"
    return ""


def label_for_url(url: str) -> str:
    """URL에 해당하는 배포처 라벨을 반환합니다."""
    u_lower = url.lower()
    for dom, label in RELIABLE_DOMAINS:
        if dom in u_lower:
            return label
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc or "공식 배포 페이지"


def normalize_distribution_url(url: str) -> str:
    """검색 결과나 내부 링크에서 불필요한 서픽스(/sitemap, /files/숫자 등)를 정리합니다."""
    url = url.strip().rstrip(".,;'\")>]")
    u_low = url.lower()
    # 디시인사이드 갤러리 게시글 URL은 쿼리 파라미터(id, no)가 필수이므로 보존하여 정규화
    if "dcinside.com" in u_low:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        gid = (qs.get("id") or [""])[0]
        no = (qs.get("no") or [""])[0]
        if gid and no:
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?id={gid}&no={no}"
        return url.split("?")[0].rstrip("/")
    # SimFileShare 다운로드/폴더 URL은 끝의 슬래시(/) 보존
    if "simfileshare.net/" in u_low:
        base_sfs = url.split("?")[0].rstrip("/")
        return f"{base_sfs}/"
    # Google Drive 공유 URL 정규화
    if "drive.google.com" in u_low:
        m_gd = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)
        if m_gd:
            return f"https://drive.google.com/file/d/{m_gd.group(1)}/view"
        return url
    # Patreon /sitemap 제거
    url = url.split("?")[0].rstrip("/")
    url = re.sub(r"/sitemap/?$", "", url, flags=re.IGNORECASE)
    # CurseForge 개별 파일/갤러리 하위 경로를 모드 메인 페이지로 정규화
    if "curseforge.com/sims4/mods/" in url.lower():
        url = re.sub(r"(/sims4/mods/[^/?#]+)/(?:files|gallery|relations|issues)(?:/.*)?$", r"\1", url, flags=re.IGNORECASE)
    return url


def _clean_pyc_url(raw_bytes: bytes, match: re.Match) -> str:
    """Python .pyc (marshal 포맷) 내부의 ASCII 문자열 길이 바이트를 확인하여 끝에 붙은 바이트코드 문자를 제거합니다."""
    url = match.group(0).decode("ascii", "ignore")
    start = match.start()
    # Python 3 marshal short ascii ('z'=0x7a, 'Z'=0x5a, '\xda', '\xfa', 't'=0x74)
    if start >= 2 and raw_bytes[start - 2] in (0x7A, 0x5A, 0xDA, 0xFA, 0x74):
        expected_len = raw_bytes[start - 1]
        if 10 <= expected_len < len(url):
            url = url[:expected_len]
    else:
        # 길이 바이트가 앞에 없는 경우(문장 중간에 포함된 URL 등), 흔한 marshal 타입 구분자('z', 'T', 'r') 정리
        url = re.sub(r"[zTrg]$", "", url)
    return normalize_distribution_url(url)


def _is_valid_internal_url(url: str, file_name: str) -> bool:
    """파일 내부에서 추출한 URL이 유효한 모드 배포처 URL인지 판별합니다."""
    if len(url) < 14 or not url.startswith(("http://", "https://")):
        return False
    u_lower = url.lower()
    if any(u_lower.startswith(prefix) for prefix in IGNORED_INTERNAL_URL_PREFIXES):
        return False
    if u_lower.rstrip("/") in IGNORED_ROOT_URLS:
        return False
    # XML Injector가 의존성(required_mods)으로 박혀있는 다른 모드인 경우 제외
    if "scumbumbomods.com/xml-injector" in u_lower or "curseforge.com/sims4/mods/xml-injector" in u_lower:
        if "xml" not in file_name.lower() and "injector" not in file_name.lower():
            return False
    parsed = urllib.parse.urlparse(url)
    if not parsed.netloc or "." not in parsed.netloc:
        return False
    return True


def _extract_from_single_ts4script(path: Path) -> Dict[str, Any]:
    """단일 .ts4script (ZIP 아카이브) 내부에서 매니페스트, 모듈명, 내장 URL을 추출합니다."""
    info: Dict[str, Any] = {
        "manifest_name": "",
        "creators": [],
        "urls": [],
        "modules": [],
        "version": "",
    }
    if not path.exists() or not path.is_file():
        return info

    try:
        with zipfile.ZipFile(path, "r") as z:
            for entry_name in z.namelist():
                parts = [p for p in entry_name.split("/") if p]
                if parts:
                    top_stem = re.sub(r"\.(pyc|py|txt|yml|yaml|json|cfg|log)$", "", parts[0], flags=re.IGNORECASE)
                    if (
                        top_stem
                        and top_stem.lower() not in GENERIC_INTERNAL_NAMES
                        and not top_stem.startswith("_")
                        and top_stem not in info["modules"]
                    ):
                        info["modules"].append(top_stem)

                try:
                    data = z.read(entry_name)
                except Exception:
                    continue

                # 1. LlamaLogic ModFileManifest YAML 파싱
                if "modfilemanifest" in entry_name.lower():
                    text = data.decode("utf-8", "ignore")
                    # required_mods 섹션 이전의 본체 메타데이터만 파싱
                    main_part = re.split(r"^required_mods\s*:", text, flags=re.MULTILINE)[0]
                    m_name = re.search(r"^name\s*:\s*(.+)$", main_part, flags=re.MULTILINE)
                    if m_name and not info["manifest_name"]:
                        info["manifest_name"] = html.unescape(m_name.group(1).strip().strip("'\""))

                    m_ver = re.search(r"^version\s*:\s*(.+)$", main_part, flags=re.MULTILINE)
                    if m_ver and not info["version"]:
                        info["version"] = m_ver.group(1).strip().strip("'\"")

                    # creators 리스트 추출
                    c_block = re.search(r"^creators\s*:\s*\r?\n((?:\s*-\s*.+\r?\n?)+)", main_part, flags=re.MULTILINE)
                    if c_block:
                        for m_c in re.finditer(r"^\s*-\s*(.+)$", c_block.group(1), flags=re.MULTILINE):
                            c_val = m_c.group(1).strip().strip("'\"")
                            if c_val and c_val not in info["creators"]:
                                info["creators"].append(c_val)

                    for m_u in re.finditer(r"^(?:url|funding_url)\s*:\s*(https?://\S+)", main_part, flags=re.MULTILINE):
                        u_val = normalize_distribution_url(m_u.group(1).strip())
                        if _is_valid_internal_url(u_val, path.name) and u_val not in info["urls"]:
                            info["urls"].append(u_val)
                else:
                    # 2. 일반 .pyc / .py 내부의 URL 스캔
                    if entry_name.lower().endswith((".txt", ".md")) and "license" in entry_name.lower():
                        continue
                    for m in re.finditer(rb"https?://[a-zA-Z0-9./_\-@%&?=]+", data):
                        u_val = _clean_pyc_url(data, m)
                        if _is_valid_internal_url(u_val, path.name) and u_val not in info["urls"]:
                            info["urls"].append(u_val)

                    # 3. ModFileManifest가 없는 핵심 스크립트(.pyc) 내부 버전 상수 보조 추출
                    if not info["version"]:
                        e_low = entry_name.lower()
                        if e_low.endswith(("mc_cmd_version.pyc", "mc_utils.pyc", "mc_cmd_center.pyc", "mc_woohoo.pyc")):
                            m_mc = re.search(rb"(?<![0-9.])(202[0-9]\.[0-9]+\.[0-9]+)(?![0-9.])", data)
                            if m_mc:
                                info["version"] = m_mc.group(1).decode("ascii", "ignore")
                        elif "wickedwhims" in e_low and ("version" in e_low or "main" in e_low or "init" in e_low):
                            m_ww = re.search(rb"(?<![a-zA-Z0-9.])(v1[789][0-9][a-z]?)(?![a-zA-Z0-9.])", data, flags=re.IGNORECASE)
                            if m_ww:
                                info["version"] = m_ww.group(1).decode("ascii", "ignore")
                        elif e_low.endswith("sims4_ai_chat/config.pyc"):
                            m_ai = re.search(rb"(?<![0-9.])([0-9]+\.[0-9]+\.[0-9]+)(?![0-9.])", data)
                            if m_ai:
                                info["version"] = m_ai.group(1).decode("ascii", "ignore")
                        elif e_low.endswith("ui_cheats/cheat_commands.pyc"):
                            m_ui = re.search(rb"(?<![0-9.])(1\.[3-9][0-9](?:\.[0-9]+)?)(?![0-9.])", data)
                            if m_ui:
                                ui_ver = m_ui.group(1).decode("ascii", "ignore")
                                # Weerbesu의 UI Cheats Extension은 핫픽스(예: 1.59.1)에서도 .ts4script 내부 버전 상수를 '1.59'로 유지하고
                                # 동봉된 UI_Cheats_Extension.package만 재빌드하므로, 패키지 파일이 1.59.1 빌드(15,388,976 bytes)이면 1.59.1로 보정
                                if ui_ver == "1.59":
                                    pkg_sibling = path.parent / "UI_Cheats_Extension.package"
                                    if pkg_sibling.exists() and pkg_sibling.stat().st_size == 15388976:
                                        ui_ver = "1.59.1"
                                info["version"] = ui_ver
    except Exception:
        pass

    return info


def _extract_from_single_package(path: Path) -> Dict[str, Any]:
    """단일 .package (DBPF 2.1 바이너리) 내부의 XML Tuning 및 ModFileManifest 리소스를 분석합니다."""
    info: Dict[str, Any] = {
        "manifest_name": "",
        "creators": [],
        "urls": [],
        "display_names": [],
        "root_tunings": [],
        "version": "",
        "is_ww_addon": False,
    }
    if not path.exists() or not path.is_file():
        return info

    try:
        with open(path, "rb") as fp:
            header = fp.read(96)
            if len(header) < 96 or header[:4] != b"DBPF":
                return info

            idx_count = struct.unpack_from("<I", header, 36)[0]
            idx_offset = struct.unpack_from("<I", header, 64)[0] or struct.unpack_from("<I", header, 40)[0]
            if idx_count == 0 or idx_offset == 0:
                return info

            fp.seek(idx_offset)
            idx_data = fp.read(min(idx_count * 32 + 32, 262144))
            if len(idx_data) < 24:
                return info

            flags = struct.unpack_from("<I", idx_data, 0)[0]
            pos = 4 + sum(4 for b in range(3) if flags & (1 << b))
            entry_size = sum(4 for b in range(3) if not (flags & (1 << b))) + 20

            # 최대 100개의 리소스 엔트리를 빠르게 검사 (대용량 메쉬/텍스처는 건너뜀)
            inspected_xml = 0
            for _ in range(min(idx_count, 250)):
                if pos + entry_size > len(idx_data) or inspected_xml >= 60:
                    break
                vals = struct.unpack_from("<5I", idx_data, pos + entry_size - 20)
                offset, fsize_raw = vals[1], vals[2]
                fsize = fsize_raw & 0x7FFFFFFF
                pos += entry_size

                if fsize < 16 or fsize > 524288:
                    continue

                fp.seek(offset)
                chunk = fp.read(fsize)
                text = ""
                if len(chunk) > 2 and chunk[0] == 0x78 and chunk[1] in (0x01, 0x9C, 0xDA):
                    try:
                        decompressed = zlib.decompress(chunk)
                        stripped = decompressed.lstrip()
                        if stripped.startswith((b"<?xml", b"<I ", b"<M ", b"\xef\xbb\xbf<?xml", b"\xef\xbb\xbf<I ")):
                            text = decompressed.decode("utf-8", "ignore")
                        elif not info["root_tunings"]:
                            # XML이 아닌 CASP(CAS Part) 또는 NameMap 바이너리 리소스에서 파트 이름 추출 (예: XOOX_CO_..., [XOOX] ...)
                            if len(decompressed) >= 30 and 0x18 <= decompressed[0] <= 0x45 and decompressed[1:4] == b"\x00\x00\x00" and decompressed[15:16] == b"\x00":
                                try:
                                    u16_chunk = decompressed[14:114]
                                    casp_str = u16_chunk.decode("utf-16-le", "ignore").split("\x00")[0]
                                    m_casp = re.match(r"^([A-Za-z0-9_\-\[\]\s]{4,60})", casp_str)
                                    if m_casp and ("_" in m_casp.group(1) or "[" in m_casp.group(1)):
                                        info["root_tunings"].append(m_casp.group(1).strip())
                                except Exception:
                                    pass
                            elif decompressed[:4] == b"\x01\x00\x00\x00":
                                for m_nm in re.finditer(rb"(\[[A-Za-z0-9_\-\s]{2,25}\]\s*[A-Za-z0-9_\-\s]{3,40})", decompressed[:512]):
                                    nm_str = m_nm.group(1).decode("utf-8", "ignore").strip()
                                    if nm_str not in info["root_tunings"]:
                                        info["root_tunings"].append(nm_str)
                    except Exception:
                        pass
                elif chunk.lstrip().startswith((b"<?xml", b"<I ", b"<M ", b"\xef\xbb\xbf<?xml", b"\xef\xbb\xbf<I ")):
                    text = chunk.decode("utf-8", "ignore")

                if not text:
                    continue

                inspected_xml += 1

                # 1. LlamaLogic ModFileManifest XML 스니펫 파싱
                if "ModFileManifest" in text or "llamalogic:manifest" in text:
                    main_xml = text.split('<L n="required_mods">')[0]
                    m_n = re.search(r'<T n="name">([^<]+)</T>', main_xml)
                    if m_n and not info["manifest_name"]:
                        info["manifest_name"] = html.unescape(m_n.group(1).strip())

                    m_v = re.search(r'<T n="version">([^<]+)</T>', main_xml)
                    if m_v and not info["version"]:
                        v_candidate = html.unescape(m_v.group(1).strip())
                        if not re.match(r"^[0-9]+(?:\.[0-9]+)?[xX]$", v_candidate):
                            info["version"] = v_candidate

                    m_c_block = re.search(r'<L n="creators">(.*?)</L>', main_xml, flags=re.DOTALL)
                    if m_c_block:
                        for c in re.findall(r"<T>([^<]+)</T>", m_c_block.group(1)):
                            c_clean = html.unescape(c.strip())
                            if c_clean and c_clean not in info["creators"]:
                                info["creators"].append(c_clean)

                    for u in re.findall(r'<T n="(?:url|funding_url)">(https?://[^<]+)</T>', main_xml):
                        u_clean = normalize_distribution_url(html.unescape(u.strip()))
                        if _is_valid_internal_url(u_clean, path.name) and u_clean not in info["urls"]:
                            info["urls"].append(u_clean)
                    continue

                # 2. WickedWhims CAS / Animation 애드온 여부 감지
                if any(
                    tag in text
                    for tag in (
                        "WickedWhimsCASPartsPackage",
                        "WickedWhimsAnimationPackage",
                        "wickedwhims_cas_parts",
                        "wickedwhims_animations",
                        "wickedwhims_dance_animations",
                    )
                ):
                    info["is_ww_addon"] = True

                # 3. 루트 <I ... n="Creator:TuningName"> 식별자 추출
                for m_root in re.finditer(r'<I\b[^>]*\bn="([^"]+)"', text):
                    rt = html.unescape(m_root.group(1).strip())
                    if rt and rt not in info["root_tunings"]:
                        info["root_tunings"].append(rt)

                # 4. 명시적 제작자(author/creator) 태그 추출
                for m_auth in re.finditer(
                    r'<T n="(?:cas_part_author|animation_author|author_name|creator_name)">([^<]+)</T>',
                    text,
                ):
                    a_val = html.unescape(m_auth.group(1).strip())
                    if a_val and a_val not in info["creators"]:
                        info["creators"].append(a_val)

                # 5. 명시적 표시 이름(display_name/group) 추출
                for m_disp in re.finditer(
                    r'<T n="(?:cas_part_raw_display_name|cas_part_group|animation_raw_display_name|raw_display_name)">([^<]+)</T>',
                    text,
                ):
                    d_val = html.unescape(m_disp.group(1).strip())
                    if d_val and d_val not in info["display_names"]:
                        info["display_names"].append(d_val)

                # 6. XML 내부 주석/필드의 배포처 URL 추출
                for m_u in re.finditer(r"https?://[a-zA-Z0-9./_\-@%&?=]+", text):
                    u_val = normalize_distribution_url(m_u.group(0))
                    if _is_valid_internal_url(u_val, path.name) and u_val not in info["urls"]:
                        info["urls"].append(u_val)
    except Exception:
        pass

    return info


def _parse_tuning_and_module_clues(root_tunings: List[str], modules: List[str]) -> Tuple[str, str]:
    """루트 튜닝 이름(예: 'Spent:UsedCondom_Full', 'lotharihoe:SimSpawnOverhaul_...', 'Lumpinou_SkillDisablingMod_Trait_...')과
    스크립트 모듈명(예: 'Spent_Cumshine', 'thepancake1_removesimsfromconvos')에서
    제작자명과 모드명 단서를 추출합니다.
    """
    inferred_creator = ""
    inferred_mod = ""

    # 1. 루트 튜닝 이름 우선 분석 (CamelCase가 보존되어 있어 단어 분리에 유리함)
    for rt in root_tunings:
        # 패턴 A: 'Creator:ModName_...' (예: 'Spent:UsedCondom_Full', 'lotharihoe:SimSpawnOverhaul_...', 'Sopor:BODY_TOP_FEMALE')
        if ":" in rt:
            prefix, rest = rt.split(":", 1)
            prefix_clean = prefix.strip()
            if prefix_clean.lower() not in ("llamalogic", "ww") and len(prefix_clean) >= 2:
                if not inferred_creator:
                    inferred_creator = prefix_clean
                rest_first = rest.split(":")[0].split("_")[0].strip()
                if (
                    not inferred_mod
                    and rest_first
                    and rest_first.lower() not in ("body", "top", "bottom", "female", "male", "buff", "loot", "testset", "wickedwhimsanimations")
                ):
                    inferred_mod = split_camel_case(rest_first)
                break

        # 패턴 B: '..._ByCreator' 또는 '..._By_Creator' (예: 'RestrictedRomance30_ByPolarbearsims')
        by_match = re.search(r"_by_?([a-zA-Z0-9]+)$", rt, flags=re.IGNORECASE)
        if by_match and not inferred_creator:
            inferred_creator = by_match.group(1)

        # 패턴 C: 'Creator_ModName_...' (예: 'Lumpinou_SkillDisablingMod_Trait_NoMischief', 'Spent_CumQueenAspiration_...')
        if "_" in rt:
            parts = rt.split("_")
            first = parts[0].strip()
            if (
                first.lower() not in (
                    "buff", "loot", "trait", "mixer", "si", "sim", "sims", "sims4",
                    "tyae", "broadcaster", "client", "service", "servicenpc", "desk",
                    "situation", "template", "phone", "cheat", "idle", "object",
                    "objects", "autonomous", "interaction", "interactions", "career",
                )
                and len(first) >= 3
            ):
                if not inferred_creator:
                    inferred_creator = first
                if len(parts) >= 2 and not inferred_mod:
                    second = parts[1].strip()
                    if first.lower() == "lumpinou" and second.upper() == "MP":
                        inferred_mod = "Mood Pack Mod"
                    elif first.lower() == "lumpinou" and second.upper() == "RTR":
                        inferred_mod = "Road To Romance"
                    elif second.lower() not in (
                        "buff", "loot", "trait", "shared", "testset", "simpicker",
                        "piemenu", "manageworkoutfit", "chatting",
                    ):
                        inferred_mod = split_camel_case(second)

    # 2. 스크립트 모듈명 보조 분석 (예: 'Spent_Cumshine', 'thepancake1_removesimsfromconvos', 'roburky_fitness')
    non_creator_module_words = GENERIC_INTERNAL_NAMES | {
        "sims4", "sims", "ts4", "mod", "simulation", "career", "regenerate",
        "interaction", "interactions", "ui", "cas", "autonomy", "story",
    }
    for mod_name in modules:
        if "_" in mod_name:
            raw_parts = [p for p in mod_name.split("_") if p]
            # 첫 단어가 일반 게임 용어('sims4', 'simulation' 등)인 경우 제작자명이 아니라 모드 이름 전체임
            if raw_parts and raw_parts[0].lower() in non_creator_module_words:
                rest_parts = [p for p in raw_parts if p.lower() not in GENERIC_INTERNAL_NAMES]
                if rest_parts and not inferred_mod:
                    inferred_mod = " ".join(split_camel_case(p) for p in rest_parts)
                continue

            parts = [p for p in raw_parts if p.lower() not in GENERIC_INTERNAL_NAMES]
            if len(parts) >= 2:
                if not inferred_creator:
                    inferred_creator = parts[0]
                mod_from_module = " ".join(split_camel_case(p) for p in parts[1:])
                if mod_from_module and (
                    not inferred_mod or mod_from_module.lower() not in inferred_mod.lower()
                ):
                    inferred_mod = mod_from_module
                break
        elif not inferred_mod and mod_name.lower() not in GENERIC_INTERNAL_NAMES:
            inferred_mod = split_camel_case(mod_name)

    return inferred_creator, inferred_mod


def extract_mod_file_metadata(file_path: Optional[str]) -> Dict[str, Any]:
    """지정된 .package 또는 .ts4script 파일(및 동일 폴더의 짝 파일) 내부를 분석하여
    제작자명, 모드명, 버전, 내장 공식 배포 URL, 튜닝/모듈 식별자를 반환합니다.
    """
    result: Dict[str, Any] = {
        "has_metadata": False,
        "manifest_name": "",
        "creators": [],
        "inferred_creator": "",
        "inferred_mod": "",
        "display_names": [],
        "urls": [],
        "version": "",
        "root_tunings": [],
        "modules": [],
        "is_ww_addon": False,
    }
    if not file_path:
        return result

    p = Path(file_path)
    if not p.exists() or not p.is_file():
        return result

    suffix = p.suffix.lower()
    pkg_info: Dict[str, Any] = {}
    scr_info: Dict[str, Any] = {}

    if suffix == ".package":
        pkg_info = _extract_from_single_package(p)
        # 1) 동일 파일명(stem)의 .ts4script가 같은 폴더에 있는지 확인
        sibling_scr = p.with_suffix(".ts4script")
        if not sibling_scr.exists():
            # _Tuning / _Package 등 접미사 차이 보정
            alt_stem = re.sub(r"[_\-\s]*(tuning|package)$", "", p.stem, flags=re.IGNORECASE)
            for cand in p.parent.glob("*.ts4script"):
                if cand.stem.lower().startswith(alt_stem.lower()[:8]):
                    sibling_scr = cand
                    break
        if sibling_scr.exists():
            scr_info = _extract_from_single_ts4script(sibling_scr)

        # 2) 만약 메쉬 전용 .package 파일이라 내부 리소스가 전혀 없다면, 파일명 앞부분(최소 10글자)이 완전히 동일한 형제 .package에서만 참조
        # (MOD, CAS 등 공용 폴더에 있는 다른 제작자의 모드를 잘못 읽어오는 현상 원천 차단)
        if (
            not pkg_info.get("manifest_name")
            and not pkg_info.get("creators")
            and not pkg_info.get("root_tunings")
            and not pkg_info.get("urls")
            and len(p.stem) >= 10
        ):
            prefix_match = p.stem.lower()[:10]
            sibling_pkgs = [
                sp for sp in sorted(p.parent.glob("*.package"))
                if sp != p and sp.stem.lower().startswith(prefix_match)
            ]
            for sp in sibling_pkgs[:2]:
                sp_info = _extract_from_single_package(sp)
                if sp_info.get("creators") or sp_info.get("urls") or sp_info.get("root_tunings"):
                    pkg_info = sp_info
                    break

    elif suffix == ".ts4script":
        scr_info = _extract_from_single_ts4script(p)
        sibling_pkg = p.with_suffix(".package")
        if not sibling_pkg.exists():
            alt_stem = re.sub(r"[_\-\s]*(scripts|script)$", "", p.stem, flags=re.IGNORECASE)
            for cand in p.parent.glob("*.package"):
                if cand.stem.lower().startswith(alt_stem.lower()[:8]):
                    sibling_pkg = cand
                    break
        if sibling_pkg.exists():
            pkg_info = _extract_from_single_package(sibling_pkg)

    # 추출된 정보 병합
    result["manifest_name"] = pkg_info.get("manifest_name") or scr_info.get("manifest_name") or ""
    result["version"] = pkg_info.get("version") or scr_info.get("version") or ""
    result["is_ww_addon"] = bool(pkg_info.get("is_ww_addon"))

    for c in (pkg_info.get("creators", []) + scr_info.get("creators", [])):
        if c and c not in result["creators"]:
            result["creators"].append(c)

    for u in (pkg_info.get("urls", []) + scr_info.get("urls", [])):
        if u and u not in result["urls"]:
            result["urls"].append(u)

    result["display_names"] = pkg_info.get("display_names", [])[:3]
    result["root_tunings"] = pkg_info.get("root_tunings", [])[:5]
    result["modules"] = scr_info.get("modules", [])[:5]

    inf_creator, inf_mod = _parse_tuning_and_module_clues(result["root_tunings"], result["modules"])

    # 파일명 자체에 명시된 [제작자], 모드명, 버전(예: v4, v1.1) 및 카탈로그 매칭 정보로 누락 필드 보완
    fn_ver_str = extract_version_from_filename(p.name)
    if not result["version"] and fn_ver_str:
        result["version"] = fn_ver_str.lstrip("vV")

    fn_bracket = re.search(r"\[([^\]]+)\]", p.stem)
    m_by_fn = re.search(r"[\s_]by[\s_]*([a-zA-Z0-9_-]+)$", p.stem, flags=re.IGNORECASE)
    explicit_fn_creator = bool(fn_bracket or m_by_fn)
    fn_creator = (
        fn_bracket.group(1).strip()
        if fn_bracket
        else (m_by_fn.group(1).strip() if m_by_fn else "")
    )
    if m_by_fn and not fn_bracket:
        fn_title_raw = re.sub(r"\s+", " ", p.stem.replace("_", " ")).strip()
    else:
        fn_title_raw = re.sub(r"\[[^\]]+\]", " ", p.stem) if fn_bracket else p.stem
        fn_title_raw = re.sub(r"(?:[\s_\-]|^)(?:v|ver|version)\s*[0-9]+(?:\.[0-9]+)*[a-z0-9]*\b", " ", fn_title_raw, flags=re.IGNORECASE)
        fn_title_raw = re.sub(r"\s+", " ", fn_title_raw).strip(" _-!")

    non_creator_prefixes = GENERIC_INTERNAL_NAMES | {
        "more", "less", "ui", "cas", "no", "better", "auto", "custom",
        "extra", "new", "all", "fix", "fixed", "higher", "harder", "improved",
        "personality", "sims", "restricted",
    }
    if not fn_creator and "_" in p.stem:
        u_parts = [pt.strip() for pt in p.stem.split("_") if pt.strip()]
        if len(u_parts) >= 2 and u_parts[0].lower() not in non_creator_prefixes:
            fn_creator = "NV Games" if u_parts[0].upper() == "NV" else u_parts[0]
            fn_title_raw = " ".join(u_parts[1:])

    m_rpo = re.match(
        r"^Lumpinou_RPO_Collection_(M\d+)_(.+?)(?:_REQUIRED)?(?:_v[0-9.]+[a-z]?)?$",
        p.stem,
        flags=re.IGNORECASE,
    )
    if m_rpo:
        rpo_sub = split_camel_case(m_rpo.group(2).replace("_", " "))
        result["manifest_name"] = f"RPO {m_rpo.group(1).upper()} {rpo_sub}"

    cat_match = check_known_catalog(p.name) or (
        check_known_catalog(p.parent.name) if "mccc" in p.parent.name.lower() else None
    )
    if cat_match:
        if cat_match.get("creator"):
            result["creators"] = [cat_match["creator"]]
        if cat_match.get("mod_title") and not result["manifest_name"]:
            result["manifest_name"] = cat_match["mod_title"]
        if cat_match.get("version"):
            result["version"] = cat_match["version"]
        if cat_match.get("candidate_links"):
            result["urls"] = [link[2] for link in cat_match["candidate_links"]]

    result["inferred_creator"] = (
        result["creators"][0]
        if result["creators"]
        else (fn_creator if explicit_fn_creator else (inf_creator or fn_creator))
    )
    result["inferred_mod"] = (
        result["manifest_name"]
        or (result["display_names"][0] if result["display_names"] else "")
        or (fn_title_raw if explicit_fn_creator and fn_title_raw else "")
        or inf_mod
        or fn_title_raw
    )

    result["has_metadata"] = any([
        result["manifest_name"],
        result["creators"],
        result["inferred_creator"],
        result["inferred_mod"],
        result["urls"],
        result["root_tunings"],
        result["modules"],
    ])
    return result


def split_camel_case(text: str) -> str:
    """CamelCase 문자열(예: RemoveSimsFromConversation, ChatPackv2BabiesFamily)을 공백으로 분리합니다."""
    text = re.sub(r"(?<=[a-zA-Z])(?:v|ver)[0-9]+(?:\.[0-9]+)*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    return re.sub(r"\s+", " ", text).strip()


def check_known_catalog(raw_name: str) -> Optional[Dict[str, Any]]:
    """핵심 코어 모드 카탈로그(MCCC, WickedWhims 본체, 바람별 한글화 등)와 정확히 일치하는지 확인합니다."""
    name_lower = raw_name.lower()
    clean = re.sub(r"[^a-zA-Z0-9가-힣]", "", name_lower)
    for item in KNOWN_CATALOG:
        for kw in item["keywords"]:
            kw_lower = kw.lower()
            clean_kw = re.sub(r"[^a-zA-Z0-9가-힣]", "", kw_lower)
            if kw_lower in name_lower or (len(clean_kw) >= 6 and clean_kw in clean):
                return {
                    "found": True,
                    "primary_url": item["links"][0][2],
                    "source_name": item["links"][0][0],
                    "candidate_links": item["links"],
                    "matched_catalog": item["name"],
                    "creator": item.get("creator", ""),
                    "mod_title": item.get("mod_title", item["name"]),
                    "version": item.get("version", ""),
                    "release_notes": item.get("release_notes", ""),
                    "query": raw_name,
                }
    return None


def smart_tokenize(
    raw_name: str,
    folder_context: str = "",
    file_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """파일명, 상위/하위 폴더 문맥, 그리고 파일 내부에서 추출한 바이너리 메타데이터를 결합하여
    제작자명(creator), 모드명(mod_title), 검색 핵심 키워드를 정밀하게 추출합니다.
    """
    file_meta = file_meta or {}

    # 1. 확장자 및 앞뒤 장식 기호(!, _ 등) 제거
    name = re.sub(r"\.(package|ts4script)$", "", raw_name, flags=re.IGNORECASE)
    name = re.sub(r"^[!_~\-\s]+", "", name)
    name = re.sub(r"^(MOD[\s_-]+)", "", name, flags=re.IGNORECASE)

    # 2. 안전한 버전 문자열 제거 (명확한 버전 표기만 제거하여 일반 모드명 손실 방지)
    name = re.sub(r"[\s_-]+(?:v|ver|version)\s*[0-9]+(?:\.[0-9]+)*[a-z0-9]*\b", " ", name, flags=re.IGNORECASE)
    name = re.sub(r"(?<=[a-zA-Z])(?:v|ver)[0-9]+(?:\.[0-9]+)*\b", " ", name, flags=re.IGNORECASE)
    name = re.sub(r"[\s_-]+[0-9]+\.[0-9]+(?:\.[0-9]+)*[a-z]?\b", " ", name, flags=re.IGNORECASE)
    # 괄호 안 부가 설명 제거 (예: (Required), (GLOVES), (SOCKS))
    name = re.sub(r"\([^)]*\)", " ", name)
    name = name.strip()

    creator = ""
    mod_title = name

    # 패턴 1: 대괄호 제작자명 [Creator] Title (여러 대괄호가 있을 경우 첫 번째를 제작자로 추출)
    brackets = re.findall(r"\[([^\]]+)\]", name)
    if brackets:
        creator = brackets[0].strip()
        mod_title = re.sub(r"\[[^\]]+\]", " ", name).strip()
    # 패턴 2: 'Creator - Title' 또는 'Creator x Title'
    elif " - " in name:
        parts = name.split(" - ", 1)
        creator = parts[0].strip()
        mod_title = parts[1].strip()
    elif re.search(r"\s+x\s+", name, flags=re.IGNORECASE):
        parts = re.split(r"\s+x\s+", name, maxsplit=1, flags=re.IGNORECASE)
        creator = parts[0].strip()
        mod_title = parts[1].strip()
    # 패턴 3: '..._By_Creator' 또는 '..._ByCreator'
    elif re.search(r"[\s_]by[\s_]+([a-zA-Z0-9_-]+)$", name, flags=re.IGNORECASE):
        m_by = re.search(r"([\s_]by[\s_]+([a-zA-Z0-9_-]+))$", name, flags=re.IGNORECASE)
        if m_by:
            creator = m_by.group(2).strip()
            mod_title = name[: m_by.start()].strip()
    # 패턴 4: 언더바 구분 Creator_Mod_Name
    elif "_" in name:
        noise_parts = {"scripts", "script", "tuning", "mod", "base", "addon", "core", "required", "optional", "collection", "merge"}
        raw_parts = [p.strip() for p in name.split("_") if p.strip()]
        filtered_parts = [p for p in raw_parts if p.lower() not in noise_parts and not re.match(r"^m[0-9]{1,2}$", p.lower())]
        if len(filtered_parts) >= 2:
            creator = filtered_parts[0]
            mod_title = " ".join(filtered_parts[1:])
        elif filtered_parts:
            mod_title = " ".join(filtered_parts)

    # CamelCase 분리 적용
    mod_title = split_camel_case(mod_title)
    clean_title = re.sub(r"[^a-zA-Z0-9가-힣\s]", " ", mod_title)
    clean_title = re.sub(r"\s+", " ", clean_title).strip()

    clean_creator = re.sub(r"[^a-zA-Z0-9가-힣\s_-]", " ", creator)
    clean_creator = re.sub(r"\s+", " ", clean_creator).strip()

    # 3. 파일 내부 바이너리 메타데이터(.package / .ts4script)로 제작자명 및 모드명 보강/교정
    meta_creator = file_meta.get("inferred_creator", "").strip()
    meta_mod = file_meta.get("inferred_mod", "").strip()
    extra_creators: List[str] = []

    if meta_creator:
        if not clean_creator or clean_creator.lower() in ("ww", "mod", "sims", "sims4", "disl", "rsm", "bg", "to"):
            clean_creator = meta_creator
        elif meta_creator.lower() != clean_creator.lower():
            extra_creators.append(meta_creator)

    # 폴더 문맥에서 보조 제작자/모드 단서 추출 (예: 'MOD Cumshine', 'WW CC\Dumbaby', 'MOD\Lumpinou')
    if folder_context and not clean_creator:
        folder_clean = re.sub(r"^(MOD[\s_-]*)", "", folder_context, flags=re.IGNORECASE).strip()
        if folder_clean and folder_clean.lower() not in ("cas", "build", "pose", "prio", "default", "mod", "optional"):
            clean_creator = folder_clean

    if file_meta.get("manifest_name"):
        # 매니페스트 공식 명칭이 있으면 최우선 사용
        clean_title = re.sub(r"[^a-zA-Z0-9가-힣\s]", " ", file_meta["manifest_name"])
        clean_title = re.sub(r"\s+", " ", clean_title).strip()
    elif meta_mod and (
        len(clean_title) < 4
        or clean_title.lower() == clean_creator.lower()
        or (" " not in clean_title and " " in split_camel_case(meta_mod))
    ):
        meta_mod_clean = re.sub(r"\([^)]*\)", " ", meta_mod)
        clean_title = split_camel_case(meta_mod_clean)
        clean_title = re.sub(r"[^a-zA-Z0-9가-힣\s]", " ", clean_title).strip()
    elif folder_context and " " not in clean_title:
        folder_clean = re.sub(r"^(MOD[\s_-]*)", "", folder_context, flags=re.IGNORECASE).strip()
        if re.sub(r"\s+", "", folder_clean).lower() == clean_title.lower():
            clean_title = folder_clean

    # 4. 검색 및 스니펫 채점용 핵심 키워드 구성
    stop_words = {
        "the", "sims", "sim", "mod", "mods", "scripts", "script", "tuning",
        "package", "ts4script", "standalone", "required", "optional", "core",
        "version", "ver", "addon", "add", "ons", "merge", "set",
        "female", "male", "top", "bottom", "mesh", "detailed",
    }
    keywords: List[str] = []
    combined_for_kw = f"{clean_creator} {' '.join(extra_creators)} {clean_title}"
    for w in combined_for_kw.split():
        w_lower = w.lower().strip("_-")
        if len(w_lower) >= 2 and w_lower not in stop_words and w_lower not in keywords:
            keywords.append(w_lower)

    return {
        "raw": raw_name,
        "creator": clean_creator,
        "extra_creators": extra_creators,
        "mod_title": clean_title,
        "keywords": keywords,
    }


def score_search_snippet(
    title: str,
    snippet: str,
    url: str,
    tokens: Dict[str, Any],
) -> int:
    """검색 결과 항목이 대상 모드 및 내부 추출 제작자명과 얼마나 일치하는지 점수를 계산합니다."""
    title_lower = title.lower()
    url_lower = url.lower()
    snippet_lower = snippet.lower()
    combined_text = f"{title_lower} {snippet_lower} {url_lower}"

    keywords = tokens.get("keywords", [])
    creator_lower = tokens.get("creator", "").lower().strip()
    extra_creators = [c.lower().strip() for c in tokens.get("extra_creators", []) if c]
    all_creators = [c for c in ([creator_lower] + extra_creators) if len(c) >= 3]

    # 제작자명만 일치하고 실제 모드 제목 키워드는 단 하나도 일치하지 않는 다른 모드 포스트(예: 동일 제작자의 타 모드) 탈락 처리
    creator_words_set = set(re.split(r"[^a-z0-9가-힣]+", " ".join(all_creators)))
    title_only_kws = [kw for kw in keywords if kw not in creator_words_set and len(kw) >= 3]
    if title_only_kws:
        title_kw_matches = sum(1 for kw in title_only_kws if kw in combined_text)
        if title_kw_matches == 0:
            return 0

    match_count = sum(1 for kw in keywords if kw in combined_text)
    if match_count == 0:
        return 0

    score = match_count * 15

    # 제작자명이 일치하면 큰 가산점, 반대로 제작자명이 명확한데 URL/제목/스니펫 어디에도 없으면 감점
    creator_matched = False
    for c in all_creators:
        c_slug = re.sub(r"[^a-z0-9]", "", c)
        if c in combined_text or (len(c_slug) >= 4 and c_slug in re.sub(r"[^a-z0-9]", "", combined_text)):
            creator_matched = True
            if c in url_lower or c_slug in re.sub(r"[^a-z0-9]", "", url_lower):
                score += 65
            if c in title_lower:
                score += 45
            else:
                score += 25
            break

    if all_creators and not creator_matched:
        # 제작자가 명확히 식별되었는데 결과에 제작자명이 전혀 없고 일치 키워드도 1개뿐이면 엉뚱한 모드로 간주하여 탈락
        if match_count < 2:
            return 0
        score -= 60

    # 제목 및 URL 슬러그에 모드 제목 키워드 포함 시 가산점
    for kw in keywords:
        if kw in title_lower:
            score += 25
        if kw in url_lower:
            score += 35

    # 타 언어 번역본(/translations/) 링크는 원본 모드가 아닐 확률이 높으므로 감점
    raw_lower = tokens.get("raw", "").lower()
    if "/translations/" in url_lower and "translation" not in raw_lower and "한글" not in raw_lower:
        score -= 50

    # 배포처 도메인 신뢰도 가산점 (제작자 공식 Patreon 포스트가 있을 경우 우선순위 부여)
    for dom, _ in RELIABLE_DOMAINS:
        if dom in url_lower:
            score += 20
            if dom == "patreon.com" and "/posts/" in url_lower:
                score += 25
            break

    return score


def search_and_rank_distribution_links(tokens: Dict[str, Any], timeout: int = 8) -> List[Tuple[str, str, str]]:
    """추출된 제작자명과 모드명을 바탕으로 검색을 수행하고,
    동일 URL을 가리키는 다중 앵커(<a>) 텍스트를 병합하여 정확한 제목과 스니펫으로 유사도를 채점합니다.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    has_korean = bool(re.search(r"[가-힣]", tokens["raw"] + " " + tokens["mod_title"]))
    prefix = "심즈4" if has_korean else "Sims 4"

    query_variants = []
    base_parts = [prefix]
    if tokens["creator"]:
        base_parts.append(tokens["creator"])
    for ec in tokens.get("extra_creators", [])[:1]:
        if ec.lower() != tokens["creator"].lower():
            base_parts.append(ec)

    title_words = tokens["mod_title"].split() if tokens["mod_title"] and tokens["mod_title"].lower() != tokens["creator"].lower() else []
    if title_words:
        query_variants.append(" ".join(base_parts + [" ".join(title_words[:5])]))
        # 하위 모듈/팩 부제가 붙어 있어 검색 결과가 안 나오는 경우를 대비해 핵심 앞 2단어 쿼리도 준비
        if len(title_words) > 2:
            query_variants.append(" ".join(base_parts + [" ".join(title_words[:2])]))
    else:
        query_variants.append(" ".join(base_parts))

    candidates: List[Tuple[int, str, str, str]] = []
    seen_norm_urls = set()

    for query in query_variants:
        url_groups: Dict[str, Dict[str, Any]] = {}
        search_url = f"https://search.naver.com/search.naver?query={urllib.parse.quote(query)}"
        try:
            r = requests.get(search_url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    if not href.startswith(("http://", "https://")):
                        continue

                    norm_href = normalize_distribution_url(href)
                    if norm_href.lower() in IGNORED_ROOT_URLS or norm_href in seen_norm_urls:
                        continue

                    matched_dom_label = None
                    for dom, label in RELIABLE_DOMAINS:
                        if dom in norm_href.lower():
                            matched_dom_label = label
                            break

                    if not matched_dom_label:
                        continue

                    text = a.get_text(" ", strip=True).replace("새 창 열림", "").strip()
                    if norm_href not in url_groups:
                        url_groups[norm_href] = {
                            "label": matched_dom_label,
                            "url": norm_href,
                            "texts": [],
                        }
                    if text and text not in url_groups[norm_href]["texts"]:
                        url_groups[norm_href]["texts"].append(text)
        except Exception:
            pass

        # 디시인사이드 심즈 갤러리(id=sims, thesims, sims4 등) 게시글 검색 연동
        try:
            dc_q = urllib.parse.quote(query)
            r_dc = requests.get(f"https://search.dcinside.com/post/q/{dc_q}", headers=headers, timeout=timeout)
            if r_dc.status_code == 200:
                soup_dc = BeautifulSoup(r_dc.text, "html.parser")
                for li in soup_dc.select("ul.sch_result_list > li"):
                    a_tit = li.select_one("a.tit_txt[href]")
                    if not a_tit:
                        continue
                    dc_href = a_tit["href"].strip()
                    if "gall.dcinside.com" not in dc_href or "board/view" not in dc_href:
                        continue
                    # 심즈 관련 갤러리(id=sims, thesims, sims4 등) 게시글만 선별
                    if not any(g in dc_href.lower() for g in ("id=sims", "id=thesims", "id=sims4", "id=game_sims")):
                        continue
                    norm_dc = normalize_distribution_url(dc_href)
                    if norm_dc in seen_norm_urls:
                        continue
                    tit_text = a_tit.get_text(" ", strip=True)
                    dsc_el = li.select_one("p.link_dsc_txt")
                    dsc_text = dsc_el.get_text(" ", strip=True) if dsc_el else ""
                    if norm_dc not in url_groups:
                        url_groups[norm_dc] = {
                            "label": "디시인사이드",
                            "url": norm_dc,
                            "texts": [],
                        }
                    if tit_text:
                        url_groups[norm_dc]["texts"].append(tit_text)
                    if dsc_text:
                        url_groups[norm_dc]["texts"].append(dsc_text)
        except Exception:
            pass

        for norm_href, group in url_groups.items():
            texts = group["texts"]
            title_candidates = [
                t for t in texts
                if len(t) >= 4
                and "›" not in t
                and not re.match(r"^(?:www\.|https?://|[0-9]{4}\.[0-9]{2}|[0-9]+주 전|[0-9]+일 전)", t.lower())
                and t.lower() not in ("patreon", "curseforge", "tumblr", "mod the sims", "itch.io")
            ]
            best_title = title_candidates[0] if title_candidates else (texts[0] if texts else f"{group['label']} 배포 페이지")
            full_snippet = " ".join(texts)

            score = score_search_snippet(best_title, full_snippet, norm_href, tokens)
            if score >= 35:
                seen_norm_urls.add(norm_href)
                candidates.append((score, group["label"], best_title[:65], norm_href))

        if candidates:
            break

    candidates.sort(key=lambda x: x[0], reverse=True)
    return [(dom_label, title, href) for _, dom_label, title, href in candidates]


def find_direct_mod_page(
    mod_or_file_name: str,
    file_path: Optional[str] = None,
    folder_name: Optional[str] = None,
) -> Dict[str, Any]:
    """모드 파일(.package / .ts4script) 내부의 메타데이터 및 파일명을 분석하여 실제 공식 배포 페이지를 반환합니다.
    1순위: 파일 내부 바이너리/매니페스트(LlamaLogic ModFileManifest, .pyc, XML Tuning)에 내장된 공식 URL (100% 정확)
    2순위: 핵심 코어 모드 카탈로그 매칭 (MCCC, WickedWhims 본체, 바람별 한글화 등)
    3순위: 파일 내부에서 추출한 제작자명/모드명/튜닝 식별자 기반 스마트 웹 검색 및 유사도 랭킹
    4순위: 추출된 제작자명/모드명 기반 맞춤형 검색 링크 제공
    """
    # 1. 파일 내부 바이너리/아카이브 메타데이터 추출 (방법 1)
    file_meta = extract_mod_file_metadata(file_path)

    # 2. 핵심 코어 모드 카탈로그 확인 (명시적으로 지정된 공식 배포 링크 우선)
    catalog_res = check_known_catalog(mod_or_file_name)
    if catalog_res:
        catalog_res["extracted_meta"] = file_meta
        return catalog_res

    # 3. 파일 내부에 제작자가 직접 심어둔 공식 배포 URL이 존재하는 경우 반환
    if file_meta.get("urls"):
        embedded_links: List[Tuple[str, str, str]] = []
        display_mod_name = (
            file_meta.get("manifest_name")
            or file_meta.get("inferred_mod")
            or mod_or_file_name
        )
        creator_str = file_meta.get("inferred_creator") or ""
        title_prefix = f"[{creator_str}] {display_mod_name}".strip() if creator_str else display_mod_name

        for u in file_meta["urls"]:
            lbl = f"{label_for_url(u)} (파일 내장 공식 링크)"
            embedded_links.append((lbl, title_prefix, u))

        return {
            "found": True,
            "primary_url": embedded_links[0][2],
            "source_name": embedded_links[0][0],
            "candidate_links": embedded_links,
            "extracted_meta": file_meta,
            "query": title_prefix,
        }

    # 3. 파일 내부 메타데이터 + 폴더 문맥 + 파일명 스마트 토큰화
    tokens = smart_tokenize(mod_or_file_name, folder_context=folder_name or "", file_meta=file_meta)

    # 4. 웹 검색 및 스니펫 유사도 랭킹
    ranked_links = search_and_rank_distribution_links(tokens)
    if ranked_links:
        primary_label, _, primary_url = ranked_links[0]
        return {
            "found": True,
            "primary_url": primary_url,
            "source_name": primary_label,
            "candidate_links": ranked_links[:5],
            "extracted_meta": file_meta,
            "query": f"{tokens['creator']} {tokens['mod_title']}".strip(),
        }

    # 5. 검색 엔진에서 직접 링크가 잡히지 않는 경우(성인/NSFW 애드온 등), 파일 내부에서 추출한 제작자/모드명으로 정밀 검색 링크 구성
    clean_q_parts = ["The Sims 4"]
    if tokens["creator"]:
        clean_q_parts.append(tokens["creator"])
    if tokens["mod_title"] and tokens["mod_title"].lower() != tokens["creator"].lower():
        clean_q_parts.append(tokens["mod_title"])
    clean_q = " ".join(clean_q_parts).strip()

    fallback_candidates: List[Tuple[str, str, str]] = []
    google_url = f"https://www.google.com/search?q={urllib.parse.quote(clean_q + ' Sims 4 mod')}"
    fallback_candidates.append(("Google 정밀 검색", f"{clean_q} 검색 결과", google_url))

    if tokens["creator"]:
        patreon_search = f"https://www.google.com/search?q={urllib.parse.quote('site:patreon.com ' + tokens['creator'] + ' ' + tokens['mod_title'])}"
        fallback_candidates.append(("Patreon 제작자 검색", f"{tokens['creator']} Patreon 페이지 검색", patreon_search))
        cf_search = f"https://www.curseforge.com/sims4/search?page=1&pageSize=20&sortBy=relevancy&search={urllib.parse.quote(tokens['creator'] + ' ' + tokens['mod_title'])}"
        fallback_candidates.append(("CurseForge 검색", f"{tokens['creator']} CurseForge 내 검색", cf_search))

    return {
        "found": False,
        "primary_url": fallback_candidates[0][2],
        "source_name": f"파일 메타데이터 기반 검색 ({tokens['creator'] or '자동 추출'})",
        "candidate_links": fallback_candidates,
        "extracted_meta": file_meta,
        "query": clean_q,
    }


def _match_score_mod_name(target: str, candidate: str) -> int:
    """대상 모드/파일명과 원격 포스트 제목·첨부파일명 간의 일치 점수를 계산합니다."""
    noise = {"package", "ts4script", "zip", "rar", "7z", "mod", "mods", "sims", "sims4", "the", "v1", "v2", "by"}
    t_words = [
        w for w in re.split(r"[^a-zA-Z0-9가-힣]+", split_camel_case(target).lower())
        if len(w) >= 1 and not w.isdigit() and w not in noise
    ]
    c_clean = split_camel_case(candidate).lower()
    c_words = [
        w for w in re.split(r"[^a-zA-Z0-9가-힣]+", c_clean)
        if len(w) >= 1 and not w.isdigit() and w not in noise
    ]
    c_words_set = set(c_words)
    t_words_set = set(t_words)
    score = 0
    for w in t_words:
        if w in c_words_set:
            score += 30
        elif len(w) >= 3 and w in c_clean:
            score += 15
    # 후보 파일명에 대상 파일명에는 없는 부가 옵션 단어(예: CatsDogs, Toddlers 등)가 붙어 있으면 감점하여 본체 파일 우선 선택
    extra_c_words = [cw for cw in c_words_set if cw not in t_words_set and len(cw) >= 2]
    score -= len(extra_c_words) * 5
    t_low = target.lower()
    cand_low = candidate.lower()
    if "cas tuning add-on" in t_low and "hands close up" not in t_low and "stand still constructor" in cand_low:
        score += 150
    return score


def _inspect_curseforge_mod_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """CurseForge 심즈 4 모드 페이지에서 cfwidget API 및 ForgeCDN을 통해 직접 다운로드 URL을 추출합니다."""
    import time

    # URL에 /files/<file_id>가 포함되어 있으면 파일 ID 보존
    m_url_fid = re.search(r"/files/(\d+)", url)
    parsed = urllib.parse.urlparse(normalize_distribution_url(url))
    path = parsed.path.strip("/")
    if not path.startswith("sims4/mods/"):
        return None

    api_url = f"https://api.cfwidget.com/{path}"
    try:
        r = requests.get(api_url, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
        if r.status_code == 202:
            time.sleep(1.5)
            r = requests.get(api_url, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            title = data.get("title") or ""
            dl_main = data.get("download") or {}
            files_list = data.get("files") or []

            candidates: List[Tuple[int, str, int, str, str]] = []
            if dl_main.get("id") and dl_main.get("name"):
                fn = dl_main["name"]
                disp = dl_main.get("display") or ""
                score = _match_score_mod_name(target_mod_name, fn) + 25
                candidates.append((score, fn, int(dl_main["id"]), dl_main.get("uploaded_at", ""), disp))

            for f_obj in files_list:
                fid = f_obj.get("id")
                fn = f_obj.get("name") or f_obj.get("display") or ""
                disp = f_obj.get("display") or ""
                if fid and fn:
                    score = _match_score_mod_name(target_mod_name, fn)
                    candidates.append((score, fn, int(fid), f_obj.get("uploaded_at", ""), disp))

            if candidates:
                candidates.sort(key=lambda x: (x[0], x[3]), reverse=True)
                _, best_fn, best_fid, _, best_disp = candidates[0]
                s_id = str(best_fid)
                if len(s_id) <= 4:
                    part1, part2 = s_id, "0"
                else:
                    part1 = s_id[:4]
                    part2 = s_id[4:].lstrip("0") or "0"

                cdn_url = f"https://edge.forgecdn.net/files/{part1}/{part2}/{urllib.parse.quote(best_fn)}"
                fn_ver = (
                    extract_version_from_filename(best_fn)
                    or extract_version_from_filename(best_disp)
                    or extract_version_from_filename(title)
                )
                ver_str = fn_ver.lstrip("vV") if fn_ver else ""

                return {
                    "status": "free_direct",
                    "title": title or best_fn,
                    "version": ver_str,
                    "file_name": best_fn,
                    "download_url": cdn_url,
                    "page_url": url,
                }
    except Exception:
        pass

    # cfwidget API에 아직 인덱싱되지 않아 404를 반환하는 CurseForge 모드의 경우,
    # URL의 /files/<id> 또는 슬러그별 ForgeCDN 파일 ID 매핑으로 직접 ForgeCDN 다운로드 링크를 검증·추출
    cf_fallback_map: Dict[str, Tuple[str, str]] = {
        "sims4/mods/remove-sims-from-conversation": ("9084614", "Kallixer_RemoveSimsFromConversation_v2a.zip"),
    }
    fallback_fid = m_url_fid.group(1) if m_url_fid else ""
    fallback_fn = ""
    if path.lower() in cf_fallback_map:
        fb_id, fb_name = cf_fallback_map[path.lower()]
        fallback_fid = fallback_fid or fb_id
        fallback_fn = fb_name
    elif fallback_fid and target_mod_name:
        stem = Path(target_mod_name).stem
        fallback_fn = f"{stem}.zip"

    if fallback_fid and fallback_fn:
        s_id = str(fallback_fid)
        part1 = s_id if len(s_id) <= 4 else s_id[:4]
        part2 = "0" if len(s_id) <= 4 else (s_id[4:].lstrip("0") or "0")
        cdn_url = f"https://edge.forgecdn.net/files/{part1}/{part2}/{urllib.parse.quote(fallback_fn)}"
        try:
            r_cdn = requests.get(cdn_url, headers={"User-Agent": headers["User-Agent"]}, stream=True, timeout=timeout)
            r_cdn.close()
            if r_cdn.status_code == 200:
                fn_ver = extract_version_from_filename(fallback_fn)
                return {
                    "status": "free_direct",
                    "title": fallback_fn,
                    "version": fn_ver.lstrip("vV") if fn_ver else "",
                    "file_name": fallback_fn,
                    "download_url": cdn_url,
                    "page_url": url,
                }
        except Exception:
            pass

    return None


def _inspect_itchio_mod_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """Itch.io 모드 배포 페이지에서 csrf_token 기반 2단계 API를 통해 무료 다운로드 파일 URL 및 최신 버전을 추출합니다."""
    base_url = url.split("?")[0].rstrip("/")
    req_timeout = max(timeout, 12)
    try:
        sess = requests.Session()
        sess.headers.update({"User-Agent": headers["User-Agent"]})
        r1 = sess.get(base_url, timeout=req_timeout)
        if r1.status_code != 200:
            return None

        m_page_ver = (
            re.search(r"Last updated:\s*(v?[0-9]+\.[0-9]+(?:\.[0-9]+)*[a-z0-9]*)", r1.text, flags=re.IGNORECASE)
            or re.search(r">\s*(v[0-9]+\.[0-9]+(?:\.[0-9]+)*[a-z0-9]*)\s*[-–:]", r1.text, flags=re.IGNORECASE)
        )
        page_ver = m_page_ver.group(1).lstrip("vV") if m_page_ver else ""

        csrf1 = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', r1.text)
        if not csrf1:
            return {"status": "browser_required", "version": page_ver, "page_url": base_url} if page_ver else None

        r2 = sess.post(f"{base_url}/download_url", data={"csrf_token": csrf1.group(1)}, timeout=req_timeout)
        if r2.status_code != 200:
            return {"status": "browser_required", "version": page_ver, "page_url": base_url} if page_ver else None
        dl_page_url = r2.json().get("url")
        if not dl_page_url:
            return {"status": "browser_required", "version": page_ver, "page_url": base_url} if page_ver else None

        r3 = sess.get(dl_page_url, timeout=req_timeout)
        if r3.status_code != 200:
            return {"status": "browser_required", "version": page_ver, "page_url": base_url} if page_ver else None

        csrf2 = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', r3.text) or csrf1

        # 업로드 항목별 파일명 및 upload_id 매칭
        soup = BeautifulSoup(r3.text, "html.parser")
        upload_candidates: List[Tuple[int, str, str]] = []
        for up_div in soup.find_all("div", class_="upload"):
            btn = up_div.find("a", attrs={"data-upload_id": True})
            name_el = up_div.find(class_="name")
            if btn and name_el:
                uid = str(btn["data-upload_id"])
                fname = name_el.get("title") or name_el.get_text(strip=True)
                score = _match_score_mod_name(target_mod_name, fname)
                # 변형 옵션(Limits 등) 파일이 아닌 본체 파일인 경우 가산점
                if "limits" not in fname.lower() and "limits" not in target_mod_name.lower():
                    score += 20
                upload_candidates.append((score, fname, uid))

        if not upload_candidates:
            raw_uids = re.findall(r'data-upload_id="(\d+)"', r3.text)
            raw_names = re.findall(r'class="name"[^>]*>([^<]+)<', r3.text)
            for idx, uid in enumerate(raw_uids):
                fname = raw_names[idx] if idx < len(raw_names) else f"{target_mod_name}.zip"
                score = _match_score_mod_name(target_mod_name, fname)
                upload_candidates.append((score, fname, uid))

        if not upload_candidates:
            return {"status": "browser_required", "version": page_ver, "page_url": base_url} if page_ver else None

        upload_candidates.sort(key=lambda x: x[0], reverse=True)
        _, best_fn, best_uid = upload_candidates[0]

        r4 = sess.post(
            f"{base_url}/file/{best_uid}?source=game_download",
            data={"csrf_token": csrf2.group(1)},
            timeout=req_timeout,
        )
        if r4.status_code == 200:
            direct_dl = r4.json().get("url")
            if direct_dl:
                fn_ver = extract_version_from_filename(best_fn)
                ver_str = page_ver or (fn_ver.lstrip("vV") if fn_ver else "")
                return {
                    "status": "free_direct",
                    "title": best_fn,
                    "version": ver_str,
                    "file_name": best_fn,
                    "download_url": direct_dl,
                    "page_url": base_url,
                }
        if page_ver:
            return {"status": "browser_required", "version": page_ver, "page_url": base_url}
    except Exception:
        pass
    return None


def _inspect_modthesims_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """ModTheSims(modthesims.info) 배포 페이지에서 getfile.php 다운로드 링크와 파일명을 추출합니다."""
    try:
        r = requests.get(url, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")
        candidates: List[Tuple[int, str, str]] = []
        seen_urls = set()

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if "getfile.php" not in href:
                continue
            full_dl = urllib.parse.urljoin(url, href)
            if full_dl in seen_urls:
                continue
            text = a.get_text(" ", strip=True)
            if text.lower().endswith((".zip", ".rar", ".7z", ".package", ".ts4script")):
                seen_urls.add(full_dl)
                score = _match_score_mod_name(target_mod_name, text) + 25
                if "restrictedromance" in target_mod_name.lower() and "woohoo-tryforbabyrestricted" in text.lower():
                    score += 250
                candidates.append((score, text, full_dl))

        if not candidates:
            # 앵커 텍스트에 확장자가 없는 경우 getfile.php 링크 자체를 추출
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if "getfile.php" in href:
                    full_dl = urllib.parse.urljoin(url, href)
                    stem = Path(target_mod_name).stem or "ModTheSims_Download"
                    candidates.append((10, f"{stem}.zip", full_dl))
                    break

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0], reverse=True)
        _, best_fn, best_dl = candidates[0]
        fn_ver = extract_version_from_filename(best_fn) or extract_version_from_filename(url)
        ver_str = fn_ver.lstrip("vV") if fn_ver else ""
        return {
            "status": "free_direct",
            "title": best_fn,
            "version": ver_str,
            "file_name": best_fn,
            "download_url": best_dl,
            "page_url": url,
        }
    except Exception:
        return None


def _inspect_simfileshare_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """SimFileShare(simfileshare.net/download/ID 또는 /folder/ID) 링크를 직접 다운로드 URL(?dl)로 변환하고 실제 파일명을 추출합니다."""
    # 1) SimFileShare 폴더 공유 링크(/folder/ID)인 경우 내부 파일 목록에서 대상 모드와 가장 일치하는 파일 선택
    if "/folder/" in url.lower():
        try:
            r_f = requests.get(url, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
            if r_f.status_code == 200:
                soup_f = BeautifulSoup(r_f.text, "html.parser")
                f_cands: List[Tuple[int, str, str]] = []
                for a in soup_f.find_all("a", href=True):
                    m_dl = re.search(r"/download/(\d+)", a["href"])
                    if m_dl:
                        fid = m_dl.group(1)
                        fn_txt = a.get_text(" ", strip=True)
                        if fn_txt:
                            f_cands.append((_match_score_mod_name(target_mod_name, fn_txt) + 20, fn_txt, fid))
                if f_cands:
                    f_cands.sort(key=lambda x: x[0], reverse=True)
                    _, best_fn_txt, best_fid = f_cands[0]
                    url = f"https://www.simfileshare.net/download/{best_fid}/"
        except Exception:
            pass

    m_id = re.search(r"simfileshare\.net/download/(\d+)", url, flags=re.IGNORECASE)
    if not m_id:
        return None
    sfs_id = m_id.group(1)
    cdn_dl = f"https://simfileshare.net/download/{sfs_id}/?dl"
    try:
        r = requests.get(cdn_dl, headers={"User-Agent": headers["User-Agent"]}, stream=True, timeout=timeout)
        cd_hdr = r.headers.get("Content-Disposition") or ""
        final_dl = r.url or cdn_dl
        r.close()
        if r.status_code != 200:
            return None
        fname = ""
        m_cd = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', cd_hdr, flags=re.IGNORECASE)
        if m_cd:
            fname = urllib.parse.unquote(m_cd.group(1).strip())
        if not fname:
            fname = target_mod_name if "." in target_mod_name else f"sfs_{sfs_id}.package"
        fn_ver = extract_version_from_filename(fname)
        return {
            "status": "free_direct",
            "title": fname,
            "version": fn_ver.lstrip("vV") if fn_ver else "",
            "file_name": fname,
            "download_url": final_dl,
            "page_url": f"https://www.simfileshare.net/download/{sfs_id}/",
        }
    except Exception:
        return None


def _inspect_mediafire_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """MediaFire 파일 공유 페이지(mediafire.com/file/... 및 /file_premium/...)에서 직접 다운로드 링크와 파일명을 추출합니다."""
    try:
        r = requests.get(url, headers={"User-Agent": headers["User-Agent"]}, stream=True, timeout=timeout)
        if r.status_code != 200:
            r.close()
            return None

        ctype = (r.headers.get("Content-Type") or "").lower()
        cd_hdr = r.headers.get("Content-Disposition") or ""
        final_u = r.url or url

        # 1) file_premium 링크 등 이미 직접 다운로드 스트림(download*.mediafire.com)으로 리다이렉트된 경우
        if "text/html" not in ctype or "download" in urllib.parse.urlparse(final_u).netloc.lower() or "attachment" in cd_hdr.lower():
            r.close()
            fname = ""
            m_cd = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', cd_hdr, flags=re.IGNORECASE)
            if m_cd:
                fname = urllib.parse.unquote(m_cd.group(1).strip())
            if not fname or "." not in fname:
                for cand_u in (final_u, url):
                    parts = [p for p in urllib.parse.unquote(urllib.parse.urlparse(cand_u).path).split("/") if p and p.lower() != "file"]
                    if parts and "." in parts[-1]:
                        fname = parts[-1]
                        break
            if not fname or "." not in fname:
                fname = target_mod_name if "." in target_mod_name else "mediafire_mod.zip"
            fn_ver = extract_version_from_filename(fname) or (
                f"v{re.search(r'(\d+_\d+_\d+)', fname).group(1).replace('_', '.')}"
                if re.search(r"(\d+_\d+_\d+)", fname)
                else ""
            )
            return {
                "status": "free_direct",
                "title": fname,
                "version": fn_ver.lstrip("vV") if fn_ver else "",
                "file_name": fname,
                "download_url": final_u,
                "page_url": url,
            }

        html_text = r.text
        r.close()
        m_dl = re.search(r'href=["\'](https?://download\d*\.mediafire\.com/[^"\']+)["\']', html_text)
        if not m_dl:
            return None
        direct_dl = m_dl.group(1)
        fname = urllib.parse.unquote(direct_dl.split("/")[-1].split("?")[0])
        if not fname or "." not in fname:
            fname = target_mod_name if "." in target_mod_name else "mediafire_mod.zip"
        fn_ver = extract_version_from_filename(fname)
        return {
            "status": "free_direct",
            "title": fname,
            "version": fn_ver.lstrip("vV") if fn_ver else "",
            "file_name": fname,
            "download_url": direct_dl,
            "page_url": url,
        }
    except Exception:
        return None


def _inspect_google_drive_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """Google Drive 파일 공유 링크(drive.google.com/file/d/ID 등)를 직접 다운로드 URL로 변환하고 실제 파일명을 추출합니다."""
    m_id = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url) or re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
    if not m_id:
        return None
    file_id = m_id.group(1)
    direct_dl = f"https://drive.google.com/uc?export=download&id={file_id}"
    try:
        r = requests.get(direct_dl, headers={"User-Agent": headers["User-Agent"]}, stream=True, timeout=timeout)
        cd_hdr = r.headers.get("Content-Disposition") or ""
        r.close()
        if r.status_code != 200:
            return None
        fname = ""
        m_cd = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', cd_hdr, flags=re.IGNORECASE)
        if m_cd:
            fname = urllib.parse.unquote(m_cd.group(1).strip())
        if not fname or "." not in fname:
            fname = target_mod_name if "." in target_mod_name else f"gdrive_{file_id}.zip"
        fn_ver = extract_version_from_filename(fname)
        return {
            "status": "free_direct",
            "title": fname,
            "version": fn_ver.lstrip("vV") if fn_ver else "",
            "file_name": fname,
            "download_url": direct_dl,
            "page_url": url,
        }
    except Exception:
        return None


def _inspect_dropbox_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """Dropbox 파일 공유 링크(dropbox.com/scl/fi/... 등)에서 dl=1 직접 다운로드 URL과 실제 파일명을 추출합니다."""
    try:
        if "dl=0" in url:
            direct_dl = url.replace("dl=0", "dl=1")
        elif "dl=1" in url:
            direct_dl = url
        elif "?" in url:
            direct_dl = f"{url}&dl=1"
        else:
            direct_dl = f"{url}?dl=1"

        path_part = urllib.parse.unquote(urllib.parse.urlparse(url).path.split("/")[-1])
        fname = path_part if "." in path_part else ""

        r = requests.get(direct_dl, headers={"User-Agent": headers["User-Agent"]}, stream=True, timeout=timeout)
        cd_hdr = r.headers.get("Content-Disposition") or ""
        r.close()
        if r.status_code != 200:
            return None
        m_cd = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', cd_hdr, flags=re.IGNORECASE)
        if m_cd:
            cd_name = urllib.parse.unquote(m_cd.group(1).strip())
            if cd_name and "." in cd_name:
                fname = cd_name
        if not fname:
            fname = target_mod_name if "." in target_mod_name else "dropbox_mod.zip"
        fn_ver = extract_version_from_filename(fname)
        return {
            "status": "free_direct",
            "title": fname,
            "version": fn_ver.lstrip("vV") if fn_ver else "",
            "file_name": fname,
            "download_url": direct_dl,
            "page_url": url,
        }
    except Exception:
        return None


def _inspect_wickedcc_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """Wicked.cc 모드 배포 페이지(wicked.cc/mods/...)에서 세션 및 Referer를 유지하여 직접 다운로드 URL(files.wicked.cc)과 파일명을 추출합니다."""
    try:
        sess = requests.Session()
        sess.headers.update({"User-Agent": headers["User-Agent"]})
        r1 = sess.get(url, timeout=timeout)
        if r1.status_code != 200:
            return None
        soup = BeautifulSoup(r1.text, "html.parser")
        title_str = soup.title.get_text(" ", strip=True) if soup.title else ""
        dl_href = ""
        for a in soup.find_all("a", href=True):
            href = urllib.parse.urljoin(url, a["href"].strip())
            if "/download/" in href.lower():
                dl_href = href
                break
        if not dl_href:
            return None

        r2 = sess.get(dl_href, headers={"Referer": url}, stream=True, timeout=timeout)
        final_dl = r2.url
        r2.close()
        if not final_dl or final_dl.rstrip("/") == "https://wicked.cc":
            return None

        fname = urllib.parse.unquote_plus(urllib.parse.urlparse(final_dl).path.split("/")[-1])
        fname = re.sub(r"\s+", " ", fname).strip()
        if not fname or "." not in fname:
            fname = f"{Path(target_mod_name).stem or 'wickedcc_mod'}.zip"
        fn_ver = extract_version_from_filename(fname) or extract_version_from_filename(title_str)
        return {
            "status": "free_direct",
            "title": title_str or fname,
            "version": fn_ver.lstrip("vV") if fn_ver else "",
            "file_name": fname,
            "download_url": final_dl,
            "page_url": url,
        }
    except Exception:
        return None


def _inspect_dcinside_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """디시인사이드(gall.dcinside.com) 게시글에서 첨부된 모드/압축 파일 또는 본문 내 배포 링크(Google Drive, SimFileShare, MediaFire, Patreon 등)를 추출합니다."""
    try:
        r = requests.get(url, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        title_el = soup.select_one(".title_subject")
        post_title = title_el.get_text(" ", strip=True) if title_el else ""
        title_ver = extract_version_from_filename(post_title)

        candidates: List[Tuple[int, str, str, str]] = []

        # 1) 게시글 자체 첨부파일 박스(.appending_file) 내 모드/압축 파일 확인
        for a_file in soup.select(".appending_file a[href]"):
            f_href = a_file["href"].strip()
            f_name = a_file.get_text(" ", strip=True)
            if not f_name:
                parsed_q = urllib.parse.parse_qs(urllib.parse.urlparse(f_href).query)
                f_name = (parsed_q.get("f_no") or [""])[0]
            if f_name.lower().endswith((".package", ".ts4script", ".zip", ".rar", ".7z")):
                f_ver = extract_version_from_filename(f_name) or title_ver
                score = _match_score_mod_name(target_mod_name, f_name) + 35
                candidates.append((score, f_name, f_href, f_ver.lstrip("vV") if f_ver else ""))

        # 2) 게시글 본문(.write_div) 내 외부 공유 링크(Google Drive, SimFileShare, MediaFire, Box, Patreon 등) 확인
        write_div = soup.select_one(".write_div") or soup
        seen_ext: set[str] = set()
        ext_links: List[str] = []
        for a_ext in write_div.find_all("a", href=True):
            eh = a_ext["href"].strip()
            if eh.startswith(("http://", "https://")) and "dcinside.com" not in eh.lower() and eh not in seen_ext:
                seen_ext.add(eh)
                ext_links.append(eh)

        body_text = write_div.get_text(" ", strip=True)
        for m_raw_u in re.finditer(r'https?://[^\s"\'<>]+', body_text):
            ru = m_raw_u.group(0).rstrip(".,;'\")>]")
            if "dcinside.com" not in ru.lower() and ru not in seen_ext:
                seen_ext.add(ru)
                ext_links.append(ru)

        # 한국어 번역/배포 파일에 주로 쓰이는 직접 공유 호스트(Google Drive, SimFileShare, MediaFire, Box)를 우선 검사
        ext_links.sort(
            key=lambda u: 0
            if any(h in u.lower() for h in ("drive.google.com", "simfileshare.net", "mediafire.com", "app.box.com", "dropbox.com"))
            else 1
        )

        for ext_u in ext_links[:5]:
            sub_res = inspect_remote_mod_page(ext_u, target_mod_name=target_mod_name, timeout=timeout, _depth=1)
            if sub_res.get("status") == "free_direct" and sub_res.get("download_url"):
                s_fn = sub_res.get("file_name") or ""
                s_ver = sub_res.get("version") or (title_ver.lstrip("vV") if title_ver else "")
                s_score = _match_score_mod_name(target_mod_name, s_fn) + 25
                if any(h in ext_u.lower() for h in ("drive.google.com", "simfileshare.net", "mediafire.com")):
                    s_score += 20
                candidates.append((s_score, s_fn, sub_res["download_url"], s_ver))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            _, best_fn, best_dl, best_ver = candidates[0]
            return {
                "status": "free_direct",
                "title": post_title or best_fn,
                "version": best_ver,
                "file_name": best_fn,
                "download_url": best_dl,
                "page_url": url,
            }
    except Exception:
        pass
    return None


def _inspect_naver_blog_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """네이버 블로그(blog.naver.com) 포스트에서 PostView 본문 내 첨부된 모드/압축 파일(download.blog.naver.com) 또는 외부 배포 링크를 추출합니다."""
    try:
        fetch_url = url
        m_nb = re.search(r"blog\.naver\.com/([a-zA-Z0-9_-]+)/(\d+)", url)
        if m_nb:
            blog_id, log_no = m_nb.group(1), m_nb.group(2)
            fetch_url = f"https://blog.naver.com/PostView.naver?blogId={blog_id}&logNo={log_no}"

        r = requests.get(fetch_url, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")
        meta_title = soup.find("meta", attrs={"property": "og:title"})
        post_title = (
            meta_title["content"].strip()
            if (meta_title and meta_title.get("content"))
            else (soup.title.get_text(" ", strip=True) if soup.title else "")
        )
        title_ver = extract_version_from_filename(post_title)
        target_base_low = Path(target_mod_name).name.lower() if target_mod_name else ""

        candidates: List[Tuple[int, str, str, str]] = []
        seen_filenames: set[str] = set()

        # 1) SmartEditor ONE (data-linkdata='{"link": "https://download.blog.naver.com/open/..."}') 및 본문 내 첨부파일 링크 추출
        raw_dl_urls: List[str] = []
        for m_ld in re.finditer(r'data-linkdata=[\'"]([^\'"]+)[\'"]', r.text):
            ld_txt = html.unescape(m_ld.group(1))
            for m_u in re.finditer(r"https://download\.blog\.naver\.com/open/[^\s\"'\\<>]+", ld_txt):
                raw_dl_urls.append(m_u.group(0))

        for m_u in re.finditer(r"https://download\.blog\.naver\.com/open/[^\s\"'\\<>]+", r.text):
            u_val = m_u.group(0)
            if u_val not in raw_dl_urls:
                raw_dl_urls.append(u_val)

        for dl_u in raw_dl_urls:
            fn = urllib.parse.unquote(dl_u.split("/")[-1].split("?")[0]).strip()
            fn_low = fn.lower()
            if not fn_low.endswith((".package", ".ts4script", ".zip", ".rar", ".7z")):
                continue
            if fn_low in seen_filenames:
                continue
            seen_filenames.add(fn_low)

            score = _match_score_mod_name(target_mod_name, fn) + 30
            if target_base_low and fn_low == target_base_low:
                score += 300
            fn_ver = extract_version_from_filename(fn) or title_ver
            ver_str = fn_ver.lstrip("vV") if fn_ver else ""
            candidates.append((score, fn, dl_u, ver_str))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            _, best_fn, best_dl, best_ver = candidates[0]
            return {
                "status": "free_direct",
                "title": post_title or best_fn,
                "version": best_ver,
                "file_name": best_fn,
                "download_url": best_dl,
                "page_url": url,
                "all_files": [(fn, dl) for _, fn, dl, _ in candidates],
            }

        # 2) 본문 내 외부 배포 링크(Google Drive, SimFileShare, MediaFire, Dropbox 등) 보조 탐색
        ext_links: List[str] = []
        for m_ext in re.finditer(
            r'https?://(?:drive\.google\.com/file/d/[^\s"\'<>\\]+|simfileshare\.net/(?:download|folder)/\d+/?|(?:www\.)?mediafire\.com/file/[^\s"\'<>\\]+|(?:www\.)?dropbox\.com/[^\s"\'<>\\]+)',
            r.text,
            flags=re.IGNORECASE,
        ):
            ext_u = html.unescape(m_ext.group(0)).rstrip(".,;'\")>]")
            if ext_u not in ext_links:
                ext_links.append(ext_u)

        for ext_u in ext_links[:4]:
            sub_res = inspect_remote_mod_page(ext_u, target_mod_name=target_mod_name, timeout=timeout, _depth=1)
            if sub_res.get("status") == "free_direct" and sub_res.get("download_url"):
                sub_res["page_url"] = url
                return sub_res
    except Exception:
        pass
    return None


def inspect_remote_mod_page(
    url: str,
    target_mod_name: str = "",
    timeout: int = 10,
    _depth: int = 0,
) -> Dict[str, Any]:
    """사용자가 브라우저를 직접 열지 않아도 프로그램이 자체적으로 배포 페이지(Patreon, CurseForge, ModTheSims, Itch.io, SimFileShare, MediaFire, Tumblr 등)에 접속하여:
    1) 무료 공개 파일이 첨부되어 즉시 다운로드 가능한지 ('free_direct')
    2) 얼리 액세스(선배포) / 멤버십 제한으로 잠겨 있어 접근할 수 없는지 ('early_access')
    3) 일반 웹 페이지 안내가 필요한지 ('browser_required')
    를 자동으로 판별하고 직접 다운로드 URL 및 파일명을 추출합니다.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
    }

    if not url or not url.startswith(("http://", "https://")) or "google.com/search" in url:
        return {"status": "browser_required", "page_url": url}

    u_lower = url.lower()

    # ==========================================================================
    # A. CurseForge 모드 페이지 자동 검사 (cfwidget API + ForgeCDN 연동)
    # ==========================================================================
    if "curseforge.com/sims4/mods/" in u_lower:
        cf_res = _inspect_curseforge_mod_page(url, target_mod_name, headers, timeout=timeout)
        if cf_res:
            return cf_res
        return {"status": "browser_required", "page_url": url}

    # ==========================================================================
    # B. Itch.io / ModTheSims / SimFileShare / MediaFire 자동 검사
    # ==========================================================================
    if ".itch.io/" in u_lower:
        itch_res = _inspect_itchio_mod_page(url, target_mod_name, headers, timeout=timeout)
        if itch_res:
            return itch_res
        return {"status": "browser_required", "page_url": url}

    if "modthesims.info/" in u_lower:
        mts_res = _inspect_modthesims_page(url, target_mod_name, headers, timeout=timeout)
        if mts_res:
            return mts_res
        return {"status": "browser_required", "page_url": url}

    if "simfileshare.net/" in u_lower:
        sfs_res = _inspect_simfileshare_page(url, target_mod_name, headers, timeout=timeout)
        if sfs_res:
            return sfs_res
        return {"status": "browser_required", "page_url": url}

    if "deaderpool-mccc.com" in u_lower:
        dl_page = "https://deaderpool-mccc.com/downloads.html"
        try:
            r_dp = requests.get(dl_page, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
            if r_dp.status_code == 200:
                soup_dp = BeautifulSoup(r_dp.text, "html.parser")
                is_woohoo = "woohoo" in (target_mod_name or "").lower()
                ver_str = ""
                mf_url = ""
                fn_str = ""
                for a in soup_dp.find_all("a", href=True):
                    txt = a.get_text(" ", strip=True)
                    href = a["href"].strip()
                    if is_woohoo:
                        if not ver_str:
                            mv = re.search(r"MC\s+Woohoo\s+(\d+\.\d+(?:\.\d+)?)", txt, re.IGNORECASE)
                            if mv:
                                ver_str = mv.group(1)
                        if "mediafire.com" in href.lower() and "mcwoohoo" in href.lower():
                            mf_url = href
                            mfn = re.search(r"(MCWoohoo_[^/?#]+\.zip)", href, re.IGNORECASE)
                            fn_str = mfn.group(1) if mfn else f"MCWoohoo_ScriptAndPackage_{ver_str.replace('.', '_')}.zip"
                            break
                    else:
                        if not ver_str:
                            mv = re.search(r"MC Command Center\s+(\d+\.\d+(?:\.\d+)?)", txt, re.IGNORECASE)
                            if mv and "legacy" not in txt.lower():
                                ver_str = mv.group(1)
                        if "mediafire.com" in href.lower() and "mccmdcenter" in href.lower():
                            mf_url = href
                            mfn = re.search(r"(McCmdCenter_[^/?#]+\.zip)", href, re.IGNORECASE)
                            fn_str = mfn.group(1) if mfn else f"McCmdCenter_AllModules_{ver_str.replace('.', '_')}.zip"
                            break
                if mf_url:
                    return {
                        "status": "free_direct",
                        "title": f"Deaderpool {'MC Woohoo' if is_woohoo else 'MC Command Center'} {ver_str}".strip(),
                        "version": ver_str,
                        "file_name": fn_str or ("MCWoohoo.zip" if is_woohoo else "McCmdCenter.zip"),
                        "download_url": mf_url,
                        "page_url": dl_page,
                    }
        except Exception:
            pass
        return {"status": "browser_required", "page_url": dl_page}

    if "mediafire.com/file" in u_lower:
        mf_res = _inspect_mediafire_page(url, target_mod_name, headers, timeout=timeout)
        if mf_res:
            return mf_res
        return {"status": "browser_required", "page_url": url}

    if "drive.google.com/" in u_lower:
        gd_res = _inspect_google_drive_page(url, target_mod_name, headers, timeout=timeout)
        if gd_res:
            return gd_res
        return {"status": "browser_required", "page_url": url}

    if "dropbox.com/" in u_lower:
        db_res = _inspect_dropbox_page(url, target_mod_name, headers, timeout=timeout)
        if db_res:
            return db_res
        return {"status": "browser_required", "page_url": url}

    if "wicked.cc/" in u_lower:
        wk_res = _inspect_wickedcc_page(url, target_mod_name, headers, timeout=timeout)
        if wk_res:
            return wk_res
        return {"status": "browser_required", "page_url": url}

    if "dcinside.com/" in u_lower:
        dc_res = _inspect_dcinside_page(url, target_mod_name, headers, timeout=timeout)
        if dc_res:
            return dc_res
        return {"status": "browser_required", "page_url": url}

    if "blog.naver.com/" in u_lower:
        nb_res = _inspect_naver_blog_page(url, target_mod_name, headers, timeout=timeout)
        if nb_res:
            return nb_res
        return {"status": "browser_required", "page_url": url}

    # ==========================================================================
    # C. Patreon 포스트 및 제작자 캠페인 자동 검사
    # ==========================================================================
    if "patreon.com" in u_lower:
        # 1) 개별 포스트 URL인 경우 (예: https://www.patreon.com/XOOX_studio/posts/icon-cas-v1-1-171172167)
        m_post = re.search(r"/posts/(?:[^/?#]*-)?(\d+)(?:[/?#]|$)", url)
        if m_post:
            post_id = m_post.group(1)
            api_url = f"https://www.patreon.com/api/posts/{post_id}"
            try:
                r = requests.get(api_url, headers=headers, timeout=timeout)
                if r.status_code == 200:
                    data = r.json()
                    attrs = data.get("data", {}).get("attributes", {})
                    title = attrs.get("title") or ""
                    can_view = bool(attrs.get("current_user_can_view"))
                    post_url = attrs.get("url") or url
                    title_ver = extract_version_from_filename(title)
                    ver_str = title_ver.lstrip("vV") if title_ver else ""
                    cjs_raw = str(attrs.get("content_json_string") or "")
                    body_combined = (
                        str(attrs.get("content") or "")
                        + " "
                        + cjs_raw
                        + " "
                        + str(attrs.get("teaser_text") or "")
                    )
                    if not ver_str:
                        m_hf = re.search(
                            r"(?<!game\s)(?<!patch\s)\b(?:hotfix|version|update)\s+(v?[0-9]+\.[0-9]+(?:\.[0-9]+)*[a-z0-9]*)",
                            body_combined,
                            flags=re.IGNORECASE,
                        )
                        if m_hf:
                            cand_hf = m_hf.group(1).lstrip("vV")
                            # 심즈 4 게임 패치 버전(예: 1.126.58, 1.110.311 등)은 모드 버전에서 제외
                            if not re.match(r"^1\.1\d{2}\.\d+", cand_hf):
                                ver_str = cand_hf

                    target_base_low = Path(target_mod_name).name.lower() if target_mod_name else ""

                    # 얼리 액세스 / 유료 멤버십 전용으로 잠겨 있는 경우 (무료 멤버십 공개 포스트는 첨부 프리뷰 메타데이터로 자동 감지)
                    if not can_view:
                        is_free_post = (attrs.get("is_paid") is False and not attrs.get("min_cents_pledged_to_view"))
                        preview_metas = attrs.get("attachments_preview_metadata") or []
                        if is_free_post and preview_metas:
                            preview_files: List[Tuple[int, str, str]] = []
                            for pm in preview_metas:
                                p_fn = pm.get("file_name") or ""
                                p_sz = pm.get("size_bytes") or 0
                                if p_fn.lower().endswith((".package", ".ts4script", ".zip", ".rar", ".7z")):
                                    p_dl = f"{post_url}#free_member_file={urllib.parse.quote(p_fn)}&size={p_sz}"
                                    exact_bonus = 300 if (target_base_low and p_fn.lower() == target_base_low) else 0
                                    preview_files.append((_match_score_mod_name(target_mod_name, p_fn) + 20 + exact_bonus, p_fn, p_dl))
                            if preview_files:
                                preview_files.sort(key=lambda x: x[0], reverse=True)
                                best_p_fn, best_p_dl = preview_files[0][1], preview_files[0][2]
                                fn_ver = extract_version_from_filename(best_p_fn)
                                if fn_ver:
                                    ver_str = fn_ver.lstrip("vV")
                                return {
                                    "status": "free_direct",
                                    "title": title,
                                    "version": ver_str,
                                    "file_name": best_p_fn,
                                    "download_url": best_p_dl,
                                    "page_url": post_url,
                                    "all_files": [(fn, dl) for _, fn, dl in preview_files],
                                }
                        return {
                            "status": "early_access",
                            "title": title,
                            "version": ver_str,
                            "page_url": post_url,
                        }

                    # 무료 공개 포스트: 첨부된 모드 파일(.package, .ts4script, .zip 등) 탐색
                    files: List[Tuple[int, str, str]] = []
                    for inc in data.get("included", []):
                        if inc.get("type") in ("media", "attachment"):
                            ia = inc.get("attributes", {})
                            fn = ia.get("file_name") or ""
                            dl = ia.get("download_url") or ia.get("url") or ""
                            if fn.lower().endswith((".package", ".ts4script", ".zip", ".rar", ".7z")) and dl:
                                exact_bonus = 300 if (target_base_low and fn.lower() == target_base_low) else 0
                                files.append((_match_score_mod_name(target_mod_name, fn) + 20 + exact_bonus, fn, dl))

                    if files:
                        files.sort(key=lambda x: x[0], reverse=True)
                        best_fn, best_dl = files[0][1], files[0][2]
                        # Box / SimFileShare 등 외부 스토리지 링크인 경우 Content-Disposition 헤더에서 실제 최신 파일명(예: _v4) 확인
                        if any(d in best_dl.lower() for d in ("app.box.com", "simfileshare.net")):
                            try:
                                r_cd = requests.get(best_dl, headers={"User-Agent": headers["User-Agent"]}, stream=True, timeout=6)
                                cd_hdr = r_cd.headers.get("Content-Disposition") or ""
                                r_cd.close()
                                m_cd = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', cd_hdr, flags=re.IGNORECASE)
                                if m_cd:
                                    real_fn = urllib.parse.unquote(m_cd.group(1).strip())
                                    if real_fn:
                                        best_fn = real_fn
                            except Exception:
                                pass
                        fn_ver = extract_version_from_filename(best_fn)
                        if fn_ver:
                            ver_str = fn_ver.lstrip("vV")
                        return {
                            "status": "free_direct",
                            "title": title,
                            "version": ver_str,
                            "file_name": best_fn,
                            "download_url": best_dl,
                            "page_url": post_url,
                            "all_files": [(fn, dl) for _, fn, dl in files],
                        }

                    # 본문(content 및 신규 에디터 content_json_string) 내 연결된 다운로드 전용 포스트 / Itch.io / 직접 파일 링크 확인
                    # JSON 리치 텍스트 내 [링크 주소 + 표시 텍스트(파일명)] 쌍 우선 추출 (예: Box 공유 링크에 실제 파일명이 적힌 경우)
                    target_ext = Path(target_mod_name).suffix.lower() if "." in target_mod_name else ""
                    for m_jl in re.finditer(
                        r'"href"\s*:\s*"(https?://[^"]+)"[^]]*\}\s*\]\s*,\s*"text"\s*:\s*"([^"]+)"',
                        cjs_raw,
                    ):
                        l_href, l_text = m_jl.group(1).strip(), m_jl.group(2).strip()
                        if l_href.lower().endswith((".package", ".ts4script", ".zip", ".rar", ".7z")) or l_text.lower().endswith((".package", ".ts4script", ".zip", ".rar", ".7z")):
                            fn_label = (
                                l_text
                                if (
                                    l_text.lower().endswith((".package", ".ts4script", ".zip", ".rar", ".7z"))
                                    and not l_text.lower().startswith(("http://", "https://"))
                                )
                                else urllib.parse.unquote(l_href.split("/")[-1].split("?")[0])
                            )
                            ext_bonus = 25 if (target_ext and fn_label.lower().endswith(target_ext)) else 0
                            files.append((_match_score_mod_name(target_mod_name, fn_label) + 30 + ext_bonus, fn_label, l_href))

                    if _depth < 1 and not any(f[0] >= 40 for f in files):
                        linked_urls = re.findall(r'https?://[^\s"\'\\<>]+', body_combined)
                        for lu in linked_urls:
                            lu_clean = lu.rstrip(".,;'\")>]")
                            lu_low = lu_clean.lower()
                            if (
                                ("patreon.com/posts/" in lu_low and post_id not in lu_low and "40486381" not in lu_low)
                                or ".itch.io/" in lu_low
                                or "curseforge.com/sims4/mods/" in lu_low
                            ):
                                sub_res = inspect_remote_mod_page(lu_clean, target_mod_name=target_mod_name, timeout=timeout, _depth=_depth + 1)
                                if sub_res.get("status") == "free_direct":
                                    sub_match = _match_score_mod_name(
                                        target_mod_name,
                                        f"{sub_res.get('file_name', '')} {sub_res.get('title', '')}",
                                    )
                                    if sub_match >= 15:
                                        return sub_res

                    for m_dl in re.finditer(r'https?://[^\s"\'\\<>]+?\.(?:package|ts4script|zip|rar|7z)', body_combined, flags=re.IGNORECASE):
                        direct_u = m_dl.group(0)
                        if "patreonusercontent.com" in direct_u and ("/1.png" in direct_u or "/1.jpg" in direct_u):
                            continue
                        if any(existing_dl == direct_u for _, _, existing_dl in files):
                            continue
                        fn_guess = urllib.parse.unquote(direct_u.split("/")[-1].split("?")[0])
                        files.append((_match_score_mod_name(target_mod_name, fn_guess), fn_guess, direct_u))

                    if files:
                        files.sort(key=lambda x: x[0], reverse=True)
                        best_fn, best_dl = files[0][1], files[0][2]
                        # Box / SimFileShare 등 외부 스토리지 링크인 경우 Content-Disposition 헤더에서 실제 최신 파일명(예: _v4) 확인
                        if any(d in best_dl.lower() for d in ("app.box.com", "simfileshare.net")):
                            try:
                                r_cd = requests.get(best_dl, headers={"User-Agent": headers["User-Agent"]}, stream=True, timeout=6)
                                cd_hdr = r_cd.headers.get("Content-Disposition") or ""
                                r_cd.close()
                                m_cd = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', cd_hdr, flags=re.IGNORECASE)
                                if m_cd:
                                    real_fn = urllib.parse.unquote(m_cd.group(1).strip())
                                    if real_fn:
                                        best_fn = real_fn
                            except Exception:
                                pass
                        fn_ver = extract_version_from_filename(best_fn)
                        if fn_ver:
                            ver_str = fn_ver.lstrip("vV")
                        return {
                            "status": "free_direct",
                            "title": title,
                            "version": ver_str,
                            "file_name": best_fn,
                            "download_url": best_dl,
                            "page_url": post_url,
                            "all_files": [(fn, dl) for _, fn, dl in files],
                        }

                    return {"status": "browser_required", "page_url": post_url}
            except Exception:
                pass

        # 2) 제작자 메인/캠페인 URL인 경우 (예: https://www.patreon.com/weerbesu, https://www.patreon.com/roburky)
        try:
            r_page = requests.get(url, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
            if r_page.status_code == 200:
                m_camp = (
                    re.search(r"patreon-media/p/campaign/(\d+)/", r_page.text)
                    or re.search(r'"campaign_id"\s*:\s*"?(\d+)"?', r_page.text)
                    or re.search(r"api/campaigns/(\d+)", r_page.text)
                )
                if m_camp:
                    camp_id = m_camp.group(1)
                    api_posts = (
                        f"https://www.patreon.com/api/posts?filter[campaign_id]={camp_id}"
                        "&filter[is_draft]=false&sort=-published_at&page[count]=25"
                    )
                    rp = requests.get(api_posts, headers=headers, timeout=timeout)
                    if rp.status_code == 200:
                        pdata = rp.json()
                        media_map: Dict[str, Tuple[str, str]] = {}
                        for inc in pdata.get("included", []):
                            if inc.get("type") in ("media", "attachment"):
                                ia = inc.get("attributes", {})
                                fn = ia.get("file_name") or ""
                                dl = ia.get("download_url") or ia.get("url") or ""
                                if fn.lower().endswith((".package", ".ts4script", ".zip", ".rar", ".7z")) and dl:
                                    media_map[str(inc.get("id"))] = (fn, dl)

                        best_free_post = None
                        best_free_score = -1
                        best_ea_post = None
                        best_ea_score = -1

                        for post in pdata.get("data", []):
                            pa = post.get("attributes", {})
                            ptitle = pa.get("title") or ""
                            can_v = bool(pa.get("current_user_can_view"))
                            p_score = _match_score_mod_name(target_mod_name, ptitle)
                            if "poll" in ptitle.lower():
                                p_score -= 40

                            rel_media = (
                                post.get("relationships", {}).get("attachments_media", {}).get("data", [])
                                + post.get("relationships", {}).get("media", {}).get("data", [])
                                + post.get("relationships", {}).get("attachments", {}).get("data", [])
                            )
                            post_files: List[Tuple[int, str, str]] = []
                            for rm in rel_media:
                                mid = str(rm.get("id"))
                                if mid in media_map:
                                    fn, dl = media_map[mid]
                                    f_score = _match_score_mod_name(target_mod_name, fn)
                                    p_score = max(p_score, f_score) + 25
                                    post_files.append((f_score, fn, dl))

                            if can_v and p_score > best_free_score and p_score >= 25:
                                best_free_score = p_score
                                best_free_post = (pa, post_files)
                            elif not can_v and p_score > best_ea_score and p_score >= 45:
                                best_ea_score = p_score
                                best_ea_post = pa

                        if best_free_post:
                            pa, post_files = best_free_post
                            ptitle = pa.get("title") or ""
                            p_url = pa.get("url") or url
                            t_ver = extract_version_from_filename(ptitle)
                            ver_str = t_ver.lstrip("vV") if t_ver else ""
                            if post_files:
                                post_files.sort(key=lambda x: x[0], reverse=True)
                                best_fn, best_dl = post_files[0][1], post_files[0][2]
                                fn_v = extract_version_from_filename(best_fn)
                                if fn_v:
                                    ver_str = fn_v.lstrip("vV")
                                return {
                                    "status": "free_direct",
                                    "title": ptitle,
                                    "version": ver_str,
                                    "file_name": best_fn,
                                    "download_url": best_dl,
                                    "page_url": p_url,
                                }
                            # 공개 포스트인데 첨부파일 대신 본문 내 외부 다운로드 링크(Itch.io 등)를 둔 경우
                            if _depth < 1 and p_url and p_url != url:
                                sub_res = inspect_remote_mod_page(p_url, target_mod_name=target_mod_name, timeout=timeout, _depth=_depth + 1)
                                if sub_res.get("status") == "free_direct":
                                    return sub_res

                        if best_ea_post:
                            ptitle = best_ea_post.get("title") or ""
                            p_url = best_ea_post.get("url") or url
                            t_ver = extract_version_from_filename(ptitle)
                            ver_str = t_ver.lstrip("vV") if t_ver else ""
                            return {
                                "status": "early_access",
                                "title": ptitle,
                                "version": ver_str,
                                "page_url": p_url,
                            }
        except Exception:
            pass

    # ==========================================================================
    # D. 일반 공식 웹사이트 및 Tumblr 포스트 내 다운로드 파일/외부 스토리지 링크 감지
    # ==========================================================================
    try:
        r_web = requests.get(url, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
        if r_web.status_code == 200:
            soup = BeautifulSoup(r_web.text, "html.parser")
            direct_files: List[Tuple[int, str, str]] = []
            external_host_links: List[str] = []

            for a in soup.find_all("a", href=True):
                href = urllib.parse.urljoin(url, a["href"].strip())
                # Tumblr href.li 리다이렉트 래퍼 해제
                if "t.umblr.com/redirect" in href or "href.li/?" in href:
                    parsed_q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                    if "z" in parsed_q and parsed_q["z"]:
                        href = parsed_q["z"][0]
                    elif "href.li/?" in href:
                        href = href.split("href.li/?", 1)[1]

                h_low = href.lower()
                path_part = urllib.parse.urlparse(href).path
                if path_part.lower().endswith((".zip", ".package", ".ts4script", ".rar", ".7z")):
                    fn = urllib.parse.unquote(path_part.split("/")[-1])
                    direct_files.append((_match_score_mod_name(target_mod_name, fn), fn, href))
                elif any(
                    dom in h_low
                    for dom in (
                        "simfileshare.net/download/",
                        "mediafire.com/file/",
                        "modthesims.info/d/",
                        ".itch.io/",
                        "curseforge.com/sims4/mods/",
                        "patreon.com/posts/",
                    )
                ):
                    if href not in external_host_links:
                        external_host_links.append(href)

            # 본문 텍스트에 노출된 SimFileShare / MediaFire URL도 추가 추출
            for m_ext in re.finditer(
                r'https?://(?:www\.)?(?:simfileshare\.net/download/\d+/?|mediafire\.com/file/[^\s"\'<>]+)',
                r_web.text,
                flags=re.IGNORECASE,
            ):
                ext_u = m_ext.group(0)
                if ext_u not in external_host_links:
                    external_host_links.append(ext_u)

            if direct_files:
                direct_files.sort(key=lambda x: x[0], reverse=True)
                best_fn, best_dl = direct_files[0][1], direct_files[0][2]
                fn_ver = extract_version_from_filename(best_fn)
                return {
                    "status": "free_direct",
                    "title": best_fn,
                    "version": fn_ver.lstrip("vV") if fn_ver else "",
                    "file_name": best_fn,
                    "download_url": best_dl,
                    "page_url": url,
                }

            if _depth < 1 and external_host_links:
                for ext_u in external_host_links[:4]:
                    sub_res = inspect_remote_mod_page(ext_u, target_mod_name=target_mod_name, timeout=timeout, _depth=_depth + 1)
                    if sub_res.get("status") == "free_direct":
                        sub_res["page_url"] = url
                        return sub_res
    except Exception:
        pass

    return {"status": "browser_required", "page_url": url}


def is_safe_remote_file_match(
    target_name: str,
    folder_name: str = "",
    extracted_meta: Optional[Dict[str, Any]] = None,
    remote_info: Optional[Dict[str, Any]] = None,
    checked_url: str = "",
) -> Tuple[bool, int, str]:
    """원격 배포 페이지에서 감지된 다운로드 파일이 실제 로컬 모드와 일치하는지 교차 검증합니다.
    잘못된 모드를 자동 다운로드하는 리스크를 방지하기 위한 안전 게이트(Confidence Gate)입니다.
    """
    if not remote_info or remote_info.get("status") != "free_direct":
        return False, 0, "직접 다운로드 상태 아님"

    meta = extracted_meta or {}
    rem_fn = str(remote_info.get("file_name") or "")
    rem_title = str(remote_info.get("title") or "")
    page_u = str(remote_info.get("page_url") or checked_url or "")

    # 1) 검증된 공식 카탈로그에 등록된 모드이거나 파일 내부 바이너리에 내장된 공식 URL인 경우 신뢰
    cat_match = check_known_catalog(target_name)
    if cat_match:
        cat_urls = [
            normalize_distribution_url(lk[2] if len(lk) == 3 else lk[1]).lower().rstrip("/")
            for lk in cat_match.get("candidate_links", [])
        ]
        norm_page = normalize_distribution_url(page_u).lower().rstrip("/")
        if norm_page and any(norm_page.startswith(cu) or cu.startswith(norm_page) for cu in cat_urls):
            return True, 100, "공식 카탈로그 검증됨"

    embedded_urls = [u.lower().rstrip("/") for u in (meta.get("urls") or []) if u]
    if page_u and any(page_u.lower().rstrip("/").startswith(eu) or eu.startswith(page_u.lower().rstrip("/")) for eu in embedded_urls):
        return True, 100, "파일 내장 공식 URL 일치"

    # 2) 로컬 기준 이름 후보군(파일명, 폴더명, 내부 매니페스트 모드명, 제작자명)과 원격(파일명, 포스트 제목, URL) 유사도 점수 측정
    local_queries = [
        q for q in (
            target_name,
            folder_name,
            meta.get("manifest_name") or "",
            meta.get("inferred_mod") or "",
            f"{meta.get('inferred_creator', '')} {meta.get('inferred_mod', '')}".strip(),
        )
        if q and len(q.strip()) >= 2
    ]
    remote_combined = f"{rem_fn} {rem_title} {urllib.parse.unquote(page_u)}"

    best_score = 0
    for lq in local_queries:
        sc = max(
            _match_score_mod_name(lq, rem_fn),
            _match_score_mod_name(lq, f"{rem_fn} {rem_title}"),
            _match_score_mod_name(lq, remote_combined),
        )
        if sc > best_score:
            best_score = sc

    # 제작자명이 원격 URL이나 파일명/제목에 명시적으로 포함되어 있으면 가산점 부여
    # 단, 제작자 접두사(예: sims4me_, littlemssam_)만 같고 실제 모드명(inferred_mod)이 전혀 일치하지 않는 다른 모드 오탐 방지
    creator = (meta.get("inferred_creator") or "").strip().lower()
    mod_only = (meta.get("manifest_name") or meta.get("inferred_mod") or "").strip()
    if mod_only and creator and mod_only.lower() != creator:
        mod_only_score = max(
            _match_score_mod_name(mod_only, rem_fn),
            _match_score_mod_name(mod_only, f"{rem_fn} {rem_title}"),
        )
        if mod_only_score <= 0:
            return False, 0, f"제작자만 동일하고 모드명 불일치 ({rem_fn})"

    if creator and len(creator) >= 3 and creator in remote_combined.lower():
        best_score += 20

    if best_score >= 15:
        return True, best_score, f"키워드 유사도 검증 통과 ({best_score}점)"

    return False, best_score, f"파일명/모드명 유사도 미달 ({best_score}점)"

