"""data/skills/hotcook-recipes/menu-catalog.json を生成する。

Phase 1 では **手動キュレーションの 30 件** をシードとして登録する。
収録基準:
  - シャープ公式メニューサイト / KN-HW24H 取扱説明書に記載されている事実情報のみ
    (メニュー番号 / 名称 / カテゴリ / 調理時間 / まぜ技要否 / 予約調理可否)
  - 詳細手順 / 分量 / 写真は格納しない (著作権配慮)
  - `verified=False` を初期値とし、レビュー後に手動で True に更新する

実行方法:
  uv run python scripts/seed_menu_catalog.py

出力:
  data/skills/hotcook-recipes/menu-catalog.json (上書き)

注意:
  ここに記載した menu_no / cook_minutes 等の値は公開情報を参考にした **下書き** です。
  実機・取扱説明書で必ず照合し、誤りがあれば修正の上 `verified=True` に上げてください。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "app"))

from models.menu import HotcookMenu, MenuCatalog  # noqa: E402

OUTPUT_PATH = REPO_ROOT / "data" / "skills" / "hotcook-recipes" / "menu-catalog.json"


# 30 メニュー (Phase 1 シード)。
# menu_no / cook_minutes / mixer_required / reservation_ok は公開情報 (シャープ公式
# メニュー一覧 / 取扱説明書) を参考にした下書き。verified=False で出荷し、人手で照合する。
SEED_MENUS: list[dict] = [
    # ── 煮物 (和風) 6件 ─────────────────────────────────────────────
    {
        "menu_no": "001", "name": "肉じゃが", "name_kana": "ニクジャガ",
        "category": "nimono", "cook_minutes": 35,
        "reservation_ok": True, "mixer_required": True, "serves": 4,
        "main_ingredients": ["じゃがいも", "牛肉", "玉ねぎ"],
        "optional_ingredients": ["にんじん", "しらたき", "絹さや"],
        "ingredient_tags": ["jagaimo", "gyuniku", "tamanegi", "ninjin", "shiratake"],
        "skill_tags": ["定番", "和食"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "002", "name": "筑前煮", "name_kana": "チクゼンニ",
        "category": "nimono", "cook_minutes": 30,
        "reservation_ok": True, "mixer_required": True, "serves": 4,
        "main_ingredients": ["鶏肉", "れんこん", "ごぼう", "にんじん"],
        "optional_ingredients": ["こんにゃく", "しいたけ"],
        "ingredient_tags": ["toriniku", "renkon", "gobou", "ninjin", "konnyaku", "shiitake"],
        "skill_tags": ["和食", "根菜たっぷり"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "003", "name": "豚の角煮", "name_kana": "ブタノカクニ",
        "category": "nimono", "cook_minutes": 90,
        "reservation_ok": False, "mixer_required": False, "serves": 4,
        "main_ingredients": ["豚バラ肉", "しょうが", "ねぎ"],
        "optional_ingredients": ["ゆで卵", "大根"],
        "ingredient_tags": ["butaniku", "shouga", "negi", "tamago", "daikon"],
        "skill_tags": ["じっくり煮込み"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "004", "name": "おでん", "name_kana": "オデン",
        "category": "nimono", "cook_minutes": 60,
        "reservation_ok": True, "mixer_required": False, "serves": 4,
        "main_ingredients": ["大根", "卵", "こんにゃく"],
        "optional_ingredients": ["はんぺん", "ちくわ", "厚揚げ"],
        "ingredient_tags": ["daikon", "tamago", "konnyaku"],
        "skill_tags": ["冬", "和食"],
        "season_tags": ["autumn", "winter"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "005", "name": "肉豆腐", "name_kana": "ニクドウフ",
        "category": "nimono", "cook_minutes": 25,
        "reservation_ok": True, "mixer_required": True, "serves": 3,
        "main_ingredients": ["牛肉", "豆腐", "玉ねぎ"],
        "optional_ingredients": ["しらたき", "ねぎ"],
        "ingredient_tags": ["gyuniku", "tofu", "tamanegi", "shiratake", "negi"],
        "skill_tags": ["和食", "丼にも"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "006", "name": "さばの味噌煮", "name_kana": "サバノミソニ",
        "category": "nimono", "cook_minutes": 25,
        "reservation_ok": False, "mixer_required": False, "serves": 2,
        "main_ingredients": ["さば", "しょうが", "味噌"],
        "optional_ingredients": ["ねぎ"],
        "ingredient_tags": ["saba", "shouga", "miso", "negi"],
        "skill_tags": ["和食", "魚"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },

    # ── カレー・シチュー 5件 ────────────────────────────────────────
    {
        "menu_no": "010", "name": "無水カレー", "name_kana": "ムスイカレー",
        "category": "curry_stew", "cook_minutes": 65,
        "reservation_ok": True, "mixer_required": True, "serves": 4,
        "main_ingredients": ["鶏肉", "玉ねぎ", "トマト", "にんじん"],
        "optional_ingredients": ["セロリ", "ズッキーニ"],
        "ingredient_tags": ["toriniku", "tamanegi", "tomato", "ninjin", "zucchini"],
        "skill_tags": ["無水", "看板メニュー"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "011", "name": "欧風ビーフカレー", "name_kana": "オウフウビーフカレー",
        "category": "curry_stew", "cook_minutes": 80,
        "reservation_ok": True, "mixer_required": True, "serves": 4,
        "main_ingredients": ["牛肉", "玉ねぎ", "にんじん", "じゃがいも"],
        "optional_ingredients": ["マッシュルーム"],
        "ingredient_tags": ["gyuniku", "tamanegi", "ninjin", "jagaimo"],
        "skill_tags": ["定番", "じっくり"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "012", "name": "クリームシチュー", "name_kana": "クリームシチュー",
        "category": "curry_stew", "cook_minutes": 45,
        "reservation_ok": True, "mixer_required": True, "serves": 4,
        "main_ingredients": ["鶏肉", "玉ねぎ", "にんじん", "じゃがいも", "牛乳"],
        "optional_ingredients": ["ブロッコリー"],
        "ingredient_tags": ["toriniku", "tamanegi", "ninjin", "jagaimo", "gyunyu"],
        "skill_tags": ["定番", "洋食"],
        "season_tags": ["autumn", "winter"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "013", "name": "ハヤシライス", "name_kana": "ハヤシライス",
        "category": "curry_stew", "cook_minutes": 50,
        "reservation_ok": True, "mixer_required": True, "serves": 4,
        "main_ingredients": ["牛肉", "玉ねぎ", "マッシュルーム"],
        "optional_ingredients": ["トマト"],
        "ingredient_tags": ["gyuniku", "tamanegi", "tomato"],
        "skill_tags": ["洋食"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "014", "name": "豚バラ大根のうま煮", "name_kana": "ブタバラダイコンノウマニ",
        "category": "curry_stew", "cook_minutes": 35,
        "reservation_ok": True, "mixer_required": True, "serves": 3,
        "main_ingredients": ["豚バラ肉", "大根", "しょうが"],
        "optional_ingredients": ["にんじん"],
        "ingredient_tags": ["butaniku", "daikon", "shouga", "ninjin"],
        "skill_tags": ["和食", "じっくり"],
        "season_tags": ["autumn", "winter"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },

    # ── スープ 5件 ──────────────────────────────────────────────────
    {
        "menu_no": "020", "name": "豚汁", "name_kana": "トンジル",
        "category": "soup", "cook_minutes": 25,
        "reservation_ok": True, "mixer_required": True, "serves": 4,
        "main_ingredients": ["豚肉", "大根", "にんじん", "ごぼう", "味噌"],
        "optional_ingredients": ["こんにゃく", "ねぎ", "豆腐"],
        "ingredient_tags": ["butaniku", "daikon", "ninjin", "gobou", "miso", "konnyaku", "negi", "tofu"],
        "skill_tags": ["和食", "汁物"],
        "season_tags": ["autumn", "winter"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "021", "name": "ミネストローネ", "name_kana": "ミネストローネ",
        "category": "soup", "cook_minutes": 30,
        "reservation_ok": True, "mixer_required": True, "serves": 4,
        "main_ingredients": ["トマト", "玉ねぎ", "にんじん", "セロリ"],
        "optional_ingredients": ["キャベツ", "ベーコン", "豆"],
        "ingredient_tags": ["tomato", "tamanegi", "ninjin", "kyabetsu"],
        "skill_tags": ["洋食", "野菜たっぷり"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "022", "name": "かぼちゃのポタージュ", "name_kana": "カボチャノポタージュ",
        "category": "soup", "cook_minutes": 30,
        "reservation_ok": False, "mixer_required": True, "serves": 3,
        "main_ingredients": ["かぼちゃ", "玉ねぎ", "牛乳"],
        "optional_ingredients": ["生クリーム"],
        "ingredient_tags": ["kabocha", "tamanegi", "gyunyu"],
        "skill_tags": ["洋食", "ポタージュ"],
        "season_tags": ["autumn", "winter"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "023", "name": "コーンスープ", "name_kana": "コーンスープ",
        "category": "soup", "cook_minutes": 25,
        "reservation_ok": False, "mixer_required": True, "serves": 3,
        "main_ingredients": ["コーン", "玉ねぎ", "牛乳"],
        "optional_ingredients": ["バター"],
        "ingredient_tags": ["tamanegi", "gyunyu"],
        "skill_tags": ["洋食", "ポタージュ"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "024", "name": "玉ねぎとベーコンのスープ", "name_kana": "タマネギトベーコンノスープ",
        "category": "soup", "cook_minutes": 30,
        "reservation_ok": True, "mixer_required": True, "serves": 3,
        "main_ingredients": ["玉ねぎ", "ベーコン"],
        "optional_ingredients": ["パセリ"],
        "ingredient_tags": ["tamanegi"],
        "skill_tags": ["洋食"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },

    # ── 蒸し料理 4件 ────────────────────────────────────────────────
    {
        "menu_no": "030", "name": "蒸し鶏", "name_kana": "ムシドリ",
        "category": "steam", "cook_minutes": 30,
        "reservation_ok": False, "mixer_required": False, "serves": 2,
        "main_ingredients": ["鶏むね肉"],
        "optional_ingredients": ["ねぎ", "しょうが"],
        "ingredient_tags": ["toriniku", "negi", "shouga"],
        "skill_tags": ["蒸し", "ヘルシー"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "031", "name": "蒸し野菜", "name_kana": "ムシヤサイ",
        "category": "steam", "cook_minutes": 20,
        "reservation_ok": False, "mixer_required": False, "serves": 3,
        "main_ingredients": ["かぼちゃ", "にんじん", "じゃがいも"],
        "optional_ingredients": ["さつまいも", "ブロッコリー"],
        "ingredient_tags": ["kabocha", "ninjin", "jagaimo", "satsumaimo"],
        "skill_tags": ["蒸し", "副菜"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "032", "name": "茶碗蒸し", "name_kana": "チャワンムシ",
        "category": "steam", "cook_minutes": 20,
        "reservation_ok": False, "mixer_required": False, "serves": 4,
        "main_ingredients": ["卵", "鶏肉"],
        "optional_ingredients": ["しいたけ", "ぎんなん", "三つ葉"],
        "ingredient_tags": ["tamago", "toriniku", "shiitake"],
        "skill_tags": ["蒸し", "和食"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "033", "name": "シュウマイ", "name_kana": "シュウマイ",
        "category": "steam", "cook_minutes": 30,
        "reservation_ok": False, "mixer_required": False, "serves": 4,
        "main_ingredients": ["豚ひき肉", "玉ねぎ"],
        "optional_ingredients": ["しいたけ", "シュウマイの皮"],
        "ingredient_tags": ["hikiniku", "tamanegi", "shiitake"],
        "skill_tags": ["蒸し", "中華"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },

    # ── 麺・米 3件 ─────────────────────────────────────────────────
    {
        "menu_no": "040", "name": "ミートソース", "name_kana": "ミートソース",
        "category": "pasta_rice", "cook_minutes": 35,
        "reservation_ok": True, "mixer_required": True, "serves": 4,
        "main_ingredients": ["合いびき肉", "玉ねぎ", "トマト"],
        "optional_ingredients": ["にんじん", "セロリ", "にんにく"],
        "ingredient_tags": ["hikiniku", "tamanegi", "tomato", "ninjin", "ninniku"],
        "skill_tags": ["洋食", "パスタ"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "041", "name": "カルボナーラ", "name_kana": "カルボナーラ",
        "category": "pasta_rice", "cook_minutes": 25,
        "reservation_ok": False, "mixer_required": True, "serves": 2,
        "main_ingredients": ["パスタ", "卵", "ベーコン"],
        "optional_ingredients": ["黒こしょう", "粉チーズ"],
        "ingredient_tags": ["pasta", "tamago"],
        "skill_tags": ["洋食", "パスタ"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "042", "name": "リゾット", "name_kana": "リゾット",
        "category": "pasta_rice", "cook_minutes": 35,
        "reservation_ok": False, "mixer_required": True, "serves": 2,
        "main_ingredients": ["米", "玉ねぎ", "鶏肉"],
        "optional_ingredients": ["きのこ", "粉チーズ"],
        "ingredient_tags": ["kome", "tamanegi", "toriniku", "shimeji", "shiitake"],
        "skill_tags": ["洋食"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },

    # ── 発酵・低温 4件 ─────────────────────────────────────────────
    {
        "menu_no": "050", "name": "鶏ハム (低温調理)", "name_kana": "トリハム",
        "category": "ferment_lowtemp", "cook_minutes": 80,
        "reservation_ok": False, "mixer_required": False, "serves": 3,
        "main_ingredients": ["鶏むね肉"],
        "optional_ingredients": ["ハーブ", "オリーブオイル"],
        "ingredient_tags": ["toriniku"],
        "skill_tags": ["低温調理", "作り置き"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "051", "name": "ローストビーフ (低温調理)", "name_kana": "ローストビーフ",
        "category": "ferment_lowtemp", "cook_minutes": 90,
        "reservation_ok": False, "mixer_required": False, "serves": 4,
        "main_ingredients": ["牛もも肉"],
        "optional_ingredients": ["にんにく", "ローズマリー"],
        "ingredient_tags": ["gyuniku", "ninniku"],
        "skill_tags": ["低温調理", "ごちそう"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "052", "name": "ヨーグルト", "name_kana": "ヨーグルト",
        "category": "ferment_lowtemp", "cook_minutes": 420,  # 7時間
        "reservation_ok": False, "mixer_required": False, "serves": 6,
        "main_ingredients": ["牛乳", "プレーンヨーグルト"],
        "optional_ingredients": [],
        "ingredient_tags": ["gyunyu"],
        "skill_tags": ["発酵"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "053", "name": "甘酒", "name_kana": "アマザケ",
        "category": "ferment_lowtemp", "cook_minutes": 360,  # 6時間
        "reservation_ok": False, "mixer_required": False, "serves": 4,
        "main_ingredients": ["米麹", "ご飯"],
        "optional_ingredients": [],
        "ingredient_tags": ["kome"],
        "skill_tags": ["発酵"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },

    # ── 副菜 3件 ───────────────────────────────────────────────────
    {
        "menu_no": "060", "name": "ラタトゥイユ", "name_kana": "ラタトゥイユ",
        "category": "side_dish", "cook_minutes": 30,
        "reservation_ok": True, "mixer_required": True, "serves": 4,
        "main_ingredients": ["なす", "ズッキーニ", "トマト", "玉ねぎ"],
        "optional_ingredients": ["パプリカ", "にんにく"],
        "ingredient_tags": ["nasu", "zucchini", "tomato", "tamanegi", "piman", "ninniku"],
        "skill_tags": ["無水", "洋食"],
        "season_tags": ["summer"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "061", "name": "きんぴらごぼう", "name_kana": "キンピラゴボウ",
        "category": "side_dish", "cook_minutes": 20,
        "reservation_ok": False, "mixer_required": True, "serves": 3,
        "main_ingredients": ["ごぼう", "にんじん"],
        "optional_ingredients": ["ごま", "唐辛子"],
        "ingredient_tags": ["gobou", "ninjin"],
        "skill_tags": ["和食", "副菜"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
    {
        "menu_no": "062", "name": "ナムル", "name_kana": "ナムル",
        "category": "side_dish", "cook_minutes": 15,
        "reservation_ok": False, "mixer_required": False, "serves": 3,
        "main_ingredients": ["もやし", "ほうれん草", "にんじん"],
        "optional_ingredients": ["ごま油"],
        "ingredient_tags": ["ninjin"],
        "skill_tags": ["副菜", "韓国"],
        "official_source": "KN-HW24H 取扱説明書 / シャープ公式メニュー",
    },
]


def build_catalog() -> MenuCatalog:
    menus = [HotcookMenu.model_validate(d) for d in SEED_MENUS]
    return MenuCatalog(version="0.1.0", menus=menus)


def main() -> int:
    catalog = build_catalog()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        catalog.model_dump_json(indent=2),
        encoding="utf-8",
    )
    print(f"wrote {len(catalog.menus)} menus to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
