"""심즈 4 모드 파일(.package, .ts4script) 내부의 바이너리/아카이브 메타데이터(LlamaLogic 매니페스트,
XML Tuning 식별자, Python 바이트코드 내장 URL, 제작자 태그 등)를 직접 추출하고,
스마트 파일명/폴더명 분석 및 웹 검색 스니펫 랭킹을 결합하여 실제 공식 배포 페이지를 찾는 엔진입니다.
"""

import copy
import datetime
import email.utils
import html
import json
import re
import struct
import threading
import time
import urllib.parse
import zipfile
import zlib
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from bs4 import BeautifulSoup
from requests.structures import CaseInsensitiveDict

from src.utils import (
    NetworkSecurityError,
    SafeHttpsSession,
    is_auxiliary_non_mod_archive,
    is_valid_https_url,
    log_security_warning,
    normalize_mod_filename_key,
    safe_https_get,
    validate_https_url,
)

try:
    import warnings
    from bs4 import XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except Exception:
    pass

# ==============================================================================
# 1. 핵심 코어 모드 카탈로그 (전용 업데이터 및 대표 통합 모드)
# ==============================================================================
KNOWN_CATALOG = [
    {
        "keywords": ["mc_woohoo", "mcwoohoo", "mc woohoo"],
        "name": "MC Woohoo (MCCC Module)",
        "creator": "Deaderpool",
        "mod_title": "MC Woohoo",
        "version": "2026.6.0",
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
        "version": "2026.6.0",
        "links": [
            ("공식 다운로드 페이지", "Deaderpool MCCC Downloads", "https://deaderpool-mccc.com/downloads.html"),
            ("Patreon", "Deaderpool Patreon", "https://www.patreon.com/mccc_deaderpool")
        ]
    },
    {
        "keywords": [
            "turbodriver_wickedwhims_scripts.ts4script",
            "turbodriver_wickedwhims_tuning.package",
            "turbodriver_wickedwhims",
            "wickedwhims_scripts",
            "wickedwhims_tuning",
            "wickedwhims.ts4script",
            "wickedwhims.package",
        ],
        "name": "WickedWhims",
        "creator": "TURBODRIVER",
        "mod_title": "WickedWhims",
        "version": "185k",
        "requires_option_modal": True,
        "option_modal_mode": "ww_channel",
        "option_modal_prompt": "WickedWhims 배포 버전을 선택해 주세요. (무료 버전 v185k 자동 업데이트 / 선배포 버전 v187.18 수동 다운로드)",
        "option_presets": [
            {
                "file_name": "ww_channel:free",
                "channel": "free",
                "label": "무료 버전 (Wicked.cc v185k · 자동 업데이트)",
                "description": "공식 무료 배포판(v185k) 기준으로 버전을 비교하고 자동 업데이트를 활성화합니다.",
            },
            {
                "file_name": "ww_channel:paid",
                "channel": "paid",
                "label": "선배포 버전 (Patreon v187.18 · 수동 다운로드)",
                "description": "Patreon 선배포 버전(v187.18) 기준으로 자동 다운로드를 실행하지 않고 '수동 확인' 상태를 유지합니다.",
            },
        ],
        "release_notes": "WickedWhims 무료 공개 배포판(v185k) · 자동 업데이트 지원",
        "links": [
            ("Wicked.cc (공식)", "WickedWhims - WickedCC | TURBODRIVER", "https://wicked.cc/mods/TURBODRIVER/wickedwhims"),
            ("Itch.io", "TURBODRIVER Itch.io", "https://turbodriver.itch.io/wickedwhims")
        ],
        "paid_version": "187.18",
        "paid_links": [
            ("Patreon (선배포)", "WickedWhims v187.18 | TURBODRIVER", "https://www.patreon.com/wickedwoohoo/posts/wickedwhims-v187-134827399"),
            ("Patreon 채널", "TURBODRIVER Official Patreon", "https://www.patreon.com/wickedwoohoo")
        ],
    },
    {
        "keywords": [
            "turbodriver_wonderfulwhims_scripts.ts4script",
            "turbodriver_wonderfulwhims_tuning.package",
            "wonderfulwhims",
            "turbodriver_wonderfulwhims",
            "wonderfulwhims_scripts",
            "wonderfulwhims_tuning",
        ],
        "name": "WonderfulWhims",
        "creator": "TURBODRIVER",
        "mod_title": "WonderfulWhims",
        "version": "v60",
        "links": [
            ("Itch.io (공식)", "WonderfulWhims | TURBODRIVER", "https://turbodriver.itch.io/wonderfulwhims"),
            ("공식 웹사이트", "WonderfulWhims Official", "https://wonderfulwhims.com/")
        ]
    },
    {
        "keywords": [
            "more_cas_columns_(3_columns).package",
            "more_cas_columns_(4_columns).package",
            "more_cas_columns_(5_columns).package",
            "more_cas_columns_(6_columns).package",
            "more_cas_columns_(3_columns)",
            "more_cas_columns_(4_columns)",
            "more_cas_columns_(5_columns)",
            "more_cas_columns_(6_columns)",
            "more_cas_columns",
            "more columns in cas",
        ],
        "name": "More Columns in CAS",
        "creator": "Weerbesu",
        "mod_title": "More Columns in CAS",
        "version": "1.38",
        "requires_option_modal": True,
        "option_modal_prompt": "CAS(심 만들기) 화면에 표시할 열 개수 옵션을 선택해 주세요. (동시 설치 불가 · 1개 선택)",
        "option_presets": [
            {"file_name": "More_CAS_Columns_(3_Columns).package", "label": "3열 (3 Columns)"},
            {"file_name": "More_CAS_Columns_(4_Columns).package", "label": "4열 (4 Columns)"},
            {"file_name": "More_CAS_Columns_(5_Columns).package", "label": "5열 (5 Columns)"},
            {"file_name": "More_CAS_Columns_(6_Columns).package", "label": "6열 (6 Columns)"},
        ],
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
        "version": "1.59.1",
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
        "version": "1.1",
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
        "version": "1.9.9",
        "links": [
            ("Patreon (공식)", "Kiss-n-Grind 1.9.9 | Provocative Grind | UTOPYA", "https://www.patreon.com/UTOPYA_cc/posts/kiss-n-grind-1-9-131081267"),
            ("Patreon 채널", "UTOPYA Official Patreon", "https://www.patreon.com/UTOPYA_cc")
        ]
    },
    {
        "keywords": [
            "[utopya] wave-n-grind mod a0.5.package",
            "[utopya] wave-n-grind mod",
            "[utopya] wave-n-grind",
            "wave-n-grind mod",
            "wave-n-grind",
            "wave_n_grind",
            "wave n grind",
            "wave and grind",
            "wave_and_grind",
            "waveandgrind",
        ],
        "name": "Wave and Grind",
        "creator": "UTOPYA",
        "mod_title": "Wave and Grind",
        "override_mod_title": True,
        "version": "a0.5",
        "links": [
            ("Patreon (공식)", "Wave and Grind a0.5 | UTOPYA", "https://www.patreon.com/UTOPYA_cc/posts/kiss-and-grind-115299392"),
            ("Patreon 채널", "UTOPYA Official Patreon", "https://www.patreon.com/UTOPYA_cc")
        ]
    },
    {
        "keywords": [
            "[utopya] passionate gifts mod 0.8.package",
            "[utopya] passionate gifts mod",
            "[utopya] passionate gifts",
            "[utopya] passionate gift",
            "utopya_passionate_gifts",
            "utopya_passionate_gift",
            "passionate gifts mod",
            "passionate gift mod",
            "passionate gifts",
            "passionate_gifts",
            "passionategifts",
            "passionate gift",
            "passionate_gift",
            "passionategift",
        ],
        "name": "Passionate Gift",
        "creator": "UTOPYA",
        "mod_title": "Passionate Gift",
        "override_mod_title": True,
        "version": "0.8",
        "links": [
            ("Patreon (공식)", "Passionate Gift 0.8 | UTOPYA", "https://www.patreon.com/UTOPYA_cc/posts/passionate-gift-151330104"),
            ("Patreon 채널", "UTOPYA Official Patreon", "https://www.patreon.com/UTOPYA_cc")
        ]
    },
    {
        "keywords": [
            "[utopya] passionate affection mod 0.1.package",
            "[utopya] passionate affection mod",
            "[utopya] passionate affection",
            "utopya_passionate_affection",
            "passionate affection mod",
            "passionate affection",
            "passionate_affection",
            "passionateaffection",
        ],
        "name": "Passionate Affection",
        "creator": "UTOPYA",
        "mod_title": "Passionate Affection",
        "override_mod_title": True,
        "version": "0.1",
        "links": [
            ("Patreon (공식)", "Passionate Affection 0.1 | UTOPYA", "https://www.patreon.com/UTOPYA_cc/posts/passionate-gift-151330104"),
            ("Patreon 채널", "UTOPYA Official Patreon", "https://www.patreon.com/UTOPYA_cc")
        ]
    },
    {
        "keywords": [
            "[utopya] functional handbag mod 0.2.2.package",
            "[utopya] functional handbag mod",
            "[utopya] functional handbag",
            "utopya_functional_handbag",
            "functional handbag mod",
            "functional handbag",
            "functional_handbag",
            "functionalhandbag",
        ],
        "name": "Functional Handbag",
        "creator": "UTOPYA",
        "mod_title": "Functional Handbag",
        "override_mod_title": True,
        "version": "0.2.2",
        "links": [
            ("Patreon (공식)", "Functional Handbag 0.2.2 | UTOPYA", "https://www.patreon.com/UTOPYA_cc/posts/functional-mod-108516027"),
            ("Patreon 채널", "UTOPYA Official Patreon", "https://www.patreon.com/UTOPYA_cc")
        ]
    },
    {
        "keywords": [
            "[utopya] romantic complaints v1.0.1.package",
            "[utopya] romantic complaints",
            "utopya_romantic_complaints",
            "romantic complaints",
            "romantic_complaints",
            "romanticcomplaints",
        ],
        "name": "Romantic Complaints",
        "creator": "UTOPYA",
        "mod_title": "Romantic Complaints",
        "override_mod_title": True,
        "version": "1.0.1",
        "links": [
            ("Patreon (공식)", "Romantic Complaints v1.0.1 | UTOPYA", "https://www.patreon.com/UTOPYA_cc/posts/romantic-sims-4-128656481"),
            ("Patreon 채널", "UTOPYA Official Patreon", "https://www.patreon.com/UTOPYA_cc")
        ]
    },
    {
        "keywords": [
            "[utopya] mistletoe kiss mod v0.1.package",
            "[utopya] mistletoe kiss mod",
            "[utopya] mistletoe kiss",
            "utopya_mistletoe_kiss",
            "mistletoe kiss mod",
            "mistletoe_kiss_mod",
            "mistletoekissmod",
            "mistletoe kiss",
            "mistletoe_kiss",
        ],
        "name": "Mistletoe Kiss Mod",
        "creator": "UTOPYA",
        "mod_title": "Mistletoe Kiss Mod",
        "override_mod_title": True,
        "version": "0.1",
        "links": [
            ("Patreon (공식)", "Mistletoe Kiss Mod v0.1 | UTOPYA", "https://www.patreon.com/posts/mistletoe-kiss-118908490"),
            ("Patreon (공식)", "Mistletoe Kiss Mod v0.1 | UTOPYA", "https://www.patreon.com/UTOPYA_cc/posts/mistletoe-kiss-118908490"),
            ("Patreon 채널", "UTOPYA Official Patreon", "https://www.patreon.com/UTOPYA_cc")
        ]
    },
    {
        "keywords": [
            "[utopya] together on a laptop 0.5.package",
            "[utopya] together on a laptop",
            "together on a laptop",
            "together_on_a_laptop",
            "[utopya] use laptop together",
            "utopya_use_laptop_together",
            "use laptop together",
            "use_laptop_together",
            "uselaptoptogether",
        ],
        "name": "Use Laptop Together",
        "creator": "UTOPYA",
        "mod_title": "Use Laptop Together",
        "override_mod_title": True,
        "version": "0.5",
        "links": [
            ("Patreon (공식)", "Use Laptop Together v0.5 | UTOPYA", "https://www.patreon.com/UTOPYA_cc/posts/use-laptop-0-5-117834485"),
            ("Patreon 채널", "UTOPYA Official Patreon", "https://www.patreon.com/UTOPYA_cc")
        ]
    },
    {
        "keywords": ["volleyball mod", "volleyball_mod", "volleyballmod", "[utopya] volleyball", "utopya_volleyball", "volleyball"],
        "name": "Volleyball Mod",
        "creator": "UTOPYA",
        "mod_title": "Volleyball Mod",
        "override_mod_title": True,
        "version": "0.2.4",
        "links": [
            ("Patreon (공식)", "Volleyball Mod 0.2.4 | UTOPYA", "https://www.patreon.com/UTOPYA_cc/posts/volleyball-mod-0-166618081"),
            ("Patreon 채널", "UTOPYA Official Patreon", "https://www.patreon.com/UTOPYA_cc")
        ]
    },
    {
        "keywords": [
            "twister game mod",
            "twister_game_mod",
            "twister mod",
            "twister_mod",
            "[utopya] twister",
            "utopya_twister",
            "twister box",
            "twister mat",
        ],
        "name": "Twister Game Mod",
        "creator": "UTOPYA",
        "mod_title": "Twister Game Mod",
        "override_mod_title": True,
        "version": "0.2.3",
        "links": [
            ("Patreon (공식)", "Twister Game Mod 0.2.3 | UTOPYA", "https://www.patreon.com/UTOPYA_cc/posts/twister-mod-158968693"),
            ("Patreon 채널", "UTOPYA Official Patreon", "https://www.patreon.com/UTOPYA_cc")
        ]
    },
    {
        "keywords": [
            "[utopya] vintage bicycle 0.2.package",
            "[utopya] vintage bicycle",
            "utopya_vintage_bicycle",
            "vintage bicycle 0.2",
            "vintage bicycle",
        ],
        "name": "[UTOPYA] Vintage Bicycle",
        "creator": "UTOPYA",
        "mod_title": "Vintage Bicycle (Ride Together)",
        "override_mod_title": True,
        "version": "0.2",
        "links": [
            ("Patreon (공식)", "Ride Together Update 0.5 | UTOPYA", "https://www.patreon.com/UTOPYA_cc/posts/ride-together-0-142863954"),
            ("Patreon 채널", "UTOPYA Official Patreon", "https://www.patreon.com/UTOPYA_cc")
        ]
    },
    {
        "keywords": [
            "[utopya] rental ebike station 0.2.package",
            "[utopya] rental ebike station",
            "utopya_rental_ebike_station",
            "rental ebike station 0.2",
            "rental ebike station",
        ],
        "name": "[UTOPYA] Rental Ebike Station",
        "creator": "UTOPYA",
        "mod_title": "Rental Ebike Station (Ride Together)",
        "override_mod_title": True,
        "version": "0.2",
        "links": [
            ("Patreon (공식)", "Ride Together Update 0.5 | UTOPYA", "https://www.patreon.com/UTOPYA_cc/posts/ride-together-0-142863954"),
            ("Patreon 채널", "UTOPYA Official Patreon", "https://www.patreon.com/UTOPYA_cc")
        ]
    },
    {
        "keywords": [
            "[utopya] ride together_mod a0.5.package",
            "[utopya] ride together_mod",
            "ride together_mod",
            "ride_together_mod",
            "[utopya] ride together",
            "utopya_ride_together",
            "ride together",
            "ride_together",
        ],
        "name": "Ride Together",
        "creator": "UTOPYA",
        "mod_title": "Ride Together",
        "override_mod_title": True,
        "version": "a0.5",
        "links": [
            ("Patreon (공식)", "Ride Together Update 0.5 | UTOPYA", "https://www.patreon.com/UTOPYA_cc/posts/ride-together-0-142863954"),
            ("Patreon 채널", "UTOPYA Official Patreon", "https://www.patreon.com/UTOPYA_cc")
        ]
    },
    {
        "keywords": [
            "littlemssam_asktocookbakegrill.package",
            "littlemssam_asktocookbakegrill.ts4script",
            "littlemssam_asktocookbakegrill",
            "asktocookbakegrill",
            "ask_to_cook_bake_grill",
            "ask to cook/bake/grill/mix drink",
            "ask to cook bake grill mix drink",
            "ask-to-cook-bake-grill-mix-drink",
            "asktocookbake",
        ],
        "name": "Ask to Cook/Bake/Grill/Mix Drink!",
        "creator": "LittleMsSam",
        "mod_title": "Ask to Cook/Bake/Grill/Mix Drink!",
        "override_mod_title": True,
        "version": "2026.02.01",
        "links": [
            ("CurseForge (공식)", "Ask to Cook/Bake/Grill/Mix Drink! | LittleMsSam", "https://www.curseforge.com/sims4/mods/ask-to-cook-bake-grill-mix-drink-including")
        ]
    },
    {
        "keywords": [
            "littlemssam_heatupleftovers.package",
            "littlemssam_heatupleftovers",
            "heatupleftovers",
            "heat_up_leftovers",
            "heat up leftovers",
            "heat-up-leftovers",
        ],
        "name": "Heat Up Leftovers",
        "creator": "LittleMsSam",
        "mod_title": "Heat Up Leftovers",
        "override_mod_title": True,
        "version": "2026.11.07",
        "links": [
            ("CurseForge (공식)", "Heat Up Leftovers | LittleMsSam", "https://www.curseforge.com/sims4/mods/heat-up-leftovers")
        ]
    },
    {
        "keywords": [
            "littlemssam_rsm_bg_fooddrinksasclutter.package",
            "littlemssam_rsm_bg_fooddrinksasclutter",
            "fooddrinksasclutter",
            "food_drinks_as_clutter",
            "rsm - food & drinks as clutter",
            "food & drinks as clutter",
            "food and drinks as clutter",
            "rsm-food-drinks-as-clutter",
        ],
        "name": "RSM - Food & Drinks As Clutter",
        "creator": "LittleMsSam",
        "mod_title": "RSM - Food & Drinks As Clutter",
        "override_mod_title": True,
        "version": "2026.09.19",
        "links": [
            ("CurseForge (공식)", "RSM - Food & Drinks As Clutter | LittleMsSam", "https://www.curseforge.com/sims4/mods/rsm-food-drinks-as-clutter")
        ]
    },
    {
        "keywords": [
            "littlemssam_betterbutler.package",
            "littlemssam_betterbutler_cannotdie.package",
            "littlemssam_betterbutler_costfix.package",
            "littlemssam_betterbutler_gotosleep.package",
            "littlemssam_betterbutler_hiremorebutlers.package",
            "littlemssam_betterbutler_lockedstats_bladder.package",
            "littlemssam_betterbutler_lockedstats_energy.package",
            "littlemssam_betterbutler_lockedstats_fun.package",
            "littlemssam_betterbutler_lockedstats_hunger.package",
            "littlemssam_betterbutler_lockedstats_hygiene.package",
            "littlemssam_betterbutler_lockedstats_social.package",
            "littlemssam_betterbutler_noautocooking.package",
            "littlemssam_betterbutler_noautoputaway.package",
            "littlemssam_betterbutler_nogardening.package",
            "littlemssam_betterbutler",
            "better butler (and hire more butler)",
            "better-butler-and-hire-more-butler",
        ],
        "name": "Better Butler (and Hire more Butler)",
        "creator": "LittleMsSam",
        "mod_title": "Better Butler (and Hire more Butler)",
        "override_mod_title": True,
        "version": "2026.02.04",
        "links": [
            ("CurseForge (공식)", "Better Butler (and Hire more Butler) | LittleMsSam", "https://www.curseforge.com/sims4/mods/better-butler-and-hire-more-butler")
        ]
    },
    {
        "keywords": [
            "littlemssam_fooddelivery.package",
            "littlemssam_fooddelivery_addon_higherpricesbasedonhouseholdfunds.package",
            "littlemssam_fooddelivery",
            "food delivery service",
            "food-delivery-service",
        ],
        "name": "Food Delivery Service",
        "creator": "LittleMsSam",
        "mod_title": "Food Delivery Service",
        "override_mod_title": True,
        "version": "2026.05.08",
        "links": [
            ("CurseForge (공식)", "Food Delivery Service | LittleMsSam", "https://www.curseforge.com/sims4/mods/food-delivery-service")
        ]
    },
    {
        "keywords": [
            "littlemssam_rsm_bg_wakeupoverhaul.package",
            "littlemssam_rsm_bg_wakeupoverhaul",
            "wakeupoverhaul",
            "wake_up_overhaul",
            "rsm - wake up animation overhaul",
            "wake up animation overhaul",
            "rsm-wake-up-animation-overhaul",
        ],
        "name": "Wake Up Animation Overhaul",
        "creator": "LittleMsSam",
        "mod_title": "Wake Up Animation Overhaul",
        "override_mod_title": True,
        "version": "2025.07.08",
        "links": [
            ("CurseForge (공식)", "RSM - Wake Up Animation Overhaul | LittleMsSam", "https://www.curseforge.com/sims4/mods/rsm-wake-up-animation-overhaul")
        ]
    },
    {
        "keywords": [
            "littlemssam_betternanny.package",
            "littlemssam_betternanny_age_adult-elder.package",
            "littlemssam_betternanny_behaviourdoesnotaffecthousehold.package",
            "littlemssam_betternanny_nocooking.package",
            "littlemssam_betternanny_nocooking.ts4script",
            "littlemssam_betternanny_regular_and_secondnanny_mainmod.package",
            "littlemssam_betternanny_regular_and_secondnanny_workingtime_8am-8pm_plusweekend.package",
            "littlemssam_betternanny",
            "better nanny (second nanny & more)",
            "better-nanny-second-nanny-more",
        ],
        "name": "Better Nanny (Second Nanny & more)",
        "creator": "LittleMsSam",
        "mod_title": "Better Nanny (Second Nanny & more)",
        "override_mod_title": True,
        "version": "2026.09.23",
        "links": [
            ("CurseForge (공식)", "Better Nanny (Second Nanny & more) | LittleMsSam", "https://www.curseforge.com/sims4/mods/better-nanny-second-nanny-more")
        ]
    },
    {
        "keywords": [
            "littlemssam_letfriendsageup.ts4script",
            "littlemssam_letfriendsageup.package",
            "littlemssam_letfriendsageup",
            "letfriendsageup",
            "let_friends_age_up",
            "let friends age up",
            "let-friends-age-up",
        ],
        "name": "Let Friends Age Up",
        "creator": "LittleMsSam",
        "mod_title": "Let Friends Age Up",
        "override_mod_title": True,
        "version": "2026.11.07",
        "links": [
            ("CurseForge (공식)", "Let Friends Age Up | LittleMsSam", "https://www.curseforge.com/sims4/mods/let-friends-age-up")
        ]
    },
    {
        "keywords": [
            "littlemssam_rsm_bg_autobushteethafterpuking.ts4script",
            "littlemssam_rsm_bg_autobrushteethafterpuking.ts4script",
            "littlemssam_rsm_bg_autobrushteethafterpuking.package",
            "littlemssam_rsm_bg_autobrushteethafterpuking_addon_aftereatingtoo.package",
            "littlemssam_rsm_bg_autobrushteethafterpuking",
            "autobrushteethafterpuking",
            "auto_brush_teeth_after_puking",
            "rsm - auto brush teeth after puking",
            "auto brush teeth after puking",
            "rsm-auto-brush-teeth",
        ],
        "name": "RSM - Auto Brush Teeth after Puking",
        "creator": "LittleMsSam",
        "mod_title": "RSM - Auto Brush Teeth after Puking",
        "override_mod_title": True,
        "version": "2026.08.09",
        "links": [
            ("CurseForge (공식)", "RSM - Auto Brush Teeth after Puking | LittleMsSam", "https://www.curseforge.com/sims4/mods/rsm-auto-brush-teeth")
        ]
    },
    {
        "keywords": [
            "frequentlybasic_flavoredmemories.package",
            "frequentlybasic_flavoredmemories",
            "flavoredmemories",
            "flavored_memories",
            "flavored memories",
            "flavored-memories",
        ],
        "name": "Flavored Memories",
        "creator": "FrequentlyBasic",
        "mod_title": "Flavored Memories",
        "override_mod_title": True,
        "version": "2026.10.19",
        "links": [
            ("CurseForge (공식)", "Flavored Memories | FrequentlyBasic", "https://www.curseforge.com/sims4/mods/flavored-memories")
        ]
    },
    {
        "keywords": [
            "frequentlybasic_captainwhitaker_thejoyfulghostdog.package",
            "frequentlybasic_captainwhitaker_thejoyfulghostdog",
            "captainwhitaker_thejoyfulghostdog",
            "thejoyfulghostdog",
            "the_joyful_ghost_dog",
            "captain whitaker - the joyful ghost dog",
            "captain whitaker the joyful ghost dog",
            "captain-whitaker-the-joyful-ghost-dog",
        ],
        "name": "Captain Whitaker - The Joyful Ghost Dog",
        "creator": "FrequentlyBasic",
        "mod_title": "Captain Whitaker - The Joyful Ghost Dog",
        "override_mod_title": True,
        "version": "2025.07.27",
        "links": [
            ("CurseForge (공식)", "Captain Whitaker - The Joyful Ghost Dog | FrequentlyBasic", "https://www.curseforge.com/sims4/mods/captain-whitaker-the-joyful-ghost-dog")
        ]
    },
    {
        "keywords": [
            "frequentlybasic_captainwhitaker_thegoodluckpup.package",
            "frequentlybasic_captainwhitaker_thegoodluckpup",
            "captainwhitaker_thegoodluckpup",
            "thegoodluckpup",
            "the_good_luck_pup",
            "captain whitaker - the good luck pup",
            "captain whitaker the good luck pup",
            "captain-whitaker-the-good-luck-pup",
        ],
        "name": "Captain Whitaker - The Good Luck Pup",
        "creator": "FrequentlyBasic",
        "mod_title": "Captain Whitaker - The Good Luck Pup",
        "override_mod_title": True,
        "version": "2026.05.14",
        "links": [
            ("CurseForge (공식)", "Captain Whitaker - The Good Luck Pup | FrequentlyBasic", "https://www.curseforge.com/sims4/mods/captain-whitaker-the-good-luck-pup")
        ]
    },
    {
        "keywords": [
            "frequentlybasic_captainwhitaker_theailmentdogtor.package",
            "frequentlybasic_captainwhitaker_theailmentdogtor",
            "captainwhitaker_theailmentdogtor",
            "theailmentdogtor",
            "the_ailment_dogtor",
            "captain whitaker - the ailment dogtor",
            "captain whitaker the ailment dogtor",
            "captain-whitaker-the-ailment-dogtor",
        ],
        "name": "Captain Whitaker - The Ailment Dogtor",
        "creator": "FrequentlyBasic",
        "mod_title": "Captain Whitaker - The Ailment Dogtor",
        "override_mod_title": True,
        "version": "2025.07.27",
        "links": [
            ("CurseForge (공식)", "Captain Whitaker - The Ailment Dogtor | FrequentlyBasic", "https://www.curseforge.com/sims4/mods/captain-whitaker-the-ailment-dogtor")
        ]
    },
    {
        "keywords": [
            "frequentlybasic_captainwhitaker_theghostdogscurse.package",
            "frequentlybasic_captainwhitaker_theghostdogscurse",
            "captainwhitaker_theghostdogscurse",
            "theghostdogscurse",
            "the_ghost_dogs_curse",
            "captain whitaker - the ghost dog's curse",
            "captain whitaker - the ghost dogs curse",
            "captain whitaker the ghost dog's curse",
            "captain whitaker the ghost dogs curse",
            "captain-whitaker-the-ghost-dogs-curse",
        ],
        "name": "Captain Whitaker - The Ghost Dog's Curse",
        "creator": "FrequentlyBasic",
        "mod_title": "Captain Whitaker - The Ghost Dog's Curse",
        "override_mod_title": True,
        "version": "2026.05.14",
        "links": [
            ("CurseForge (공식)", "Captain Whitaker - The Ghost Dog's Curse | FrequentlyBasic", "https://www.curseforge.com/sims4/mods/captain-whitaker-the-ghost-dogs-curse")
        ]
    },
    {
        "keywords": [
            "frequentlybasic_captainwhitakerfix.package",
            "frequentlybasic_captainwhitakerfix.ts4script",
            "frequentlybasic_captainwhitakerfix",
            "captainwhitakerfix",
            "captain_whitaker_fix",
            "captain whitaker fix",
            "captain-whitaker-fix",
        ],
        "name": "Captain Whitaker Fix",
        "creator": "FrequentlyBasic",
        "mod_title": "Captain Whitaker Fix",
        "override_mod_title": True,
        "version": "2026.05.14",
        "links": [
            ("CurseForge (공식)", "Captain Whitaker Fix | FrequentlyBasic", "https://www.curseforge.com/sims4/mods/captain-whitaker-fix")
        ]
    },
    {
        "keywords": [
            "mercuryfoam_trma_tags.ts4script",
            "mercuryfoam_trma",
            "trma_martialarts",
            "martialartsgi",
            "vo_mfspar_",
            "martial arts mod",
            "martial_arts_mod",
            "tankyfix",
        ],
        "name": "Martial Arts Mod",
        "creator": "Tanky",
        "mod_title": "Martial Arts Mod",
        "override_mod_title": True,
        "version": "2026.06.24",
        "links": [
            ("Patreon (공식)", "Martial Arts Mod | Tanky", "https://www.patreon.com/TankyFix/posts/martial-arts-mod-124737889"),
            ("Patreon 채널", "Tanky Official Patreon", "https://www.patreon.com/TankyFix")
        ]
    },
    {
        "keywords": [
            "ilkavelle_lettertofatherwinter.package",
            "ilkavelle_lettertofatherwinter.zip",
            "ilkavelle_lettertofatherwinter",
            "lettertofatherwinter",
            "letter_to_father_winter",
            "letter to father winter",
            "letter-to-father-winter",
        ],
        "name": "Letter to Father Winter",
        "creator": "IlkaVelle",
        "mod_title": "Letter to Father Winter",
        "override_mod_title": True,
        "version": "2025.01.23",
        "links": [
            ("Patreon (공식)", "Letter to Father Winter | IlkaVelle", "https://www.patreon.com/ilkavelle/posts/letter-to-father-118562777"),
            ("Patreon 채널", "IlkaVelle Official Patreon", "https://www.patreon.com/ilkavelle")
        ]
    },
    {
        "keywords": [
            "simkatu_extended_phone_calls.package",
            "simkatu_extended_phone_calls",
            "extended_phone_calls",
            "extended phone calls",
        ],
        "name": "Extended Phone Calls",
        "creator": "simkatu",
        "mod_title": "Extended Phone Calls",
        "override_mod_title": True,
        "version": "2026.07.03",
        "links": [
            ("Patreon (공식)", "extended phone calls | simkatu", "https://www.patreon.com/simkatu/posts/extended-phone-117285790"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_reading_override_v3.package",
            "simkatu_reading_override.package",
            "simkatu_reading_override",
            "reading_override",
            "reading override",
            "reading-override",
            "simkatu_animations_addon_loungechair.package",
            "simkatu_animations_addon_loungechair",
            "simkatu_animations_addon_murphybed_sp16.package",
            "simkatu_animations_addon_murphybed_sp16",
        ],
        "name": "Reading Override",
        "creator": "simkatu",
        "mod_title": "Reading Override",
        "override_mod_title": True,
        "version": "3",
        "links": [
            ("Patreon (공식)", "reading override (v3) | simkatu", "https://www.patreon.com/simkatu/posts/reading-override-174169741"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_eating_at_the_table_animation_override.package",
            "simkatu_eating_at_the_table.package",
            "simkatu_eating_at_table.package",
            "simkatu_eating_at_the_table",
            "simkatu_eating_at_table",
            "eating_at_the_table_animation_override",
            "eating at the table animation override",
            "eating-at-table",
        ],
        "name": "Eating at the Table Animation Override",
        "creator": "simkatu",
        "mod_title": "Eating at the Table Animation Override",
        "override_mod_title": True,
        "version": "2025.07.26",
        "links": [
            ("Patreon (공식)", "eating at the table animation override | simkatu", "https://www.patreon.com/simkatu/posts/eating-at-table-134998014"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_functional_mini_easels.package",
            "simkatu_functional_mini_easels",
            "functional_mini_easels",
            "functional mini easels",
        ],
        "name": "Painting Animation Override - Functional Mini Easels",
        "creator": "simkatu",
        "mod_title": "Painting Animation Override - Functional Mini Easels",
        "override_mod_title": True,
        "version": "2026.08.02",
        "links": [
            ("Patreon (공식)", "painting animation override (Functional Mini Easels) | simkatu", "https://www.patreon.com/simkatu/posts/painting-mini-130600688"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_canvas_frame_override_v1.package",
            "simkatu_canvas_frame_override_v2.package",
            "simkatu_canvas_frame_override_v3.package",
            "simkatu_canvas_frame_override_v1",
            "simkatu_canvas_frame_override_v2",
            "simkatu_canvas_frame_override_v3",
            "simkatu_canvas_frame_override",
            "canvas_frame_override",
            "canvas frame override",
        ],
        "name": "Painting Animation Override - Canvas Frame Override",
        "creator": "simkatu",
        "mod_title": "Painting Animation Override - Canvas Frame Override",
        "override_mod_title": True,
        "version": "2026.08.02",
        "links": [
            ("Patreon (공식)", "painting animation override (Canvas Frame Override) | simkatu", "https://www.patreon.com/simkatu/posts/painting-mini-130600688"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_painting_animation_override.package",
            "simkatu_painting_animation_override_gender_neutral.package",
            "simkatu_painting_override.package",
            "simkatu_painting_animation_override_gender_neutral",
            "simkatu_painting_animation_override",
            "simkatu_painting_override",
            "simkatu_painting",
            "painting_animation_override",
            "painting animation override",
            "painting-animation-override",
        ],
        "name": "Painting Animation Override",
        "creator": "simkatu",
        "mod_title": "Painting Animation Override",
        "override_mod_title": True,
        "version": "2026.08.02",
        "links": [
            ("Patreon (공식)", "painting animation override | simkatu", "https://www.patreon.com/simkatu/posts/painting-mini-130600688"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_compute_animation_override.package",
            "simkatu_computer_animation_override.package",
            "simkatu_compute_animation_override",
            "simkatu_computer_animation_override",
            "compute_animation_override",
            "computer_animation_override",
            "computer animation override",
            "computer-animation-override",
        ],
        "name": "Computer Animation Override",
        "creator": "simkatu",
        "mod_title": "Computer Animation Override",
        "override_mod_title": True,
        "version": "2025.06.25",
        "links": [
            ("Patreon (공식)", "computer animation override | simkatu", "https://www.patreon.com/simkatu/posts/computer-126595678"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_phone_calls_animations_override.package",
            "simkatu_phone_call_animation_override.package",
            "simkatu_phone_calls_animations_override",
            "simkatu_phone_call_animation_override",
            "phone_calls_animations_override",
            "phone_call_animation_override",
            "phone call animations override",
            "phone call animation override",
            "phone-call-animations-override",
        ],
        "name": "Phone Call Animation Override",
        "creator": "simkatu",
        "mod_title": "Phone Call Animation Override",
        "override_mod_title": True,
        "version": "2025.06.04",
        "links": [
            ("Patreon (공식)", "phone call animations override | simkatu", "https://www.patreon.com/simkatu/posts/phone-call-118902550"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_writing_animation_override.package",
            "simkatu_writing_animation_override",
            "writing_animation_override",
            "writing animation override",
            "writing-animation-override",
            "writing-override",
        ],
        "name": "Writing Animation Override",
        "creator": "simkatu",
        "mod_title": "Writing Animation Override",
        "override_mod_title": True,
        "version": "2024.10.16",
        "links": [
            ("Patreon (공식)", "writing animation override | simkatu", "https://www.patreon.com/simkatu/posts/writing-override-113770138"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_relaxed_tv_watching_override.package",
            "simkatu_relaxed_tv_watching_override",
            "simkatu_relaxed_tv_watching_animation_override",
            "relaxed_tv_watching_override",
            "relaxed tv watching animations override",
            "relaxed tv watching animation override",
            "relaxed tv watching override",
            "relaxed-tv-watching",
        ],
        "name": "Relaxed TV Watching Animation Override",
        "creator": "simkatu",
        "mod_title": "Relaxed TV Watching Animation Override",
        "override_mod_title": True,
        "version": "2026.10.30",
        "links": [
            ("Patreon (공식)", "relaxed tv watching animations override | simkatu", "https://www.patreon.com/simkatu/posts/relaxed-tv-113487807"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_singing_animation_with_microphone.package",
            "simkatu_singing_animation_with_microphone",
            "simkatu_override_of_singing_animation_with_microphone.package",
            "simkatu_override_of_singing_animation_with_microphone",
            "simkatu_singing_with_microphone.package",
            "simkatu_singing_with_microphone",
            "simkatu_singing_override.package",
            "simkatu_singing_override",
            "override_of_singing_animation_with_microphone",
            "override of singing animation with microphone",
            "singing_animation_with_microphone",
            "singing animation with microphone",
            "singing_with_microphone_override",
            "override-of-with-107265096",
        ],
        "name": "Override of Singing Animation with Microphone",
        "creator": "simkatu",
        "mod_title": "Override of Singing Animation with Microphone",
        "override_mod_title": True,
        "version": "2024.07.01",
        "links": [
            ("Patreon (공식)", "override of singing animation with microphone | simkatu", "https://www.patreon.com/simkatu/posts/override-of-with-107265096"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_tryonweddingpromoutfits_wardrobeplatform_addon.package",
            "simkatu_tryonweddingpromoutfits_wardrobeplatform_addon",
            "tryonweddingpromoutfits_wardrobeplatform_addon",
            "wardrobeplatform_addon",
            "wardrobe platform addon",
            "try on wedding & prom outfits - addon",
            "try on wedding and prom outfits - addon",
        ],
        "name": "Try on Wedding & Prom Outfits - Addon",
        "creator": "simkatu",
        "mod_title": "Try on Wedding & Prom Outfits - Addon",
        "override_mod_title": True,
        "version": "2026.10.26",
        "links": [
            ("Patreon (공식)", "try on wedding & prom outfits | simkatu", "https://www.patreon.com/simkatu/posts/try-on-wedding-166429206"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_tryonweddingpromoutfits_alllots_v1.package",
            "simkatu_tryonweddingpromoutfits_retailthriftlots_v2.package",
            "simkatu_tryonweddingpromoutfits",
            "tryonweddingpromoutfits",
            "try on wedding & prom outfits",
            "try on wedding and prom outfits",
            "try-on-wedding-166429206",
        ],
        "name": "Try on Wedding & Prom Outfits",
        "creator": "simkatu",
        "mod_title": "Try on Wedding & Prom Outfits",
        "override_mod_title": True,
        "version": "2026.10.26",
        "requires_option_modal": True,
        "option_modal_prompt": "설치할 부지 적용 버전을 선택해 주세요. (allLots_v1 / retailThriftLots_v2 중 1개 선택 · 동시 설치 불가)",
        "option_presets": [
            {
                "file_name": "simkatu_tryOnWeddingPromOutfits_allLots_v1.package",
                "label": "allLots_v1 (모든 부지 적용)",
                "match_tokens": ["alllots_v1"],
            },
            {
                "file_name": "simkatu_tryOnWeddingPromOutfits_retailThriftLots_v2.package",
                "label": "retailThriftLots_v2 (상점 · 중고매장 부지 전용)",
                "match_tokens": ["retailthriftlots_v2"],
            },
        ],
        "links": [
            ("Patreon (공식)", "try on wedding & prom outfits | simkatu", "https://www.patreon.com/simkatu/posts/try-on-wedding-166429206"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_selfcare_washface.package",
            "simkatu_selfcare_washface",
            "selfcare_washface",
            "washface",
            "selfcare - wash face",
        ],
        "name": "Selfcare - Wash Face",
        "creator": "simkatu",
        "mod_title": "Selfcare - Wash Face",
        "override_mod_title": True,
        "version": "2026.08.31",
        "links": [
            ("Patreon (공식)", "wash face and sanitize hands | simkatu", "https://www.patreon.com/simkatu/posts/wash-face-and-159477437"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_selfcare_handsanitizer.package",
            "simkatu_selfcare_handsanitizer",
            "selfcare_handsanitizer",
            "handsanitizer",
            "selfcare - hand sanitizer",
        ],
        "name": "Selfcare - Hand Sanitizer",
        "creator": "simkatu",
        "mod_title": "Selfcare - Hand Sanitizer",
        "override_mod_title": True,
        "version": "2026.08.31",
        "links": [
            ("Patreon (공식)", "wash face and sanitize hands | simkatu", "https://www.patreon.com/simkatu/posts/wash-face-and-159477437"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_selfcare_addon_purchasefromcomputer.package",
            "simkatu_selfcare_addon_purchasefromcomputer",
            "selfcare_addon_purchasefromcomputer",
            "purchasefromcomputer",
            "purchase from computer",
            "selfcare - addon - purchase from computer",
        ],
        "name": "Selfcare - Addon - Purchase From Computer",
        "creator": "simkatu",
        "mod_title": "Selfcare - Addon - Purchase From Computer",
        "override_mod_title": True,
        "version": "2026.08.31",
        "links": [
            ("Patreon (공식)", "wash face and sanitize hands | simkatu", "https://www.patreon.com/simkatu/posts/wash-face-and-159477437"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_selfcare_wallsanitizer_gettowork_override.package",
            "simkatu_selfcare_wallsanitizer_gettowork_override",
            "simkatu_selfcare_wallsanitizer_gettowork",
            "wallsanitizer_gettowork",
            "selfcare - wall sanitizer - get to work",
        ],
        "name": "Selfcare - Wall Sanitizer - Get To Work",
        "creator": "simkatu",
        "mod_title": "Selfcare - Wall Sanitizer - Get To Work",
        "override_mod_title": True,
        "version": "2026.08.31",
        "links": [
            ("Patreon (공식)", "wash face and sanitize hands | simkatu", "https://www.patreon.com/simkatu/posts/wash-face-and-159477437"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_selfcare_wallsanitizer_basegame.package",
            "simkatu_selfcare_wallsanitizer_basegame",
            "wallsanitizer_basegame",
            "simkatu_selfcare_wallsanitizer",
            "wallsanitizer",
            "selfcare - wall sanitizer - base game",
        ],
        "name": "Selfcare - Wall Sanitizer - Base Game",
        "creator": "simkatu",
        "mod_title": "Selfcare - Wall Sanitizer - Base Game",
        "override_mod_title": True,
        "version": "2026.08.31",
        "links": [
            ("Patreon (공식)", "wash face and sanitize hands | simkatu", "https://www.patreon.com/simkatu/posts/wash-face-and-159477437"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_mirrorphoto_posepack_female.package",
            "simkatu_mirrorphoto_posepack_female",
            "mirrorphoto_posepack_female",
            "posepack_female",
            "mirror photo posepack female",
            "mirror selfie - mirror photo posepack female",
        ],
        "name": "Mirror Selfie - Mirror Photo Posepack Female",
        "creator": "simkatu",
        "mod_title": "Mirror Selfie - Mirror Photo Posepack Female",
        "override_mod_title": True,
        "version": "2026.08.31",
        "links": [
            ("Patreon (공식)", "mirror selfie | simkatu", "https://www.patreon.com/simkatu/posts/mirror-selfie-146833653"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_mirrorphoto_posepack_male.package",
            "simkatu_mirrorphoto_posepack_male",
            "mirrorphoto_posepack_male",
            "posepack_male",
            "mirror photo posepack male",
            "mirror selfie - mirror photo posepack male",
        ],
        "name": "Mirror Selfie - Mirror Photo Posepack Male",
        "creator": "simkatu",
        "mod_title": "Mirror Selfie - Mirror Photo Posepack Male",
        "override_mod_title": True,
        "version": "2026.08.31",
        "links": [
            ("Patreon (공식)", "mirror selfie | simkatu", "https://www.patreon.com/simkatu/posts/mirror-selfie-146833653"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_mirrorphoto_phone.package",
            "simkatu_mirrorphoto_phone",
            "mirrorphoto_phone",
            "mirror photo phone",
            "mirror selfie - mirror photo phone",
        ],
        "name": "Mirror Selfie - Mirror Photo Phone",
        "creator": "simkatu",
        "mod_title": "Mirror Selfie - Mirror Photo Phone",
        "override_mod_title": True,
        "version": "2026.08.31",
        "links": [
            ("Patreon (공식)", "mirror selfie | simkatu", "https://www.patreon.com/simkatu/posts/mirror-selfie-146833653"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_mirrorphoto_v2_genderneutral.package",
            "simkatu_mirrorphoto_v2_genderneutral",
            "mirrorphoto_v2_genderneutral",
            "mirror selfie - mirror photo v2",
            "mirror photo v2",
        ],
        "name": "Mirror Selfie - Mirror Photo v2",
        "creator": "simkatu",
        "mod_title": "Mirror Selfie - Mirror Photo v2",
        "override_mod_title": True,
        "version": "2026.08.31",
        "requires_option_modal": True,
        "option_modal_prompt": "설치할 Mirror Photo 버전을 선택해 주세요. (mirrorphoto 기본 / v2 genderneutral 중 1개 선택 · 동시 설치 불가)",
        "option_presets": [
            {
                "file_name": "simkatu_mirrorphoto.package",
                "label": "mirrorphoto (기본 버전 · 택1)",
                "match_tokens": ["simkatu_mirrorphoto.package"],
            },
            {
                "file_name": "simkatu_mirrorphoto_v2_genderneutral.package",
                "label": "mirrorphoto_v2_genderneutral (성별 무관 v2 · 택1)",
                "match_tokens": ["mirrorphoto_v2_genderneutral"],
            },
        ],
        "links": [
            ("Patreon (공식)", "mirror selfie | simkatu", "https://www.patreon.com/simkatu/posts/mirror-selfie-146833653"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_mirrorphoto.package",
            "simkatu_mirrorphoto",
            "mirrorphoto",
            "mirror selfie - mirror photo",
            "mirror-selfie-146833653",
        ],
        "name": "Mirror Selfie - Mirror Photo",
        "creator": "simkatu",
        "mod_title": "Mirror Selfie - Mirror Photo",
        "override_mod_title": True,
        "version": "2026.08.31",
        "requires_option_modal": True,
        "option_modal_prompt": "설치할 Mirror Photo 버전을 선택해 주세요. (mirrorphoto 기본 / v2 genderneutral 중 1개 선택 · 동시 설치 불가)",
        "option_presets": [
            {
                "file_name": "simkatu_mirrorphoto.package",
                "label": "mirrorphoto (기본 버전 · 택1)",
                "match_tokens": ["simkatu_mirrorphoto.package"],
            },
            {
                "file_name": "simkatu_mirrorphoto_v2_genderneutral.package",
                "label": "mirrorphoto_v2_genderneutral (성별 무관 v2 · 택1)",
                "match_tokens": ["mirrorphoto_v2_genderneutral"],
            },
        ],
        "links": [
            ("Patreon (공식)", "mirror selfie | simkatu", "https://www.patreon.com/simkatu/posts/mirror-selfie-146833653"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_read_in_bed.package",
            "simkatu_read_in_bed",
            "simkatu_readinbed.package",
            "simkatu_readinbed",
            "read_in_bed",
            "read in bed",
            "readinbed",
            "read-in-bed-128394840",
        ],
        "name": "Read in Bed",
        "creator": "simkatu",
        "mod_title": "Read in Bed",
        "override_mod_title": True,
        "version": "2026.08.31",
        "links": [
            ("Patreon (공식)", "read in bed | simkatu", "https://www.patreon.com/simkatu/posts/read-in-bed-128394840"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_music_listening_interactions_autonomy_off.package",
            "simkatu_music_listening_interactions_autonomy_off",
            "music_listening_interactions_autonomy_off",
            "simkatu_music_listening_interactions.package",
            "simkatu_music_listening_interactions",
            "music_listening_interactions",
            "new music listening interactions",
            "music listening interactions",
            "new-music-114984579",
        ],
        "name": "Music Listening Interactions",
        "creator": "simkatu",
        "mod_title": "Music Listening Interactions",
        "override_mod_title": True,
        "version": "2026.03.20",
        "requires_option_modal": True,
        "option_modal_prompt": "설치할 Music Listening Interactions 버전을 선택해 주세요. (기본 버전 / Autonomy Off 중 1개 선택 · 동시 설치 불가)",
        "option_presets": [
            {
                "file_name": "simkatu_music_listening_interactions.package",
                "label": "music_listening_interactions (기본 버전 · 택1)",
                "match_tokens": ["simkatu_music_listening_interactions.package"],
            },
            {
                "file_name": "simkatu_music_listening_interactions_autonomy_off.package",
                "label": "music_listening_interactions_autonomy_off (자율성 끄기 · 택1)",
                "match_tokens": ["music_listening_interactions_autonomy_off"],
            },
        ],
        "links": [
            ("Patreon (공식)", "new music listening interactions | simkatu", "https://www.patreon.com/simkatu/posts/new-music-114984579"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_cry_mod_v2.package",
            "simkatu_cry_mod_v2",
            "simkatu_cry_mod.package",
            "simkatu_cry_mod",
            "cry_mod_v2",
            "cry_mod",
            "cry mod",
            "cry-mod-v-2-141863817",
        ],
        "name": "Cry Mod",
        "creator": "simkatu",
        "mod_title": "Cry Mod",
        "override_mod_title": True,
        "version": "2",
        "links": [
            ("Patreon (공식)", "cry mod v.2 | simkatu", "https://www.patreon.com/simkatu/posts/cry-mod-v-2-141863817"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_nap_on_the_table_more_energy.package",
            "simkatu_nap_on_the_table_more_energy",
            "nap_on_the_table_more_energy",
            "simkatu_nap_on_the_table.package",
            "simkatu_nap_on_the_table",
            "nap_on_the_table",
            "nap on the table",
            "nap-on-table-112677899",
        ],
        "name": "Nap on the Table",
        "creator": "simkatu",
        "mod_title": "Nap on the Table",
        "override_mod_title": True,
        "version": "2026.05.15",
        "requires_option_modal": True,
        "option_modal_prompt": "설치할 Nap on the Table 버전을 선택해 주세요. (기본 버전 / More Energy 중 1개 선택 · 동시 설치 불가)",
        "option_presets": [
            {
                "file_name": "simkatu_nap_on_the_table.package",
                "label": "nap_on_the_table (기본 버전 · 택1)",
                "match_tokens": ["simkatu_nap_on_the_table.package"],
            },
            {
                "file_name": "simkatu_nap_on_the_table_more_energy.package",
                "label": "nap_on_the_table_more_energy (에너지 회복 증가 · 택1)",
                "match_tokens": ["nap_on_the_table_more_energy"],
            },
        ],
        "links": [
            ("Patreon (공식)", "nap on the table | simkatu", "https://www.patreon.com/simkatu/posts/nap-on-table-112677899"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_mod_endless_grief_with_autonomy.package",
            "simkatu_mod_endless_grief_with_autonomy",
            "simkatu_mod_endless_grief_without_autonomy.package",
            "simkatu_mod_endless_grief_without_autonomy",
            "endless_grief_with_autonomy",
            "endless_grief_without_autonomy",
            "simkatu_mod_endless_grief",
            "endless_grief",
            "endless grief",
            "endless-grief-111074342",
        ],
        "name": "Endless Grief",
        "creator": "simkatu",
        "mod_title": "Endless Grief",
        "override_mod_title": True,
        "version": "2026.03.20",
        "requires_option_modal": True,
        "option_modal_prompt": "설치할 Endless Grief 버전을 선택해 주세요. (With Autonomy / Without Autonomy 중 1개 선택 · 동시 설치 불가)",
        "option_presets": [
            {
                "file_name": "simkatu_mod_endless_grief_with_autonomy.package",
                "label": "endless_grief_with_autonomy (자율성 켜기 · 택1)",
                "match_tokens": ["endless_grief_with_autonomy"],
            },
            {
                "file_name": "simkatu_mod_endless_grief_without_autonomy.package",
                "label": "endless_grief_without_autonomy (자율성 끄기 · 택1)",
                "match_tokens": ["endless_grief_without_autonomy"],
            },
        ],
        "links": [
            ("Patreon (공식)", "endless grief | simkatu", "https://www.patreon.com/simkatu/posts/endless-grief-111074342"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_group_announcements.package",
            "simkatu_group_announcements",
            "group_announcements",
            "group announcements",
            "group-165200366",
        ],
        "name": "Group Announcements",
        "creator": "simkatu",
        "mod_title": "Group Announcements",
        "override_mod_title": True,
        "version": "2026.07.31",
        "links": [
            ("Patreon (공식)", "group announcements | simkatu", "https://www.patreon.com/simkatu/posts/group-165200366"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_cuddle_while_watching_tv.package",
            "simkatu_cuddle_while_watching_tv",
            "cuddle_while_watching_tv",
            "cuddle while watching tv",
            "cuddle-while-tv-161199341",
        ],
        "name": "Cuddle While Watching TV",
        "creator": "simkatu",
        "mod_title": "Cuddle While Watching TV",
        "override_mod_title": True,
        "version": "2026.08.31",
        "links": [
            ("Patreon (공식)", "cuddle while watching tv | simkatu", "https://www.patreon.com/simkatu/posts/cuddle-while-tv-161199341"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_intimate_lap_kiss.package",
            "simkatu_intimate_lap_kiss",
            "intimate_lap_kiss",
            "intimate lap kiss",
            "intimate-lap-156435424",
        ],
        "name": "Intimate Lap Kiss",
        "creator": "simkatu",
        "mod_title": "Intimate Lap Kiss",
        "override_mod_title": True,
        "version": "2026.04.24",
        "links": [
            ("Patreon (공식)", "intimate lap kiss | simkatu", "https://www.patreon.com/simkatu/posts/intimate-lap-156435424"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_hangout_and_chat_on_bed.package",
            "simkatu_hangout_and_chat_on_bed",
            "hangout_and_chat_on_bed",
            "hang_out_and_chat_on_the_bed",
            "hang out and chat on the bed",
            "hangout and chat on bed",
            "hang-out-and-on-143636880",
        ],
        "name": "Hang Out and Chat on the Bed",
        "creator": "simkatu",
        "mod_title": "Hang Out and Chat on the Bed",
        "override_mod_title": True,
        "version": "2026.07.03",
        "links": [
            ("Patreon (공식)", "hang out and chat on the bed | simkatu", "https://www.patreon.com/simkatu/posts/hang-out-and-on-143636880"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_interaction_ask_to_learn_how_to_kiss.package",
            "simkatu_interaction_ask_to_learn_how_to_kiss",
            "interaction_ask_to_learn_how_to_kiss",
            "ask_to_learn_how_to_kiss",
            "ask to learn how to kiss",
            "new-interaction-109317608",
        ],
        "name": "Ask to Learn How to Kiss",
        "creator": "simkatu",
        "mod_title": "Ask to Learn How to Kiss",
        "override_mod_title": True,
        "version": "2025.04.07",
        "links": [
            ("Patreon (공식)", "new interaction \"ask to learn how to kiss\" | simkatu", "https://www.patreon.com/simkatu/posts/new-interaction-109317608"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_show_off_the_baby.package",
            "simkatu_show_off_the_baby",
            "show_off_the_baby",
            "show off the baby",
            "show-off-baby-145686121",
        ],
        "name": "Show Off the Baby",
        "creator": "simkatu",
        "mod_title": "Show Off the Baby",
        "override_mod_title": True,
        "version": "2025.12.12",
        "links": [
            ("Patreon (공식)", "show off the baby | simkatu", "https://www.patreon.com/simkatu/posts/show-off-baby-145686121"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_dance_with_baby_in_arms.package",
            "simkatu_dance_with_baby_in_arms",
            "dance_with_baby_in_arms",
            "dance with baby in arms",
            "dance-with-baby-132101139",
        ],
        "name": "Dance with Baby in Arms",
        "creator": "simkatu",
        "mod_title": "Dance with Baby in Arms",
        "override_mod_title": True,
        "version": "2025.06.23",
        "links": [
            ("Patreon (공식)", "dance with baby in arms | simkatu", "https://www.patreon.com/simkatu/posts/dance-with-baby-132101139"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_nap_with_baby_in_bed_v2_more_energy.package",
            "simkatu_nap_with_baby_in_bed_v2_more_energy",
            "nap_with_baby_in_bed_v2_more_energy",
            "simkatu_nap_with_baby_in_bed.package",
            "simkatu_nap_with_baby_in_bed",
            "nap_with_baby_in_bed",
            "nap with baby in bed",
            "nap-with-baby-in-137123858",
        ],
        "name": "Nap With Baby in Bed",
        "creator": "simkatu",
        "mod_title": "Nap With Baby in Bed",
        "override_mod_title": True,
        "version": "2026.04.18",
        "requires_option_modal": True,
        "option_modal_prompt": "설치할 Nap With Baby in Bed 버전을 선택해 주세요. (기본 버전 / v2 More Energy 중 1개 선택 · 동시 설치 불가)",
        "option_presets": [
            {
                "file_name": "simkatu_nap_with_baby_in_bed.package",
                "label": "nap_with_baby_in_bed (기본 버전 · 택1)",
                "match_tokens": ["simkatu_nap_with_baby_in_bed.package"],
            },
            {
                "file_name": "simkatu_nap_with_baby_in_bed_v2_more_energy.package",
                "label": "nap_with_baby_in_bed_v2_more_energy (에너지 회복 증가 v2 · 택1)",
                "match_tokens": ["nap_with_baby_in_bed_v2_more_energy"],
            },
        ],
        "links": [
            ("Patreon (공식)", "nap with baby in bed | simkatu", "https://www.patreon.com/simkatu/posts/nap-with-baby-in-137123858"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_nap_with_infant.package",
            "simkatu_nap_with_infant",
            "nap_with_infant",
            "take a nap with infant",
            "take a nap with a infant",
            "take a nap with an infant",
            "take-nap-with-116027318",
        ],
        "name": "Take a Nap with Infant",
        "creator": "simkatu",
        "mod_title": "Take a Nap with Infant",
        "override_mod_title": True,
        "version": "2025.02.25",
        "links": [
            ("Patreon (공식)", "take a nap with infant | simkatu", "https://www.patreon.com/simkatu/posts/take-nap-with-116027318"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_nap_with_toddler.package",
            "simkatu_nap_with_toddler",
            "nap_with_toddler",
            "take a nap with a toddler",
            "take a nap with toddler",
            "take-nap-with-172527464",
        ],
        "name": "Take a Nap with a Toddler",
        "creator": "simkatu",
        "mod_title": "Take a Nap with a Toddler",
        "override_mod_title": True,
        "version": "2026.10.17",
        "links": [
            ("Patreon (공식)", "take a nap with a toddler | simkatu", "https://www.patreon.com/simkatu/posts/take-nap-with-172527464"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_nap_with_child.package",
            "simkatu_nap_with_child",
            "nap_with_child",
            "take a nap with a child",
            "take a nap with child",
            "take-nap-with-171262356",
        ],
        "name": "Take a Nap with a Child",
        "creator": "simkatu",
        "mod_title": "Take a Nap with a Child",
        "override_mod_title": True,
        "version": "2026.10.02",
        "links": [
            ("Patreon (공식)", "take a nap with a child | simkatu", "https://www.patreon.com/simkatu/posts/take-nap-with-171262356"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_infant_lap_interactions.package",
            "simkatu_infant_lap_interactions",
            "infant_lap_interactions",
            "infant lap interactions",
            "lap reading for infants & reading while infants nap on laps",
            "lap reading for infants",
            "reading while infants nap on laps",
            "lap-reading-for-121264123",
        ],
        "name": "Lap Reading for Infants & Reading While Infants Nap on Laps",
        "creator": "simkatu",
        "mod_title": "Lap Reading for Infants & Reading While Infants Nap on Laps",
        "override_mod_title": True,
        "version": "2025.11.26",
        "links": [
            ("Patreon (공식)", "lap reading for infants & reading while infants nap on laps | simkatu", "https://www.patreon.com/simkatu/posts/lap-reading-for-121264123"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_read_snuggle_toddlerbed.package",
            "simkatu_read_snuggle_toddlerbed",
            "read_snuggle_toddlerbed",
            "read and snuggle on toddler bed",
            "read-and-snuggle-139398872",
        ],
        "name": "Read and Snuggle on Toddler Bed",
        "creator": "simkatu",
        "mod_title": "Read and Snuggle on Toddler Bed",
        "override_mod_title": True,
        "version": "2025.09.21",
        "links": [
            ("Patreon (공식)", "read and snuggle on toddler bed | simkatu", "https://www.patreon.com/simkatu/posts/read-and-snuggle-139398872"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_infants_toddlers_play_toys_on_highchairs_cribs.package",
            "simkatu_infants_toddlers_play_toys_on_highchairs_cribs",
            "infants_toddlers_play_toys_on_highchairs_cribs",
            "play_toys_on_highchairs_cribs",
            "playing with toys on highchairs and cribs",
            "playing with toys on high chair and cribs",
            "playing-with-on-132837938",
        ],
        "name": "Playing with Toys on Highchairs and Cribs",
        "creator": "simkatu",
        "mod_title": "Playing with Toys on Highchairs and Cribs",
        "override_mod_title": True,
        "version": "2026.02.14",
        "links": [
            ("Patreon (공식)", "playing with toys on highchairs and cribs | simkatu", "https://www.patreon.com/simkatu/posts/playing-with-on-132837938"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_override_gradeschool_homework.package",
            "simkatu_override_gradeschool_homework",
            "override_gradeschool_homework",
            "gradeschool_homework",
            "homework override",
        ],
        "name": "Homework Override",
        "creator": "simkatu",
        "mod_title": "Homework Override",
        "override_mod_title": True,
        "version": "2026.03.20",
        "links": [
            ("Patreon (공식)", "kids interaction pack + homework override | simkatu", "https://www.patreon.com/simkatu/posts/kids-interaction-125422688"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_kids_interactions_pack_v1_ea_homework.package",
            "simkatu_kids_interactions_pack_v1_ea_homework",
            "simkatu_kids_interactions_pack_v2_custom_homework.package",
            "simkatu_kids_interactions_pack_v2_custom_homework",
            "kids_interactions_pack_v1_ea_homework",
            "kids_interactions_pack_v2_custom_homework",
            "kids_interactions_pack",
            "kids interaction pack",
            "kids-interaction-125422688",
        ],
        "name": "Kids Interaction Pack",
        "creator": "simkatu",
        "mod_title": "Kids Interaction Pack",
        "override_mod_title": True,
        "version": "2026.03.20",
        "requires_option_modal": True,
        "option_modal_prompt": "설치할 Kids Interaction Pack 버전을 선택해 주세요. (v1 EA Homework / v2 Custom Homework 중 1개 선택 · 동시 설치 불가)",
        "option_presets": [
            {
                "file_name": "simkatu_kids_interactions_pack_v1_ea_homework.package",
                "label": "kids_interactions_pack_v1_ea_homework (EA 기본 숙제 버전 · 택1)",
                "match_tokens": ["v1_ea_homework"],
            },
            {
                "file_name": "simkatu_kids_interactions_pack_v2_custom_homework.package",
                "label": "kids_interactions_pack_v2_custom_homework (커스텀 숙제 버전 · 택1)",
                "match_tokens": ["v2_custom_homework"],
            },
        ],
        "links": [
            ("Patreon (공식)", "kids interaction pack + homework override | simkatu", "https://www.patreon.com/simkatu/posts/kids-interaction-125422688"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_givemedicine_v1_sickness_gtw.package",
            "simkatu_givemedicine_v1_sickness_gtw",
            "simkatu_givemedicine_v2_sickness_ailments_gtw_ebn.package",
            "simkatu_givemedicine_v2_sickness_ailments_gtw_ebn",
            "givemedicine_v1_sickness_gtw",
            "givemedicine_v2_sickness_ailments_gtw_ebn",
            "simkatu_givemedicine",
            "give medicine to treat sickness and ailments",
            "give-medicine-to-160426834",
        ],
        "name": "Give Medicine to Treat Sickness and Ailments",
        "creator": "simkatu",
        "mod_title": "Give Medicine to Treat Sickness and Ailments",
        "override_mod_title": True,
        "version": "2026.06.07",
        "requires_option_modal": True,
        "option_modal_prompt": "설치할 Give Medicine 버전을 선택해 주세요. (v1 Sickness GTW / v2 Sickness & Ailments GTW+EBN 중 1개 선택 · 동시 설치 불가)",
        "option_presets": [
            {
                "file_name": "simkatu_giveMedicine_v1_sickness_GTW.package",
                "label": "giveMedicine_v1_sickness_GTW (질병 전용 · GTW · 택1)",
                "match_tokens": ["v1_sickness_gtw"],
            },
            {
                "file_name": "simkatu_giveMedicine_v2_sickness_ailments_GTW_EBN.package",
                "label": "giveMedicine_v2_sickness_ailments_GTW_EBN (질병+질환 · GTW+EBN · 택1)",
                "match_tokens": ["v2_sickness_ailments_gtw_ebn"],
            },
        ],
        "links": [
            ("Patreon (공식)", "give medicine to treat sickness and ailments | simkatu", "https://www.patreon.com/simkatu/posts/give-medicine-to-160426834"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_functional_pacifier_v2.package",
            "simkatu_functional_pacifier_v2",
            "simkatu_functional_pacifier.package",
            "simkatu_functional_pacifier",
            "functional_pacifier_v2",
            "functional_pacifier",
            "functional pacifier",
            "functional-2-0-119983715",
        ],
        "name": "Functional Pacifier",
        "creator": "simkatu",
        "mod_title": "Functional Pacifier",
        "override_mod_title": True,
        "version": "2",
        "links": [
            ("Patreon (공식)", "functional pacifier 2.0 | simkatu", "https://www.patreon.com/simkatu/posts/functional-2-0-119983715"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_functional_stroller_syb_helios.package",
            "simkatu_functional_stroller_syb_helios",
            "functional_stroller_syb_helios",
            "functional stroller_syb_helios",
            "syb_helios",
            "functional strollers by syboulette - helios",
        ],
        "name": "Functional Strollers By Syboulette - Helios",
        "creator": "simkatu",
        "mod_title": "Functional Strollers By Syboulette - Helios",
        "override_mod_title": True,
        "version": "2026.03.25",
        "links": [
            ("Patreon (공식)", "functional strollers by syboulette | simkatu", "https://www.patreon.com/simkatu/posts/functional-by-152419156"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_functional_stroller_syb_charles.package",
            "simkatu_functional_stroller_syb_charles",
            "functional_stroller_syb_charles",
            "functional stroller_syb_charles",
            "syb_charles",
            "functional strollers by syboulette - charles",
        ],
        "name": "Functional Strollers By Syboulette - Charles",
        "creator": "simkatu",
        "mod_title": "Functional Strollers By Syboulette - Charles",
        "override_mod_title": True,
        "version": "2026.03.25",
        "links": [
            ("Patreon (공식)", "functional strollers by syboulette | simkatu", "https://www.patreon.com/simkatu/posts/functional-by-152419156"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_functional_stroller_syb_enchanted_dreams.package",
            "simkatu_functional_stroller_syb_enchanted_dreams",
            "functional_stroller_syb_enchanted_dreams",
            "functional stroller_syb_enchanted_dreams",
            "syb_enchanted_dreams",
            "functional strollers by syboulette - enchanted dreams",
        ],
        "name": "Functional Strollers By Syboulette - Enchanted Dreams",
        "creator": "simkatu",
        "mod_title": "Functional Strollers By Syboulette - Enchanted Dreams",
        "override_mod_title": True,
        "version": "2026.03.25",
        "links": [
            ("Patreon (공식)", "functional strollers by syboulette | simkatu", "https://www.patreon.com/simkatu/posts/functional-by-152419156"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_functional_stroller_gameanim_override.package",
            "simkatu_functional_stroller_gameanim_override",
            "functional_stroller_gameanim_override",
            "functional stroller - animation override",
            "functional stroller animation override",
        ],
        "name": "Functional Stroller - Animation Override",
        "creator": "simkatu",
        "mod_title": "Functional Stroller - Animation Override",
        "override_mod_title": True,
        "version": "2026.03.07",
        "links": [
            ("Patreon (공식)", "functional stroller for infants | simkatu", "https://www.patreon.com/simkatu/posts/functional-for-149952231"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simkatu_functional_stroller.package",
            "simkatu_functional_stroller",
            "functional_stroller",
            "functional stroller for infants",
            "functional stroller",
            "functional-for-149952231",
        ],
        "name": "Functional Stroller",
        "creator": "simkatu",
        "mod_title": "Functional Stroller",
        "override_mod_title": True,
        "version": "2026.03.07",
        "links": [
            ("Patreon (공식)", "functional stroller for infants | simkatu", "https://www.patreon.com/simkatu/posts/functional-for-149952231"),
            ("Patreon 채널", "simkatu Official Patreon", "https://www.patreon.com/simkatu")
        ]
    },
    {
        "keywords": [
            "simplyanjuta_nomakeupnoacc_onrandomizedsims.package",
            "simplyanjuta_nomakeupnoacc_onrandomizedsims",
            "nomakeupnoacc_onrandomizedsims",
            "no make-up & no accessories on randomized sims",
            "no make-up no accessories on randomized sims",
        ],
        "name": "No Make-Up & No Accessories on Randomized Sims",
        "creator": "SimplyAnjuta",
        "mod_title": "No Make-Up & No Accessories on Randomized Sims",
        "override_mod_title": True,
        "version": "2026.05.13",
        "links": [
            ("Tumblr (공식)", "CAS Mod - No Make-Up & No Accessories on Randomized Sims | SimplyAnjuta", "https://www.tumblr.com/simplyanjuta/669037700728373248/cas-mod-no-make-up-no-accessories-on"),
            ("CurseForge (공식)", "No Make-Up & No Accessories on Randomized Sims | SimplyAnjuta", "https://www.curseforge.com/sims4/mods/no-make-up-no-accessories-on-randomized-sims")
        ]
    },
    {
        "keywords": [
            "turbodriver_simulationtimelineunclogger.ts4script",
            "turbodriver_simulationtimelineunclogger",
            "simulationtimelineunclogger",
            "simulation_timeline_unclogger",
            "simulation timeline unclogger",
            "simulation unclogger",
        ],
        "name": "Simulation Unclogger",
        "creator": "TURBODRIVER",
        "mod_title": "Simulation Unclogger",
        "override_mod_title": True,
        "version": "2022.09.10",
        "links": [
            ("CurseForge (공식)", "Simulation Unclogger | TURBODRIVER", "https://www.curseforge.com/sims4/mods/simulation-unclogger")
        ]
    },
    {
        "keywords": [
            "kayaker_gtw_aliensreloaded",
            "aliensreloaded",
            "aliens_reloaded",
            "aliens reloaded",
            "aliens-reloaded",
            "onemorekayaker",
        ],
        "name": "Aliens Reloaded",
        "creator": "OneMoreKayaker",
        "mod_title": "Aliens Reloaded",
        "override_mod_title": True,
        "version": "4.0.4",
        "links": [
            ("Itch.io (공식)", "Aliens Reloaded | OneMoreKayaker", "https://onemorekayaker.itch.io/aliens-reloaded")
        ]
    },
    {
        "keywords": [
            "kemzima_politicalworld",
            "politicalworld",
            "political_world",
            "political world",
            "political-world",
            "kemzima",
        ],
        "name": "Political World",
        "creator": "KemZima",
        "mod_title": "Political World",
        "override_mod_title": True,
        "version": "8.1",
        "links": [
            ("KemZima (공식)", "Political World | KemZima", "https://kemzimamods.com/political-world-mod/political-world-realistic-version-download-page/")
        ]
    },
    {
        "keywords": ["sims4_aichat_byok_addon", "aichat_byok", "byok_addon", "sims 4 ai chat byok addon"],
        "name": "Sims 4 AI Chat BYOK Addon",
        "creator": "lvl2032",
        "mod_title": "Sims 4 AI Chat BYOK Addon",
        "version": "2.6.1 (핫픽스)",
        "links": [
            ("제작자 공식 사이트", "S4m AI Chat BYOK 공식 배포 페이지", "https://s4m-byok.prmptplus.chatgpt.site/")
        ]
    },
    {
        "keywords": ["sims4_ai_chat.ts4script", "sims4_ai_chat", "sims 4 ai chat", "sims4aichat", "mod ai chat"],
        "name": "Sims 4 AI Chat",
        "creator": "VirtualConsciousnessLabs",
        "mod_title": "Sims 4 AI Chat",
        "version": "2.6.1",
        "links": [
            ("제작자 공식 사이트", "Sims 4 AI Chat v2.6.1 | Virtual Consciousness Labs", "https://sims4ai.virtualconscious.com/#install"),
            ("Patreon 채널", "Virtual Consciousness Labs Official Patreon", "https://www.patreon.com/VirtualConsciousnessLabs")
        ]
    },
    {
        "keywords": ["khlas_males_interactions", "males_interactions", "males interaction", "males interactions"],
        "name": "Males Interactions",
        "creator": "Khlas",
        "mod_title": "Males Interactions",
        "version": "1.91",
        "is_early_access": True,
        "links": [
            ("Patreon (선배포)", "KMI 1.91 + WW anims + others | Khlas", "https://www.patreon.com/khlas/posts/kmi-1-91-ww-164160544"),
            ("Patreon 채널", "Khlas Official Patreon", "https://www.patreon.com/khlas")
        ]
    },
    {
        "keywords": ["skarrd_perverted_expansion_pack", "perverted_expansion_pack", "perverted expansion pack"],
        "name": "Perverted Expansion Pack",
        "creator": "Skarrd",
        "mod_title": "Perverted Expansion Pack",
        "version": "3.0.1",
        "links": [
            ("LoversLab (공식)", "Skarrd's Perverted Expansion Pack | Skarrd", "https://www.loverslab.com/files/file/24771-skarrds-perverted-expansion-pack/")
        ]
    },
    {
        "keywords": ["cumshine", "spent_cumshine"],
        "name": "Cumshine",
        "creator": "Spent",
        "mod_title": "Cumshine",
        "version": "2026.10.23",
        "links": [
            ("Wicked.cc (공식)", "Cumshine - WickedCC | Spent", "https://wicked.cc/mods/spent/cumshine/"),
            ("Patreon 채널", "Spent Official Patreon", "https://www.patreon.com/Spent")
        ]
    },
    {
        "keywords": [
            "fitnesscontrols-limits",
            "fitnesscontrols_limits",
            "fitness controls limits",
            "limits-1.75x",
            "limits-3.00x",
            "limits-5.00x",
        ],
        "name": "Fitness Controls - Limits (애드온)",
        "creator": "roBurky",
        "mod_title": "Fitness Controls - Limits",
        "version": "2.0.12.0",
        "links": [
            ("Itch.io (공식)", "Fitness Controls Limits Addon | roBurky", "https://roburky.itch.io/sims4-fitness")
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
        "keywords": ["lot51_core.ts4script", "lot51_core", "lot 51 core library", "lot51 core library"],
        "name": "Lot 51 Core Library",
        "creator": "Lot 51",
        "mod_title": "Lot 51 Core Library",
        "version": "1.43.1",
        "links": [
            ("제작자 공식 사이트", "Lot 51 Core Library | Lot 51", "https://lot51.cc/core"),
            ("CurseForge (공식)", "Lot 51 Core Library - CurseForge", "https://www.curseforge.com/sims4/mods/lot-51-core-library")
        ]
    },
    {
        "keywords": ["xmlinjector_script.ts4script", "xmlinjector", "xml_injector", "xml injector", "scumbumbo"],
        "name": "XML Injector",
        "creator": "Scumbumbo",
        "mod_title": "XML Injector",
        "version": "4.2",
        "links": [
            ("공식 웹사이트", "Scumbumbo Mods XML Injector", "https://scumbumbomods.com/xml-injector"),
            ("CurseForge", "CurseForge XML Injector", "https://www.curseforge.com/sims4/mods/xml-injector")
        ]
    },
    {
        "keywords": [
            "lumpinou_rpo_collection_m00_corelibrary_required.ts4script",
            "lumpinou_rpo_collection",
            "rpo_collection_m",
            "rpo_collection",
            "relationship & pregnancy overhaul",
            "relationship and pregnancy overhaul",
        ],
        "name": "Relationship & Pregnancy Overhaul (RPO Collection)",
        "creator": "Lumpinou",
        "mod_title": "Relationship & Pregnancy Overhaul (RPO Collection)",
        "version": "3",
        "is_early_access": True,
        "requires_option_modal": True,
        "option_modal_mode": "rpo_channel",
        "option_modal_prompt": "RPO Collection에 적용할 배포 버전을 선택해 주세요. 선택한 옵션은 로컬 설정에 저장되어 다음 실행 시에도 유지됩니다.",
        "option_presets": [
            {
                "file_name": "rpo_channel:early_access",
                "channel": "early_access",
                "label": "선배포 버전 (Patreon Early Access · 수동 확인)",
                "description": "자동 다운로드를 실행하지 않고 기존의 '수동 확인' 상태를 유지합니다.",
            },
            {
                "file_name": "rpo_channel:free",
                "channel": "free",
                "label": "무료 버전 (공식 무료 공개 배포판 · 자동 업데이트)",
                "description": "무료 공개 배포판 기준으로 버전을 비교하고 자동 업데이트를 활성화합니다.",
            },
        ],
        "release_notes": "얼리 액세스(선배포) 버전 · Patreon 수동 다운로드 안내 (RPO v3)",
        "links": [
            ("Patreon (선배포)", "[Early Access] RPO v3 - Debuting \"Extra Opinions\" & Heavy Duty background changes | Lumpinou", "https://www.patreon.com/lumpinou/posts/early-access-rpo-174694816"),
            ("Patreon 채널", "Lumpinou Official Patreon", "https://www.patreon.com/lumpinou")
        ],
        "free_version": "2.986",
        "free_links": [
            ("Patreon (무료 공개)", "[Mod] Relationship & Pregnancy Overhaul, ALL-FILES-IN-ONE-CLICK | Lumpinou", "https://www.patreon.com/lumpinou/posts/mod-relationship-75983577"),
            ("Patreon 채널", "Lumpinou Official Patreon", "https://www.patreon.com/lumpinou")
        ],
    },
    {
        "keywords": ["lumpinou_toolbox.ts4script", "lumpinou_toolbox", "lumpinous_toolbox", "lumpinou's toolbox"],
        "name": "Lumpinou's Toolbox",
        "creator": "Lumpinou",
        "mod_title": "Lumpinou's Toolbox (Script Library)",
        "version": "6",
        "links": [
            ("Patreon (공식)", "[Mod] Lumpinou's Toolbox - Script Library-Mod - Sims 4", "https://www.patreon.com/lumpinou/posts/mod-lumpinous-4-86658397")
        ]
    },
    {
        "keywords": ["lumpinou_contextualsocialinteractions.package", "contextualsocialinteractions", "contextual_social_interactions", "contextual social interactions", "lumpinou_contextualsocialinteractions"],
        "name": "Lumpinou_ContextualSocialInteractions",
        "creator": "Lumpinou",
        "mod_title": "Contextual Social Interactions",
        "version": "2026.02.05",
        "links": [
            ("Patreon (공식)", "[Mod] Contextual Social Interactions - Sims 4", "https://www.patreon.com/lumpinou/posts/mod-contextual-4-40485793")
        ]
    },
    {
        "keywords": ["talentsweaknesses_core_(required).package", "talentsweaknesses", "talents_weaknesses", "talentsandweaknesses", "talents & weaknesses", "talents and weaknesses"],
        "name": "Lumpinou Talents & Weaknesses",
        "creator": "Lumpinou",
        "mod_title": "Talents & Weaknesses",
        "version": "2026.04.03",
        "links": [
            ("Patreon (공식)", "[Mod] Talents & Weaknesses | Lumpinou", "https://www.patreon.com/lumpinou/posts/mod-talents-51561971")
        ]
    },
    {
        "keywords": [
            "lumpinou_firstimpressions_withtimedecay_3days_(required).package",
            "lumpinou_firstimpressions_notimedecay_(required).package",
            "lumpinou_firstimpressions_notimedecay_(donotdelete).package",
            "lumpinou_firstimpressions",
            "firstimpressions",
            "first_impressions",
            "first impressions",
        ],
        "name": "First Impressions",
        "creator": "Lumpinou",
        "mod_title": "First Impressions",
        "version": "1",
        "requires_option_modal": True,
        "option_modal_prompt": "First Impressions 본체 버전(택1)과 함께 설치할 세부 옵션 파일을 선택해 주세요.",
        "option_presets": [
            {
                "file_name": "Lumpinou_FirstImpressions_WithTimeDecay_3days.zip",
                "label": "WithTimeDecay (3일 경과 시 첫인상 소멸 · 기본)",
                "match_tokens": ["withtimedecay"],
            },
            {
                "file_name": "Lumpinou_FirstImpressions_NoTimeDecay.zip",
                "label": "NoTimeDecay (시간 경과 소멸 없음 · 새 감정 발생 시만 변경)",
                "match_tokens": ["notimedecay"],
            },
        ],
        "optional_addons": [
            {
                "file_name": "Lumpinou_FirstImpressions_Optional_IntroTypeMatters.package",
                "label": "IntroTypeMatters (첫인사 유형이 첫인상에 영향 · 선택)",
            },
            {
                "file_name": "Lumpinou_FirstImpressions_Optional_PostConversationMoodlets.package",
                "label": "PostConversationMoodlets (대화 후 첫인상 무드렛 부여 · 선택)",
            },
        ],
        "links": [
            ("Patreon (공식)", "[Mod] First Impressions | Lumpinou", "https://www.patreon.com/lumpinou/posts/mod-first-sims-4-44832679")
        ]
    },
    {
        "keywords": ["lumpinou_moodpackmod", "moodpackmod", "mood pack mod"],
        "name": "Lumpinou_MoodPackMod",
        "creator": "Lumpinou",
        "mod_title": "Mood Pack Mod",
        "version": "1.677",
        "links": [
            ("Patreon (공식)", "[Mod] Lumpinou's Mood Pack Mod | Lumpinou", "https://www.patreon.com/lumpinou/posts/mod-lumpinous-43759541"),
            ("CurseForge", "Mood Pack : New Moods for your Sims - The Sims 4 Mods", "https://www.curseforge.com/sims4/mods/mood-pack")
        ]
    },
    {
        "keywords": [
            "lumpinou_roadtoromance_bg_(nolovestruckep)",
            "lumpinou_roadtoromance_bg",
            "roadtoromance_bg",
            "nolovestruckep",
        ],
        "name": "Lumpinou_RoadToRomance_BG_(NoLovestruckEp)",
        "creator": "Lumpinou",
        "mod_title": "Road To Romance (BG / No Lovestruck EP)",
        "version": "2025.02.02",
        "links": [
            ("Patreon (공식)", "[Mod] Road to Romance - Lovestruck Edition - OR - BG Ver | Lumpinou", "https://www.patreon.com/lumpinou/posts/mod-road-to-or-4-39785932")
        ]
    },
    {
        "keywords": [
            "lumpinou_roadtoromance_lovestruckep",
            "lumpinou_roadtoromance",
            "roadtoromance",
            "road to romance",
        ],
        "name": "Lumpinou_RoadToRomance",
        "creator": "Lumpinou",
        "mod_title": "Road To Romance",
        "version": "2025.02.02",
        "links": [
            ("Patreon (공식)", "[Mod] Road to Romance - Lovestruck Edition - OR - BG Ver | Lumpinou", "https://www.patreon.com/lumpinou/posts/mod-road-to-or-4-39785932")
        ]
    },
    {
        "keywords": [
            "lumpinou_lawanddisorder.ts4script",
            "lumpinou_lawanddisorder.package",
            "lumpinou_lawanddisorder",
            "lawanddisorder",
            "law_and_disorder",
            "law and disorder",
            "law & disorder",
        ],
        "name": "Law and Disorder",
        "creator": "Lumpinou",
        "mod_title": "Law and Disorder",
        "version": "2025.11.03",
        "links": [
            ("Patreon (공식)", "[Mod] Law & Disorder - Maxis-Match Crime & Justice System | Lumpinou", "https://www.patreon.com/lumpinou/posts/mod-law-disorder-140597715")
        ]
    },
    {
        "keywords": ["restrictedromance_bypolarbearsims", "restrictedromance"],
        "name": "RestrictedRomance By Polarbearsims",
        "creator": "Polarbearsims",
        "mod_title": "RestrictedRomance By Polarbearsims",
        "version": "2022.08.09",
        "links": [
            ("ModTheSims", "Have Some Personality Please! | Polarbearsims", "https://modthesims.info/d/594573/have-some-personality-please.html")
        ]
    },
    {
        "keywords": ["sims_learninfo_bypolarbearsims", "sims_learninfo"],
        "name": "Sims LearnInfo By Polarbearsims",
        "creator": "Polarbearsims",
        "mod_title": "Sims LearnInfo By Polarbearsims",
        "version": "2025.05.24",
        "links": [
            ("ModTheSims", "Have Some Personality Please! | Polarbearsims", "https://modthesims.info/d/594573/have-some-personality-please.html")
        ]
    },
    {
        "keywords": [
            "personalityplease!_catsdogs_bypolarbearsims",
            "personalityplease_catsdogs_bypolarbearsims",
            "personality_please_catsdogs",
            "personalityplease!_catsdogs",
            "personalityplease_catsdogs",
        ],
        "name": "PersonalityPlease!_CatsDogs_ByPolarbearsims",
        "creator": "Polarbearsims",
        "mod_title": "Personality Please! - Cats & Dogs By Polarbearsims",
        "version": "2025.05.26",
        "links": [
            ("ModTheSims", "Have Some Personality Please! | Polarbearsims", "https://modthesims.info/d/594573/have-some-personality-please.html")
        ]
    },
    {
        "keywords": [
            "personality_please!_toddlers_by_polarbearsims",
            "personality_please_toddlers_by_polarbearsims",
            "personalityplease_toddlers",
            "personality_please!_toddlers",
            "personality_please_toddlers",
        ],
        "name": "Personality_Please!_Toddlers_By_Polarbearsims",
        "creator": "Polarbearsims",
        "mod_title": "Personality Please! - Toddlers By Polarbearsims",
        "version": "2025.05.24",
        "links": [
            ("ModTheSims", "Have Some Personality Please! | Polarbearsims", "https://modthesims.info/d/594573/have-some-personality-please.html")
        ]
    },
    {
        "keywords": [
            "personality_please_woohoo-tryforbabyrestricted_bypolarbearsims",
            "woohoo-tryforbabyrestricted",
            "tryforbabyrestricted",
            "woohoo_tryforbabyrestricted",
        ],
        "name": "Personality_Please_Woohoo-TryForBabyRestricted_ByPolarbearsims",
        "creator": "Polarbearsims",
        "mod_title": "Personality Please! - Woohoo & Try For Baby Restricted By Polarbearsims",
        "version": "2023.10.26",
        "links": [
            ("ModTheSims", "Have Some Personality Please! | Polarbearsims", "https://modthesims.info/d/594573/have-some-personality-please.html")
        ]
    },
    {
        "keywords": [
            "personalityplease_meaninteractions_bypolarbearsims",
            "personality_please_meaninteractions",
            "personalityplease_meaninteractions",
            "meaninteractions_bypolarbearsims",
        ],
        "name": "PersonalityPlease_MeanInteractions_ByPolarbearsims",
        "creator": "Polarbearsims",
        "mod_title": "Personality Please! - Mean Interactions By Polarbearsims",
        "version": "2025.05.24",
        "links": [
            ("ModTheSims", "Have Some Personality Please! | Polarbearsims", "https://modthesims.info/d/594573/have-some-personality-please.html")
        ]
    },
    {
        "keywords": ["personality_please", "personalityplease"],
        "name": "Personality Please! By Polarbearsims",
        "creator": "Polarbearsims",
        "mod_title": "Personality Please! By Polarbearsims",
        "version": "2025.05.24",
        "links": [
            ("ModTheSims", "Have Some Personality Please! | Polarbearsims", "https://modthesims.info/d/594573/have-some-personality-please.html")
        ]
    },
    {
        "keywords": [
            "disl_to_nooutfitchangepromoted.package",
            "disl_to_nooutfitchangepromoted.ts4script",
            "disl_to_nooutfitchangepromoted",
            "nooutfitchangepromoted",
            "no outfit change when promoted",
        ],
        "name": "Townies & Outfits - No Outfit Change When Promoted",
        "creator": "Down-In-Simsland",
        "mod_title": "Townies & Outfits - No Outfit Change When Promoted",
        "version": "2025.09.27",
        "links": [
            ("SimFileShare", "DISL_TO_NoOutfitChangePromoted | Down-In-Simsland", "https://www.simfileshare.net/download/5174540/")
        ]
    },
    {
        "keywords": [
            "disl_c_fireandwood.package",
            "disl_c_fireandwood",
            "fireandwood",
            "fire and wood",
            "castaway life - fire and wood",
        ],
        "name": "Castaway Life - Fire and Wood",
        "creator": "Down-In-Simsland",
        "mod_title": "Castaway Life - Fire and Wood",
        "override_mod_title": True,
        "version": "2025.09.27",
        "links": [
            ("SimFileShare", "DISL_C_FireAndWood | Down-In-Simsland", "https://www.simfileshare.net/download/5194316/"),
            ("Tumblr (공식)", "Castaway Life | Down-In-Simsland", "https://down-in-simsland.tumblr.com/post/769961699450175488/castaway-life"),
        ]
    },
    {
        "keywords": [
            "disl_c_beachtreasures.package",
            "disl_c_beachtreasures",
            "beachtreasures",
            "beach treasures",
            "castaway life - beach treasures",
        ],
        "name": "Castaway Life - Beach Treasures",
        "creator": "Down-In-Simsland",
        "mod_title": "Castaway Life - Beach Treasures",
        "override_mod_title": True,
        "version": "2025.07.19",
        "links": [
            ("SimFileShare", "DISL_C_BeachTreasures | Down-In-Simsland", "https://www.simfileshare.net/download/5194317/"),
            ("Tumblr (공식)", "Castaway Life | Down-In-Simsland", "https://down-in-simsland.tumblr.com/post/769961699450175488/castaway-life"),
        ]
    },
    {
        "keywords": [
            "disl_c_phonebattery.package",
            "disl_c_phonebattery.ts4script",
            "disl_c_phonebattery.zip",
            "disl_c_phonebattery",
            "phonebattery",
            "phone battery",
            "castaway life - phone battery",
        ],
        "name": "Castaway Life - Phone Battery",
        "creator": "Down-In-Simsland",
        "mod_title": "Castaway Life - Phone Battery",
        "override_mod_title": True,
        "version": "2025.02.27",
        "links": [
            ("SimFileShare", "DISL_C_PhoneBattery | Down-In-Simsland", "https://www.simfileshare.net/download/5194320/"),
            ("Tumblr (공식)", "Castaway Life | Down-In-Simsland", "https://down-in-simsland.tumblr.com/post/769961699450175488/castaway-life"),
        ]
    },
    {
        "keywords": [
            "disl_c_dyecreationwooldyeing.package",
            "disl_c_dyecreationwooldyeing",
            "dyecreationwooldyeing",
            "dye creation and wool dyeing",
            "castaway life - dye creation and wool dyeing",
        ],
        "name": "Castaway Life - Dye Creation and Wool Dyeing",
        "creator": "Down-In-Simsland",
        "mod_title": "Castaway Life - Dye Creation and Wool Dyeing",
        "override_mod_title": True,
        "version": "2025.03.08",
        "links": [
            ("SimFileShare", "DISL_C_DyeCreationWoolDyeing | Down-In-Simsland", "https://www.simfileshare.net/download/5194319/"),
            ("Tumblr (공식)", "Castaway Life | Down-In-Simsland", "https://down-in-simsland.tumblr.com/post/769961699450175488/castaway-life"),
        ]
    },
    {
        "keywords": [
            "disl_c_campfirefood.package",
            "disl_c_campfirefood",
            "campfirefood",
            "campfire food replacement",
            "castaway life - campfire food replacement",
        ],
        "name": "Castaway Life - Campfire Food Replacement",
        "creator": "Down-In-Simsland",
        "mod_title": "Castaway Life - Campfire Food Replacement",
        "override_mod_title": True,
        "version": "2025.09.27",
        "links": [
            ("SimFileShare", "DISL_C_CampfireFood | Down-In-Simsland", "https://www.simfileshare.net/download/5194318/"),
            ("Tumblr (공식)", "Castaway Life | Down-In-Simsland", "https://down-in-simsland.tumblr.com/post/769961699450175488/castaway-life"),
        ]
    },
    {
        "keywords": [
            "disl_c_showersink.package",
            "disl_c_showersink",
            "showersink",
            "shower at sink",
            "castaway life - shower at sink",
        ],
        "name": "Castaway Life - Shower at Sink",
        "creator": "Down-In-Simsland",
        "mod_title": "Castaway Life - Shower at Sink",
        "override_mod_title": True,
        "version": "2025.03.08",
        "links": [
            ("SimFileShare", "DISL_C_ShowerSink | Down-In-Simsland", "https://www.simfileshare.net/download/5186477/"),
            ("Tumblr (공식)", "Castaway Life | Down-In-Simsland", "https://down-in-simsland.tumblr.com/post/769961699450175488/castaway-life"),
        ]
    },
    {
        "keywords": [
            "disl_diy_core.package",
            "disl_diy_core.ts4script",
            "disl_diy_core.zip",
            "disl_diy_core",
            "do it yourself - core mod",
            "do it yourself core mod",
        ],
        "name": "Do it Yourself - Core Mod",
        "creator": "Down-In-Simsland",
        "mod_title": "Do it Yourself - Core Mod",
        "override_mod_title": True,
        "version": "2025.02.27",
        "links": [
            ("SimFileShare", "DISL_DIY_Core | Down-In-Simsland", "https://www.simfileshare.net/download/5194803/"),
            ("Tumblr (공식)", "Do it Yourself | Down-In-Simsland", "https://down-in-simsland.tumblr.com/post/769961661885038592/do-it-yourself"),
        ]
    },
    {
        "keywords": [
            "disl_diy_fabricationwoodworkingtable.package",
            "disl_diy_fabricationwoodworkingtable",
            "fabricationwoodworkingtable",
            "fabrication at the woodworking table",
            "do it yourself - fabrication at the woodworking table",
        ],
        "name": "Do it Yourself - Fabrication at the Woodworking Table",
        "creator": "Down-In-Simsland",
        "mod_title": "Do it Yourself - Fabrication at the Woodworking Table",
        "override_mod_title": True,
        "version": "2026.02.14",
        "links": [
            ("SimFileShare", "DISL_DIY_FabricationWoodworkingTable | Down-In-Simsland", "https://www.simfileshare.net/download/5194806/"),
            ("Tumblr (공식)", "Do it Yourself | Down-In-Simsland", "https://down-in-simsland.tumblr.com/post/769961661885038592/do-it-yourself"),
        ]
    },
    {
        "keywords": [
            "disl_diy_morewoodworks.package",
            "disl_diy_morewoodworks",
            "morewoodworks",
            "more woodworks",
            "do it yourself - more woodworks",
        ],
        "name": "Do it Yourself - More Woodworks",
        "creator": "Down-In-Simsland",
        "mod_title": "Do it Yourself - More Woodworks",
        "override_mod_title": True,
        "version": "2026.02.14",
        "links": [
            ("SimFileShare", "DISL_DIY_MoreWoodworks | Down-In-Simsland", "https://www.simfileshare.net/download/5194804/"),
            ("Tumblr (공식)", "Do it Yourself | Down-In-Simsland", "https://down-in-simsland.tumblr.com/post/769961661885038592/do-it-yourself"),
        ]
    },
    {
        "keywords": [
            "disl_diy_morefabrication.package",
            "disl_diy_morefabrication",
            "morefabrication",
            "more fabrication",
            "do it yourself - more fabrication",
        ],
        "name": "Do it Yourself - More Fabrication",
        "creator": "Down-In-Simsland",
        "mod_title": "Do it Yourself - More Fabrication",
        "override_mod_title": True,
        "version": "2026.02.18",
        "links": [
            ("SimFileShare", "DISL_DIY_MoreFabrication | Down-In-Simsland", "https://www.simfileshare.net/download/5194805/"),
            ("Tumblr (공식)", "Do it Yourself | Down-In-Simsland", "https://down-in-simsland.tumblr.com/post/769961661885038592/do-it-yourself"),
        ]
    },
    {
        "keywords": [
            "disl_diy_moreknits.package",
            "disl_diy_moreknits",
            "moreknits",
            "more knits",
            "do it yourself - more knits",
        ],
        "name": "Do it Yourself - More Knits",
        "creator": "Down-In-Simsland",
        "mod_title": "Do it Yourself - More Knits",
        "override_mod_title": True,
        "version": "2026.02.14",
        "links": [
            ("SimFileShare", "DISL_DIY_MoreKnits | Down-In-Simsland", "https://www.simfileshare.net/download/5194807/"),
            ("Tumblr (공식)", "Do it Yourself | Down-In-Simsland", "https://down-in-simsland.tumblr.com/post/769961661885038592/do-it-yourself"),
        ]
    },
    {
        "keywords": [
            "[kuttoe] homeregions.zip",
            "[kuttoe] homeregions.package",
            "[kuttoe] homeregions.ts4script",
            "[kuttoe] homeregions",
            "kuttoe_homeregions",
            "homeregions",
            "home regions",
            "keep sims in home region",
            "keep-sims-in-home-region",
        ],
        "name": "Home Regions",
        "creator": "Kuttoe",
        "mod_title": "Home Regions",
        "override_mod_title": True,
        "version": "2026.11.21",
        "links": [
            ("Itch.io (공식)", "Home Regions | Kuttoe", "https://kuttoe.itch.io/keep-sims-in-home-region"),
            ("Itch.io 채널", "Kuttoe Official Itch.io", "https://kuttoe.itch.io/"),
        ]
    },
    {
        "keywords": [
            "[kuttoe] newcivicpolicies.zip",
            "[kuttoe] newcivicpolicies.package",
            "[kuttoe] newcivicpolicies.ts4script",
            "[kuttoe] newcivicpolicies",
            "kuttoe_newcivicpolicies",
            "newcivicpolicies",
            "new civic policies",
            "new-civic-policies",
        ],
        "name": "New Civic Policies",
        "creator": "Kuttoe",
        "mod_title": "New Civic Policies",
        "override_mod_title": True,
        "version": "2026.07.02",
        "links": [
            ("Itch.io (공식)", "New Civic Policies | Kuttoe", "https://kuttoe.itch.io/new-civic-policies"),
            ("Itch.io 채널", "Kuttoe Official Itch.io", "https://kuttoe.itch.io/"),
        ]
    },
    {
        "keywords": ["kallixer_removesimsfromconversation", "removesimsfromconversation"],
        "name": "Remove Sims From Conversation",
        "creator": "Kallixer",
        "mod_title": "Remove Sims From Conversation",
        "version": "2a",
        "links": [
            ("CurseForge (공식)", "Remove Sims from Conversation | Kallixer", "https://www.curseforge.com/sims4/mods/remove-sims-from-conversation")
        ]
    },
    {
        "keywords": [
            "natethel0ser_chatpackv2_lifestages.package",
            "natethel0ser_chatpackv2_babiesfamily.package",
            "natethel0ser_chatpackv2_lifestages",
            "natethel0ser_chatpackv2_babiesfamily",
            "natethel0ser_chatpackv2",
            "natethel0ser_chatpack",
            "chatpackv2_lifestages",
            "chatpackv2_babiesfamily",
            "chatpackv2",
            "chat pack v2",
            "chat pack.zip",
            "chat pack - more social interactions",
            "chat pack",
        ],
        "name": "Chat Pack",
        "creator": "NateTheL0ser",
        "mod_title": "Chat Pack - More Social Interactions for Your Sims",
        "version": "2",
        "links": [
            ("ModTheSims (공식)", "Chat Pack - More Social Interactions for Your Sims V2.0 | NateTheL0ser", "https://modthesims.info/d/627991/chat-pack-more-social-interactions-for-your-sims-v2-0-now-requires-xmlinjector.html")
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
        "mod_title": "Controlled Position Mod (CAS Tuning)",
        "override_mod_title": True,
        "version": "2.3",
        "links": [
            ("Patreon (공식)", "CONTROLLED POSITION MOD | NORTHERN SIBERIA WINDS", "https://www.patreon.com/northernsiberiawinds/posts/controlled-mod-103628223")
        ]
    },
    {
        "keywords": [
            "!!!!![northern siberia winds] even better in-game lighting mod v1.1 average.package",
            "!!!!![northern siberia winds] even better in-game lighting mod v1.1 bright.package",
            "!!!!![northern siberia winds] even better in-game lighting mod v1.1 dark.package",
            "[northern siberia winds] even better in-game lighting mod v1.1 average",
            "[northern siberia winds] even better in-game lighting mod v1.1 bright",
            "[northern siberia winds] even better in-game lighting mod v1.1 dark",
            "[northern siberia winds] even better in-game lighting mod",
            "even better in-game lighting mod",
            "even_better_in-game_lighting_mod",
            "even better in game lighting mod",
        ],
        "name": "Even Better In-Game Lighting Mod",
        "creator": "NORTHERN SIBERIA WINDS",
        "mod_title": "Even Better In-Game Lighting Mod",
        "override_mod_title": True,
        "version": "1.1",
        "links": [
            ("Patreon (공식)", "EVEN BETTER IN-GAME LIGHTING MOD | NORTHERN SIBERIA WINDS", "https://www.patreon.com/northernsiberiawinds/posts/even-better-in-107494052")
        ]
    },
    {
        "keywords": [
            "!!![northern siberia winds] better in-game lighting mod v1.1 average base light rooms.package",
            "!!![northern siberia winds] better in-game lighting mod v1.1 average pale light rooms.package",
            "!!![northern siberia winds] better in-game lighting mod v1.1 average saturated light rooms.package",
            "!!![northern siberia winds] better in-game lighting mod v1.1 bright base light rooms.package",
            "!!![northern siberia winds] better in-game lighting mod v1.1 bright pale light rooms.package",
            "!!![northern siberia winds] better in-game lighting mod v1.1 bright saturated light rooms.package",
            "!!![northern siberia winds] better in-game lighting mod v1.1 dark base light rooms.package",
            "!!![northern siberia winds] better in-game lighting mod v1.1 dark pale light rooms.package",
            "!!![northern siberia winds] better in-game lighting mod v1.1 dark saturated light rooms.package",
            "!!![northern siberia winds] better in-game lighting mod v1.1 extra dark saturated light rooms.package",
            "!!![northern siberia winds] better in-game lighting mod v1.1 average base dark rooms.package",
            "!!![northern siberia winds] better in-game lighting mod v1.1 average pale dark rooms.package",
            "!!![northern siberia winds] better in-game lighting mod v1.1 average saturated dark rooms.package",
            "!!![northern siberia winds] better in-game lighting mod v1.1 bright base dark rooms.package",
            "!!![northern siberia winds] better in-game lighting mod v1.1 bright pale dark rooms.package",
            "!!![northern siberia winds] better in-game lighting mod v1.1 bright saturated dark rooms.package",
            "!!![northern siberia winds] better in-game lighting mod v1.1 dark base dark rooms.package",
            "!!![northern siberia winds] better in-game lighting mod v1.1 dark pale dark rooms.package",
            "!!![northern siberia winds] better in-game lighting mod v1.1 dark saturated dark rooms.package",
            "!!![northern siberia winds] better in-game lighting mod v1.1 extra dark saturated dark rooms.package",
            "[northern siberia winds] better in-game lighting mod v1.1 average base light rooms",
            "[northern siberia winds] better in-game lighting mod v1.1 average pale light rooms",
            "[northern siberia winds] better in-game lighting mod v1.1 average saturated light rooms",
            "[northern siberia winds] better in-game lighting mod v1.1 bright base light rooms",
            "[northern siberia winds] better in-game lighting mod v1.1 bright pale light rooms",
            "[northern siberia winds] better in-game lighting mod v1.1 bright saturated light rooms",
            "[northern siberia winds] better in-game lighting mod v1.1 dark base light rooms",
            "[northern siberia winds] better in-game lighting mod v1.1 dark pale light rooms",
            "[northern siberia winds] better in-game lighting mod v1.1 dark saturated light rooms",
            "[northern siberia winds] better in-game lighting mod v1.1 extra dark saturated light rooms",
            "[northern siberia winds] better in-game lighting mod v1.1 average base dark rooms",
            "[northern siberia winds] better in-game lighting mod v1.1 average pale dark rooms",
            "[northern siberia winds] better in-game lighting mod v1.1 average saturated dark rooms",
            "[northern siberia winds] better in-game lighting mod v1.1 bright base dark rooms",
            "[northern siberia winds] better in-game lighting mod v1.1 bright pale dark rooms",
            "[northern siberia winds] better in-game lighting mod v1.1 bright saturated dark rooms",
            "[northern siberia winds] better in-game lighting mod v1.1 dark base dark rooms",
            "[northern siberia winds] better in-game lighting mod v1.1 dark pale dark rooms",
            "[northern siberia winds] better in-game lighting mod v1.1 dark saturated dark rooms",
            "[northern siberia winds] better in-game lighting mod v1.1 extra dark saturated dark rooms",
            "[northern siberia winds] better in-game lighting mod",
            "better in-game lighting mod",
            "better_in-game_lighting_mod",
            "better in game lighting mod",
        ],
        "name": "Better In-Game Lighting Mod",
        "creator": "NORTHERN SIBERIA WINDS",
        "mod_title": "Better In-Game Lighting Mod",
        "override_mod_title": True,
        "version": "1.1",
        "links": [
            ("Patreon (공식)", "BETTER IN-GAME LIGHTING MOD v1.1 | NORTHERN SIBERIA WINDS", "https://www.patreon.com/northernsiberiawinds/posts/better-in-game-1-79174144")
        ]
    },
    {
        "keywords": [
            "[northern siberia winds] gentle cas lighting.package",
            "[northern siberia winds] gentle cas lighting",
            "northern_siberia_winds_gentle_cas_lighting",
            "gentle cas lighting mod",
            "gentle cas lighting",
            "gentle_cas_lighting",
        ],
        "name": "Gentle CAS Lighting",
        "creator": "NORTHERN SIBERIA WINDS",
        "mod_title": "Gentle CAS Lighting",
        "override_mod_title": True,
        "version": "2023.07.25",
        "links": [
            ("Patreon (공식)", "GENTLE CAS LIGHTING MOD | NORTHERN SIBERIA WINDS", "https://www.patreon.com/northernsiberiawinds/posts/gentle-cas-mod-61063863"),
            ("CurseForge (공식)", "Gentle CAS Lighting | NORTHERN SIBERIA WINDS", "https://www.curseforge.com/sims4/mods/gentle-cas-lighting")
        ]
    },
    {
        "keywords": ["simmattically_family_loadingscreen", "family_loadingscreen"],
        "name": "Family Loading Screen",
        "creator": "SimMattically",
        "mod_title": "Family Loading Screen",
        "version": "2026.02.16",
        "links": [
            ("Patreon (공식)", "Family Loading Screen | The Sims 4 | SimMattically", "https://www.patreon.com/SimMattically/posts/family-loading-4-150916961")
        ]
    },
    {
        "keywords": [
            "simmattically_refreshedmainmenu_optional_alternativelogo",
            "refreshedmainmenu_optional_alternativelogo",
            "optional_alternativelogo",
        ],
        "name": "SimMattically_RefreshedMainMenu_Optional_AlternativeLogo",
        "creator": "SimMattically",
        "mod_title": "Refreshed Main Menu: Optional Alternative Logo",
        "version": "2025.05.06",
        "links": [
            ("Patreon (공식)", "Refreshed Main Menu: Homeview | SimMattically", "https://www.patreon.com/SimMattically/posts/refreshed-main-126640866")
        ]
    },
    {
        "keywords": [
            "simmattically_refreshedmainmenu_standalone_homeview.package",
            "simmattically_refreshedmainmenu_standalone_homeview",
            "refreshedmainmenu_standalone_homeview",
            "refreshed main menu: homeview",
            "refreshed main menu homeview",
        ],
        "name": "Refreshed Main Menu: Homeview",
        "creator": "SimMattically",
        "mod_title": "Refreshed Main Menu: Homeview",
        "version": "2025.05.06",
        "links": [
            ("Patreon (공식)", "Refreshed Main Menu: Homeview | SimMattically", "https://www.patreon.com/SimMattically/posts/refreshed-main-126640866")
        ]
    },
    {
        "keywords": [
            "nv_sm_motive_fail_energy_animation_replacement.package",
            "nv_sm_motive_fail_energy_animation_replacement",
            "motive_fail_energy_animation_replacement",
        ],
        "name": "NV_SM_Motive_Fail_Energy_Animation_Replacement",
        "creator": "NV Games",
        "mod_title": "Motive Fail Energy Animation Replacement",
        "version": "2025.03.14",
        "links": [
            ("Patreon (공식)", "SMALL MODS | NV . Games", "https://www.patreon.com/nv_games/posts/small-mods-69121597")
        ]
    },
    {
        "keywords": [
            "nv_sm_asymcelebsocial_fan_faint_animation_replacement.package",
            "nv_sm_asymcelebsocial_fan_faint_animation_replacement",
            "asymcelebsocial_fan_faint_animation_replacement",
        ],
        "name": "NV_SM_AsymCelebSocial_Fan_Faint_Animation_Replacement",
        "creator": "NV Games",
        "mod_title": "AsymCelebSocial Fan Faint Animation Replacement",
        "version": "2025.03.14",
        "links": [
            ("Patreon (공식)", "SMALL MODS | NV . Games", "https://www.patreon.com/nv_games/posts/small-mods-69121597")
        ]
    },
    {
        "keywords": [
            "nv_sm_werewolf_howling_animation_replacement.package",
            "nv_sm_werewolf_howling_animation_replacement",
            "werewolf_howling_animation_replacement",
        ],
        "name": "NV_SM_Werewolf_Howling_Animation_Replacement",
        "creator": "NV Games",
        "mod_title": "Werewolf Howling Animation Replacement",
        "version": "2025.03.14",
        "links": [
            ("Patreon (공식)", "SMALL MODS | NV . Games", "https://www.patreon.com/nv_games/posts/small-mods-69121597")
        ]
    },
    {
        "keywords": [
            "nv_sm_no_overhead_effects.package",
            "nv_sm_no_overhead_effects",
            "no_overhead_effects",
        ],
        "name": "NV_SM_No_Overhead_Effects",
        "creator": "NV Games",
        "mod_title": "No Overhead Effects",
        "version": "2022.09.16",
        "links": [
            ("Patreon (공식)", "SMALL MODS | NV . Games", "https://www.patreon.com/nv_games/posts/small-mods-69121597")
        ]
    },
    {
        "keywords": [
            "nv_sm_no_effects.package",
            "nv_sm_no_effects",
        ],
        "name": "NV_SM_No_Effects",
        "creator": "NV Games",
        "mod_title": "No Effects",
        "version": "2025.03.14",
        "links": [
            ("Patreon (공식)", "SMALL MODS | NV . Games", "https://www.patreon.com/nv_games/posts/small-mods-69121597")
        ]
    },
    {
        "keywords": [
            "nv_sm_standing_idle_neutral.package",
            "nv_sm_standing_idle_neutral",
            "nv_sm_standing_idle.package",
            "nv_sm_standing_idle",
            "nv.sm standing idle",
            "nv. sm standing idle",
        ],
        "name": "NV_SM_Standing_Idle",
        "creator": "NV Games",
        "mod_title": "Standing Idle",
        "version": "2023.03.21",
        "links": [
            ("Patreon (공식)", "SMALL MODS | NV . Games", "https://www.patreon.com/nv_games/posts/small-mods-69121597")
        ]
    },
    {
        "keywords": [
            "nv_sm_facialoverlay_animation_replacement_adult_all.package",
            "nv_sm_facialoverlay_animation_replacement_adult_angry.package",
            "nv_sm_facialoverlay_animation_replacement_adult_bored.package",
            "nv_sm_facialoverlay_animation_replacement_adult_confident.package",
            "nv_sm_facialoverlay_animation_replacement_adult_happy.package",
            "nv_sm_facialoverlay_animation_replacement_adult_sad.package",
            "nv_sm_facialoverlay_animation_replacement_children_all.package",
            "nv_sm_facialoverlay_animation_replacement_children_angry.package",
            "nv_sm_facialoverlay_animation_replacement_children_bored.package",
            "nv_sm_facialoverlay_animation_replacement_children_happy.package",
            "nv_sm_facialoverlay_animation_replacement_children_sad.package",
            "nv_sm_facialoverlay_animation_replacement",
            "facialoverlay_animation_replacement",
            "nv.sm facial overlay animation replacement",
            "nv. sm facial overlay animation replacement",
        ],
        "name": "NV_SM_FacialOverlay_Animation_Replacement",
        "creator": "NV Games",
        "mod_title": "Facial Overlay Animation Replacement",
        "version": "2025.03.15",
        "links": [
            ("Patreon (공식)", "SMALL MODS | NV . Games", "https://www.patreon.com/nv_games/posts/small-mods-69121597")
        ]
    },
    {
        "keywords": ["nv_sm_ui_mood", "nv_sm_ui_mood_01_adult_all", "nv_sm_ui_mood_01_children_all"],
        "name": "NV_SM_UI_Mood",
        "creator": "NV Games",
        "mod_title": "",
        "version": "2025.03.15",
        "links": [
            ("Patreon (공식)", "SMALL MODS | NV . Games", "https://www.patreon.com/nv_games/posts/small-mods-69121597")
        ]
    },
    {
        "keywords": ["sims4me_lessfacialoveraction", "lessfacialoveraction", "less facial overaction"],
        "name": "Less Facial Overaction",
        "creator": "Bienchen (sims4me)",
        "mod_title": "Less Facial Overaction",
        "version": "2026.09.06",
        "links": [
            ("CurseForge (공식)", "Less Facial Overaction | Bienchen (sims4me)", "https://www.curseforge.com/sims4/mods/less-facial-overaction")
        ]
    },
    {
        "keywords": ["friedgil_random_name_korean_translation_compilation"],
        "name": "FriedGil_Random_Name_Korean_Translation_Compilation",
        "creator": "FriedGil",
        "mod_title": "Random Name Korean Translation Compilation",
        "version": "2026.02.05",
        "release_notes": "네이버 블로그 참고 (무료)",
        "links": [
            ("네이버 블로그 참고 (무료)", "FriedGil 랜덤 이름 한글화 배포 포스트", "https://blog.naver.com/friedg/221810746795")
        ]
    },
    {
        "keywords": ["friedgil_random_name_korean_translation_no_korean"],
        "name": "FriedGil_Random_Name_Korean_Translation_NO_Korean",
        "creator": "FriedGil",
        "mod_title": "Random Name Korean Translation (NO Korean)",
        "version": "2026.02.05",
        "release_notes": "네이버 블로그 참고 (무료)",
        "links": [
            ("네이버 블로그 참고 (무료)", "FriedGil 랜덤 이름 한글화 배포 포스트", "https://blog.naver.com/friedg/221810746795")
        ]
    },
    {
        "keywords": ["friedgil_random_name_korean_translation_no_cl&il", "friedgil_random_name_korean_translation_no_cl_il"],
        "name": "FriedGil_Random_Name_Korean_Translation_NO_CL&IL",
        "creator": "FriedGil",
        "mod_title": "Random Name Korean Translation (NO CL&IL)",
        "version": "2026.02.05",
        "release_notes": "네이버 블로그 참고 (무료)",
        "links": [
            ("네이버 블로그 참고 (무료)", "FriedGil 랜덤 이름 한글화 배포 포스트", "https://blog.naver.com/friedg/221810746795")
        ]
    },
    {
        "keywords": ["friedgil_random_name_korean_translation", "friedgil", "friedgil_random_name", "random_name_korean_translation"],
        "name": "FriedGil_Random_Name_Korean_Translation",
        "creator": "FriedGil",
        "mod_title": "Random Name Korean Translation",
        "version": "2026.02.05",
        "release_notes": "네이버 블로그 참고 (무료)",
        "links": [
            ("네이버 블로그 참고 (무료)", "FriedGil 랜덤 이름 한글화 배포 포스트", "https://blog.naver.com/friedg/221810746795")
        ]
    },
    {
        "keywords": ["tmex-betterexceptions", "betterexceptions", "better exceptions"],
        "name": "Better Exceptions",
        "creator": "TwistedMexi",
        "mod_title": "Better Exceptions",
        "version": "3.17",
        "links": [
            ("Patreon (공식)", "Better Exceptions v3.17 | TwistedMexi", "https://www.patreon.com/TwistedMexi/posts/better-v3-17-mod-130049745"),
            ("Patreon 채널", "TwistedMexi Official Patreon", "https://www.patreon.com/TwistedMexi"),
            ("CurseForge (공식)", "Better Exceptions | TwistedMexi", "https://www.curseforge.com/sims4/mods/better-exceptions")
        ]
    },
    {
        "keywords": [
            "tmex-betterbuildbuy.ts4script",
            "tmex-betterbuildbuy.package",
            "tmex-betterbuildbuy",
            "tmex_betterbuildbuy",
            "betterbuildbuy",
            "better_buildbuy",
            "better buildbuy",
            "better build buy",
            "better_build_buy",
        ],
        "name": "Better BuildBuy",
        "creator": "TwistedMexi",
        "mod_title": "Better BuildBuy",
        "version": "4.5",
        "links": [
            ("Patreon (공식)", "Better BuildBuy v4.5 | TwistedMexi", "https://www.patreon.com/TwistedMexi/posts/better-buildbuy-135871452"),
            ("Patreon 채널", "TwistedMexi Official Patreon", "https://www.patreon.com/TwistedMexi")
        ]
    },
    {
        "keywords": ["walkingbounce.package", "walkingbounce", "walking bounce", "walking bounces", "bouncing sims 4"],
        "name": "Walking Bounce",
        "creator": "Bouncing Sims 4",
        "mod_title": "Walking Bounce",
        "override_mod_title": True,
        "version": "2026.11.10",
        "is_paid": True,
        "release_notes": "유료 상품이어서 자동 다운로드가 불가능합니다. (Patreon 공식 링크)",
        "links": [
            ("Patreon (유료 상품)", "Bouncing Sims 4 | WalkingBounce", "https://www.patreon.com/TonicSims/posts/bouncing-sims-4-174891794")
        ]
    },
    {
        "keywords": [
            "sulsul_ai_mod",
            "sulsul ai mod",
            "sulsul_ai",
            "mod sulsul ai",
        ],
        "name": "SulSul AI Mod",
        "creator": "sulsul",
        "mod_title": "SulSul AI Mod",
        "override_mod_title": True,
        "version": "",
        "is_unreleased": True,
        "release_notes": "미출시 상태 모드로 업데이트 대상에서 제외됩니다.",
        "links": [],
    },
    {
        "keywords": [
            "pandasama_dramageneratorscript.ts4script",
            "pandasama_dramageneratorscript",
            "pandasama_dramagenerator_core",
            "pandasama_dramagenerator_abandonedbaby_module",
            "pandasama_dramagenerator_runawaychild_module",
            "pandasama_dramagenerator",
            "drama_generator",
            "dramagenerator",
            "drama generator",
        ],
        "name": "Drama Generator",
        "creator": "Pandasama",
        "mod_title": "Drama Generator",
        "version": "1.23",
        "links": [
            ("Pandasama Official (공식)", "Drama Generator Mod | Pandasama", "https://www.pandasama.com/drama-generator-mod/#downloads")
        ]
    },
    {
        "keywords": [
            "pandasama_childbirth.ts4script",
            "pandasama_childbirth_mod",
            "pandasama_childbirth",
            "childbirth_mod",
            "child_birth_mod",
            "child birth mod",
            "child birth",
            "childbirth",
        ],
        "name": "Child Birth",
        "creator": "Pandasama",
        "mod_title": "Child Birth",
        "version": "1.98",
        "links": [
            ("Pandasama Official (공식)", "Child Birth Mod | Pandasama", "https://www.pandasama.com/child-birth-mod/#downloads")
        ]
    },
    {
        "keywords": [
            "divine ascension trailer - lot&sims.zip",
            "divine ascension trailer - lot&sims",
            "divine_ascension_trailer_lot&sims",
            "divine ascension trailer",
            "lot&sims",
        ],
        "name": "Divine Ascension Trailer - Lot&Sims",
        "creator": "SpinningPlumbobs",
        "mod_title": "Divine Ascension Trailer - Lot&Sims",
        "version": "2026.07.21",
        "links": [
            ("Patreon (공식)", "Divine Ascension Mod (Lot & Sims) | SpinningPlumbobs", "https://www.patreon.com/spinningplumbobs/posts/divine-ascension-152466612")
        ]
    },
    {
        "keywords": [
            "spinningplumbobs_divineascension",
            "spinningplumbobs_divinemod.ts4script",
            "spinningplumbobs_divinemod",
            "spinningplumbobs_divineascension_main.package",
            "spinningplumbobs_divineascension_main",
            "sp_divineascension_stbls.package",
            "sp_divineascension_stbls",
            "sp_da_animations",
            "divine ascension mod",
            "divine_ascension",
            "divineascension",
        ],
        "name": "Divine Ascension Mod",
        "creator": "SpinningPlumbobs",
        "mod_title": "Divine Ascension Mod",
        "version": "2026.07.21",
        "links": [
            ("Patreon (공식)", "Divine Ascension Mod | SpinningPlumbobs", "https://www.patreon.com/spinningplumbobs/posts/divine-ascension-152466612")
        ]
    },
    {
        "keywords": ["_kor_juicetodrink.package", "_kor_juicetodrink", "kor_juicetodrink", "(kor)juicetodrink", "juicetodrink"],
        "name": "_KOR_JuicetoDrink",
        "creator": "바람별",
        "mod_title": "바람별 한글화 모드 애드온 (_KOR_JuicetoDrink)",
        "version": "2024.03.17",
        "release_notes": "바람별 통합한글화모음 애드온 (Postype 무료 공개)",
        "links": [
            ("Postype (무료)", "통합한글화모음 애드온 | 바람별", "https://www.postype.com/@wwwindystar/post/10314790"),
            ("Patreon (무료)", "통합한글화모음 애드온 | 바람별 ZIMS", "https://www.patreon.com/wwindystarZIMS/posts/tonghabhangeulhw-53821570")
        ]
    },
    {
        "keywords": ["_kor_beerbrewing.package", "_kor_beerbrewing", "kor_beerbrewing", "(kor)beerbrewing", "beerbrewing"],
        "name": "_KOR_BeerBrewing",
        "creator": "바람별",
        "mod_title": "바람별 한글화 모드 애드온 (_KOR_BeerBrewing)",
        "version": "2024.03.17",
        "release_notes": "바람별 통합한글화모음 애드온 (Postype 무료 공개)",
        "links": [
            ("Postype (무료)", "통합한글화모음 애드온 | 바람별", "https://www.postype.com/@wwwindystar/post/10314790"),
            ("Patreon (무료)", "통합한글화모음 애드온 | 바람별 ZIMS", "https://www.patreon.com/wwindystarZIMS/posts/tonghabhangeulhw-53821570")
        ]
    },
    {
        "keywords": ["_kor_plasmatoblood.package", "_kor_plasmatoblood", "kor_plasmatoblood", "(kor)plasmatoblood", "plasmatoblood"],
        "name": "_KOR_PlasmaToBlood",
        "creator": "바람별",
        "mod_title": "바람별 한글화 모드 애드온 (_KOR_PlasmaToBlood)",
        "version": "2024.03.17",
        "release_notes": "바람별 통합한글화모음 애드온 (Postype 무료 공개)",
        "links": [
            ("Postype (무료)", "통합한글화모음 애드온 | 바람별", "https://www.postype.com/@wwwindystar/post/10314790"),
            ("Patreon (무료)", "통합한글화모음 애드온 | 바람별 ZIMS", "https://www.patreon.com/wwindystarZIMS/posts/tonghabhangeulhw-53821570")
        ]
    },
    {
        "keywords": ["_kor_bloodbeer.package", "_kor_bloodbeer", "kor_bloodbeer", "(kor)bloodbeer", "bloodbeer"],
        "name": "_KOR_BloodBeer",
        "creator": "바람별",
        "mod_title": "바람별 한글화 모드 애드온 (_KOR_BloodBeer)",
        "version": "2024.03.17",
        "release_notes": "바람별 통합한글화모음 애드온 (Postype 무료 공개)",
        "links": [
            ("Postype (무료)", "통합한글화모음 애드온 | 바람별", "https://www.postype.com/@wwwindystar/post/10314790"),
            ("Patreon (무료)", "통합한글화모음 애드온 | 바람별 ZIMS", "https://www.patreon.com/wwindystarZIMS/posts/tonghabhangeulhw-53821570")
        ]
    },
    {
        "keywords": ["automaticpreferences.package", "automaticpreferences", "automatic_preferences"],
        "name": "AutomaticPreferences",
        "creator": "바람별",
        "mod_title": "바람별 한글화 모드 애드온 (AutomaticPreferences)",
        "version": "2024.03.17",
        "release_notes": "바람별 통합한글화모음 애드온 (Postype 무료 공개)",
        "links": [
            ("Postype (무료)", "통합한글화모음 애드온 | 바람별", "https://www.postype.com/@wwwindystar/post/10314790"),
            ("Patreon (무료)", "통합한글화모음 애드온 | 바람별 ZIMS", "https://www.patreon.com/wwindystarZIMS/posts/tonghabhangeulhw-53821570")
        ]
    },
    {
        "keywords": [
            "wlpo-livedrag.zip",
            "wlpo-livedrag",
            "wlpo_livedragall.package",
            "wlpo_livedragall",
            "wlpo_livedrag",
            "livedrag.zip",
            "livedragall.package",
            "livedragall",
            "livedrag",
            "생활 구매 향상 모드 애드온",
        ],
        "name": "생활 구매 향상 모드 애드온",
        "creator": "바람별",
        "mod_title": "생활 구매 향상 모드 애드온",
        "override_mod_title": True,
        "version": "V13.1",
        "requires_option_modal": True,
        "option_modal_prompt": "설치할 생활 구매 향상 모드 애드온 버전을 선택해 주세요. (분리버전 LiveDrag.zip / 통합버전 LiveDragAll.package 중 1개 선택 · 동시 설치 불가)",
        "option_presets": [
            {
                "file_name": "WLPO-LiveDrag.zip",
                "label": "LiveDrag.zip (분리버전 · 택1)",
                "match_tokens": ["wlpo-livedrag", "livedrag.zip", "livedrag"],
            },
            {
                "file_name": "WLPO_LiveDragAll.package",
                "label": "LiveDragAll.package (통합버전 · 택1)",
                "match_tokens": ["livedragall"],
            },
        ],
        "links": [
            ("네이버 블로그 (무료)", "V13.1 생활 구매 향상 모드 | 바람별", "https://blog.naver.com/wwwindystar/222803448393")
        ]
    },
    {
        "keywords": [
            "wlpo.package",
            "wlpo-nocc.package",
            "wlpo_nocc.package",
            "wlpo-all.package",
            "wlpo_all.package",
            "wlpo_nocc",
            "wlpo-nocc",
            "wlpo-all",
            "wlpo_all",
            "wlpo",
            "생활 구매 향상 모드",
            "222803448393",
        ],
        "name": "생활 구매 향상 모드",
        "creator": "바람별",
        "mod_title": "생활 구매 향상 모드",
        "override_mod_title": True,
        "version": "V13.1",
        "requires_option_modal": True,
        "option_modal_prompt": "설치할 생활 구매 향상 모드 코어 버전을 선택해 주세요. (WLPO 기본 / WLPO_NOCC 태그 미수정 / WLPO-ALL 통합 중 1개 선택 · 동시 설치 불가)",
        "option_presets": [
            {
                "file_name": "WLPO.package",
                "label": "WLPO (기본 · 택1)",
                "match_tokens": ["wlpo.package"],
            },
            {
                "file_name": "WLPO-NOCC.package",
                "label": "WLPO_NOCC (태그 미수정 · 택1)",
                "match_tokens": ["wlpo-nocc", "wlpo_nocc"],
            },
            {
                "file_name": "WLPO-ALL.package",
                "label": "WLPO-ALL (전체 통합 · 택1)",
                "match_tokens": ["wlpo-all", "wlpo_all"],
            },
        ],
        "links": [
            ("네이버 블로그 (무료)", "V13.1 생활 구매 향상 모드 | 바람별", "https://blog.naver.com/wwwindystar/222803448393")
        ]
    },
    {
        "keywords": [
            "sorter.package",
            "sorter.ts4script",
            "sorterv21",
            "sorterv20",
            "sorterv19",
            "sorterv",
            "파이 메뉴 정렬 모드",
            "파이메뉴 정렬 모드",
            "222905723480",
        ],
        "name": "파이 메뉴 정렬 모드",
        "creator": "바람별",
        "mod_title": "파이 메뉴 정렬 모드",
        "override_mod_title": True,
        "version": "V21",
        "links": [
            ("네이버 블로그 (무료)", "V21 파이 메뉴 정렬 모드 | 바람별", "https://blog.naver.com/wwwindystar/222905723480")
        ]
    },
    {
        "keywords": [
            "personalityturnons.package",
            "personalityturnons",
            "호불호 수정 모드",
            "호불호 수정",
        ],
        "name": "호불호 수정 모드",
        "creator": "바람별",
        "mod_title": "호불호 수정 모드",
        "override_mod_title": True,
        "version": "2026.06.05",
        "links": [
            ("네이버 블로그 (무료)", "호불호 수정 모드 (2026.06.05) | 바람별", "https://blog.naver.com/wwwindystar/222905723480")
        ]
    },
    {
        "keywords": ["!wamtik-v97.9r-ff", "_wamtik-v97.9r-ff", "wamtik-v97.9r-ff", "!wamtik-v97.8r-ff", "_wamtik-v97.8r-ff", "wamtik-v97.8r-ff"],
        "name": "!WAMTIK-V97.9R-FF",
        "creator": "바람별",
        "mod_title": "바람별 공식 한글화 모드 빨간맛 (성씨-이름 FF)",
        "version": "V97.9R",
        "release_notes": "바람별 공식 한글화 모드 공개버전 빨간맛 · 풀네임 성씨-이름(FF) 표시 버전 (Patreon 무료 공개)",
        "links": [
            ("Patreon (공식)", "통합한글화모음 V97.9R | 바람별 ZIMS", "https://www.patreon.com/wwindystarZIMS/posts/tonghabhangeulhw-58263282"),
            ("Postype", "바람별의 포스타입 (Postype)", "https://www.postype.com/@wwwindystar"),
            ("네이버 블로그", "바람별의 심즈 4 네이버 블로그", "https://blog.naver.com/wwwindystar")
        ]
    },
    {
        "keywords": ["!wamtik-v97.9r", "_wamtik-v97.9r", "wamtik-v97.9r", "!wamtik-v97.8r", "_wamtik-v97.8r", "wamtik-v97.8r"],
        "name": "!WAMTIK-V97.9R",
        "creator": "바람별",
        "mod_title": "바람별 공식 한글화 모드 빨간맛",
        "version": "V97.9R",
        "release_notes": "바람별 공식 한글화 모드 공개버전 빨간맛 · 기본 이름 표시 버전 (Patreon 무료 공개)",
        "links": [
            ("Patreon (공식)", "통합한글화모음 V97.9R | 바람별 ZIMS", "https://www.patreon.com/wwindystarZIMS/posts/tonghabhangeulhw-58263282"),
            ("Postype", "바람별의 포스타입 (Postype)", "https://www.postype.com/@wwwindystar"),
            ("네이버 블로그", "바람별의 심즈 4 네이버 블로그", "https://blog.naver.com/wwwindystar")
        ]
    },
    {
        "keywords": ["!wamtik-v97.9-ff", "_wamtik-v97.9-ff", "wamtik-v97.9-ff", "!wamtik-v97.8-ff", "_wamtik-v97.8-ff", "wamtik-v97.8-ff"],
        "name": "!WAMTIK-V97.9-FF",
        "creator": "바람별",
        "mod_title": "바람별 공식 한글화 모드 (성씨-이름 FF)",
        "version": "V97.9",
        "release_notes": "바람별 공식 한글화 모드 · 풀네임 성씨-이름(FF) 표시 버전 (네이버 블로그 무료 공개)",
        "links": [
            ("네이버 블로그 참고 (무료)", "바람별 심즈 4 공식 한글화 모드", "https://blog.naver.com/wwwindystar/220460594769"),
            ("Postype", "바람별의 포스타입 (Postype)", "https://www.postype.com/@wwwindystar"),
            ("Patreon (선배포)", "바람별 ZIMS 통합 한글화 (Patreon)", "https://www.patreon.com/cw/wwindystarZIMS")
        ]
    },
    {
        "keywords": ["!wamtik-v97.9", "_wamtik-v97.9", "wamtik-v97.9", "!wamtik-v97.8", "_wamtik-v97.8", "wamtik-v97.8"],
        "name": "!WAMTIK-V97.9",
        "creator": "바람별",
        "mod_title": "바람별 공식 한글화 모드",
        "version": "V97.9",
        "release_notes": "바람별 공식 한글화 모드 · 기본 이름 표시 버전 (네이버 블로그 무료 공개)",
        "links": [
            ("네이버 블로그 참고 (무료)", "바람별 심즈 4 공식 한글화 모드", "https://blog.naver.com/wwwindystar/220460594769"),
            ("Postype", "바람별의 포스타입 (Postype)", "https://www.postype.com/@wwwindystar"),
            ("Patreon (선배포)", "바람별 ZIMS 통합 한글화 (Patreon)", "https://www.patreon.com/cw/wwindystarZIMS")
        ]
    },
    {
        "keywords": ["_wamtik-v98-alpha-ff", "!wamtik-v98-alpha-ff", "wamtik-v98-alpha-ff", "_wamtik-v98p8-ff", "!wamtik-v98p8-ff", "wamtik-v98p8-ff"],
        "name": "_WAMTIK-V98-alpha-FF",
        "creator": "바람별",
        "mod_title": "바람별 한글화 모드 순한맛 (성씨-이름 FF)",
        "version": "V98-alpha",
        "is_early_access": True,
        "release_notes": "바람별 한글화 모드 순한맛(순결버전) · 풀네임 성씨-이름(FF) 표시 버전 (후원자 전용 · 수동 다운로드 안내)",
        "links": [
            ("Postype", "통합한글화모음 V98-alpha 순결버전 (Postype)", "https://www.postype.com/@wwwindystar/post/9789832"),
            ("Patreon (후원자 전용)", "바람별 ZIMS 통합 한글화 (Patreon)", "https://www.patreon.com/cw/wwindystarZIMS"),
            ("네이버 블로그", "바람별의 심즈 4 네이버 블로그", "https://blog.naver.com/wwwindystar")
        ]
    },
    {
        "keywords": ["_wamtik-v98-alpha", "!wamtik-v98-alpha", "wamtik-v98-alpha", "_wamtik-v98p8", "!wamtik-v98p8", "wamtik-v98p8"],
        "name": "_WAMTIK-V98-alpha",
        "creator": "바람별",
        "mod_title": "바람별 한글화 모드 순한맛",
        "version": "V98-alpha",
        "is_early_access": True,
        "release_notes": "바람별 한글화 모드 순한맛(순결버전) · 기본 이름 표시 버전 (후원자 전용 · 수동 다운로드 안내)",
        "links": [
            ("Postype", "통합한글화모음 V98-alpha 순결버전 (Postype)", "https://www.postype.com/@wwwindystar/post/9789832"),
            ("Patreon (후원자 전용)", "바람별 ZIMS 통합 한글화 (Patreon)", "https://www.patreon.com/cw/wwindystarZIMS"),
            ("네이버 블로그", "바람별의 심즈 4 네이버 블로그", "https://blog.naver.com/wwwindystar")
        ]
    },
    {
        "keywords": ["!wamtik-v98r-alpha-ff", "_wamtik-v98r-alpha-ff", "wamtik-v98r-alpha-ff", "!wamtik-v98b8-ff", "_wamtik-v98b8-ff", "wamtik-v98b8-ff"],
        "name": "!WAMTIK-V98R-alpha-FF",
        "creator": "바람별",
        "mod_title": "바람별 한글화 모드 베타버전 빨간맛 (성씨-이름 FF)",
        "version": "V98R-alpha",
        "is_early_access": True,
        "release_notes": "베타버전 빨간맛 · 풀네임 성씨-이름(FF) 표시 버전 (후원자 전용 · 수동 다운로드 안내)",
        "links": [
            ("Patreon (후원자 전용)", "통합한글화모음 V98R-alpha | 바람별 ZIMS", "https://www.patreon.com/wwindystarZIMS/posts/tonghabhangeulhw-69805432"),
            ("Postype", "바람별의 포스타입 (Postype)", "https://www.postype.com/@wwwindystar"),
            ("네이버 블로그", "바람별의 심즈 4 네이버 블로그", "https://blog.naver.com/wwwindystar")
        ]
    },
    {
        "keywords": ["!wamtik-v98r-alpha", "_wamtik-v98r-alpha", "wamtik-v98r-alpha", "!wamtik-v98b8", "_wamtik-v98b8", "wamtik-v98b8"],
        "name": "!WAMTIK-V98R-alpha",
        "creator": "바람별",
        "mod_title": "바람별 한글화 모드 베타버전 빨간맛",
        "version": "V98R-alpha",
        "is_early_access": True,
        "release_notes": "베타버전 빨간맛 · 기본 이름 표시 버전 (후원자 전용 · 수동 다운로드 안내)",
        "links": [
            ("Patreon (후원자 전용)", "통합한글화모음 V98R-alpha | 바람별 ZIMS", "https://www.patreon.com/wwindystarZIMS/posts/tonghabhangeulhw-69805432"),
            ("Postype", "바람별의 포스타입 (Postype)", "https://www.postype.com/@wwwindystar"),
            ("네이버 블로그", "바람별의 심즈 4 네이버 블로그", "https://blog.naver.com/wwwindystar")
        ]
    },
    {
        "keywords": ["!wamtik-v98g10-ff", "_wamtik-v98g10-ff", "wamtik-v98g10-ff", "!wamtik-v98g8-ff", "_wamtik-v98g8-ff", "wamtik-v98g8-ff"],
        "name": "!WAMTIK-V98G10-FF",
        "creator": "바람별",
        "mod_title": "바람별 한글화 모드 (성씨-이름 FF)",
        "version": "V98G10",
        "is_early_access": True,
        "release_notes": "선배포모드 번역이 추가되는 광역후원자 버전 · 풀네임 성씨-이름(FF) 표시 (수동 다운로드 안내)",
        "links": [
            ("Patreon (선배포)", "바람별 ZIMS 통합 한글화 (Patreon)", "https://www.patreon.com/cw/wwindystarZIMS"),
            ("Postype", "바람별의 포스타입 (Postype)", "https://www.postype.com/@wwwindystar"),
            ("네이버 블로그", "바람별의 심즈 4 네이버 블로그", "https://blog.naver.com/wwwindystar")
        ]
    },
    {
        "keywords": ["!wamtik-v98g10", "_wamtik-v98g10", "wamtik-v98g10", "!wamtik-v98g8", "_wamtik-v98g8", "wamtik-v98g8", "wamtik", "바람별", "바람별한글화"],
        "name": "!WAMTIK-V98G10",
        "creator": "바람별",
        "mod_title": "바람별 한글화 모드",
        "version": "V98G10",
        "is_early_access": True,
        "release_notes": "선배포모드 번역이 추가되는 광역후원자 버전 (수동 다운로드 안내)",
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
    ("s4m-byok.prmptplus.chatgpt.site", "S4m AI Chat BYOK Official"),
    ("github.com", "GitHub"),
    ("sims4studio.com", "Sims 4 Studio"),
    ("seebee.de", "ichschaf Sims 4 Mods"),
    ("kemzimamods.com", "KemZima Mods"),
    ("pandasama.com", "Pandasama Official"),
    ("lot51.cc", "Lot 51"),
    ("twistedmexi.com", "TwistedMexi"),
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
    "https://support.patreon.com",
    "https://wicked.cc/contact",
    "https://frankkmods.com",
    "https://www.lovense.com",
    "http://wonderf.cluster026.hosting.ovh.net",
    "http://twistedmexi.com/betterexceptions/knownexceptions.php",
    "https://twistedmexi.com/betterexceptions/knownexceptions.php",
)

# 무시할 일반 파이썬/심즈 기본 모듈명 및 튜닝 속성명
GENERIC_INTERNAL_NAMES = {
    "__init__", "injector", "config", "enums", "commands", "reload", "utils",
    "version", "patches", "snippets", "main", "core", "common", "settings",
    "tuning", "helpers", "elements", "ctypes", "services", "sims4", "llamalogic",
    "modfilemanifest", "xml_injector", "_do_not_unzip_", "test", "tests",
}


def extract_date_from_filename(text: str) -> str:
    """파일명, 폴더명 또는 제목에 버전 숫자 대신 '날짜'만 표기된 경우 이를 감지하여
    비교가 가능한 표준 날짜 형식('YYYY.MM.DD')으로 변환해 반환합니다.
    (직접 수정 및 커스텀이 쉽도록 패턴별로 분리되어 있습니다.)
    지원 패턴:
      1) YYYY.MM.DD / YYYY-MM-DD / YYYY_MM_DD (예: 2026.03.15, 2026-03-15)
      2) DD.MM.YYYY / DD-MM-YYYY / MM.DD.YYYY (예: 15.03.2026, 03-15-2026)
      3) YY.MM.DD / DD.MM.YY / MM.DD.YY (예: 26.03.15, 27.09.25, [26.02.14])
      4) YYYYMMDD 8자리 또는 구분자/대괄호 안의 YYMMDD 6자리 (예: 20260315, [260315], _260315)
    """
    if not text:
        return ""

    # 1) YYYY.MM.DD / YYYY-MM-DD / YYYY_MM_DD (월/일이 2자리 0패딩된 날짜, MCCC의 2026.1.1과 구분)
    m_ymd4 = re.search(
        r"(?:^|[\s_\-\[\(])(201[4-9]|202[0-9])[\.\-_](0[1-9]|1[0-2])[\.\-_](0[1-9]|[12][0-9]|3[01])(?=$|[^0-9])",
        text,
    )
    if m_ymd4:
        return f"{m_ymd4.group(1)}.{m_ymd4.group(2)}.{m_ymd4.group(3)}"

    # 2) DD.MM.YYYY 또는 MM.DD.YYYY
    m_dmy4 = re.search(
        r"(?:^|[\s_\-\[\(])([0-3][0-9])[\.\-_]([0-3][0-9])[\.\-_](201[4-9]|202[0-9])(?=$|[^0-9])",
        text,
    )
    if m_dmy4:
        n1, n2, yyyy = int(m_dmy4.group(1)), int(m_dmy4.group(2)), m_dmy4.group(3)
        if 1 <= n2 <= 12 and 1 <= n1 <= 31:
            return f"{yyyy}.{n2:02d}.{n1:02d}"
        if 1 <= n1 <= 12 and 1 <= n2 <= 31:
            return f"{yyyy}.{n1:02d}.{n2:02d}"

    # 3) 2자리 연도 날짜: YY.MM.DD / DD.MM.YY / MM.DD.YY (예: 26.03.15, 27.09.25)
    for m_2y in re.finditer(
        r"(?:^|[\s_\-\[\(])([0-3][0-9])[\.\-_]([0-3][0-9])[\.\-_]([0-3][0-9])(?=$|[^0-9.])",
        text,
    ):
        a, b, c = int(m_2y.group(1)), int(m_2y.group(2)), int(m_2y.group(3))
        # (a) B가 월(1~12)인 경우: YY.MM.DD 또는 DD.MM.YY 판별
        if 1 <= b <= 12:
            # A가 연도 범위를 벗어나거나(>26 또는 <14) C가 확실한 연도(14~26)인 경우 -> DD.MM.YY (유럽식, 예: 27.09.25)
            if (a > 26 or a < 14) and 14 <= c <= 26 and 1 <= a <= 31:
                return f"20{c:02d}.{b:02d}.{a:02d}"
            # A가 확실한 연도(14~26)이고 C가 일(1~31)인 경우 -> YY.MM.DD (한국식, 예: 26.03.15)
            if 14 <= a <= 26 and 1 <= c <= 31:
                return f"20{a:02d}.{b:02d}.{c:02d}"
        # (b) A가 월(1~12), B가 일(13~31), C가 연도(14~26)인 경우 -> MM.DD.YY (북미식, 예: 09.27.25)
        if 1 <= a <= 12 and 13 <= b <= 31 and 14 <= c <= 26:
            return f"20{c:02d}.{a:02d}.{b:02d}"

    # 4) 구분자 없는 8자리 YYYYMMDD (예: 20260315, [20260315])
    m_8d = re.search(
        r"(?:^|[\s_\-\[\(])(201[4-9]|202[0-9])(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])(?=$|[^0-9])",
        text,
    )
    if m_8d:
        return f"{m_8d.group(1)}.{m_8d.group(2)}.{m_8d.group(3)}"

    # 5) 대괄호 또는 구분자 뒤의 6자리 YYMMDD (예: [260315], _260315)
    m_6d = re.search(
        r"(?:[\[\(_\-])(2[0-6])(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])(?=$|[\]\)\s_\-])",
        text,
    )
    if m_6d:
        return f"20{m_6d.group(1)}.{m_6d.group(2)}.{m_6d.group(3)}"

    return ""


def extract_version_from_filename(filename: str) -> str:
    """파일명/폴더명에 버전(예: v1, v2, v4, v1.1, 0.1, 0.1.0, v2.986, V98G8 등) 또는
    날짜 버전(예: 2026.03.15, 26.03.15, 27.09.25, 20260315 등)이 명시되어 있으면
    버전 문자열을 반환하고, 적혀 있지 않으면 빈 문자열('')을 반환합니다.
    """
    if not filename:
        return ""
    stem = re.sub(r"\.(?:package|ts4script|zip|rar|7z)$", "", filename, flags=re.IGNORECASE)
    stem = re.sub(
        r"(?<=canvas_frame_override)_v[123]$|(?<=alllots)_v1$|(?<=retailthriftlots)_v2$|(?<=mirrorphoto)_v2(?=_genderneutral|$)",
        "",
        stem,
        flags=re.IGNORECASE,
    )
    # 1) 명시적 v / ver / version 접두사가 있는 버전 (예: v4, v1.1, v2.986, v2a, V2.3, ChatPackv2_BabiesFamily)
    # 파이썬 정규식에서 언더바(_)는 단어 문자(\w)이므로 \b 대신 (?=$|[^a-zA-Z0-9.]) 경계를 사용합니다.
    m_v = re.search(
        r"(?:^|[\s_\-\.\[\(]|(?<=[a-zA-Z]))(?:v|ver|version)\.?\s*([0-9]+(?:\.[0-9]+)*[a-z]?)(?=$|[^a-zA-Z0-9.])",
        stem,
        flags=re.IGNORECASE,
    )
    if m_v:
        raw_v = m_v.group(1).lstrip("vV")
        return f"v{raw_v}"
    # 1-b) 바람별 통합한글화모음 스타일 버전 (예: V98G8, V98B8, V98P8, V97.8R, V97.9R, V98R 등)
    m_vg = re.search(r"(?:^|[\s_\-\[\(])(V[0-9]+(?:\.[0-9]+)?[GBPR][0-9]*)(?=$|[^a-zA-Z0-9.])", stem, flags=re.IGNORECASE)
    if m_vg:
        return m_vg.group(1).upper()

    # 2) 날짜 형식 버전 감지 (예: 26.03.15, 27.09.25, 2026-03-15, [260315] 등 -> 'YYYY.MM.DD'로 정규화)
    date_ver = extract_date_from_filename(stem)
    if date_ver:
        return date_ver

    # 3) 점이 포함된 일반 버전 숫자 (예: 0.1, 0.1.0, a0.5, a0.2.4, b1.0, 1.8, 2026.1.1 - 단 배수 표기 1.75x 제외)
    m_dot = re.search(
        r"(?:^|[\s_\-\[\(])([ab])?([0-9]+\.[0-9]+(?:\.[0-9]+)*[a-wyz]?)(?=$|[^a-zA-Z0-9.xX가-힣])",
        stem,
        flags=re.IGNORECASE,
    )
    if m_dot:
        ab_prefix = (m_dot.group(1) or "").lower()
        raw_dot = m_dot.group(2)
        return f"{ab_prefix}{raw_dot}" if ab_prefix else f"v{raw_dot}"

    # 4) 폴더/파일명 끝에 대괄호로 표기된 버전 (예: GSM MCCC [2026.1.1], GSM WickedWhims [185k], GM SomeMod [4], [a0.5])
    # 단, 'GSM-[1]', 'GSM_[1]', 'GSM [1]'처럼 폴더 순번만 적힌 경우는 제외
    if not re.match(r"^(?:[\d\-]+[\.\s_\-]*)?(?:GSM|GM|MOD)[\s_\-]*\[\s*\d+\s*\]\s*$", stem, flags=re.IGNORECASE):
        m_bracket_end = re.search(
            r"\[\s*(?:([ab])|(?:v|ver|version)?\.?)\s*([0-9]+(?:\.[0-9]+)*[a-z]?)\s*\]\s*$",
            stem,
            flags=re.IGNORECASE,
        )
        if m_bracket_end:
            b_ab = (m_bracket_end.group(1) or "").lower()
            return f"{b_ab}{m_bracket_end.group(2)}" if b_ab else f"v{m_bracket_end.group(2)}"
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
    # LoversLab 및 KemZima 파일 배포 페이지 URL은 끝의 슬래시(/) 보존
    if "loverslab.com/" in u_low or "kemzimamods.com/" in u_low:
        base_ll = url.split("?")[0].rstrip("/")
        return f"{base_ll}/"
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
    """파일 내부에서 추출한 URL이 유효한 HTTPS 모드 배포처 URL인지 판별합니다 (일반 HTTP 차단)."""
    if not url or len(url) < 14:
        return False
    u_lower = url.lower()
    if not u_lower.startswith("https://"):
        return False
    if any(u_lower.startswith(prefix) for prefix in IGNORED_INTERNAL_URL_PREFIXES):
        return False
    if u_lower.rstrip("/") in IGNORED_ROOT_URLS:
        return False
    # XML Injector가 의존성(required_mods)으로 박혀있는 다른 모드인 경우 제외
    if "scumbumbomods.com/xml-injector" in u_lower or "curseforge.com/sims4/mods/xml-injector" in u_lower:
        if "xml" not in file_name.lower() and "injector" not in file_name.lower():
            return False
    if not is_valid_https_url(url):
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
        MAX_TS4SCRIPT_ENTRY_BYTES = 32 * 1024 * 1024  # 단일 엔트리 최대 32MB (압축 폭탄 메모리 고갈 방지)
        byok_max_date = (0, 0, 0)
        with zipfile.ZipFile(path, "r") as z:
            for z_info in z.infolist():
                entry_name = z_info.filename
                if z_info.is_dir():
                    continue
                if entry_name.lower().startswith("sims4_ai_chat_addon/"):
                    dt_tuple = tuple(z_info.date_time[:3])
                    if dt_tuple > byok_max_date:
                        byok_max_date = dt_tuple
                parts = [p for p in entry_name.replace("\\", "/").split("/") if p]
                if parts:
                    top_stem = re.sub(r"\.(pyc|py|txt|yml|yaml|json|cfg|log)$", "", parts[0], flags=re.IGNORECASE)
                    if (
                        top_stem
                        and top_stem.lower() not in GENERIC_INTERNAL_NAMES
                        and not top_stem.startswith("_")
                        and top_stem not in info["modules"]
                    ):
                        info["modules"].append(top_stem)

                if z_info.file_size < 0 or z_info.file_size > MAX_TS4SCRIPT_ENTRY_BYTES:
                    continue

                try:
                    data = z.read(z_info)
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
                        info["version"] = m_ver.group(1).strip().strip("'\"").lstrip("vV")

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
                    e_low = entry_name.lower()
                    if e_low.startswith("sims4_ai_chat_addon/") and e_low.endswith(".pyc"):
                        for m_byok in re.finditer(rb"(?<![0-9.])(2\.[0-9]+\.[0-9]+)(?![0-9]|\.[0-9])", data):
                            cand_byok = m_byok.group(1).decode("ascii", "ignore")
                            cur_parts = tuple(int(x) for x in info["version"].split(".") if x.isdigit()) if info["version"] else ()
                            cand_parts = tuple(int(x) for x in cand_byok.split(".") if x.isdigit())
                            if cand_parts > cur_parts:
                                info["version"] = cand_byok
                    elif not info["version"]:
                        if e_low.endswith(("mc_cmd_version.pyc", "mc_utils.pyc", "mc_cmd_center.pyc", "mc_woohoo.pyc")):
                            m_mc = re.search(rb"(?<![0-9.])(202[0-9]\.[0-9]+\.[0-9]+)(?![0-9.])", data)
                            if m_mc:
                                info["version"] = m_mc.group(1).decode("ascii", "ignore")
                        elif "wickedwhims" in e_low and ("version" in e_low or "main" in e_low or "init" in e_low):
                            m_ww = re.search(
                                rb"(?<![a-zA-Z0-9.])v?(1[789][0-9](?:\.[0-9]+|[a-z]))(?![a-zA-Z0-9.])",
                                data,
                                flags=re.IGNORECASE,
                            ) or re.search(
                                rb"(?<![a-zA-Z0-9.])v(1[789][0-9])(?![a-zA-Z0-9.])",
                                data,
                                flags=re.IGNORECASE,
                            )
                            if m_ww:
                                info["version"] = m_ww.group(1).decode("ascii", "ignore")
                        elif "wonderfulwhims" in e_low and ("version" in e_low or "main" in e_low or "init" in e_low):
                            m_wfw = re.search(rb"(?<![a-zA-Z0-9.])v([456789][0-9][a-z]?)(?![a-zA-Z0-9.])", data, flags=re.IGNORECASE)
                            if m_wfw:
                                info["version"] = f"v{m_wfw.group(1).decode('ascii', 'ignore')}"
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
                        elif "tmex_belibrary.pyc" in e_low:
                            m_be = re.search(rb"(?<![0-9.])([234]\.[0-9]{1,2}(?:\.[0-9]+)?)(?![0-9.])", data)
                            if m_be:
                                info["version"] = m_be.group(1).decode("ascii", "ignore")
            if info["version"] == "2.5.5" and byok_max_date >= (2026, 11, 21):
                info["version"] = "2.5.5 (핫픽스)"
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
                        v_candidate = html.unescape(m_v.group(1).strip()).lstrip("vV")
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


_MOD_META_CACHE_LOCK = threading.Lock()
_MOD_META_CACHE: Dict[Tuple[str, int, int], Dict[str, Any]] = {}
_CATALOG_CACHE_LOCK = threading.Lock()
_COMPILED_CATALOG_LEN = -1
_COMPILED_CATALOG_ITEMS: List[Tuple[Dict[str, Any], List[Tuple[str, str]]]] = []


def _get_compiled_catalog() -> List[Tuple[Dict[str, Any], List[Tuple[str, str]]]]:
    """KNOWN_CATALOG 키워드를 소문자/정규화 형태로 사전 컴파일하여 반복 정규식 치환 비용을 제거합니다."""
    global _COMPILED_CATALOG_LEN, _COMPILED_CATALOG_ITEMS
    cur_len = len(KNOWN_CATALOG)
    if _COMPILED_CATALOG_LEN == cur_len and _COMPILED_CATALOG_ITEMS:
        return _COMPILED_CATALOG_ITEMS

    with _CATALOG_CACHE_LOCK:
        cur_len = len(KNOWN_CATALOG)
        if _COMPILED_CATALOG_LEN == cur_len and _COMPILED_CATALOG_ITEMS:
            return _COMPILED_CATALOG_ITEMS
        compiled: List[Tuple[Dict[str, Any], List[Tuple[str, str]]]] = []
        for item in KNOWN_CATALOG:
            kw_pairs: List[Tuple[str, str]] = []
            for kw in item["keywords"]:
                kw_lower = kw.lower()
                clean_kw = re.sub(r"[^a-zA-Z0-9가-힣]", "", kw_lower)
                kw_pairs.append((kw_lower, clean_kw))
            compiled.append((item, kw_pairs))
        _COMPILED_CATALOG_ITEMS = compiled
        _COMPILED_CATALOG_LEN = cur_len
        return compiled


def extract_mod_file_metadata(file_path: Optional[str]) -> Dict[str, Any]:
    """지정된 .package 또는 .ts4script 파일(및 동일 폴더의 짝 파일) 내부를 분석하여
    제작자명, 모드명, 버전, 내장 공식 배포 URL, 튜닝/모듈 식별자를 반환합니다.
    (동일 파일 mtime/size 기준 스레드 안전 메모리 캐싱으로 중복 압축 해제를 방지합니다.)
    """
    empty_result: Dict[str, Any] = {
        "has_metadata": False,
        "manifest_name": "",
        "creators": [],
        "inferred_creator": "",
        "inferred_mod": "",
        "display_names": [],
        "urls": [],
        "version": "",
        "binary_version": "",
        "root_tunings": [],
        "modules": [],
        "is_ww_addon": False,
    }
    if not file_path:
        return empty_result

    p = Path(file_path)
    try:
        if not p.exists() or not p.is_file():
            return empty_result
        st = p.stat()
        cache_key = (
            str(p.resolve()),
            int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
            int(st.st_size),
        )
    except OSError:
        return empty_result

    with _MOD_META_CACHE_LOCK:
        cached = _MOD_META_CACHE.get(cache_key)
        if cached is not None:
            return copy.deepcopy(cached)

    result = _extract_mod_file_metadata_uncached(p)

    with _MOD_META_CACHE_LOCK:
        if len(_MOD_META_CACHE) >= 512:
            _MOD_META_CACHE.clear()
        _MOD_META_CACHE[cache_key] = copy.deepcopy(result)

    return result


def _extract_mod_file_metadata_uncached(p: Path) -> Dict[str, Any]:
    """실제 바이너리/아카이브 메타데이터 추출 구현부."""
    result: Dict[str, Any] = {
        "has_metadata": False,
        "manifest_name": "",
        "creators": [],
        "inferred_creator": "",
        "inferred_mod": "",
        "display_names": [],
        "urls": [],
        "version": "",
        "binary_version": "",
        "root_tunings": [],
        "modules": [],
        "is_ww_addon": False,
    }

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
        if not pkg_info.get("urls") and not scr_info.get("urls") and len(p.stem) >= 12:
            prefix_match = p.stem.lower()[:12]
            for sp in sorted(p.parent.glob("*.package"), key=lambda x: len(x.name))[:3]:
                if sp != sibling_pkg and sp.stem.lower().startswith(prefix_match):
                    sp_info = _extract_from_single_package(sp)
                    if sp_info.get("urls") or sp_info.get("manifest_name"):
                        pkg_info = sp_info
                        break

    # 추출된 정보 병합
    result["manifest_name"] = pkg_info.get("manifest_name") or scr_info.get("manifest_name") or ""
    raw_merged_ver = (pkg_info.get("version") or scr_info.get("version") or "").strip()
    result["version"] = (
        raw_merged_ver
        if re.match(r"^V\d+G\d+$", raw_merged_ver, flags=re.IGNORECASE)
        else raw_merged_ver.lstrip("vV")
    )
    if result["version"]:
        result["binary_version"] = result["version"]
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

    if not result["version"] and scr_info.get("modules"):
        for mod_name_entry in scr_info.get("modules", [])[:5]:
            m_rpo_mod_ver = re.match(r"^Lumpinou_RPO(\d+)_", str(mod_name_entry or ""), flags=re.IGNORECASE)
            if m_rpo_mod_ver:
                result["version"] = m_rpo_mod_ver.group(1)
                result["binary_version"] = m_rpo_mod_ver.group(1)
                break

    inf_creator, inf_mod = _parse_tuning_and_module_clues(result["root_tunings"], result["modules"])

    # 파일명 자체에 명시된 [제작자], 모드명, 버전(예: v4, v1.1) 및 카탈로그 매칭 정보로 누락 필드 보완
    fn_ver_str = extract_version_from_filename(p.name)
    if not result["version"] and fn_ver_str:
        result["version"] = fn_ver_str.lstrip("vV")
    if not result["version"] and suffix == ".ts4script" and sibling_pkg.exists():
        sib_ver_str = extract_version_from_filename(sibling_pkg.name)
        if sib_ver_str:
            result["version"] = sib_ver_str.lstrip("vV")
    if not result["version"] and p.name.lower().startswith("mc_") and (p.parent / "mc_cmd_center.ts4script").exists():
        mc_core_info = _extract_from_single_ts4script(p.parent / "mc_cmd_center.ts4script")
        if mc_core_info.get("version"):
            result["version"] = mc_core_info["version"].lstrip("vV")
            result["binary_version"] = result["version"]

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
        if cat_match.get("mod_title") and (not result["manifest_name"] or cat_match.get("override_mod_title")):
            result["manifest_name"] = cat_match["mod_title"]
        if cat_match.get("version") and (not result["version"] or result["version"] == "4.04"):
            if result["version"] == "4.04":
                result["binary_version"] = ""
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


def check_known_catalog(
    raw_name: str,
    rpo_channel: Optional[str] = None,
    ww_channel: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """핵심 코어 모드 카탈로그(MCCC, WickedWhims 본체, 바람별 한글화 등)와 정확히 일치하는지 확인합니다."""
    if not raw_name:
        return None
    name_lower = raw_name.lower()
    clean = re.sub(r"[^a-zA-Z0-9가-힣]", "", name_lower)
    rpo_mode = str(rpo_channel or "").strip().lower()
    ww_mode = str(ww_channel or "").strip().lower()
    for item, kw_pairs in _get_compiled_catalog():
        for kw_lower, clean_kw in kw_pairs:
            if kw_lower in name_lower or (len(clean_kw) >= 6 and clean_kw in clean):
                is_rpo_free = (
                    item.get("name") == "Relationship & Pregnancy Overhaul (RPO Collection)"
                    and rpo_mode == "free"
                )
                is_ww_paid = (
                    item.get("name") == "WickedWhims"
                    and ww_mode == "paid"
                )
                if is_rpo_free:
                    links = item.get("free_links") or item.get("links") or []
                    resolved_ver = item.get("free_version", item.get("version", ""))
                    resolved_paid = bool(item.get("is_paid", False))
                    resolved_ea = False
                    resolved_notes = "무료 공개 배포판 기준 버전 비교 및 자동 업데이트 활성화"
                elif is_ww_paid:
                    links = item.get("paid_links") or item.get("links") or []
                    resolved_ver = item.get("paid_version", item.get("version", ""))
                    resolved_paid = True
                    resolved_ea = True
                    resolved_notes = "선배포(Patreon) 버전 · 수동 다운로드 안내 (WickedWhims v187.18)"
                else:
                    links = item.get("links") or []
                    resolved_ver = item.get("version", "")
                    resolved_paid = bool(item.get("is_paid", False))
                    resolved_ea = bool(item.get("is_early_access", False))
                    resolved_notes = item.get("release_notes", "")
                return {
                    "found": True,
                    "primary_url": links[0][2] if links else "",
                    "source_name": links[0][0] if links else "미출시 모드",
                    "candidate_links": links,
                    "matched_catalog": item["name"],
                    "creator": item.get("creator", ""),
                    "mod_title": item.get("mod_title", item["name"]),
                    "override_mod_title": bool(item.get("override_mod_title", False)),
                    "version": resolved_ver,
                    "is_paid": resolved_paid,
                    "is_early_access": resolved_ea,
                    "is_unreleased": bool(item.get("is_unreleased", False)),
                    "requires_option_modal": bool(item.get("requires_option_modal", False)),
                    "option_modal_mode": item.get("option_modal_mode", ""),
                    "option_modal_prompt": item.get("option_modal_prompt", ""),
                    "option_presets": list(item.get("option_presets") or []),
                    "optional_addons": list(item.get("optional_addons") or []),
                    "release_notes": resolved_notes,
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

    # 폴더 문맥에서 보조 제작자/모드 단서 추출 (예: 'MOD Cumshine', 'GSM [제작자] [모드] [버전]', 'GM [모드] [버전]', 'MOD\Lumpinou', '5 GSM 1', 'GSM-1', 'GSM_1')
    def _clean_folder_clue(f_ctx: str) -> str:
        # 하위 폴더 경로(예: 'MOD\Lumpinou', '5 GSM-1\LittleMsSam')인 경우 마지막 하위 폴더명을 우선 사용
        parts = [p.strip() for p in re.split(r"[\\/]+", f_ctx) if p.strip()]
        target_part = parts[-1] if parts else f_ctx
        cleaned = re.sub(
            r"^(?:[\d\-]+[\.\s_-]*)?(?:(?:MOD|GSM|GM)(?:[\s_-]*\[?\d+\]?)?[\s_-]*)+",
            "",
            target_part,
            flags=re.IGNORECASE,
        ).strip()
        cleaned = re.sub(
            r"\[\s*(?:v|ver|version)?\.?\s*[0-9]+(?:[\.\-_][0-9]+)*[a-z]?\s*\]\s*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        if not cleaned or cleaned.isdigit() or cleaned.lower() in (
            "cas", "build", "pose", "prio", "high priority mods", "3 high priority mods",
            "overrides", "override", "default", "mod", "mods", "gsm", "gm", "optional",
            "(mods 루트)",
        ):
            return ""
        return cleaned

    if folder_context and not clean_creator:
        folder_clean = _clean_folder_clue(folder_context)
        if folder_clean:
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
        folder_clean = _clean_folder_clue(folder_context)
        if folder_clean and re.sub(r"\s+", "", folder_clean).lower() == clean_title.lower():
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

    generic_title_words = {
        "better", "even", "more", "less", "new", "old", "custom", "default",
        "game", "in", "on", "of", "for", "and", "with", "no", "not", "all",
        "cas", "ui", "bg", "base", "pack", "set", "v1", "v2", "v3", "v4", "v5",
        "bright", "dark", "soft", "gentle", "extended", "overhaul", "control",
        "controls", "interactions", "interaction", "sims", "sim", "mod", "mods",
        "life", "stages", "family", "babies", "phone", "calls", "adult", "mood",
    }
    specific_title_kws = [kw for kw in title_only_kws if kw not in generic_title_words and len(kw) >= 3]

    match_count = sum(1 for kw in keywords if kw in combined_text)
    if match_count == 0:
        return 0

    score = match_count * 15

    # 제작자명이 일치하면 큰 가산점, 반대로 제작자명이 명확한데 URL/제목/스니펫 어디에도 없으면 즉시 탈락(무관한 링크 차단)
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
        # 제작자가 식별되었는데 검색 결과에 제작자명이 전혀 없으면 관련 없는 타인의 모드로 간주하여 즉시 탈락
        return 0

    # 제작자가 식별되지 않은 미상 모드의 경우, 고유한 제목 키워드가 제목/URL에 최소 2개 이상(또는 8글자 이상 고유 단어) 직접 포함되어야만 인정
    title_or_url_text = f"{title_lower} {url_lower}"
    if not all_creators:
        spec_matches_in_head = [kw for kw in specific_title_kws if kw in title_or_url_text]
        if len(spec_matches_in_head) < 2 and not any(len(kw) >= 9 for kw in spec_matches_in_head):
            return 0
    elif title_only_kws:
        if not any(kw in title_or_url_text for kw in title_only_kws):
            return 0

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


def _explain_snippet_rejection(
    title: str, snippet: str, url: str, tokens: Dict[str, Any], score: int
) -> str:
    """검색 후보 링크가 임계값(85점)을 통과하지 못한 구체적 사유를 반환합니다."""
    title_lower = title.lower()
    snippet_lower = snippet.lower()
    url_lower = url.lower()
    combined_text = f"{title_lower} {snippet_lower} {url_lower}"
    title_or_url_text = f"{title_lower} {url_lower}"

    keywords = tokens.get("keywords", [])
    creator_lower = tokens.get("creator", "").lower().strip()
    extra_creators = [c.lower().strip() for c in tokens.get("extra_creators", []) if c]
    all_creators = [c for c in ([creator_lower] + extra_creators) if len(c) >= 3]

    if not keywords:
        return "파일명 및 내부 메타데이터에서 추출된 유효 검색 키워드 없음"

    creator_words_set = set(re.split(r"[^a-z0-9가-힣]+", " ".join(all_creators)))
    title_only_kws = [kw for kw in keywords if kw not in creator_words_set and len(kw) >= 3]
    if title_only_kws and sum(1 for kw in title_only_kws if kw in combined_text) == 0:
        return f"모드 제목 핵심 키워드({', '.join(title_only_kws[:4])})가 검색 결과에 전혀 없음"

    if sum(1 for kw in keywords if kw in combined_text) == 0:
        return f"검색 키워드({', '.join(keywords[:4])}) 불일치"

    creator_matched = False
    for c in all_creators:
        c_slug = re.sub(r"[^a-z0-9]", "", c)
        if c in combined_text or (len(c_slug) >= 4 and c_slug in re.sub(r"[^a-z0-9]", "", combined_text)):
            creator_matched = True
            break
    if all_creators and not creator_matched:
        return f"추출된 제작자명({', '.join(all_creators)})이 검색 결과 제목/URL/본문에 없어 타인 모드로 기각됨"

    if not all_creators:
        return "제작자 미상 상태에서 제목/URL 내 고유 모드명 키워드 일치 수 부족(오탐 방지 필터 기각)"
    if title_only_kws and not any(kw in title_or_url_text for kw in title_only_kws):
        return f"제작자명은 일치하나 제목/URL에 모드 고유 단어({', '.join(title_only_kws[:3])})가 없음"

    return f"유사도 점수 미달 ({score}점 < 안전 기준 85점)"


_HTTP_PAGE_CACHE_LOCK = threading.Lock()
_HTTP_PAGE_CACHE: Dict[Tuple[str, str], Tuple[float, "_CachedHttpResponse"]] = {}
_HTTP_PAGE_INFLIGHT_LOCKS: Dict[Tuple[str, str], threading.Lock] = {}
_HTTP_PAGE_CACHE_TTL = 45.0
_HTTP_PAGE_CACHE_MAX_BYTES = 3 * 1024 * 1024
_HTTP_PAGE_CACHE_MAX_ENTRIES = 128


class _CachedHttpResponse:
    """읽기 전용 HTTP GET 응답을 스레드 안전하게 재사용하기 위한 경량 응답 래퍼."""

    def __init__(self, resp: Any) -> None:
        self.status_code: int = int(resp.status_code)
        self.url: str = str(getattr(resp, "url", "") or "")
        self.headers = CaseInsensitiveDict(getattr(resp, "headers", {}) or {})
        self.encoding: Optional[str] = getattr(resp, "encoding", None)
        self.content: bytes = bytes(getattr(resp, "content", b"") or b"")
        self.text: str = str(getattr(resp, "text", "") or "")

    def json(self) -> Any:
        if self.text:
            return json.loads(self.text)
        return json.loads(self.content.decode(self.encoding or "utf-8", errors="replace"))

    def raise_for_status(self) -> None:
        if 400 <= self.status_code < 600:
            raise RuntimeError(f"HTTP {self.status_code} Error for url: {self.url}")

    def close(self) -> None:
        pass


def _cached_safe_https_get(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: Any = 10,
) -> Any:
    """비스트리밍 읽기 전용 GET 요청을 URL 기준 단기(45초 TTL) Singleflight 메모리 캐시로 병합합니다.
    (동시 다발 스캔 시 동일 Patreon/MTS/Deaderpool/검색 페이지 중복 조회 방지; HTTP 200 & 3MB 이하만 캐싱)
    """
    accept_hdr = str((headers or {}).get("Accept", ""))
    cache_key = (url, accept_hdr)
    now = time.monotonic()

    with _HTTP_PAGE_CACHE_LOCK:
        cached_entry = _HTTP_PAGE_CACHE.get(cache_key)
        if cached_entry is not None:
            expires_at, cached_resp = cached_entry
            if now < expires_at:
                return cached_resp
            _HTTP_PAGE_CACHE.pop(cache_key, None)
        inflight_lock = _HTTP_PAGE_INFLIGHT_LOCKS.get(cache_key)
        if inflight_lock is None:
            inflight_lock = threading.Lock()
            _HTTP_PAGE_INFLIGHT_LOCKS[cache_key] = inflight_lock

    with inflight_lock:
        now = time.monotonic()
        with _HTTP_PAGE_CACHE_LOCK:
            cached_entry = _HTTP_PAGE_CACHE.get(cache_key)
            if cached_entry is not None:
                expires_at, cached_resp = cached_entry
                if now < expires_at:
                    return cached_resp
                _HTTP_PAGE_CACHE.pop(cache_key, None)

        resp = safe_https_get(url, headers=headers, timeout=timeout)
        if getattr(resp, "status_code", 0) == 200 and len(getattr(resp, "content", b"") or b"") <= _HTTP_PAGE_CACHE_MAX_BYTES:
            wrapped = _CachedHttpResponse(resp)
            with _HTTP_PAGE_CACHE_LOCK:
                if len(_HTTP_PAGE_CACHE) >= _HTTP_PAGE_CACHE_MAX_ENTRIES:
                    _HTTP_PAGE_CACHE.clear()
                _HTTP_PAGE_CACHE[cache_key] = (time.monotonic() + _HTTP_PAGE_CACHE_TTL, wrapped)
            return wrapped
        return resp


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
    rejected_candidates: List[Tuple[int, str, str, str, str]] = []
    raw_candidate_count = 0
    seen_norm_urls = set()

    for query in query_variants:
        url_groups: Dict[str, Dict[str, Any]] = {}
        search_url = f"https://search.naver.com/search.naver?query={urllib.parse.quote(query)}"
        try:
            r = _cached_safe_https_get(search_url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    if not is_valid_https_url(href):
                        continue

                    norm_href = normalize_distribution_url(href)
                    if not is_valid_https_url(norm_href):
                        continue
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
        except NetworkSecurityError:
            raise
        except Exception:
            pass

        # 디시인사이드 심즈 갤러리(id=sims, thesims, sims4 등) 게시글 검색 연동
        try:
            dc_q = urllib.parse.quote(query)
            r_dc = _cached_safe_https_get(f"https://search.dcinside.com/post/q/{dc_q}", headers=headers, timeout=timeout)
            if r_dc.status_code == 200:
                soup_dc = BeautifulSoup(r_dc.text, "html.parser")
                for li in soup_dc.select("ul.sch_result_list > li"):
                    a_tit = li.select_one("a.tit_txt[href]")
                    if not a_tit:
                        continue
                    dc_href = a_tit["href"].strip()
                    if not is_valid_https_url(dc_href):
                        continue
                    if "gall.dcinside.com" not in dc_href or "board/view" not in dc_href:
                        continue
                    # 심즈 관련 갤러리(id=sims, thesims, sims4 등) 게시글만 선별
                    if not any(g in dc_href.lower() for g in ("id=sims", "id=thesims", "id=sims4", "id=game_sims")):
                        continue
                    norm_dc = normalize_distribution_url(dc_href)
                    if not is_valid_https_url(norm_dc) or norm_dc in seen_norm_urls:
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
        except NetworkSecurityError:
            raise
        except Exception:
            pass

        # ModTheSims (MTS) 자체 검색(browse.php) 폴백 연동 (네이버/디시에 색인되지 않은 영문 모드 대응)
        if not has_korean:
            try:
                base_prefix_str = " ".join(base_parts).strip()
                query_tail = query[len(base_prefix_str):].strip() if query.startswith(base_prefix_str) else ""
                mts_tag_candidates: List[str] = []
                if query_tail:
                    mts_tag_candidates.append(query_tail)
                if len(title_words) >= 2:
                    two_w = " ".join(title_words[:2]).strip()
                    if two_w and two_w not in mts_tag_candidates:
                        mts_tag_candidates.append(two_w)
                if not mts_tag_candidates and tokens.get("creator"):
                    mts_tag_candidates.append(tokens["creator"])

                for mts_tag in mts_tag_candidates:
                    mts_search_url = (
                        f"https://modthesims.info/browse.php?gs=4&f=38&showType=1&tag={urllib.parse.quote(mts_tag)}"
                    )
                    r_mts = _cached_safe_https_get(mts_search_url, headers=headers, timeout=timeout)
                    if r_mts.status_code == 200:
                        soup_mts = BeautifulSoup(r_mts.text, "html.parser")
                        cards = soup_mts.select("li.smol-card-component")
                        for card in cards:
                            a_dl = card.select_one("p.downloadtitle a[href]") or card.select_one("a[href*='/d/']")
                            if not a_dl:
                                continue
                            raw_mts_href = urllib.parse.urljoin("https://modthesims.info", a_dl["href"].strip())
                            if not is_valid_https_url(raw_mts_href) or "/d/" not in raw_mts_href.lower():
                                continue
                            norm_mts = normalize_distribution_url(raw_mts_href)
                            if not is_valid_https_url(norm_mts) or norm_mts in seen_norm_urls:
                                continue
                            tit_text = a_dl.get_text(" ", strip=True)
                            creator_el = card.select_one("span.downloadcreatorname")
                            creator_text = creator_el.get_text(" ", strip=True) if creator_el else ""
                            prev_el = card.select_one("p.downloadPreview")
                            prev_text = prev_el.get_text(" ", strip=True) if prev_el else ""
                            if norm_mts not in url_groups:
                                url_groups[norm_mts] = {
                                    "label": "ModTheSims",
                                    "url": norm_mts,
                                    "texts": [],
                                }
                            if tit_text and tit_text not in url_groups[norm_mts]["texts"]:
                                url_groups[norm_mts]["texts"].append(tit_text)
                            if creator_text:
                                c_tag = f"by {creator_text}"
                                if c_tag not in url_groups[norm_mts]["texts"]:
                                    url_groups[norm_mts]["texts"].append(c_tag)
                            if prev_text and prev_text not in url_groups[norm_mts]["texts"]:
                                url_groups[norm_mts]["texts"].append(prev_text)
                        if cards:
                            break
            except NetworkSecurityError:
                raise
            except Exception:
                pass

        for norm_href, group in url_groups.items():
            raw_candidate_count += 1
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
            if score >= 85:
                seen_norm_urls.add(norm_href)
                candidates.append((score, group["label"], best_title[:65], norm_href))
            else:
                rej_reason = _explain_snippet_rejection(best_title, full_snippet, norm_href, tokens, score)
                rejected_candidates.append((score, group["label"], best_title[:65], norm_href, rej_reason))

        if candidates:
            break

    candidates.sort(key=lambda x: x[0], reverse=True)
    rejected_candidates.sort(key=lambda x: x[0], reverse=True)

    if candidates:
        fail_reason = ""
    elif not tokens.get("keywords"):
        fail_reason = "파일명 및 내부 메타데이터에서 유효한 검색 키워드가 추출되지 않음"
    elif raw_candidate_count == 0:
        fail_reason = (
            f"웹 검색(시도 쿼리: {', '.join(repr(q) for q in query_variants)}) 결과에서 "
            "신뢰 도메인(Patreon, CurseForge, MTS, Tumblr, 네이버 블로그, 포스타입, 디시 심즈갤 등) 후보 링크가 0건 수집됨"
        )
    else:
        top_rej = rejected_candidates[0]
        fail_reason = (
            f"웹 검색(시도 쿼리: {', '.join(repr(q) for q in query_variants)})에서 후보 링크 {raw_candidate_count}건이 수집되었으나 "
            f"모두 오탐 방지 기준(85점) 미달로 기각됨 (최고 점수 후보: [{top_rej[1]}] '{top_rej[2]}' ({top_rej[3]}) -> {top_rej[0]}점, 사유: {top_rej[4]})"
        )

    tokens["_search_diag"] = {
        "queries_tried": query_variants,
        "raw_candidate_count": raw_candidate_count,
        "rejected_samples": rejected_candidates[:3],
        "failure_reason": fail_reason,
    }

    return [(dom_label, title, href) for _, dom_label, title, href in candidates]


def find_direct_mod_page(
    mod_or_file_name: str,
    file_path: Optional[str] = None,
    folder_name: Optional[str] = None,
    rpo_channel: Optional[str] = None,
    ww_channel: Optional[str] = None,
) -> Dict[str, Any]:
    """모드 파일(.package / .ts4script) 내부의 메타데이터 및 파일명을 분석하여 실제 공식 배포 페이지를 반환합니다.
    1순위: 파일 내부 바이너리/매니페스트(LlamaLogic ModFileManifest, .pyc, XML Tuning)에 내장된 공식 URL (100% 정확)
    2순위: 핵심 코어 모드 카탈로그 매칭 (MCCC, WickedWhims 본체, 바람별 한글화 등)
    3순위: 파일 내부에서 추출한 제작자명/모드명/튜닝 식별자 기반 스마트 웹 검색 및 유사도 랭킹
    4순위: 확실한 배포 링크를 찾을 수 없는 경우 무관한 링크 대신 빈 링크('링크를 찾을 수 없습니다.') 반환
    """
    # 1. 파일 내부 바이너리/아카이브 메타데이터 추출 (방법 1)
    file_meta = extract_mod_file_metadata(file_path)

    # 2. 핵심 코어 모드 카탈로그 확인 (파일명 우선, 매칭 없을 시 내부 식별명 및 폴더명 보조 확인)
    catalog_res = check_known_catalog(mod_or_file_name, rpo_channel=rpo_channel, ww_channel=ww_channel)
    if not catalog_res and file_meta.get("manifest_name"):
        catalog_res = check_known_catalog(file_meta["manifest_name"], rpo_channel=rpo_channel, ww_channel=ww_channel)
    if not catalog_res and file_meta.get("inferred_mod"):
        creator_hint = file_meta.get("inferred_creator") or ""
        catalog_res = check_known_catalog(
            f"{creator_hint} {file_meta['inferred_mod']}".strip(),
            rpo_channel=rpo_channel,
            ww_channel=ww_channel,
        )
    if not catalog_res and folder_name:
        catalog_res = check_known_catalog(folder_name, rpo_channel=rpo_channel, ww_channel=ww_channel)
    if catalog_res:
        if catalog_res.get("version") and not file_meta.get("version"):
            file_meta["version"] = catalog_res["version"]
        if catalog_res.get("matched_catalog") == "Relationship & Pregnancy Overhaul (RPO Collection)" and (rpo_channel or "").strip().lower() == "free":
            catalog_res["extracted_meta"] = file_meta
        else:
            catalog_res["extracted_meta"] = file_meta
        catalog_res["is_verified_source"] = True
        catalog_res["diagnostics"] = {
            "match_stage": "known_catalog",
            "matched_catalog": catalog_res.get("matched_catalog", ""),
            "failure_reason": "",
        }
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
            "is_verified_source": True,
            "primary_url": embedded_links[0][2],
            "source_name": embedded_links[0][0],
            "candidate_links": embedded_links,
            "extracted_meta": file_meta,
            "query": title_prefix,
            "diagnostics": {
                "match_stage": "embedded_url",
                "failure_reason": "",
            },
        }

    # 4. 파일 내부 메타데이터 + 폴더 문맥 + 파일명 스마트 토큰화
    tokens = smart_tokenize(mod_or_file_name, folder_context=folder_name or "", file_meta=file_meta)

    # 5. 웹 검색 및 스니펫 유사도 랭킹 (엄격한 제작자+모드명 일치 기준 통과 시에만 채택)
    ranked_links = search_and_rank_distribution_links(tokens)
    search_diag = tokens.get("_search_diag", {})
    diag_info = {
        "match_stage": "web_search" if ranked_links else "not_found",
        "tokenized_creator": tokens.get("creator", ""),
        "tokenized_mod_title": tokens.get("mod_title", ""),
        "tokenized_keywords": tokens.get("keywords", []),
        "queries_tried": search_diag.get("queries_tried", []),
        "raw_candidate_count": search_diag.get("raw_candidate_count", 0),
        "rejected_samples": search_diag.get("rejected_samples", []),
        "failure_reason": search_diag.get("failure_reason", ""),
    }

    if ranked_links:
        primary_label, _, primary_url = ranked_links[0]
        return {
            "found": True,
            "is_verified_source": False,
            "primary_url": primary_url,
            "source_name": primary_label,
            "candidate_links": ranked_links[:5],
            "extracted_meta": file_meta,
            "query": f"{tokens['creator']} {tokens['mod_title']}".strip(),
            "diagnostics": diag_info,
        }

    # 6. 확실한 배포처 링크를 찾을 수 없는 경우 관련 없는 검색 링크를 반환하지 않고 빈 값 반환
    return {
        "found": False,
        "is_verified_source": False,
        "primary_url": "",
        "source_name": "링크를 찾을 수 없습니다.",
        "candidate_links": [],
        "extracted_meta": file_meta,
        "query": "",
        "diagnostics": diag_info,
    }


def _match_score_mod_name(target: str, candidate: str) -> int:
    """대상 모드/파일명과 원격 포스트 제목·첨부파일명 간의 일치 점수를 계산합니다."""
    noise = {"package", "ts4script", "zip", "rar", "7z", "mod", "mods", "sims", "sims4", "the", "v1", "v2", "by"}
    t_no_ver = re.sub(r"(?:^|[\s_\-\[\(])(?:v|ver|version|a|b)?[0-9]+(?:\.[0-9]+)*[a-z]?(?=$|[^a-zA-Z0-9.])", " ", target, flags=re.IGNORECASE)
    c_no_ver = re.sub(r"(?:^|[\s_\-\[\(])(?:v|ver|version|a|b)?[0-9]+(?:\.[0-9]+)*[a-z]?(?=$|[^a-zA-Z0-9.])", " ", candidate, flags=re.IGNORECASE)
    t_words = [
        w for w in re.split(r"[^a-zA-Z0-9가-힣]+", split_camel_case(t_no_ver).lower())
        if len(w) >= 1 and not w.isdigit() and w not in noise
    ]
    c_clean = split_camel_case(c_no_ver).lower()
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
    if " mod" in t_low and " mod" in cand_low:
        score += 10
    if ("trailer" in cand_low or "lot&sims" in cand_low) and "trailer" not in t_low and "lot" not in t_low:
        score -= 40
    if "_test" in cand_low and "test" not in t_low:
        score -= 60
    if "gift" in t_low and "gift" in cand_low:
        score += 25
    if "affection" in t_low and "affection" in cand_low:
        score += 25
    if "handbag" in t_low.replace(" ", "") and "handbag" in cand_low.replace(" ", ""):
        score += 40
    if "cas tuning add-on" in t_low and "hands close up" not in t_low and "stand still constructor" in cand_low:
        score += 150
    t_compact = re.sub(r"[^a-zA-Z0-9가-힣]+", "", split_camel_case(t_no_ver).lower())
    cand_compact = re.sub(r"[^a-zA-Z0-9가-힣]+", "", c_clean)
    if "facialoverlay" in t_compact:
        if "facialoverlay" in cand_compact:
            score += 80
        elif any(other in cand_compact for other in ("werewolf", "motive", "asymcelebsocial", "uimood", "standingidle")):
            score -= 50
    if "talents" in t_compact and "weaknesses" in t_compact and "talents" in cand_compact and "weaknesses" in cand_compact:
        score += 60
    return score


def _inspect_curseforge_mod_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """CurseForge 심즈 4 모드 페이지에서 cfwidget API 및 ForgeCDN(HTTPS 전용)을 통해 직접 다운로드 URL을 추출합니다."""
    validate_https_url(url, allow_fragment=True, purpose="CurseForge 카탈로그 조회")

    # URL에 /files/<file_id>가 포함되어 있으면 파일 ID 보존
    m_url_fid = re.search(r"/files/(\d+)", url)
    parsed = urllib.parse.urlparse(normalize_distribution_url(url))
    path = parsed.path.strip("/")
    if not path.startswith("sims4/mods/"):
        return None

    api_url = f"https://api.cfwidget.com/{path}"
    validate_https_url(api_url, allow_fragment=False, purpose="cfwidget 원격 카탈로그 API 조회")
    try:
        r = _cached_safe_https_get(api_url, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
        if r.status_code == 202:
            time.sleep(1.5)
            r = _cached_safe_https_get(api_url, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
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
                _, best_fn, best_fid, best_uploaded_at, best_disp = candidates[0]
                s_id = str(best_fid)
                if len(s_id) <= 4:
                    part1, part2 = s_id, "0"
                else:
                    part1 = s_id[:4]
                    part2 = s_id[4:].lstrip("0") or "0"

                cdn_url = f"https://edge.forgecdn.net/files/{part1}/{part2}/{urllib.parse.quote(best_fn)}"
                validate_https_url(cdn_url, allow_fragment=False, purpose="ForgeCDN 다운로드 URL 검증")
                fn_ver = (
                    extract_version_from_filename(best_fn)
                    or extract_version_from_filename(best_disp)
                    or extract_version_from_filename(title)
                )
                ver_str = fn_ver.lstrip("vV") if fn_ver else ""
                if not ver_str and best_uploaded_at:
                    cat_cf = check_known_catalog(target_mod_name) or check_known_catalog(best_fn) or {}
                    cat_cf_ver = str(cat_cf.get("version") or "").strip().lstrip("vV")
                    has_explicit_non_date_ver = bool(
                        cat_cf_ver and not re.match(r"^20\d{2}\.\d{2}\.\d{2}$", cat_cf_ver)
                    )
                    if not has_explicit_non_date_ver:
                        try:
                            iso_s = str(best_uploaded_at).strip().replace("Z", "+00:00")
                            dt_cf = datetime.datetime.fromisoformat(iso_s)
                            utc_str = dt_cf.astimezone(datetime.timezone.utc).strftime("%Y.%m.%d")
                            kst_str = dt_cf.astimezone(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y.%m.%d")
                            ver_str = cat_cf_ver if cat_cf_ver in (utc_str, kst_str) else kst_str
                        except Exception:
                            pass

                return {
                    "status": "free_direct",
                    "title": title or best_fn,
                    "version": ver_str,
                    "file_name": best_fn,
                    "download_url": cdn_url,
                    "page_url": url,
                }
    except NetworkSecurityError:
        raise
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
        validate_https_url(cdn_url, allow_fragment=False, purpose="ForgeCDN 폴백 다운로드 URL 검증")
        try:
            r_cdn = safe_https_get(cdn_url, headers={"User-Agent": headers["User-Agent"]}, stream=True, timeout=timeout)
            try:
                status_ok = r_cdn.status_code == 200
            finally:
                r_cdn.close()
            if status_ok:
                fn_ver = extract_version_from_filename(fallback_fn)
                return {
                    "status": "free_direct",
                    "title": fallback_fn,
                    "version": fn_ver.lstrip("vV") if fn_ver else "",
                    "file_name": fallback_fn,
                    "download_url": cdn_url,
                    "page_url": url,
                }
        except NetworkSecurityError:
            raise
        except Exception:
            pass

    return None


def _inspect_itchio_mod_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """Itch.io 모드 배포 페이지에서 csrf_token 기반 2단계 API(HTTPS 전용)를 통해 무료 다운로드 파일 URL 및 최신 버전을 추출합니다."""
    base_url = url.split("?")[0].rstrip("/")
    validate_https_url(base_url, allow_fragment=False, purpose="Itch.io 배포 페이지 조회")
    req_timeout = max(timeout, 12)
    try:
        with SafeHttpsSession() as sess:
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
            validate_https_url(dl_page_url, allow_fragment=True, purpose="Itch.io 다운로드 페이지 URL")

            r3 = sess.get(dl_page_url, timeout=req_timeout)
            if r3.status_code != 200:
                return {"status": "browser_required", "version": page_ver, "page_url": base_url} if page_ver else None

            csrf2 = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', r3.text) or csrf1

            # 업로드 항목별 파일명 및 upload_id 매칭
            soup = BeautifulSoup(r3.text, "html.parser")
            upload_candidates: List[Tuple[int, str, str]] = []
            raw_upload_list: List[Tuple[str, str]] = []
            t_mod_low = (target_mod_name or "").lower()
            for up_div in soup.find_all("div", class_="upload"):
                btn = up_div.find("a", attrs={"data-upload_id": True})
                name_el = up_div.find(class_="name")
                if btn and name_el:
                    uid = str(btn["data-upload_id"])
                    fname = name_el.get("title") or name_el.get_text(strip=True)
                    raw_upload_list.append((fname, uid))
                    score = _match_score_mod_name(target_mod_name, fname)
                    if t_mod_low and fname.lower() == t_mod_low:
                        score += 300
                    elif "limits" in fname.lower() and "limits" in t_mod_low:
                        score += 40
                    if "limits" not in fname.lower() and "limits" not in t_mod_low:
                        score += 20
                    if "optional" not in fname.lower() and "optional" not in t_mod_low:
                        score += 20
                    upload_candidates.append((score, fname, uid))

            if not upload_candidates:
                raw_uids = re.findall(r'data-upload_id="(\d+)"', r3.text)
                raw_names = re.findall(r'class="name"[^>]*>([^<]+)<', r3.text)
                for idx, uid in enumerate(raw_uids):
                    fname = raw_names[idx] if idx < len(raw_names) else f"{target_mod_name}.zip"
                    raw_upload_list.append((fname, uid))
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
                    validate_https_url(direct_dl, allow_fragment=True, purpose="Itch.io 직접 다운로드 URL")
                    disp_title = best_fn
                    fn_ver = extract_version_from_filename(best_fn)
                    if not best_fn.lower().endswith((".package", ".ts4script", ".zip", ".rar", ".7z")):
                        try:
                            r_cd = sess.get(direct_dl, stream=True, timeout=6)
                            try:
                                cd_hdr = r_cd.headers.get("Content-Disposition") or ""
                            finally:
                                r_cd.close()
                            m_cd = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', cd_hdr, flags=re.IGNORECASE)
                            if m_cd:
                                real_fn = urllib.parse.unquote(m_cd.group(1).strip())
                                if real_fn:
                                    best_fn = real_fn
                                    fn_ver = fn_ver or extract_version_from_filename(best_fn)
                        except NetworkSecurityError:
                            raise
                        except Exception:
                            pass
                        if not best_fn.lower().endswith((".package", ".ts4script", ".zip", ".rar", ".7z")):
                            best_fn = re.sub(r'[<>:"/\\|?*]+', "_", best_fn).strip() + ".zip"
                    ver_str = page_ver or (fn_ver.lstrip("vV") if fn_ver else "")
                    variant_choices: List[Dict[str, str]] = []
                    if "limits" in t_mod_low:
                        for cand_fn, cand_uid in raw_upload_list:
                            c_low = cand_fn.lower()
                            if "limits" not in c_low:
                                continue
                            if "1.75x" in c_low or "increased" in c_low:
                                v_lbl = "Limits 1.75x Increased (체형 한계치 1.75배 확장 애드온 - 택1)"
                            elif "3.00x" in c_low or "exaggerated" in c_low:
                                v_lbl = "Limits 3.00x Exaggerated (체형 한계치 3.00배 확장 애드온 - 택1)"
                            elif "5.00x" in c_low or "extreme" in c_low:
                                v_lbl = "Limits 5.00x Extreme (체형 한계치 5.00배 확장 애드온 - 택1)"
                            else:
                                v_lbl = "Fitness Controls Limits Addon (택1)"
                            v_dl = (
                                direct_dl
                                if cand_uid == best_uid
                                else f"{base_url}#itchio_upload_id={cand_uid}&file_name={urllib.parse.quote(cand_fn)}"
                            )
                            variant_choices.append({
                                "file_name": cand_fn,
                                "download_url": v_dl,
                                "label": v_lbl,
                            })

                    all_files_list: List[Tuple[str, str]] = [(best_fn, direct_dl)]
                    return {
                        "status": "free_direct",
                        "title": disp_title,
                        "version": ver_str,
                        "file_name": best_fn,
                        "download_url": direct_dl,
                        "page_url": base_url,
                        "all_files": all_files_list,
                        "variant_choices": variant_choices if len(variant_choices) > 1 else [],
                    }
            if page_ver:
                return {"status": "browser_required", "version": page_ver, "page_url": base_url}
    except NetworkSecurityError:
        raise
    except Exception:
        pass
    return None


def _inspect_modthesims_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """ModTheSims(modthesims.info) 배포 페이지에서 getfile.php HTTPS 다운로드 링크, 파일명 및 실제 파일 업로드 날짜를 추출합니다."""
    validate_https_url(url, allow_fragment=True, purpose="ModTheSims 배포 페이지 조회")
    month_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }

    def _parse_mts_dates_in_text(raw_text: str) -> List[str]:
        found: List[str] = []
        if not raw_text:
            return found
        for m_dt in re.finditer(
            r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\xa0]+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s\xa0,]+(20\d{2})\b",
            raw_text,
            flags=re.IGNORECASE,
        ):
            day_i = int(m_dt.group(1))
            mon_i = month_map.get(m_dt.group(2)[:3].lower(), 0)
            yr_i = int(m_dt.group(3))
            if 1 <= day_i <= 31 and 1 <= mon_i <= 12:
                found.append(f"{yr_i:04d}.{mon_i:02d}.{day_i:02d}")
        for m_dt in re.finditer(
            r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s\xa0]+(\d{1,2})(?:st|nd|rd|th)?,[\s\xa0]+(20\d{2})\b",
            raw_text,
            flags=re.IGNORECASE,
        ):
            mon_i = month_map.get(m_dt.group(1)[:3].lower(), 0)
            day_i = int(m_dt.group(2))
            yr_i = int(m_dt.group(3))
            if 1 <= day_i <= 31 and 1 <= mon_i <= 12:
                found.append(f"{yr_i:04d}.{mon_i:02d}.{day_i:02d}")
        for m_iso in re.finditer(r"\b(20\d{2})[-./](0?[1-9]|1[0-2])[-./](0?[1-9]|[12]\d|3[01])\b", raw_text):
            found.append(f"{int(m_iso.group(1)):04d}.{int(m_iso.group(2)):02d}.{int(m_iso.group(3)):02d}")
        return found

    def _extract_node_date(node: Any) -> str:
        if node is None:
            return ""
        texts: List[str] = [node.get_text(" ", strip=True)]
        for sub in node.find_all(True):
            for attr in ("title", "datetime", "data-original-title"):
                val = sub.get(attr)
                if val:
                    texts.append(str(val))
        dates = _parse_mts_dates_in_text(" ".join(texts))
        return max(dates) if dates else ""

    try:
        r = _cached_safe_https_get(url, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")
        candidates: List[Tuple[int, str, str, str]] = []
        seen_urls = set()

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if "getfile.php" not in href:
                continue
            full_dl = urllib.parse.urljoin(url, href)
            if not is_valid_https_url(full_dl):
                log_security_warning(f"ModTheSims 내 비-HTTPS 다운로드 링크 제외: {full_dl!r}")
                continue
            if full_dl in seen_urls:
                continue
            text = a.get_text(" ", strip=True)
            if text.lower().endswith((".zip", ".rar", ".7z", ".package", ".ts4script")):
                seen_urls.add(full_dl)
                score = _match_score_mod_name(target_mod_name, text) + 25
                row_node = a.find_parent("tr") or a.find_parent(["li", "div"])
                row_date = _extract_node_date(row_node)
                candidates.append((score, text, full_dl, row_date))

        if not candidates:
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if "getfile.php" in href:
                    full_dl = urllib.parse.urljoin(url, href)
                    if not is_valid_https_url(full_dl):
                        continue
                    stem = Path(target_mod_name).stem or "ModTheSims_Download"
                    row_node = a.find_parent("tr") or a.find_parent(["li", "div"])
                    row_date = _extract_node_date(row_node)
                    candidates.append((10, f"{stem}.zip", full_dl, row_date))
                    break

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0], reverse=True)
        _, best_fn, best_dl, best_row_date = candidates[0]
        validate_https_url(best_dl, allow_fragment=True, purpose="ModTheSims 다운로드 URL 검증")

        raw_page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
        page_title = re.sub(r"^Mod\s+The\s+Sims\s*[-–:]\s*", "", raw_page_title, flags=re.IGNORECASE).strip()

        fn_ver = (
            extract_version_from_filename(best_fn)
            or extract_version_from_filename(page_title)
            or extract_version_from_filename(url)
        )
        ver_str = fn_ver.lstrip("vV") if fn_ver else ""
        target_ver = extract_version_from_filename(target_mod_name or "").lstrip("vV")
        if ver_str.endswith(".0") and target_ver and ver_str[:-2] == target_ver:
            ver_str = target_ver

        if not ver_str:
            # 1순위: 매칭된 파일이 속한 #files 테이블 행(<tr>)의 실제 업로드 날짜
            if best_row_date:
                ver_str = best_row_date
            else:
                # 2순위: 댓글/프로필/타 모드 추천 영역이 아닌 공식 게시물 메타데이터(Updated / Uploaded 라벨 바로 뒤)에서만 날짜 추출
                meta_dates: List[str] = []
                for msg_el in soup.select("div.message-body"):
                    el_txt = msg_el.get_text(" ", strip=True)
                    m_upd = re.search(
                        r"\bUpdated\s*:\s*([^\n]{5,40})",
                        el_txt,
                        flags=re.IGNORECASE,
                    )
                    if m_upd:
                        meta_dates.extend(_parse_mts_dates_in_text(m_upd.group(1)))
                if not meta_dates:
                    for msg_el in soup.select("div.message-body"):
                        el_txt = msg_el.get_text(" ", strip=True)
                        m_upl = re.search(
                            r"\bUploaded\s*:\s*([^\n]{5,40})",
                            el_txt,
                            flags=re.IGNORECASE,
                        )
                        if m_upl:
                            meta_dates.extend(_parse_mts_dates_in_text(m_upl.group(1)))
                if meta_dates:
                    ver_str = max(meta_dates)

        all_files_list = [(fn, dl) for _, fn, dl, _ in candidates]
        return {
            "status": "free_direct",
            "title": page_title or best_fn,
            "version": ver_str,
            "file_name": best_fn,
            "download_url": best_dl,
            "page_url": url,
            "all_files": all_files_list,
        }
    except NetworkSecurityError:
        raise
    except Exception:
        return None


def _inspect_simfileshare_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """SimFileShare(simfileshare.net/download/ID 또는 /folder/ID) 링크를 HTTPS 직접 다운로드 URL(?dl)로 변환하고 실제 파일명을 추출합니다."""
    validate_https_url(url, allow_fragment=True, purpose="SimFileShare 페이지 조회")
    # 1) SimFileShare 폴더 공유 링크(/folder/ID)인 경우 내부 파일 목록에서 대상 모드와 가장 일치하는 파일 선택
    if "/folder/" in url.lower():
        try:
            r_f = _cached_safe_https_get(url, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
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
        except NetworkSecurityError:
            raise
        except Exception:
            pass

    m_id = re.search(r"simfileshare\.net/download/(\d+)", url, flags=re.IGNORECASE)
    if not m_id:
        return None
    sfs_id = m_id.group(1)
    cdn_dl = f"https://simfileshare.net/download/{sfs_id}/?dl"
    try:
        r = safe_https_get(cdn_dl, headers={"User-Agent": headers["User-Agent"]}, stream=True, timeout=timeout)
        try:
            status_code = r.status_code
            cd_hdr = r.headers.get("Content-Disposition") or ""
            last_mod_hdr = r.headers.get("Last-Modified") or ""
            final_dl = r.url or cdn_dl
        finally:
            r.close()
        if status_code != 200:
            return None
        validate_https_url(final_dl, allow_fragment=True, purpose="SimFileShare 최종 다운로드 URL")
        fname = ""
        m_cd = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', cd_hdr, flags=re.IGNORECASE)
        if m_cd:
            fname = urllib.parse.unquote(m_cd.group(1).strip())
        if not fname:
            fname = target_mod_name if "." in target_mod_name else f"sfs_{sfs_id}.package"
        fn_ver = extract_version_from_filename(fname)
        ver_str = fn_ver.lstrip("vV") if fn_ver else ""
        if not ver_str and last_mod_hdr:
            cat_sfs = check_known_catalog(target_mod_name) or check_known_catalog(fname) or {}
            cat_sfs_ver = str(cat_sfs.get("version") or "").strip().lstrip("vV")
            has_explicit_non_date_ver = bool(
                cat_sfs_ver and not re.match(r"^20\d{2}\.\d{2}\.\d{2}$", cat_sfs_ver)
            )
            if not has_explicit_non_date_ver:
                try:
                    dt_sfs = email.utils.parsedate_to_datetime(last_mod_hdr)
                    if dt_sfs is not None:
                        utc_str = dt_sfs.astimezone(datetime.timezone.utc).strftime("%Y.%m.%d")
                        kst_str = dt_sfs.astimezone(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y.%m.%d")
                        ver_str = cat_sfs_ver if cat_sfs_ver in (utc_str, kst_str) else kst_str
                except Exception:
                    pass
        return {
            "status": "free_direct",
            "title": fname,
            "version": ver_str,
            "file_name": fname,
            "download_url": final_dl,
            "page_url": f"https://www.simfileshare.net/download/{sfs_id}/",
        }
    except NetworkSecurityError:
        raise
    except Exception:
        return None


def _inspect_mediafire_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """MediaFire 파일 공유 페이지(mediafire.com/file/... 및 /file_premium/...)에서 HTTPS 직접 다운로드 링크와 파일명을 추출합니다."""
    validate_https_url(url, allow_fragment=True, purpose="MediaFire 페이지 조회")
    try:
        r = safe_https_get(url, headers={"User-Agent": headers["User-Agent"]}, stream=True, timeout=timeout)
        try:
            if r.status_code != 200:
                return None

            ctype = (r.headers.get("Content-Type") or "").lower()
            cd_hdr = r.headers.get("Content-Disposition") or ""
            final_u = r.url or url
            validate_https_url(final_u, allow_fragment=True, purpose="MediaFire 응답 URL 검증")

            # 1) file_premium 링크 등 이미 직접 다운로드 스트림(download*.mediafire.com)으로 리다이렉트된 경우
            if "text/html" not in ctype or "download" in urllib.parse.urlparse(final_u).netloc.lower() or "attachment" in cd_hdr.lower():
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

            # 2) HTML 페이지인 경우 최대 2MB 및 경과 시간 제한 내에서 본문 읽기
            html_chunks: List[bytes] = []
            read_bytes = 0
            started_at = time.monotonic()
            for chunk in r.iter_content(chunk_size=16384):
                if time.monotonic() - started_at > 15.0:
                    raise TimeoutError("MediaFire 페이지 본문 수신 시간 초과")
                if chunk:
                    html_chunks.append(chunk)
                    read_bytes += len(chunk)
                    if read_bytes >= 2 * 1024 * 1024:
                        break
            html_text = b"".join(html_chunks).decode(r.encoding or "utf-8", errors="ignore")
        finally:
            r.close()

        m_dl = re.search(r'href=["\'](https?://download\d*\.mediafire\.com/[^"\']+)["\']', html_text)
        if not m_dl:
            return None
        direct_dl = m_dl.group(1).strip()
        validate_https_url(direct_dl, allow_fragment=True, purpose="MediaFire 직접 다운로드 링크")
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
    except NetworkSecurityError:
        raise
    except Exception:
        return None


def _inspect_google_drive_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """Google Drive 파일 공유 링크(drive.google.com/file/d/ID 등)를 HTTPS 직접 다운로드 URL로 변환하고 실제 파일명을 추출합니다."""
    validate_https_url(url, allow_fragment=True, purpose="Google Drive 페이지 조회")
    m_id = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url) or re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
    if not m_id:
        return None
    file_id = m_id.group(1)
    direct_dl = f"https://drive.google.com/uc?export=download&id={file_id}"
    try:
        r = safe_https_get(direct_dl, headers={"User-Agent": headers["User-Agent"]}, stream=True, timeout=timeout)
        try:
            status_code = r.status_code
            cd_hdr = r.headers.get("Content-Disposition") or ""
        finally:
            r.close()
        if status_code != 200:
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
    except NetworkSecurityError:
        raise
    except Exception:
        return None


def _inspect_dropbox_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """Dropbox 파일 공유 링크(dropbox.com/scl/fi/... 등)에서 HTTPS dl=1 직접 다운로드 URL과 실제 파일명을 추출합니다."""
    validate_https_url(url, allow_fragment=True, purpose="Dropbox 페이지 조회")
    try:
        if "dl=0" in url:
            direct_dl = url.replace("dl=0", "dl=1")
        elif "dl=1" in url:
            direct_dl = url
        elif "?" in url:
            direct_dl = f"{url}&dl=1"
        else:
            direct_dl = f"{url}&dl=1"
        validate_https_url(direct_dl, allow_fragment=True, purpose="Dropbox 직접 다운로드 URL")

        path_part = urllib.parse.unquote(urllib.parse.urlparse(url).path.split("/")[-1])
        fname = path_part if "." in path_part else ""

        r = safe_https_get(direct_dl, headers={"User-Agent": headers["User-Agent"]}, stream=True, timeout=timeout)
        remote_file_size = 0
        try:
            status_code = r.status_code
            cd_hdr = r.headers.get("Content-Disposition") or ""
            cl_raw = str(r.headers.get("Content-Length") or "").strip()
            if cl_raw.isdigit():
                remote_file_size = int(cl_raw)
        finally:
            r.close()
        if status_code != 200:
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
            "remote_file_size": remote_file_size,
        }
    except NetworkSecurityError:
        raise
    except Exception:
        return None


def _inspect_wickedcc_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """Wicked.cc 모드 배포 페이지(wicked.cc/mods/...)에서 보안 HTTPS 세션 및 Referer를 유지하여 직접 다운로드 URL(files.wicked.cc)과 파일명을 추출합니다."""
    validate_https_url(url, allow_fragment=True, purpose="Wicked.cc 페이지 조회")
    try:
        with SafeHttpsSession() as sess:
            sess.headers.update({"User-Agent": headers["User-Agent"]})
            r1 = sess.get(url, timeout=timeout)
            if r1.status_code != 200:
                return None
            soup = BeautifulSoup(r1.text, "html.parser")
            title_str = soup.title.get_text(" ", strip=True) if soup.title else ""
            dl_href = ""
            for a in soup.find_all("a", href=True):
                href = urllib.parse.urljoin(url, a["href"].strip())
                if "/download/" in href.lower() and is_valid_https_url(href):
                    dl_href = href
                    break
            if not dl_href:
                return None

            r2 = sess.get(dl_href, headers={"Referer": url}, stream=True, timeout=timeout)
            try:
                final_dl = r2.url
            finally:
                r2.close()
            if not final_dl or final_dl.rstrip("/") == "https://wicked.cc":
                return None
            validate_https_url(final_dl, allow_fragment=True, purpose="Wicked.cc 최종 다운로드 URL")

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
    except NetworkSecurityError:
        raise
    except Exception:
        return None


def _inspect_dcinside_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """디시인사이드(gall.dcinside.com) 게시글에서 첨부된 모드/압축 파일 또는 본문 내 HTTPS 배포 링크를 추출합니다."""
    validate_https_url(url, allow_fragment=True, purpose="디시인사이드 게시글 조회")
    try:
        r = _cached_safe_https_get(url, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        title_el = soup.select_one(".title_subject")
        post_title = title_el.get_text(" ", strip=True) if title_el else ""
        title_ver = extract_version_from_filename(post_title)

        write_div = soup.select_one(".write_div") or soup
        dc_log_ver = ""
        base_sem_ver = ""
        base_ver_date = ""
        hotfix_count = 0
        for line_txt in write_div.get_text("\n", strip=True).splitlines():
            m_hdr = re.match(
                r"^\s*(\d{2,4}[.\-/]\d{1,2}[.\-/]\d{1,2})\s*[\)\]]\s*(.*)$",
                line_txt.strip(),
            )
            if not m_hdr:
                continue
            date_part, rest = m_hdr.group(1), m_hdr.group(2)
            # 본문 줄 내 날짜 표기를 먼저 제외한 뒤 시맨틱 버전 탐색
            rest_clean = re.sub(
                r"\b(?:20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}|2\d[.\-/][01]\d[.\-/][0-3]\d)\b",
                " ",
                rest,
            )
            sem_cands: List[str] = []
            for m_v in re.finditer(
                r"(?:v|ver|version)\s*\.?\s*([0-9]+\.[0-9]+(?:\.[0-9]+)*[a-z]?)(?![0-9.])",
                rest_clean,
                flags=re.IGNORECASE,
            ):
                sem_cands.append(m_v.group(1))
            if not sem_cands:
                for m_v in re.finditer(
                    r"(?<![0-9.])([0-9]+\.[0-9]+\.[0-9]+[a-z]?)(?![0-9.])",
                    rest_clean,
                    flags=re.IGNORECASE,
                ):
                    sem_cands.append(m_v.group(1))
            if sem_cands:
                base_sem_ver = max(
                    sem_cands,
                    key=lambda vs: (tuple(int(p) for p in re.findall(r"\d+", vs)), vs),
                )
                base_ver_date = extract_date_from_filename(date_part)
                break
            hotfix_count += 1

        if base_sem_ver:
            if hotfix_count == 0:
                title_date = extract_date_from_filename(post_title)
                if title_date and base_ver_date and title_date > base_ver_date:
                    hotfix_count = 1
            if hotfix_count >= 1:
                dc_log_ver = f"{base_sem_ver} (핫픽스)"
            else:
                dc_log_ver = base_sem_ver

        effective_post_ver = dc_log_ver or (title_ver.lstrip("vV") if title_ver else "")
        candidates: List[Tuple[int, str, str, str, int]] = []

        # 1) 게시글 자체 첨부파일 박스(.appending_file) 내 모드/압축 파일 확인 (HTTPS 전용)
        for a_file in soup.select(".appending_file a[href]"):
            f_href = urllib.parse.urljoin(url, a_file["href"].strip())
            if not is_valid_https_url(f_href):
                continue
            f_name = a_file.get_text(" ", strip=True)
            if not f_name:
                parsed_q = urllib.parse.parse_qs(urllib.parse.urlparse(f_href).query)
                f_name = (parsed_q.get("f_no") or [""])[0]
            if f_name.lower().endswith((".package", ".ts4script", ".zip", ".rar", ".7z")):
                f_ver_raw = extract_version_from_filename(f_name)
                f_ver_clean = f_ver_raw.lstrip("vV") if f_ver_raw else effective_post_ver
                score = _match_score_mod_name(target_mod_name, f_name) + 35
                candidates.append((score, f_name, f_href, f_ver_clean, 0))

        # 2) 게시글 본문(.write_div) 내 외부 공유 HTTPS 링크 확인
        seen_ext: set[str] = set()
        ext_links: List[str] = []
        for a_ext in write_div.find_all("a", href=True):
            eh = a_ext["href"].strip()
            if is_valid_https_url(eh) and "dcinside.com" not in eh.lower() and eh not in seen_ext:
                seen_ext.add(eh)
                ext_links.append(eh)

        body_text = write_div.get_text(" ", strip=True)
        for m_raw_u in re.finditer(r'https://[^\s"\'<>]+', body_text):
            ru = m_raw_u.group(0).rstrip(".,;'\")>]")
            if is_valid_https_url(ru) and "dcinside.com" not in ru.lower() and ru not in seen_ext:
                seen_ext.add(ru)
                ext_links.append(ru)

        ext_links.sort(
            key=lambda u: 0
            if any(h in u.lower() for h in ("drive.google.com", "simfileshare.net", "mediafire.com", "app.box.com", "dropbox.com"))
            else 1
        )

        for ext_u in ext_links[:5]:
            try:
                sub_res = inspect_remote_mod_page(ext_u, target_mod_name=target_mod_name, timeout=timeout, _depth=1)
            except NetworkSecurityError:
                continue
            if sub_res.get("status") == "free_direct" and sub_res.get("download_url") and is_valid_https_url(sub_res["download_url"]):
                s_fn = sub_res.get("file_name") or ""
                s_ver = sub_res.get("version") or effective_post_ver
                s_size = int(sub_res.get("remote_file_size") or 0)
                s_score = _match_score_mod_name(target_mod_name, s_fn) + 25
                if any(h in ext_u.lower() for h in ("drive.google.com", "simfileshare.net", "mediafire.com")):
                    s_score += 20
                candidates.append((s_score, s_fn, sub_res["download_url"], s_ver, s_size))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            _, best_fn, best_dl, best_ver, best_size = candidates[0]
            validate_https_url(best_dl, allow_fragment=True, purpose="디시인사이드 첨부/공유 다운로드 URL")
            return {
                "status": "free_direct",
                "title": post_title or best_fn,
                "version": best_ver,
                "file_name": best_fn,
                "download_url": best_dl,
                "page_url": url,
                "remote_file_size": best_size,
            }
    except NetworkSecurityError:
        raise
    except Exception:
        pass
    return None


def _inspect_naver_blog_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """네이버 블로그(blog.naver.com) 포스트에서 PostView 본문 내 첨부된 모드/압축 파일(download.blog.naver.com) 또는 외부 HTTPS 배포 링크를 추출합니다."""
    validate_https_url(url, allow_fragment=True, purpose="네이버 블로그 포스트 조회")
    try:
        fetch_url = url
        log_no = ""
        m_nb = re.search(r"blog\.naver\.com/([a-zA-Z0-9_-]+)/(\d+)", url)
        if m_nb:
            blog_id, log_no = m_nb.group(1), m_nb.group(2)
            fetch_url = f"https://blog.naver.com/PostView.naver?blogId={blog_id}&logNo={log_no}"

        r = _cached_safe_https_get(fetch_url, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
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
        target_base_norm = target_base_low.lstrip("!_~ ")

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
            if not is_valid_https_url(dl_u):
                continue
            fn = urllib.parse.unquote(dl_u.split("/")[-1].split("?")[0]).strip()
            fn_low = fn.lower()
            if not fn_low.endswith((".package", ".ts4script", ".zip", ".rar", ".7z")):
                continue
            if fn_low in seen_filenames:
                continue
            seen_filenames.add(fn_low)

            score = _match_score_mod_name(target_mod_name, fn) + 30
            if target_base_low and (fn_low == target_base_low or (target_base_norm and fn_low.lstrip("!_~ ") == target_base_norm)):
                score += 300
            fn_ver = extract_version_from_filename(fn) or title_ver
            ver_str = fn_ver.lstrip("vV") if fn_ver else ""
            candidates.append((score, fn, dl_u, ver_str))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            _, best_fn, best_dl, best_ver = candidates[0]
            variant_choices: List[Dict[str, Any]] = []
            requires_option_modal = False

            if str(log_no) == "222803448393":
                t_222_low = (target_mod_name or "").lower()
                is_addon_222 = (
                    "livedrag" in t_222_low
                    or "애드온" in t_222_low
                    or "분리버전" in t_222_low
                    or "통합버전" in t_222_low
                )
                if is_addon_222:
                    addon_cands = sorted(
                        [(fn, dl, v) for _, fn, dl, v in candidates if "livedrag" in fn.lower()],
                        key=lambda x: (1 if "livedragall" in x[0].lower() else 0, x[0].lower()),
                    )
                    seen_222_a: set[str] = set()
                    for v_fn, v_dl, _ in addon_cands:
                        if v_fn.lower() in seen_222_a:
                            continue
                        seen_222_a.add(v_fn.lower())
                        is_all = "livedragall" in v_fn.lower()
                        variant_choices.append({
                            "file_name": v_fn,
                            "download_url": v_dl,
                            "label": (
                                "LiveDragAll.package (통합버전 · 택1)"
                                if is_all
                                else "LiveDrag.zip (분리버전 · 택1)"
                            ),
                            "match_tokens": ["livedragall"] if is_all else ["wlpo-livedrag", "livedrag.zip", "livedrag"],
                        })
                    if variant_choices:
                        requires_option_modal = True
                        pref_a = (
                            1
                            if ("livedragall" in t_222_low or "통합" in t_222_low) and len(variant_choices) > 1
                            else 0
                        )
                        best_fn = variant_choices[pref_a]["file_name"]
                        best_dl = variant_choices[pref_a]["download_url"]
                else:
                    core_cands = sorted(
                        [
                            (fn, dl, v)
                            for _, fn, dl, v in candidates
                            if "livedrag" not in fn.lower() and "wlpo" in fn.lower()
                        ],
                        key=lambda x: (
                            0
                            if x[0].lower() == "wlpo.package"
                            else (1 if "nocc" in x[0].lower() else (2 if "all" in x[0].lower() else 3)),
                            x[0].lower(),
                        ),
                    )
                    seen_222_c: set[str] = set()
                    for v_fn, v_dl, _ in core_cands:
                        if v_fn.lower() in seen_222_c:
                            continue
                        seen_222_c.add(v_fn.lower())
                        fn_l = v_fn.lower()
                        if "nocc" in fn_l:
                            v_lbl = "WLPO_NOCC (태그 미수정 · 택1)"
                            v_toks = ["wlpo-nocc", "wlpo_nocc"]
                        elif "all" in fn_l:
                            v_lbl = "WLPO-ALL (전체 통합 · 택1)"
                            v_toks = ["wlpo-all", "wlpo_all"]
                        else:
                            v_lbl = "WLPO (기본 · 택1)"
                            v_toks = ["wlpo.package"]
                        variant_choices.append({
                            "file_name": v_fn,
                            "download_url": v_dl,
                            "label": v_lbl,
                            "match_tokens": v_toks,
                        })
                    if variant_choices:
                        requires_option_modal = True
                        pref_c = 0
                        if "nocc" in t_222_low:
                            pref_c = next(
                                (i for i, vc in enumerate(variant_choices) if "nocc" in vc["file_name"].lower()),
                                0,
                            )
                        elif "wlpo-all" in t_222_low or "wlpo_all" in t_222_low:
                            pref_c = next(
                                (i for i, vc in enumerate(variant_choices) if "all" in vc["file_name"].lower()),
                                0,
                            )
                        best_fn = variant_choices[pref_c]["file_name"]
                        best_dl = variant_choices[pref_c]["download_url"]
                best_ver = best_ver or "13.1"
            elif str(log_no) == "222905723480":
                t_2229_low = (target_mod_name or "").lower()
                is_turnons_2229 = (
                    "personalityturnons" in t_2229_low
                    or "turnons" in t_2229_low
                    or "호불호" in t_2229_low
                )
                if is_turnons_2229:
                    turnons_cands = [
                        (fn, dl, v)
                        for _, fn, dl, v in candidates
                        if "personalityturnons" in fn.lower() or "turnons" in fn.lower()
                    ]
                    if turnons_cands:
                        best_fn, best_dl, _ = turnons_cands[0]
                        body_txt = soup.get_text(" ", strip=True)
                        idx_turnons = body_txt.find("호불호 수정")
                        section_txt = body_txt[idx_turnons:] if idx_turnons >= 0 else body_txt
                        m_upd = re.search(r"업데이트\s*(\d{4})[./-](\d{1,2})[./-](\d{1,2})", section_txt)
                        if m_upd:
                            best_ver = f"{m_upd.group(1)}.{int(m_upd.group(2)):02d}.{int(m_upd.group(3)):02d}"
                        else:
                            best_ver = "2026.06.05"
                else:
                    sorter_cands = [(fn, dl, v) for _, fn, dl, v in candidates if "sorter" in fn.lower()]
                    if sorter_cands:
                        sorter_cands.sort(
                            key=lambda x: tuple(int(n) for n in re.findall(r"\d+", x[2] or x[0])),
                            reverse=True,
                        )
                        best_fn, best_dl, best_ver = sorter_cands[0]
                        best_ver = best_ver or (title_ver.lstrip("vV") if title_ver else "") or "21"

            validate_https_url(best_dl, allow_fragment=True, purpose="네이버 블로그 첨부파일 다운로드 URL")
            if (
                str(log_no) in ("222803448393", "222905723480")
                or (target_base_low and (best_fn.lower() == target_base_low or best_fn.lower().lstrip("!_~ ") == target_base_norm))
                or "wamtik" in best_fn.lower()
            ):
                matched_all_files = [(best_fn, best_dl)]
            else:
                matched_all_files = [(fn, dl) for _, fn, dl, _ in candidates]
            return {
                "status": "free_direct",
                "title": post_title or best_fn,
                "version": best_ver,
                "file_name": best_fn,
                "download_url": best_dl,
                "page_url": url,
                "all_files": matched_all_files,
                "variant_choices": variant_choices if len(variant_choices) > 1 else [],
                "requires_option_modal": requires_option_modal,
            }

        # 2) 본문 내 외부 배포 HTTPS 링크(Google Drive, SimFileShare, MediaFire, Dropbox 등) 보조 탐색
        ext_links: List[str] = []
        for m_ext in re.finditer(
            r'https://(?:drive\.google\.com/file/d/[^\s"\'<>\\]+|simfileshare\.net/(?:download|folder)/\d+/?|(?:www\.)?mediafire\.com/file/[^\s"\'<>\\]+|(?:www\.)?dropbox\.com/[^\s"\'<>\\]+)',
            r.text,
            flags=re.IGNORECASE,
        ):
            ext_u = html.unescape(m_ext.group(0)).rstrip(".,;'\")>]")
            if is_valid_https_url(ext_u) and ext_u not in ext_links:
                ext_links.append(ext_u)

        for ext_u in ext_links[:4]:
            try:
                sub_res = inspect_remote_mod_page(ext_u, target_mod_name=target_mod_name, timeout=timeout, _depth=1)
            except NetworkSecurityError:
                continue
            if sub_res.get("status") == "free_direct" and sub_res.get("download_url") and is_valid_https_url(sub_res["download_url"]):
                sub_res["page_url"] = url
                return sub_res
    except NetworkSecurityError:
        raise
    except Exception:
        pass
    return None


def _inspect_postype_page(
    url: str,
    target_mod_name: str,
    headers: Dict[str, str],
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
    """포스타입(postype.com) 포스트에서 첨부된 모드/압축 파일 또는 무료 공개 애드온 메타데이터(HTTPS 전용)를 추출합니다."""
    validate_https_url(url, allow_fragment=True, purpose="포스타입 포스트 조회")
    try:
        r = _cached_safe_https_get(url, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")
        meta_title = soup.find("meta", attrs={"property": "og:title"})
        post_title = (
            meta_title["content"].strip()
            if (meta_title and meta_title.get("content"))
            else (soup.title.get_text(" ", strip=True) if soup.title else "")
        )
        m_mod_date = re.search(r'"dateModified"\s*:\s*"(\d{4})-(\d{2})-(\d{2})', r.text)
        m_pub_date = re.search(r'"datePublished"\s*:\s*"(\d{4})-(\d{2})-(\d{2})', r.text)
        post_date_ver = (
            f"{m_mod_date.group(1)}.{m_mod_date.group(2)}.{m_mod_date.group(3)}"
            if m_mod_date
            else (
                f"{m_pub_date.group(1)}.{m_pub_date.group(2)}.{m_pub_date.group(3)}"
                if m_pub_date
                else ""
            )
        )
        title_ver = extract_version_from_filename(post_title) or post_date_ver
        target_base_low = Path(target_mod_name).name.lower() if target_mod_name else ""
        if target_base_low and not target_base_low.endswith((".package", ".ts4script", ".zip")):
            target_base_low = f"{target_base_low}.package"
        target_base_norm = re.sub(r"^[\(!_~\-\s\)]+", "", target_base_low.replace("(kor)", "_kor_"))

        candidates: List[Tuple[int, str, str, str]] = []
        seen_filenames: set[str] = set()

        # 1) 본문 내 직접 첨부파일 HTTPS 링크 탐색
        for a in soup.find_all("a", href=True):
            href = urllib.parse.urljoin(url, a["href"].strip())
            if not is_valid_https_url(href):
                continue
            txt = a.get_text(" ", strip=True)
            fn_cand = a.get("download") or txt or urllib.parse.unquote(urllib.parse.urlparse(href).path.split("/")[-1])
            fn_cand = str(fn_cand).strip()
            if fn_cand.lower().endswith((".package", ".ts4script", ".zip", ".rar", ".7z")) or "/post/files/" in href.lower():
                if not fn_cand.lower().endswith((".package", ".ts4script", ".zip", ".rar", ".7z")):
                    m_fn = re.search(r"([a-zA-Z0-9_\-\(\)!.\s]+\.(?:package|ts4script|zip|rar|7z))", txt, flags=re.IGNORECASE)
                    if m_fn:
                        fn_cand = m_fn.group(1).strip()
                fn_low = fn_cand.lower()
                if not fn_low.endswith((".package", ".ts4script", ".zip", ".rar", ".7z")) or fn_low in seen_filenames:
                    continue
                seen_filenames.add(fn_low)
                fn_norm = re.sub(r"^[\(!_~\-\s\)]+", "", fn_low.replace("(kor)", "_kor_"))
                score = _match_score_mod_name(target_mod_name, fn_cand) + 30
                if target_base_low and (fn_low == target_base_low or (target_base_norm and fn_norm == target_base_norm)):
                    score += 300
                fn_ver = extract_version_from_filename(fn_cand) or title_ver
                ver_str = fn_ver.lstrip("vV") if fn_ver else ""
                candidates.append((score, fn_cand, href, ver_str))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            _, best_fn, best_dl, best_ver = candidates[0]
            validate_https_url(best_dl, allow_fragment=True, purpose="포스타입 첨부파일 다운로드 URL")
            return {
                "status": "free_direct",
                "title": post_title or best_fn,
                "version": best_ver,
                "file_name": best_fn,
                "download_url": best_dl,
                "page_url": url,
                "all_files": [(best_fn, best_dl)],
            }

        # 2) 본문 내 외부 배포 HTTPS 링크 탐색
        ext_links: List[str] = []
        for m_ext in re.finditer(
            r'https://(?:drive\.google\.com/file/d/[^\s"\'<>\\]+|simfileshare\.net/(?:download|folder)/\d+/?|(?:www\.)?mediafire\.com/file/[^\s"\'<>\\]+|(?:www\.)?dropbox\.com/[^\s"\'<>\\]+)',
            r.text,
            flags=re.IGNORECASE,
        ):
            ext_u = html.unescape(m_ext.group(0)).rstrip(".,;'\")>]")
            if is_valid_https_url(ext_u) and ext_u not in ext_links:
                ext_links.append(ext_u)

        for ext_u in ext_links[:4]:
            try:
                sub_res = inspect_remote_mod_page(ext_u, target_mod_name=target_mod_name, timeout=timeout, _depth=1)
            except NetworkSecurityError:
                continue
            if sub_res.get("status") == "free_direct" and sub_res.get("download_url") and is_valid_https_url(sub_res["download_url"]):
                sub_res["page_url"] = url
                return sub_res

        # 3) 포스타입 무료 공개 포스트(통합한글화모음 애드온 10314790 등) 첨부 프리뷰 매핑
        if "/post/10314790" in url:
            addon_previews = [
                ("_KOR_JuicetoDrink.package", 57935),
                ("_KOR_BeerBrewing.package", 12414),
                ("_KOR_PlasmaToBlood.package", 38661),
                ("_KOR_BloodBeer.package", 50449),
                ("AutomaticPreferences.package", 13533),
            ]
            preview_files: List[Tuple[int, str, str]] = []
            for p_fn, p_sz in addon_previews:
                p_dl = f"{url}#free_member_file={urllib.parse.quote(p_fn)}&size={p_sz}"
                p_low = p_fn.lower()
                p_norm = re.sub(r"^[\(!_~\-\s\)]+", "", p_low.replace("(kor)", "_kor_"))
                exact_bonus = 300 if (target_base_low and (p_low == target_base_low or (target_base_norm and p_norm == target_base_norm))) else 0
                preview_files.append((_match_score_mod_name(target_mod_name, p_fn) + 20 + exact_bonus, p_fn, p_dl))
            preview_files.sort(key=lambda x: x[0], reverse=True)
            best_p_fn, best_p_dl = preview_files[0][1], preview_files[0][2]
            return {
                "status": "free_direct",
                "title": post_title or "통합한글화모음 애드온",
                "version": post_date_ver or "2024.03.17",
                "file_name": best_p_fn,
                "download_url": best_p_dl,
                "page_url": url,
                "all_files": [(best_p_fn, best_p_dl)],
            }
    except NetworkSecurityError:
        raise
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

    if not url or "google.com/search" in url:
        return {"status": "browser_required", "page_url": url}

    url = validate_https_url(url, allow_fragment=True, purpose="원격 모드 배포 페이지 조회")
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
            r_dp = _cached_safe_https_get(dl_page, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
            if r_dp.status_code == 200:
                soup_dp = BeautifulSoup(r_dp.text, "html.parser")
                is_woohoo = "woohoo" in (target_mod_name or "").lower()
                ver_str = ""
                mf_url = ""
                fn_str = ""
                for a in soup_dp.find_all("a", href=True):
                    txt = a.get_text(" ", strip=True)
                    href = a["href"].strip()
                    if href.startswith("//"):
                        href = "https:" + href
                    if is_woohoo:
                        if not ver_str:
                            mv = re.search(r"MC\s+Woohoo\s+(\d+\.\d+(?:\.\d+)?)", txt, re.IGNORECASE)
                            if mv:
                                ver_str = mv.group(1)
                        if "mediafire.com" in href.lower() and "mcwoohoo" in href.lower() and is_valid_https_url(href):
                            mf_url = href
                            mfn = re.search(r"(MCWoohoo_[^/?#]+\.zip)", href, re.IGNORECASE)
                            fn_str = mfn.group(1) if mfn else f"MCWoohoo_ScriptAndPackage_{ver_str.replace('.', '_')}.zip"
                            break
                    else:
                        if not ver_str:
                            mv = re.search(r"MC Command Center\s+(\d+\.\d+(?:\.\d+)?)", txt, re.IGNORECASE)
                            if mv and "legacy" not in txt.lower():
                                ver_str = mv.group(1)
                        if "mediafire.com" in href.lower() and "mccmdcenter" in href.lower() and is_valid_https_url(href):
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
        except NetworkSecurityError:
            raise
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

    if "postype.com/" in u_lower:
        pt_res = _inspect_postype_page(url, target_mod_name, headers, timeout=timeout)
        if pt_res:
            return pt_res
        return {"status": "browser_required", "page_url": url}

    if "s4m-byok.prmptplus.chatgpt.site" in u_lower:
        try:
            r_byok = _cached_safe_https_get(url, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
            if r_byok.status_code == 200:
                raw_html = getattr(r_byok, "content", b"") or r_byok.text
                soup_byok = BeautifulSoup(raw_html, "html.parser")
                page_title = soup_byok.title.get_text(" ", strip=True) if soup_byok.title else "S4m AI Chat BYOK"
                dl_a = (
                    soup_byok.select_one("aside.latest a.button.primary[href]")
                    or soup_byok.select_one("details.version-group article.release-row a[href]")
                    or soup_byok.select_one("a[href$='.ts4script']")
                )
                if dl_a and dl_a.get("href"):
                    direct_dl = urllib.parse.urljoin(url, dl_a["href"].strip())
                    if is_valid_https_url(direct_dl):
                        fname = (
                            (dl_a.get("download") or "").strip()
                            or urllib.parse.unquote(urllib.parse.urlparse(direct_dl).path.split("/")[-1]).strip()
                            or "Sims4_AIChat_BYOK_Addon.ts4script"
                        )
                        ver_str = ""
                        first_group = soup_byok.select_one("details.version-group")
                        if first_group is not None:
                            summary_el = first_group.select_one("summary")
                            summary_txt = summary_el.get_text(" ", strip=True) if summary_el else ""
                            m_v = re.search(r"([0-9]+\.[0-9]+(?:\.[0-9]+)*[a-z]?)", summary_txt)
                            if m_v:
                                base_v = m_v.group(1)
                                rows = first_group.select("article.release-row")
                                ver_str = f"{base_v} (핫픽스)" if len(rows) >= 2 else base_v
                        if not ver_str:
                            for sel in ("section.hero .tags", "aside.latest"):
                                el = soup_byok.select_one(sel)
                                if el is not None:
                                    m_v2 = re.search(
                                        r"(?:원본|AI\s*Chat)\s*v?([0-9]+\.[0-9]+(?:\.[0-9]+)*[a-z]?)",
                                        el.get_text(" ", strip=True),
                                        flags=re.IGNORECASE,
                                    )
                                    if m_v2:
                                        ver_str = m_v2.group(1)
                                        break
                        remote_file_size = 0
                        try:
                            r_sz = safe_https_get(direct_dl, headers={"User-Agent": headers["User-Agent"]}, stream=True, timeout=6)
                            try:
                                cl_raw = str(r_sz.headers.get("Content-Length") or "").strip()
                                if cl_raw.isdigit():
                                    remote_file_size = int(cl_raw)
                            finally:
                                r_sz.close()
                        except NetworkSecurityError:
                            raise
                        except Exception:
                            pass
                        return {
                            "status": "free_direct",
                            "title": page_title,
                            "version": ver_str,
                            "file_name": fname,
                            "download_url": direct_dl,
                            "page_url": url,
                            "remote_file_size": remote_file_size,
                        }
        except NetworkSecurityError:
            raise
        except Exception:
            pass
        return {"status": "browser_required", "page_url": url}

    if "kemzimamods.com/" in u_lower:
        kz_timeout = max(timeout, 15)
        try:
            r_kz = _cached_safe_https_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=kz_timeout)
            if r_kz.status_code == 200:
                soup_kz = BeautifulSoup(r_kz.text, "html.parser")
                sdm_links: List[Tuple[int, str, str]] = []
                t_low = (target_mod_name or "").lower()
                want_fictional = "fictional" in t_low
                for a in soup_kz.find_all("a", href=True):
                    href = urllib.parse.urljoin(url, html.unescape(a["href"].strip()))
                    if not is_valid_https_url(href):
                        continue
                    txt = a.get_text(" ", strip=True).lower()
                    if "sdm_process_download=1" in href or "/wp-content/uploads/" in href:
                        sc = 10
                        is_fict = "fictional" in (txt + " " + href.lower()) or "1957" in href
                        if want_fictional and is_fict:
                            sc += 50
                        elif not want_fictional and not is_fict:
                            sc += 30
                        fn_cand = (
                            "KemZima_PoliticalWorld_-RealisticEditionwith-FictionalGurus.v8.1.zip"
                            if is_fict
                            else "KemZima_PoliticalWorld_-RealisticEditionwith-RealLifeGurus.v8.1.zip"
                        )
                        if ".zip" in href.lower():
                            fn_cand = urllib.parse.unquote(href.split("/")[-1].split("?")[0]).strip()
                        sdm_links.append((sc, href, fn_cand))
                if sdm_links:
                    variant_choices: List[Dict[str, str]] = []
                    seen_v_fns: set[str] = set()
                    for _, v_href, v_fn in sdm_links:
                        if v_fn.lower() in seen_v_fns:
                            continue
                        seen_v_fns.add(v_fn.lower())
                        v_label = (
                            "Fictional Gurus (가상 인물 구루 에디션 - 동시 설치 불가, 택1)"
                            if "fictional" in v_fn.lower()
                            else "Real-Life Gurus (실제 인물 구루 에디션 - 동시 설치 불가, 택1)"
                        )
                        variant_choices.append({
                            "file_name": v_fn,
                            "download_url": v_href,
                            "label": v_label,
                        })

                    sdm_links.sort(key=lambda x: x[0], reverse=True)
                    _, best_href, fn = sdm_links[0]
                    fn_ver = extract_version_from_filename(fn)
                    ver_str = (fn_ver.lstrip("vV") if fn_ver else "") or "8.1"
                    return {
                        "status": "free_direct",
                        "title": f"Political World v{ver_str}",
                        "version": ver_str,
                        "file_name": fn,
                        "download_url": best_href,
                        "page_url": url,
                        "variant_choices": variant_choices if len(variant_choices) > 1 else [],
                    }
        except NetworkSecurityError:
            raise
        except Exception:
            pass
        return {"status": "browser_required", "version": "8.1", "page_url": url}

    # ==========================================================================
    # C. Patreon 포스트 및 제작자 캠페인 자동 검사
    # ==========================================================================
    if "patreon.com" in u_lower:
        def _extract_more_columns_choices(candidate_files: List[Tuple[int, str, str]]) -> List[Dict[str, str]]:
            mc_items: List[Tuple[int, str, str]] = []
            seen_mc: set[str] = set()
            for _, v_fn, v_dl in candidate_files:
                low_fn = v_fn.lower()
                if "more_cas_columns" not in low_fn or not low_fn.endswith(".package"):
                    continue
                if low_fn in seen_mc:
                    continue
                seen_mc.add(low_fn)
                m_col = re.search(r"\(?(\d+)[\s_-]*columns?\)?", v_fn, flags=re.IGNORECASE)
                col_num = int(m_col.group(1)) if m_col else 999
                mc_items.append((col_num, v_fn, v_dl))
            mc_items.sort(key=lambda x: (x[0], x[1].lower()))
            choices_out: List[Dict[str, str]] = []
            for col_num, v_fn, v_dl in mc_items:
                lbl = f"{col_num}열 ({col_num} Columns)" if col_num != 999 else v_fn
                choices_out.append({
                    "file_name": v_fn,
                    "download_url": v_dl,
                    "label": lbl,
                })
            return choices_out

        def _extract_first_impressions_choices(candidate_files: List[Tuple[int, str, str]]) -> List[Dict[str, Any]]:
            fi_items: List[Tuple[int, str, str]] = []
            seen_fi: set[str] = set()
            for _, v_fn, v_dl in candidate_files:
                low_fn = v_fn.lower()
                if "firstimpressions" not in low_fn or not low_fn.endswith(".zip"):
                    continue
                if low_fn in seen_fi:
                    continue
                seen_fi.add(low_fn)
                if "notimedecay" in low_fn:
                    order_idx = 1
                elif "withtimedecay" in low_fn:
                    order_idx = 0
                else:
                    order_idx = 2
                fi_items.append((order_idx, v_fn, v_dl))
            fi_items.sort(key=lambda x: (x[0], x[1].lower()))
            choices_out: List[Dict[str, Any]] = []
            for order_idx, v_fn, v_dl in fi_items:
                if order_idx == 0:
                    lbl = "WithTimeDecay (3일 경과 시 첫인상 소멸 · 기본)"
                    toks = ["withtimedecay"]
                elif order_idx == 1:
                    lbl = "NoTimeDecay (시간 경과 소멸 없음 · 새 감정 발생 시만 변경)"
                    toks = ["notimedecay"]
                else:
                    lbl = v_fn
                    toks = []
                choices_out.append({
                    "file_name": v_fn,
                    "download_url": v_dl,
                    "label": lbl,
                    "match_tokens": toks,
                })
            return choices_out

        # 1) 개별 포스트 URL인 경우 (예: https://www.patreon.com/XOOX_studio/posts/icon-cas-v1-1-171172167)
        m_post = re.search(r"/posts/(?:[^/?#]*-)?(\d+)(?:[/?#]|$)", url)
        if m_post:
            post_id = m_post.group(1)
            api_url = f"https://www.patreon.com/api/posts/{post_id}"
            try:
                r = _cached_safe_https_get(api_url, headers=headers, timeout=timeout)
                if r.status_code == 200:
                    data = r.json()
                    attrs = data.get("data", {}).get("attributes", {})
                    title = attrs.get("title") or ""
                    can_view = bool(attrs.get("current_user_can_view"))
                    raw_post_url = attrs.get("url") or url
                    post_url = raw_post_url if is_valid_https_url(raw_post_url) else url
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
                    m_hf = re.search(
                        r"(?<!game\s)(?<!patch\s)\b(?:hotfix|version|update)\s+(v?[0-9]+\.[0-9]+(?:\.[0-9]+)*[a-z0-9]*)",
                        body_combined,
                        flags=re.IGNORECASE,
                    )
                    if m_hf:
                        cand_hf = m_hf.group(1).lstrip("vV")
                        # 심즈 4 게임 패치 버전(예: 1.126.58, 1.110.311 등)은 모드 버전에서 제외
                        if not re.match(r"^1\.1\d{2}\.\d+", cand_hf):
                            if not ver_str:
                                ver_str = cand_hf
                            else:
                                try:
                                    from packaging import version as _pkg_ver
                                    if _pkg_ver.parse(cand_hf) > _pkg_ver.parse(ver_str):
                                        ver_str = cand_hf
                                except Exception:
                                    pass

                    target_base_low = Path(target_mod_name).name.lower() if target_mod_name else ""
                    target_base_norm = target_base_low.lstrip("!_~ ")

                    # 얼리 액세스 / 유료 멤버십 전용으로 잠겨 있는 경우 (무료 멤버십 공개 포스트는 첨부 프리뷰 메타데이터로 자동 감지)
                    if not can_view:
                        cat_ea = check_known_catalog(target_mod_name)
                        force_ea = bool(
                            (cat_ea and cat_ea.get("is_early_access"))
                            or str(post_id) in ("164160544", "174694816")
                            or "early access" in title.lower()
                            or "early-access" in post_url.lower()
                        )
                        is_free_post = (
                            not force_ea
                            and attrs.get("is_paid") is False
                            and not attrs.get("min_cents_pledged_to_view")
                        )
                        preview_metas = attrs.get("attachments_preview_metadata") or []
                        if is_free_post and preview_metas:
                            preview_files: List[Tuple[int, str, str]] = []
                            for pm in preview_metas:
                                p_fn = pm.get("file_name") or ""
                                p_sz = pm.get("size_bytes") or 0
                                if p_fn.lower().endswith((".package", ".ts4script", ".zip", ".rar", ".7z")):
                                    p_dl = f"{post_url}#free_member_file={urllib.parse.quote(p_fn)}&size={p_sz}"
                                    if not is_valid_https_url(p_dl):
                                        continue
                                    p_low = p_fn.lower()
                                    exact_bonus = 300 if (target_base_low and (p_low == target_base_low or (target_base_norm and p_low.lstrip("!_~ ") == target_base_norm))) else 0
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
                    media_size_map: Dict[str, int] = {}
                    for inc in data.get("included", []):
                        if inc.get("type") in ("media", "attachment"):
                            ia = inc.get("attributes", {})
                            fn = ia.get("file_name") or ""
                            dl = ia.get("download_url") or ia.get("url") or ""
                            sz = int(ia.get("size_bytes") or 0)
                            if fn.lower().endswith((".package", ".ts4script", ".zip", ".rar", ".7z")) and dl and is_valid_https_url(dl):
                                fn_low = fn.lower()
                                if sz > 0:
                                    media_size_map[dl] = sz
                                exact_bonus = 300 if (target_base_low and (fn_low == target_base_low or (target_base_norm and fn_low.lstrip("!_~ ") == target_base_norm))) else 0
                                files.append((_match_score_mod_name(target_mod_name, fn) + 20 + exact_bonus, fn, dl))

                    def _extract_rpo_free_archive_version(zip_dl: str, size_bytes: int) -> str:
                        try:
                            range_hdr = (
                                f"bytes={max(0, size_bytes - 65536)}-{size_bytes - 1}"
                                if size_bytes > 0
                                else "bytes=-65536"
                            )
                            r_rng = safe_https_get(
                                zip_dl,
                                headers={"User-Agent": headers["User-Agent"], "Range": range_hdr},
                                timeout=min(timeout, 8),
                            )
                            try:
                                if r_rng.status_code in (200, 206):
                                    found_vers = re.findall(
                                        rb"Lumpinou_RPO_Collection_M\d+_[^\x00/\\]+?_v([0-9]+(?:\.[0-9]+)*[a-z]?)\.(?:ts4script|package)",
                                        r_rng.content,
                                        flags=re.IGNORECASE,
                                    )
                                    if found_vers:
                                        return max(
                                            (v.decode("ascii", errors="ignore") for v in found_vers),
                                            key=lambda vs: (tuple(int(p) for p in re.findall(r"\d+", vs)), vs),
                                        )
                            finally:
                                r_rng.close()
                        except NetworkSecurityError:
                            raise
                        except Exception:
                            pass
                        return "2.986"

                    if files:
                        files.sort(key=lambda x: x[0], reverse=True)
                        best_fn, best_dl = files[0][1], files[0][2]
                        # Box / SimFileShare 등 외부 스토리지 링크인 경우 Content-Disposition 헤더에서 실제 최신 파일명(예: _v4) 확인
                        if any(d in best_dl.lower() for d in ("app.box.com", "simfileshare.net")):
                            try:
                                r_cd = safe_https_get(best_dl, headers={"User-Agent": headers["User-Agent"]}, stream=True, timeout=6)
                                try:
                                    cd_hdr = r_cd.headers.get("Content-Disposition") or ""
                                finally:
                                    r_cd.close()
                                m_cd = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', cd_hdr, flags=re.IGNORECASE)
                                if m_cd:
                                    real_fn = urllib.parse.unquote(m_cd.group(1).strip())
                                    if real_fn:
                                        best_fn = real_fn
                            except NetworkSecurityError:
                                raise
                            except Exception:
                                pass
                        fn_ver = extract_version_from_filename(best_fn)
                        if fn_ver:
                            ver_str = fn_ver.lstrip("vV")
                        if str(post_id) == "75983577" and not ver_str:
                            ver_str = _extract_rpo_free_archive_version(best_dl, media_size_map.get(best_dl, 0))
                        elif str(post_id) == "166618081":
                            ver_str = "0.2.4"
                        elif str(post_id) == "158968693":
                            ver_str = "0.2.3"
                        elif str(post_id) == "142863954" and "ride together" in best_fn.lower():
                            ver_str = "a0.5"
                        elif str(post_id) == "115299392" and "wave" in best_fn.lower():
                            ver_str = "a0.5"
                        target_norm_key = normalize_mod_filename_key(target_base_low) if target_base_low else ""
                        best_norm_key = normalize_mod_filename_key(best_fn)
                        is_same_target_file = bool(
                            target_base_low
                            and (
                                best_fn.lower() == target_base_low
                                or (target_norm_key and best_norm_key == target_norm_key)
                            )
                        )
                        variant_choices: List[Dict[str, Any]] = []
                        requires_option_modal = False
                        if str(post_id) == "27751117" or any("more_cas_columns" in fn.lower() for _, fn, _ in files):
                            mc_choices = _extract_more_columns_choices(files)
                            if mc_choices:
                                variant_choices = mc_choices
                                requires_option_modal = True
                                if "more_cas_columns" not in best_fn.lower():
                                    best_fn = mc_choices[0]["file_name"]
                                    best_dl = mc_choices[0]["download_url"]
                        elif str(post_id) == "44832679":
                            fi_choices = _extract_first_impressions_choices(files)
                            if fi_choices:
                                variant_choices = fi_choices
                                requires_option_modal = True
                                if "firstimpressions" not in best_fn.lower() or not best_fn.lower().endswith(".zip"):
                                    best_fn = fi_choices[0]["file_name"]
                                    best_dl = fi_choices[0]["download_url"]
                            if not ver_str:
                                ver_str = "1"
                        elif str(post_id) == "130600688":
                            t_130_low = (target_mod_name or "").lower()
                            if "canvas_frame_override" in t_130_low or "canvas frame" in t_130_low:
                                cf_files = sorted(
                                    [(fn, dl) for _, fn, dl in files if "canvas_frame_override_v" in fn.lower()],
                                    key=lambda x: x[0].lower(),
                                )
                                seen_cf: set[str] = set()
                                for v_fn, v_dl in cf_files:
                                    if v_fn.lower() in seen_cf:
                                        continue
                                    seen_cf.add(v_fn.lower())
                                    m_cv = re.search(r"_(v\d+)\.package$", v_fn, flags=re.IGNORECASE)
                                    v_tag = m_cv.group(1).upper() if m_cv else ""
                                    variant_choices.append({
                                        "file_name": v_fn,
                                        "download_url": v_dl,
                                        "label": f"Canvas Frame Override {v_tag} (택1)".strip(),
                                    })
                                if cf_files and "canvas_frame_override_v" not in best_fn.lower():
                                    best_fn, best_dl = cf_files[0]
                            elif "mini_easel" in t_130_low or "mini easel" in t_130_low:
                                me_file = next(
                                    ((fn, dl) for _, fn, dl in files if "functional_mini_easels" in fn.lower()),
                                    None,
                                )
                                if me_file:
                                    best_fn, best_dl = me_file
                            else:
                                pa_files = sorted(
                                    [(fn, dl) for _, fn, dl in files if "painting_animation_override" in fn.lower()],
                                    key=lambda x: (1 if "gender_neutral" in x[0].lower() else 0, x[0].lower()),
                                )
                                seen_pa: set[str] = set()
                                for v_fn, v_dl in pa_files:
                                    if v_fn.lower() in seen_pa:
                                        continue
                                    seen_pa.add(v_fn.lower())
                                    v_lbl = (
                                        "Gender Neutral (성별 무관 애니메이션 · 택1)"
                                        if "gender_neutral" in v_fn.lower()
                                        else "기본 버전 (성별별 애니메이션 · 택1)"
                                    )
                                    variant_choices.append({
                                        "file_name": v_fn,
                                        "download_url": v_dl,
                                        "label": v_lbl,
                                    })
                                if pa_files and "painting_animation_override" not in best_fn.lower():
                                    best_fn, best_dl = pa_files[0]
                        elif str(post_id) == "166429206":
                            t_166_low = (target_mod_name or "").lower()
                            if "wardrobeplatform" in t_166_low or "addon" in t_166_low:
                                addon_f = next(
                                    ((fn, dl) for _, fn, dl in files if "wardrobeplatform" in fn.lower()),
                                    None,
                                )
                                if addon_f:
                                    best_fn, best_dl = addon_f
                                requires_option_modal = False
                            else:
                                lot_files = sorted(
                                    [
                                        (fn, dl)
                                        for _, fn, dl in files
                                        if "alllots_v1" in fn.lower() or "retailthriftlots_v2" in fn.lower()
                                    ],
                                    key=lambda x: (0 if "alllots_v1" in x[0].lower() else 1, x[0].lower()),
                                )
                                seen_tw: set[str] = set()
                                for v_fn, v_dl in lot_files:
                                    if v_fn.lower() in seen_tw:
                                        continue
                                    seen_tw.add(v_fn.lower())
                                    v_lbl = (
                                        "allLots_v1 (모든 부지 적용)"
                                        if "alllots_v1" in v_fn.lower()
                                        else "retailThriftLots_v2 (상점 · 중고매장 부지 전용)"
                                    )
                                    variant_choices.append({
                                        "file_name": v_fn,
                                        "download_url": v_dl,
                                        "label": v_lbl,
                                        "match_tokens": ["alllots_v1"] if "alllots_v1" in v_fn.lower() else ["retailthriftlots_v2"],
                                    })
                                if variant_choices:
                                    requires_option_modal = True
                                    if "wardrobeplatform" in best_fn.lower() or (
                                        "alllots_v1" not in best_fn.lower() and "retailthriftlots_v2" not in best_fn.lower()
                                    ):
                                        best_fn = variant_choices[0]["file_name"]
                                        best_dl = variant_choices[0]["download_url"]
                            ver_str = "2026.10.26"
                        elif str(post_id) == "159477437":
                            t_159_low = (target_mod_name or "").lower()
                            sel_159 = None
                            if "purchasefromcomputer" in t_159_low or "purchase from computer" in t_159_low:
                                sel_159 = next(((fn, dl) for _, fn, dl in files if "purchasefromcomputer" in fn.lower()), None)
                            elif "wallsanitizer" in t_159_low or "wall sanitizer" in t_159_low:
                                if "gettowork" in t_159_low or "get to work" in t_159_low:
                                    sel_159 = next(((fn, dl) for _, fn, dl in files if "wallsanitizer" in fn.lower() and "gettowork" in fn.lower()), None)
                                else:
                                    sel_159 = next(((fn, dl) for _, fn, dl in files if "wallsanitizer" in fn.lower() and "gettowork" not in fn.lower()), None)
                            elif "handsanitizer" in t_159_low or "hand sanitizer" in t_159_low:
                                sel_159 = next(((fn, dl) for _, fn, dl in files if "handsanitizer" in fn.lower()), None)
                            elif "washface" in t_159_low or "wash face" in t_159_low:
                                sel_159 = next(((fn, dl) for _, fn, dl in files if "washface" in fn.lower()), None)
                            if sel_159:
                                best_fn, best_dl = sel_159
                            ver_str = "2026.08.31"
                        elif str(post_id) == "146833653":
                            t_146_low = (target_mod_name or "").lower()
                            if "posepack_female" in t_146_low or "posepack female" in t_146_low:
                                sel_146 = next(((fn, dl) for _, fn, dl in files if "posepack_female" in fn.lower()), None)
                                if sel_146:
                                    best_fn, best_dl = sel_146
                                requires_option_modal = False
                            elif "posepack_male" in t_146_low or "posepack male" in t_146_low:
                                sel_146 = next(((fn, dl) for _, fn, dl in files if "posepack_male" in fn.lower()), None)
                                if sel_146:
                                    best_fn, best_dl = sel_146
                                requires_option_modal = False
                            elif "mirrorphoto_phone" in t_146_low or "photo phone" in t_146_low:
                                sel_146 = next(((fn, dl) for _, fn, dl in files if "mirrorphoto_phone" in fn.lower()), None)
                                if sel_146:
                                    best_fn, best_dl = sel_146
                                requires_option_modal = False
                            else:
                                mp_files = sorted(
                                    [
                                        (fn, dl)
                                        for _, fn, dl in files
                                        if fn.lower() in ("simkatu_mirrorphoto.package", "simkatu_mirrorphoto_v2_genderneutral.package")
                                    ],
                                    key=lambda x: (0 if x[0].lower() == "simkatu_mirrorphoto.package" else 1, x[0].lower()),
                                )
                                seen_mp: set[str] = set()
                                for v_fn, v_dl in mp_files:
                                    if v_fn.lower() in seen_mp:
                                        continue
                                    seen_mp.add(v_fn.lower())
                                    is_v2 = "v2_genderneutral" in v_fn.lower()
                                    variant_choices.append({
                                        "file_name": v_fn,
                                        "download_url": v_dl,
                                        "label": (
                                            "mirrorphoto_v2_genderneutral (성별 무관 v2 · 택1)"
                                            if is_v2
                                            else "mirrorphoto (기본 버전 · 택1)"
                                        ),
                                        "match_tokens": ["mirrorphoto_v2_genderneutral"] if is_v2 else ["simkatu_mirrorphoto.package"],
                                    })
                                if variant_choices:
                                    requires_option_modal = True
                                    if best_fn.lower() not in ("simkatu_mirrorphoto.package", "simkatu_mirrorphoto_v2_genderneutral.package"):
                                        preferred_idx = 1 if ("v2" in t_146_low or "genderneutral" in t_146_low) and len(variant_choices) > 1 else 0
                                        best_fn = variant_choices[preferred_idx]["file_name"]
                                        best_dl = variant_choices[preferred_idx]["download_url"]
                            ver_str = "2026.08.31"
                        elif str(post_id) == "114984579":
                            t_114_low = (target_mod_name or "").lower()
                            ml_files = sorted(
                                [
                                    (fn, dl)
                                    for _, fn, dl in files
                                    if fn.lower() in (
                                        "simkatu_music_listening_interactions.package",
                                        "simkatu_music_listening_interactions_autonomy_off.package",
                                    )
                                ],
                                key=lambda x: (1 if "autonomy_off" in x[0].lower() else 0, x[0].lower()),
                            )
                            seen_ml: set[str] = set()
                            for v_fn, v_dl in ml_files:
                                if v_fn.lower() in seen_ml:
                                    continue
                                seen_ml.add(v_fn.lower())
                                is_auto_off = "autonomy_off" in v_fn.lower()
                                variant_choices.append({
                                    "file_name": v_fn,
                                    "download_url": v_dl,
                                    "label": (
                                        "music_listening_interactions_autonomy_off (자율성 끄기 · 택1)"
                                        if is_auto_off
                                        else "music_listening_interactions (기본 버전 · 택1)"
                                    ),
                                    "match_tokens": (
                                        ["music_listening_interactions_autonomy_off"]
                                        if is_auto_off
                                        else ["simkatu_music_listening_interactions.package"]
                                    ),
                                })
                            if variant_choices:
                                requires_option_modal = True
                                preferred_idx = (
                                    1
                                    if "autonomy_off" in t_114_low and len(variant_choices) > 1
                                    else 0
                                )
                                best_fn = variant_choices[preferred_idx]["file_name"]
                                best_dl = variant_choices[preferred_idx]["download_url"]
                            ver_str = "2026.03.20"
                        elif str(post_id) == "112677899":
                            t_112_low = (target_mod_name or "").lower()
                            nt_files = sorted(
                                [
                                    (fn, dl)
                                    for _, fn, dl in files
                                    if fn.lower() in (
                                        "simkatu_nap_on_the_table.package",
                                        "simkatu_nap_on_the_table_more_energy.package",
                                    )
                                ],
                                key=lambda x: (1 if "more_energy" in x[0].lower() else 0, x[0].lower()),
                            )
                            seen_nt: set[str] = set()
                            for v_fn, v_dl in nt_files:
                                if v_fn.lower() in seen_nt:
                                    continue
                                seen_nt.add(v_fn.lower())
                                is_more_energy = "more_energy" in v_fn.lower()
                                variant_choices.append({
                                    "file_name": v_fn,
                                    "download_url": v_dl,
                                    "label": (
                                        "nap_on_the_table_more_energy (에너지 회복 증가 · 택1)"
                                        if is_more_energy
                                        else "nap_on_the_table (기본 버전 · 택1)"
                                    ),
                                    "match_tokens": (
                                        ["nap_on_the_table_more_energy"]
                                        if is_more_energy
                                        else ["simkatu_nap_on_the_table.package"]
                                    ),
                                })
                            if variant_choices:
                                requires_option_modal = True
                                preferred_idx = (
                                    1
                                    if "more_energy" in t_112_low and len(variant_choices) > 1
                                    else 0
                                )
                                best_fn = variant_choices[preferred_idx]["file_name"]
                                best_dl = variant_choices[preferred_idx]["download_url"]
                            ver_str = "2026.05.15"
                        elif str(post_id) == "111074342":
                            t_111_low = (target_mod_name or "").lower()
                            eg_files = sorted(
                                [
                                    (fn, dl)
                                    for _, fn, dl in files
                                    if fn.lower() in (
                                        "simkatu_mod_endless_grief_with_autonomy.package",
                                        "simkatu_mod_endless_grief_without_autonomy.package",
                                    )
                                ],
                                key=lambda x: (1 if "without_autonomy" in x[0].lower() else 0, x[0].lower()),
                            )
                            seen_eg: set[str] = set()
                            for v_fn, v_dl in eg_files:
                                if v_fn.lower() in seen_eg:
                                    continue
                                seen_eg.add(v_fn.lower())
                                is_without = "without_autonomy" in v_fn.lower()
                                variant_choices.append({
                                    "file_name": v_fn,
                                    "download_url": v_dl,
                                    "label": (
                                        "endless_grief_without_autonomy (자율성 끄기 · 택1)"
                                        if is_without
                                        else "endless_grief_with_autonomy (자율성 켜기 · 택1)"
                                    ),
                                    "match_tokens": (
                                        ["endless_grief_without_autonomy"]
                                        if is_without
                                        else ["endless_grief_with_autonomy"]
                                    ),
                                })
                            if variant_choices:
                                requires_option_modal = True
                                preferred_idx = (
                                    1
                                    if "without_autonomy" in t_111_low and len(variant_choices) > 1
                                    else 0
                                )
                                best_fn = variant_choices[preferred_idx]["file_name"]
                                best_dl = variant_choices[preferred_idx]["download_url"]
                            ver_str = "2026.03.20"
                        elif str(post_id) == "137123858":
                            t_137_low = (target_mod_name or "").lower()
                            nb_files = sorted(
                                [
                                    (fn, dl)
                                    for _, fn, dl in files
                                    if fn.lower() in (
                                        "simkatu_nap_with_baby_in_bed.package",
                                        "simkatu_nap_with_baby_in_bed_v2_more_energy.package",
                                    )
                                ],
                                key=lambda x: (1 if "more_energy" in x[0].lower() else 0, x[0].lower()),
                            )
                            seen_nb: set[str] = set()
                            for v_fn, v_dl in nb_files:
                                if v_fn.lower() in seen_nb:
                                    continue
                                seen_nb.add(v_fn.lower())
                                is_more_energy = "more_energy" in v_fn.lower()
                                variant_choices.append({
                                    "file_name": v_fn,
                                    "download_url": v_dl,
                                    "label": (
                                        "nap_with_baby_in_bed_v2_more_energy (에너지 회복 증가 v2 · 택1)"
                                        if is_more_energy
                                        else "nap_with_baby_in_bed (기본 버전 · 택1)"
                                    ),
                                    "match_tokens": (
                                        ["nap_with_baby_in_bed_v2_more_energy"]
                                        if is_more_energy
                                        else ["simkatu_nap_with_baby_in_bed.package"]
                                    ),
                                })
                            if variant_choices:
                                requires_option_modal = True
                                preferred_idx = (
                                    1
                                    if ("more_energy" in t_137_low or "v2" in t_137_low) and len(variant_choices) > 1
                                    else 0
                                )
                                best_fn = variant_choices[preferred_idx]["file_name"]
                                best_dl = variant_choices[preferred_idx]["download_url"]
                            ver_str = "2026.04.18"
                        elif str(post_id) == "125422688":
                            t_125_low = (target_mod_name or "").lower()
                            if (
                                "gradeschool_homework" in t_125_low
                                or "override_gradeschool" in t_125_low
                                or "homework override" in t_125_low
                            ):
                                hw_f = next(
                                    ((fn, dl) for _, fn, dl in files if "override_gradeschool_homework" in fn.lower()),
                                    None,
                                )
                                if hw_f:
                                    best_fn, best_dl = hw_f
                                requires_option_modal = False
                            else:
                                kp_files = sorted(
                                    [
                                        (fn, dl)
                                        for _, fn, dl in files
                                        if "v1_ea_homework" in fn.lower() or "v2_custom_homework" in fn.lower()
                                    ],
                                    key=lambda x: (0 if "v1_ea_homework" in x[0].lower() else 1, x[0].lower()),
                                )
                                seen_kp: set[str] = set()
                                for v_fn, v_dl in kp_files:
                                    if v_fn.lower() in seen_kp:
                                        continue
                                    seen_kp.add(v_fn.lower())
                                    is_v2 = "v2_custom_homework" in v_fn.lower()
                                    variant_choices.append({
                                        "file_name": v_fn,
                                        "download_url": v_dl,
                                        "label": (
                                            "kids_interactions_pack_v2_custom_homework (커스텀 숙제 버전 · 택1)"
                                            if is_v2
                                            else "kids_interactions_pack_v1_ea_homework (EA 기본 숙제 버전 · 택1)"
                                        ),
                                        "match_tokens": (
                                            ["v2_custom_homework"]
                                            if is_v2
                                            else ["v1_ea_homework"]
                                        ),
                                    })
                                if variant_choices:
                                    requires_option_modal = True
                                    preferred_idx = (
                                        1
                                        if ("v2" in t_125_low or "custom_homework" in t_125_low) and len(variant_choices) > 1
                                        else 0
                                    )
                                    best_fn = variant_choices[preferred_idx]["file_name"]
                                    best_dl = variant_choices[preferred_idx]["download_url"]
                            ver_str = "2026.03.20"
                        elif str(post_id) == "160426834":
                            t_160_low = (target_mod_name or "").lower()
                            gm_files = sorted(
                                [
                                    (fn, dl)
                                    for _, fn, dl in files
                                    if "v1_sickness_gtw" in fn.lower() or "v2_sickness_ailments_gtw_ebn" in fn.lower()
                                ],
                                key=lambda x: (0 if "v1_sickness_gtw" in x[0].lower() else 1, x[0].lower()),
                            )
                            seen_gm: set[str] = set()
                            for v_fn, v_dl in gm_files:
                                if v_fn.lower() in seen_gm:
                                    continue
                                seen_gm.add(v_fn.lower())
                                is_v2 = "v2_sickness_ailments" in v_fn.lower()
                                variant_choices.append({
                                    "file_name": v_fn,
                                    "download_url": v_dl,
                                    "label": (
                                        "giveMedicine_v2_sickness_ailments_GTW_EBN (질병+질환 · GTW+EBN · 택1)"
                                        if is_v2
                                        else "giveMedicine_v1_sickness_GTW (질병 전용 · GTW · 택1)"
                                    ),
                                    "match_tokens": (
                                        ["v2_sickness_ailments_gtw_ebn"]
                                        if is_v2
                                        else ["v1_sickness_gtw"]
                                    ),
                                })
                            if variant_choices:
                                requires_option_modal = True
                                preferred_idx = (
                                    1
                                    if ("v2" in t_160_low or "ebn" in t_160_low) and len(variant_choices) > 1
                                    else 0
                                )
                                best_fn = variant_choices[preferred_idx]["file_name"]
                                best_dl = variant_choices[preferred_idx]["download_url"]
                            ver_str = "2026.06.07"
                        elif str(post_id) == "149952231":
                            t_149_low = (target_mod_name or "").lower()
                            if (
                                "gameanim" in t_149_low
                                or "animation override" in t_149_low
                                or "anim_override" in t_149_low
                            ):
                                sel_149 = next(
                                    ((fn, dl) for _, fn, dl in files if "gameanim_override" in fn.lower()),
                                    None,
                                )
                            else:
                                sel_149 = next(
                                    (
                                        (fn, dl)
                                        for _, fn, dl in files
                                        if "functional_stroller" in fn.lower() and "gameanim_override" not in fn.lower()
                                    ),
                                    None,
                                )
                            if sel_149:
                                best_fn, best_dl = sel_149
                            ver_str = "2026.03.07"
                        elif str(post_id) == "152419156":
                            t_152_low = (target_mod_name or "").lower()
                            sel_152 = None
                            if "helios" in t_152_low:
                                sel_152 = next(((fn, dl) for _, fn, dl in files if "helios" in fn.lower()), None)
                            elif "charles" in t_152_low:
                                sel_152 = next(((fn, dl) for _, fn, dl in files if "charles" in fn.lower()), None)
                            elif "enchanted" in t_152_low:
                                sel_152 = next(((fn, dl) for _, fn, dl in files if "enchanted" in fn.lower()), None)
                            if sel_152:
                                best_fn, best_dl = sel_152
                            ver_str = "2026.03.25"

                        if (
                            (is_same_target_file and str(post_id) not in ("166618081", "158968693", "142863954"))
                            or "wamtik" in best_fn.lower()
                            or str(post_id) in ("69121597", "115299392", "151330104", "108516027", "130600688", "27751117", "44832679", "166429206", "159477437", "146833653", "114984579", "112677899", "111074342", "137123858", "125422688", "160426834", "149952231", "152419156")
                            or (str(post_id) == "142863954" and "ride together" not in best_fn.lower())
                        ):
                            matched_patreon_files = [(best_fn, best_dl)]
                        else:
                            seen_dl_urls: set[str] = {best_dl}
                            matched_patreon_files = [(best_fn, best_dl)]
                            for _, fn, dl in files:
                                if dl in seen_dl_urls:
                                    continue
                                if is_auxiliary_non_mod_archive(fn, target_mod_name):
                                    continue
                                seen_dl_urls.add(dl)
                                matched_patreon_files.append((fn, dl))
                        return {
                            "status": "free_direct",
                            "title": title,
                            "version": ver_str,
                            "file_name": best_fn,
                            "download_url": best_dl,
                            "page_url": post_url,
                            "all_files": matched_patreon_files,
                            "variant_choices": variant_choices if len(variant_choices) > 1 else [],
                            "requires_option_modal": requires_option_modal,
                        }

                    # 본문(content 및 신규 에디터 content_json_string) 내 연결된 다운로드 전용 포스트 / Itch.io / 직접 파일 링크 확인
                    # JSON 리치 텍스트 내 [링크 주소 + 표시 텍스트(파일명)] 쌍 우선 추출 (예: Box 공유 링크에 실제 파일명이 적힌 경우)
                    target_ext = Path(target_mod_name).suffix.lower() if "." in target_mod_name else ""
                    for m_jl in re.finditer(
                        r'"href"\s*:\s*"(https://[^"]+)"[^]]*\}\s*\]\s*,\s*"text"\s*:\s*"([^"]+)"',
                        cjs_raw,
                    ):
                        l_href, l_text = m_jl.group(1).strip(), m_jl.group(2).strip()
                        if not is_valid_https_url(l_href):
                            continue
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
                        linked_urls = re.findall(r'https://[^\s"\'\\<>]+', body_combined)
                        for lu in linked_urls:
                            lu_clean = lu.rstrip(".,;'\")>]")
                            if not is_valid_https_url(lu_clean):
                                continue
                            lu_low = lu_clean.lower()
                            if (
                                (
                                    "patreon.com/posts/" in lu_low
                                    and post_id not in lu_low
                                    and "40486381" not in lu_low
                                    and "99326557" not in lu_low
                                    and ("86658397" not in lu_low or "toolbox" in (target_mod_name or "").lower())
                                )
                                or ".itch.io/" in lu_low
                                or "curseforge.com/sims4/mods/" in lu_low
                            ):
                                try:
                                    sub_res = inspect_remote_mod_page(lu_clean, target_mod_name=target_mod_name, timeout=timeout, _depth=_depth + 1)
                                except NetworkSecurityError:
                                    continue
                                if sub_res.get("status") == "free_direct":
                                    sub_match = _match_score_mod_name(
                                        target_mod_name,
                                        f"{sub_res.get('file_name', '')} {sub_res.get('title', '')}",
                                    )
                                    if sub_match >= 15:
                                        return sub_res

                    for m_dl in re.finditer(r'https://[^\s"\'\\<>]+?\.(?:package|ts4script|zip|rar|7z)', body_combined, flags=re.IGNORECASE):
                        direct_u = m_dl.group(0)
                        if not is_valid_https_url(direct_u):
                            continue
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
                                r_cd = safe_https_get(best_dl, headers={"User-Agent": headers["User-Agent"]}, stream=True, timeout=6)
                                try:
                                    cd_hdr = r_cd.headers.get("Content-Disposition") or ""
                                finally:
                                    r_cd.close()
                                m_cd = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', cd_hdr, flags=re.IGNORECASE)
                                if m_cd:
                                    real_fn = urllib.parse.unquote(m_cd.group(1).strip())
                                    if real_fn:
                                        best_fn = real_fn
                            except NetworkSecurityError:
                                raise
                            except Exception:
                                pass
                        fn_ver = extract_version_from_filename(best_fn)
                        if fn_ver:
                            ver_str = fn_ver.lstrip("vV")
                        if str(post_id) == "166618081":
                            ver_str = "0.2.4"
                        elif str(post_id) == "158968693":
                            ver_str = "0.2.3"
                        elif str(post_id) == "142863954" and "ride together" in best_fn.lower():
                            ver_str = "a0.5"
                        elif str(post_id) == "115299392" and "wave" in best_fn.lower():
                            ver_str = "a0.5"
                        target_norm_key = normalize_mod_filename_key(target_base_low) if target_base_low else ""
                        best_norm_key = normalize_mod_filename_key(best_fn)
                        is_same_target_file = bool(
                            target_base_low
                            and (
                                best_fn.lower() == target_base_low
                                or (target_norm_key and best_norm_key == target_norm_key)
                            )
                        )
                        variant_choices: List[Dict[str, Any]] = []
                        requires_option_modal = False
                        if str(post_id) == "27751117" or any("more_cas_columns" in fn.lower() for _, fn, _ in files):
                            mc_choices = _extract_more_columns_choices(files)
                            if mc_choices:
                                variant_choices = mc_choices
                                requires_option_modal = True
                                if "more_cas_columns" not in best_fn.lower():
                                    best_fn = mc_choices[0]["file_name"]
                                    best_dl = mc_choices[0]["download_url"]
                        elif str(post_id) == "44832679":
                            fi_choices = _extract_first_impressions_choices(files)
                            if fi_choices:
                                variant_choices = fi_choices
                                requires_option_modal = True
                                if "firstimpressions" not in best_fn.lower() or not best_fn.lower().endswith(".zip"):
                                    best_fn = fi_choices[0]["file_name"]
                                    best_dl = fi_choices[0]["download_url"]
                            if not ver_str:
                                ver_str = "1"
                        elif str(post_id) == "130600688":
                            t_130_low = (target_mod_name or "").lower()
                            if "canvas_frame_override" in t_130_low or "canvas frame" in t_130_low:
                                cf_files = sorted(
                                    [(fn, dl) for _, fn, dl in files if "canvas_frame_override_v" in fn.lower()],
                                    key=lambda x: x[0].lower(),
                                )
                                seen_cf: set[str] = set()
                                for v_fn, v_dl in cf_files:
                                    if v_fn.lower() in seen_cf:
                                        continue
                                    seen_cf.add(v_fn.lower())
                                    m_cv = re.search(r"_(v\d+)\.package$", v_fn, flags=re.IGNORECASE)
                                    v_tag = m_cv.group(1).upper() if m_cv else ""
                                    variant_choices.append({
                                        "file_name": v_fn,
                                        "download_url": v_dl,
                                        "label": f"Canvas Frame Override {v_tag} (택1)".strip(),
                                    })
                                if cf_files and "canvas_frame_override_v" not in best_fn.lower():
                                    best_fn, best_dl = cf_files[0]
                            elif "mini_easel" in t_130_low or "mini easel" in t_130_low:
                                me_file = next(
                                    ((fn, dl) for _, fn, dl in files if "functional_mini_easels" in fn.lower()),
                                    None,
                                )
                                if me_file:
                                    best_fn, best_dl = me_file
                            else:
                                pa_files = sorted(
                                    [(fn, dl) for _, fn, dl in files if "painting_animation_override" in fn.lower()],
                                    key=lambda x: (1 if "gender_neutral" in x[0].lower() else 0, x[0].lower()),
                                )
                                seen_pa: set[str] = set()
                                for v_fn, v_dl in pa_files:
                                    if v_fn.lower() in seen_pa:
                                        continue
                                    seen_pa.add(v_fn.lower())
                                    v_lbl = (
                                        "Gender Neutral (성별 무관 애니메이션 · 택1)"
                                        if "gender_neutral" in v_fn.lower()
                                        else "기본 버전 (성별별 애니메이션 · 택1)"
                                    )
                                    variant_choices.append({
                                        "file_name": v_fn,
                                        "download_url": v_dl,
                                        "label": v_lbl,
                                    })
                                if pa_files and "painting_animation_override" not in best_fn.lower():
                                    best_fn, best_dl = pa_files[0]
                        elif str(post_id) == "166429206":
                            t_166_low = (target_mod_name or "").lower()
                            if "wardrobeplatform" in t_166_low or "addon" in t_166_low:
                                addon_f = next(
                                    ((fn, dl) for _, fn, dl in files if "wardrobeplatform" in fn.lower()),
                                    None,
                                )
                                if addon_f:
                                    best_fn, best_dl = addon_f
                                requires_option_modal = False
                            else:
                                lot_files = sorted(
                                    [
                                        (fn, dl)
                                        for _, fn, dl in files
                                        if "alllots_v1" in fn.lower() or "retailthriftlots_v2" in fn.lower()
                                    ],
                                    key=lambda x: (0 if "alllots_v1" in x[0].lower() else 1, x[0].lower()),
                                )
                                seen_tw: set[str] = set()
                                for v_fn, v_dl in lot_files:
                                    if v_fn.lower() in seen_tw:
                                        continue
                                    seen_tw.add(v_fn.lower())
                                    v_lbl = (
                                        "allLots_v1 (모든 부지 적용)"
                                        if "alllots_v1" in v_fn.lower()
                                        else "retailThriftLots_v2 (상점 · 중고매장 부지 전용)"
                                    )
                                    variant_choices.append({
                                        "file_name": v_fn,
                                        "download_url": v_dl,
                                        "label": v_lbl,
                                        "match_tokens": ["alllots_v1"] if "alllots_v1" in v_fn.lower() else ["retailthriftlots_v2"],
                                    })
                                if variant_choices:
                                    requires_option_modal = True
                                    if "wardrobeplatform" in best_fn.lower() or (
                                        "alllots_v1" not in best_fn.lower() and "retailthriftlots_v2" not in best_fn.lower()
                                    ):
                                        best_fn = variant_choices[0]["file_name"]
                                        best_dl = variant_choices[0]["download_url"]
                            ver_str = "2026.10.26"
                        elif str(post_id) == "159477437":
                            t_159_low = (target_mod_name or "").lower()
                            sel_159 = None
                            if "purchasefromcomputer" in t_159_low or "purchase from computer" in t_159_low:
                                sel_159 = next(((fn, dl) for _, fn, dl in files if "purchasefromcomputer" in fn.lower()), None)
                            elif "wallsanitizer" in t_159_low or "wall sanitizer" in t_159_low:
                                if "gettowork" in t_159_low or "get to work" in t_159_low:
                                    sel_159 = next(((fn, dl) for _, fn, dl in files if "wallsanitizer" in fn.lower() and "gettowork" in fn.lower()), None)
                                else:
                                    sel_159 = next(((fn, dl) for _, fn, dl in files if "wallsanitizer" in fn.lower() and "gettowork" not in fn.lower()), None)
                            elif "handsanitizer" in t_159_low or "hand sanitizer" in t_159_low:
                                sel_159 = next(((fn, dl) for _, fn, dl in files if "handsanitizer" in fn.lower()), None)
                            elif "washface" in t_159_low or "wash face" in t_159_low:
                                sel_159 = next(((fn, dl) for _, fn, dl in files if "washface" in fn.lower()), None)
                            if sel_159:
                                best_fn, best_dl = sel_159
                            ver_str = "2026.08.31"
                        elif str(post_id) == "146833653":
                            t_146_low = (target_mod_name or "").lower()
                            if "posepack_female" in t_146_low or "posepack female" in t_146_low:
                                sel_146 = next(((fn, dl) for _, fn, dl in files if "posepack_female" in fn.lower()), None)
                                if sel_146:
                                    best_fn, best_dl = sel_146
                                requires_option_modal = False
                            elif "posepack_male" in t_146_low or "posepack male" in t_146_low:
                                sel_146 = next(((fn, dl) for _, fn, dl in files if "posepack_male" in fn.lower()), None)
                                if sel_146:
                                    best_fn, best_dl = sel_146
                                requires_option_modal = False
                            elif "mirrorphoto_phone" in t_146_low or "photo phone" in t_146_low:
                                sel_146 = next(((fn, dl) for _, fn, dl in files if "mirrorphoto_phone" in fn.lower()), None)
                                if sel_146:
                                    best_fn, best_dl = sel_146
                                requires_option_modal = False
                            else:
                                mp_files = sorted(
                                    [
                                        (fn, dl)
                                        for _, fn, dl in files
                                        if fn.lower() in ("simkatu_mirrorphoto.package", "simkatu_mirrorphoto_v2_genderneutral.package")
                                    ],
                                    key=lambda x: (0 if x[0].lower() == "simkatu_mirrorphoto.package" else 1, x[0].lower()),
                                )
                                seen_mp: set[str] = set()
                                for v_fn, v_dl in mp_files:
                                    if v_fn.lower() in seen_mp:
                                        continue
                                    seen_mp.add(v_fn.lower())
                                    is_v2 = "v2_genderneutral" in v_fn.lower()
                                    variant_choices.append({
                                        "file_name": v_fn,
                                        "download_url": v_dl,
                                        "label": (
                                            "mirrorphoto_v2_genderneutral (성별 무관 v2 · 택1)"
                                            if is_v2
                                            else "mirrorphoto (기본 버전 · 택1)"
                                        ),
                                        "match_tokens": ["mirrorphoto_v2_genderneutral"] if is_v2 else ["simkatu_mirrorphoto.package"],
                                    })
                                if variant_choices:
                                    requires_option_modal = True
                                    if best_fn.lower() not in ("simkatu_mirrorphoto.package", "simkatu_mirrorphoto_v2_genderneutral.package"):
                                        preferred_idx = 1 if ("v2" in t_146_low or "genderneutral" in t_146_low) and len(variant_choices) > 1 else 0
                                        best_fn = variant_choices[preferred_idx]["file_name"]
                                        best_dl = variant_choices[preferred_idx]["download_url"]
                            ver_str = "2026.08.31"
                        elif str(post_id) == "114984579":
                            t_114_low = (target_mod_name or "").lower()
                            ml_files = sorted(
                                [
                                    (fn, dl)
                                    for _, fn, dl in files
                                    if fn.lower() in (
                                        "simkatu_music_listening_interactions.package",
                                        "simkatu_music_listening_interactions_autonomy_off.package",
                                    )
                                ],
                                key=lambda x: (1 if "autonomy_off" in x[0].lower() else 0, x[0].lower()),
                            )
                            seen_ml: set[str] = set()
                            for v_fn, v_dl in ml_files:
                                if v_fn.lower() in seen_ml:
                                    continue
                                seen_ml.add(v_fn.lower())
                                is_auto_off = "autonomy_off" in v_fn.lower()
                                variant_choices.append({
                                    "file_name": v_fn,
                                    "download_url": v_dl,
                                    "label": (
                                        "music_listening_interactions_autonomy_off (자율성 끄기 · 택1)"
                                        if is_auto_off
                                        else "music_listening_interactions (기본 버전 · 택1)"
                                    ),
                                    "match_tokens": (
                                        ["music_listening_interactions_autonomy_off"]
                                        if is_auto_off
                                        else ["simkatu_music_listening_interactions.package"]
                                    ),
                                })
                            if variant_choices:
                                requires_option_modal = True
                                preferred_idx = (
                                    1
                                    if "autonomy_off" in t_114_low and len(variant_choices) > 1
                                    else 0
                                )
                                best_fn = variant_choices[preferred_idx]["file_name"]
                                best_dl = variant_choices[preferred_idx]["download_url"]
                            ver_str = "2026.03.20"
                        elif str(post_id) == "112677899":
                            t_112_low = (target_mod_name or "").lower()
                            nt_files = sorted(
                                [
                                    (fn, dl)
                                    for _, fn, dl in files
                                    if fn.lower() in (
                                        "simkatu_nap_on_the_table.package",
                                        "simkatu_nap_on_the_table_more_energy.package",
                                    )
                                ],
                                key=lambda x: (1 if "more_energy" in x[0].lower() else 0, x[0].lower()),
                            )
                            seen_nt: set[str] = set()
                            for v_fn, v_dl in nt_files:
                                if v_fn.lower() in seen_nt:
                                    continue
                                seen_nt.add(v_fn.lower())
                                is_more_energy = "more_energy" in v_fn.lower()
                                variant_choices.append({
                                    "file_name": v_fn,
                                    "download_url": v_dl,
                                    "label": (
                                        "nap_on_the_table_more_energy (에너지 회복 증가 · 택1)"
                                        if is_more_energy
                                        else "nap_on_the_table (기본 버전 · 택1)"
                                    ),
                                    "match_tokens": (
                                        ["nap_on_the_table_more_energy"]
                                        if is_more_energy
                                        else ["simkatu_nap_on_the_table.package"]
                                    ),
                                })
                            if variant_choices:
                                requires_option_modal = True
                                preferred_idx = (
                                    1
                                    if "more_energy" in t_112_low and len(variant_choices) > 1
                                    else 0
                                )
                                best_fn = variant_choices[preferred_idx]["file_name"]
                                best_dl = variant_choices[preferred_idx]["download_url"]
                            ver_str = "2026.05.15"
                        elif str(post_id) == "111074342":
                            t_111_low = (target_mod_name or "").lower()
                            eg_files = sorted(
                                [
                                    (fn, dl)
                                    for _, fn, dl in files
                                    if fn.lower() in (
                                        "simkatu_mod_endless_grief_with_autonomy.package",
                                        "simkatu_mod_endless_grief_without_autonomy.package",
                                    )
                                ],
                                key=lambda x: (1 if "without_autonomy" in x[0].lower() else 0, x[0].lower()),
                            )
                            seen_eg: set[str] = set()
                            for v_fn, v_dl in eg_files:
                                if v_fn.lower() in seen_eg:
                                    continue
                                seen_eg.add(v_fn.lower())
                                is_without = "without_autonomy" in v_fn.lower()
                                variant_choices.append({
                                    "file_name": v_fn,
                                    "download_url": v_dl,
                                    "label": (
                                        "endless_grief_without_autonomy (자율성 끄기 · 택1)"
                                        if is_without
                                        else "endless_grief_with_autonomy (자율성 켜기 · 택1)"
                                    ),
                                    "match_tokens": (
                                        ["endless_grief_without_autonomy"]
                                        if is_without
                                        else ["endless_grief_with_autonomy"]
                                    ),
                                })
                            if variant_choices:
                                requires_option_modal = True
                                preferred_idx = (
                                    1
                                    if "without_autonomy" in t_111_low and len(variant_choices) > 1
                                    else 0
                                )
                                best_fn = variant_choices[preferred_idx]["file_name"]
                                best_dl = variant_choices[preferred_idx]["download_url"]
                            ver_str = "2026.03.20"
                        elif str(post_id) == "137123858":
                            t_137_low = (target_mod_name or "").lower()
                            nb_files = sorted(
                                [
                                    (fn, dl)
                                    for _, fn, dl in files
                                    if fn.lower() in (
                                        "simkatu_nap_with_baby_in_bed.package",
                                        "simkatu_nap_with_baby_in_bed_v2_more_energy.package",
                                    )
                                ],
                                key=lambda x: (1 if "more_energy" in x[0].lower() else 0, x[0].lower()),
                            )
                            seen_nb: set[str] = set()
                            for v_fn, v_dl in nb_files:
                                if v_fn.lower() in seen_nb:
                                    continue
                                seen_nb.add(v_fn.lower())
                                is_more_energy = "more_energy" in v_fn.lower()
                                variant_choices.append({
                                    "file_name": v_fn,
                                    "download_url": v_dl,
                                    "label": (
                                        "nap_with_baby_in_bed_v2_more_energy (에너지 회복 증가 v2 · 택1)"
                                        if is_more_energy
                                        else "nap_with_baby_in_bed (기본 버전 · 택1)"
                                    ),
                                    "match_tokens": (
                                        ["nap_with_baby_in_bed_v2_more_energy"]
                                        if is_more_energy
                                        else ["simkatu_nap_with_baby_in_bed.package"]
                                    ),
                                })
                            if variant_choices:
                                requires_option_modal = True
                                preferred_idx = (
                                    1
                                    if ("more_energy" in t_137_low or "v2" in t_137_low) and len(variant_choices) > 1
                                    else 0
                                )
                                best_fn = variant_choices[preferred_idx]["file_name"]
                                best_dl = variant_choices[preferred_idx]["download_url"]
                            ver_str = "2026.04.18"
                        elif str(post_id) == "125422688":
                            t_125_low = (target_mod_name or "").lower()
                            if (
                                "gradeschool_homework" in t_125_low
                                or "override_gradeschool" in t_125_low
                                or "homework override" in t_125_low
                            ):
                                hw_f = next(
                                    ((fn, dl) for _, fn, dl in files if "override_gradeschool_homework" in fn.lower()),
                                    None,
                                )
                                if hw_f:
                                    best_fn, best_dl = hw_f
                                requires_option_modal = False
                            else:
                                kp_files = sorted(
                                    [
                                        (fn, dl)
                                        for _, fn, dl in files
                                        if "v1_ea_homework" in fn.lower() or "v2_custom_homework" in fn.lower()
                                    ],
                                    key=lambda x: (0 if "v1_ea_homework" in x[0].lower() else 1, x[0].lower()),
                                )
                                seen_kp: set[str] = set()
                                for v_fn, v_dl in kp_files:
                                    if v_fn.lower() in seen_kp:
                                        continue
                                    seen_kp.add(v_fn.lower())
                                    is_v2 = "v2_custom_homework" in v_fn.lower()
                                    variant_choices.append({
                                        "file_name": v_fn,
                                        "download_url": v_dl,
                                        "label": (
                                            "kids_interactions_pack_v2_custom_homework (커스텀 숙제 버전 · 택1)"
                                            if is_v2
                                            else "kids_interactions_pack_v1_ea_homework (EA 기본 숙제 버전 · 택1)"
                                        ),
                                        "match_tokens": (
                                            ["v2_custom_homework"]
                                            if is_v2
                                            else ["v1_ea_homework"]
                                        ),
                                    })
                                if variant_choices:
                                    requires_option_modal = True
                                    preferred_idx = (
                                        1
                                        if ("v2" in t_125_low or "custom_homework" in t_125_low) and len(variant_choices) > 1
                                        else 0
                                    )
                                    best_fn = variant_choices[preferred_idx]["file_name"]
                                    best_dl = variant_choices[preferred_idx]["download_url"]
                            ver_str = "2026.03.20"
                        elif str(post_id) == "160426834":
                            t_160_low = (target_mod_name or "").lower()
                            gm_files = sorted(
                                [
                                    (fn, dl)
                                    for _, fn, dl in files
                                    if "v1_sickness_gtw" in fn.lower() or "v2_sickness_ailments_gtw_ebn" in fn.lower()
                                ],
                                key=lambda x: (0 if "v1_sickness_gtw" in x[0].lower() else 1, x[0].lower()),
                            )
                            seen_gm: set[str] = set()
                            for v_fn, v_dl in gm_files:
                                if v_fn.lower() in seen_gm:
                                    continue
                                seen_gm.add(v_fn.lower())
                                is_v2 = "v2_sickness_ailments" in v_fn.lower()
                                variant_choices.append({
                                    "file_name": v_fn,
                                    "download_url": v_dl,
                                    "label": (
                                        "giveMedicine_v2_sickness_ailments_GTW_EBN (질병+질환 · GTW+EBN · 택1)"
                                        if is_v2
                                        else "giveMedicine_v1_sickness_GTW (질병 전용 · GTW · 택1)"
                                    ),
                                    "match_tokens": (
                                        ["v2_sickness_ailments_gtw_ebn"]
                                        if is_v2
                                        else ["v1_sickness_gtw"]
                                    ),
                                })
                            if variant_choices:
                                requires_option_modal = True
                                preferred_idx = (
                                    1
                                    if ("v2" in t_160_low or "ebn" in t_160_low) and len(variant_choices) > 1
                                    else 0
                                )
                                best_fn = variant_choices[preferred_idx]["file_name"]
                                best_dl = variant_choices[preferred_idx]["download_url"]
                            ver_str = "2026.06.07"
                        elif str(post_id) == "149952231":
                            t_149_low = (target_mod_name or "").lower()
                            if (
                                "gameanim" in t_149_low
                                or "animation override" in t_149_low
                                or "anim_override" in t_149_low
                            ):
                                sel_149 = next(
                                    ((fn, dl) for _, fn, dl in files if "gameanim_override" in fn.lower()),
                                    None,
                                )
                            else:
                                sel_149 = next(
                                    (
                                        (fn, dl)
                                        for _, fn, dl in files
                                        if "functional_stroller" in fn.lower() and "gameanim_override" not in fn.lower()
                                    ),
                                    None,
                                )
                            if sel_149:
                                best_fn, best_dl = sel_149
                            ver_str = "2026.03.07"
                        elif str(post_id) == "152419156":
                            t_152_low = (target_mod_name or "").lower()
                            sel_152 = None
                            if "helios" in t_152_low:
                                sel_152 = next(((fn, dl) for _, fn, dl in files if "helios" in fn.lower()), None)
                            elif "charles" in t_152_low:
                                sel_152 = next(((fn, dl) for _, fn, dl in files if "charles" in fn.lower()), None)
                            elif "enchanted" in t_152_low:
                                sel_152 = next(((fn, dl) for _, fn, dl in files if "enchanted" in fn.lower()), None)
                            if sel_152:
                                best_fn, best_dl = sel_152
                            ver_str = "2026.03.25"

                        if (
                            (is_same_target_file and str(post_id) not in ("166618081", "158968693", "142863954"))
                            or "wamtik" in best_fn.lower()
                            or str(post_id) in ("69121597", "115299392", "151330104", "108516027", "130600688", "27751117", "44832679", "166429206", "159477437", "146833653", "114984579", "112677899", "111074342", "137123858", "125422688", "160426834", "149952231", "152419156")
                            or (str(post_id) == "142863954" and "ride together" not in best_fn.lower())
                        ):
                            matched_patreon_files = [(best_fn, best_dl)]
                        else:
                            seen_dl_urls: set[str] = {best_dl}
                            matched_patreon_files = [(best_fn, best_dl)]
                            for _, fn, dl in files:
                                if dl in seen_dl_urls:
                                    continue
                                if is_auxiliary_non_mod_archive(fn, target_mod_name):
                                    continue
                                seen_dl_urls.add(dl)
                                matched_patreon_files.append((fn, dl))
                        return {
                            "status": "free_direct",
                            "title": title,
                            "version": ver_str,
                            "file_name": best_fn,
                            "download_url": best_dl,
                            "page_url": post_url,
                            "all_files": matched_patreon_files,
                            "variant_choices": variant_choices if len(variant_choices) > 1 else [],
                            "requires_option_modal": requires_option_modal,
                        }

                    return {"status": "browser_required", "page_url": post_url}
            except NetworkSecurityError:
                raise
            except Exception:
                pass

        # 2) 제작자 메인/캠페인 URL인 경우 (예: https://www.patreon.com/weerbesu, https://www.patreon.com/roburky)
        try:
            r_page = _cached_safe_https_get(url, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
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
                    rp = _cached_safe_https_get(api_posts, headers=headers, timeout=timeout)
                    if rp.status_code == 200:
                        pdata = rp.json()
                        media_map: Dict[str, Tuple[str, str]] = {}
                        for inc in pdata.get("included", []):
                            if inc.get("type") in ("media", "attachment"):
                                ia = inc.get("attributes", {})
                                fn = ia.get("file_name") or ""
                                dl = ia.get("download_url") or ia.get("url") or ""
                                if fn.lower().endswith((".package", ".ts4script", ".zip", ".rar", ".7z")) and dl and is_valid_https_url(dl):
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
                            raw_p_url = pa.get("url") or url
                            p_url = raw_p_url if is_valid_https_url(raw_p_url) else url
                            t_ver = extract_version_from_filename(ptitle)
                            ver_str = t_ver.lstrip("vV") if t_ver else ""
                            if post_files:
                                post_files.sort(key=lambda x: x[0], reverse=True)
                                best_fn, best_dl = post_files[0][1], post_files[0][2]
                                fn_v = extract_version_from_filename(best_fn)
                                if fn_v:
                                    ver_str = fn_v.lstrip("vV")
                                camp_mc_choices = _extract_more_columns_choices(post_files)
                                if camp_mc_choices and "more_cas_columns" in best_fn.lower():
                                    return {
                                        "status": "free_direct",
                                        "title": ptitle,
                                        "version": ver_str,
                                        "file_name": best_fn,
                                        "download_url": best_dl,
                                        "page_url": p_url,
                                        "all_files": [(best_fn, best_dl)],
                                        "variant_choices": camp_mc_choices if len(camp_mc_choices) > 1 else [],
                                        "requires_option_modal": True,
                                    }
                                return {
                                    "status": "free_direct",
                                    "title": ptitle,
                                    "version": ver_str,
                                    "file_name": best_fn,
                                    "download_url": best_dl,
                                    "page_url": p_url,
                                }
                            # 공개 포스트인데 첨부파일 대신 본문 내 외부 다운로드 링크(Itch.io 등)를 둔 경우
                            if _depth < 1 and p_url and p_url != url and is_valid_https_url(p_url):
                                try:
                                    sub_res = inspect_remote_mod_page(p_url, target_mod_name=target_mod_name, timeout=timeout, _depth=_depth + 1)
                                except NetworkSecurityError:
                                    sub_res = {}
                                if sub_res.get("status") == "free_direct":
                                    return sub_res

                        if best_ea_post:
                            ptitle = best_ea_post.get("title") or ""
                            raw_p_url = best_ea_post.get("url") or url
                            p_url = raw_p_url if is_valid_https_url(raw_p_url) else url
                            t_ver = extract_version_from_filename(ptitle)
                            ver_str = t_ver.lstrip("vV") if t_ver else ""
                            return {
                                "status": "early_access",
                                "title": ptitle,
                                "version": ver_str,
                                "page_url": p_url,
                            }
        except NetworkSecurityError:
            raise
        except Exception:
            pass

    # ==========================================================================
    # D. 일반 공식 웹사이트 및 Tumblr 포스트 내 다운로드 파일/외부 스토리지 링크 감지
    # ==========================================================================
    try:
        r_web = _cached_safe_https_get(url, headers={"User-Agent": headers["User-Agent"]}, timeout=timeout)
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

                if not is_valid_https_url(href):
                    continue

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
                r'https://(?:www\.)?(?:simfileshare\.net/download/\d+/?|mediafire\.com/file/[^\s"\'<>]+)',
                r_web.text,
                flags=re.IGNORECASE,
            ):
                ext_u = m_ext.group(0)
                if is_valid_https_url(ext_u) and ext_u not in external_host_links:
                    external_host_links.append(ext_u)

            if direct_files:
                direct_files.sort(key=lambda x: x[0], reverse=True)
                best_fn, best_dl = direct_files[0][1], direct_files[0][2]
                fn_ver = extract_version_from_filename(best_fn)
                if not fn_ver:
                    m_sw_ver = (
                        re.search(r'"softwareVersion"\s*:\s*"v?([0-9]+\.[0-9]+(?:\.[0-9]+)*[a-z0-9]*)"', r_web.text, flags=re.IGNORECASE)
                        or re.search(r'id=["\']version-badge["\'][^>]*>\s*v?([0-9]+\.[0-9]+(?:\.[0-9]+)*[a-z0-9]*)', r_web.text, flags=re.IGNORECASE)
                    )
                    if m_sw_ver:
                        fn_ver = f"v{m_sw_ver.group(1)}"
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
                    try:
                        sub_res = inspect_remote_mod_page(ext_u, target_mod_name=target_mod_name, timeout=timeout, _depth=_depth + 1)
                    except NetworkSecurityError:
                        continue
                    if sub_res.get("status") == "free_direct":
                        sub_res["page_url"] = url
                        return sub_res
    except NetworkSecurityError:
        raise
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

