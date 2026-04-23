# Ingredient Mapping

ユーザー入力の食材名を menu-catalog.json の `ingredient_tags` に変換する辞書 (人間向けドキュメント)。
プログラム側の正本は `app/agents/ingredient_resolver.py` の `INGREDIENT_ALIASES` 辞書。
ここはレビュー用に同じ内容を Markdown で並べる。

## 野菜

| タグ | 表記ゆれ |
|---|---|
| `jagaimo` | じゃがいも / ジャガイモ / じゃが芋 / 馬鈴薯 / potato / メークイン / 男爵 |
| `tamanegi` | 玉ねぎ / タマネギ / 玉葱 / たまねぎ / onion |
| `ninjin` | にんじん / ニンジン / 人参 / carrot |
| `kabocha` | かぼちゃ / カボチャ / 南瓜 / pumpkin |
| `daikon` | 大根 / だいこん / ダイコン / 白首大根 / radish |
| `hakusai` | 白菜 / はくさい / chinese cabbage |
| `kyabetsu` | キャベツ / きゃべつ / cabbage |
| `renkon` | れんこん / レンコン / 蓮根 |
| `gobou` | ごぼう / ゴボウ / 牛蒡 |
| `satsumaimo` | さつまいも / サツマイモ / 薩摩芋 / sweet potato |
| `negi` | ねぎ / ネギ / 葱 / 長ねぎ / 青ねぎ / 万能ねぎ |
| `tomato` | トマト / とまと / ホールトマト / カットトマト / tomato |
| `nasu` | なす / ナス / 茄子 / eggplant |
| `zucchini` | ズッキーニ / zucchini |
| `piman` | ピーマン / パプリカ / bell pepper |
| `shimeji` | しめじ / シメジ / 占地 |
| `shiitake` | しいたけ / シイタケ / 椎茸 |
| `enoki` | えのき / エノキ / 榎茸 |
| `maitake` | まいたけ / マイタケ / 舞茸 |

## 肉・魚

| タグ | 表記ゆれ |
|---|---|
| `gyuniku` | 牛肉 / ビーフ / beef / 牛切り落とし / 牛こま |
| `butaniku` | 豚肉 / ポーク / pork / 豚バラ / 豚こま / 豚ロース |
| `toriniku` | 鶏肉 / チキン / 鶏もも / 鶏むね / 鶏ささみ / 手羽元 / 手羽先 |
| `hikiniku` | ひき肉 / 挽肉 / 合いびき肉 |
| `sake` | 鮭 / サケ / salmon |
| `saba` | さば / サバ / 鯖 / mackerel |
| `tara` | たら / タラ / 鱈 / cod |

## 加工品・その他

| タグ | 表記ゆれ |
|---|---|
| `tofu` | 豆腐 / とうふ / 絹ごし豆腐 / 木綿豆腐 / tofu |
| `abura_age` | 油揚げ / あぶらあげ |
| `konnyaku` | こんにゃく / コンニャク / 蒟蒻 |
| `shiratake` | しらたき / シラタキ / 白滝 |
| `tamago` | 卵 / たまご / 玉子 / egg |
| `miso` | 味噌 / みそ |
| `shoyu` | 醤油 / しょうゆ / soy sauce |
| `gyunyu` | 牛乳 / ぎゅうにゅう / ミルク / milk |
| `kome` | 米 / こめ / rice / 白米 |
| `pasta` | パスタ / ぱすた / spaghetti / スパゲッティ |
| `ninniku` | にんにく / ニンニク / garlic |
| `shouga` | しょうが / ショウガ / 生姜 / ginger |

## 拡張時の注意

- 1 タグは 1 食材カテゴリに対応させ、部位 (鶏もも vs 鶏むね) は同一タグでまとめる (Phase 1)
- 「ピーマン」と「パプリカ」は栄養・調理性質が近いので同一タグでよい
- 「玉ねぎ」と「ねぎ」は別物なので別タグにする (味噌汁の代用にしない)
- 新タグを追加する際は `INGREDIENT_ALIASES` と `menu-catalog.json` の両方に登録する
