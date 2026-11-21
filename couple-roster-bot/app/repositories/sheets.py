"""Google スプレッドシート版の `RosterRepo` 実装。

`gspread` を薄くラップする。ワークシートの 1 行目を `FIELD_ORDER` のヘッダとし、
2 行目以降を 1 レコードとして扱う。

依存 (`gspread` / `google-auth`) は `sheets` extra。テストや in-memory 運用では
import されないよう、モジュール内で遅延 import する。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models import FIELD_ORDER, RosterEntry

if TYPE_CHECKING:  # 型チェック時のみ。実行時は遅延 import。
    import gspread


def _open_worksheet(
    spreadsheet_id: str,
    worksheet_name: str,
    credentials_path: str,
) -> gspread.Worksheet:
    """認証してワークシートを開く。無ければ作成しヘッダ行を書き込む。"""
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    if credentials_path:
        creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
        client = gspread.authorize(creds)
    else:
        # ADC (Cloud Run のサービスアカウント等)。
        import google.auth

        adc_creds, _ = google.auth.default(scopes=scopes)
        client = gspread.authorize(adc_creds)

    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=worksheet_name, rows=1, cols=len(FIELD_ORDER)
        )
        worksheet.append_row(list(FIELD_ORDER))
    return worksheet


class SheetsRosterRepo:
    """スプレッドシートを永続化先とする名簿リポジトリ。

    `worksheet` を差し込めるようにして、テストでモック可能にする。
    通常は `from_settings` で構築する。
    """

    def __init__(self, worksheet: gspread.Worksheet) -> None:
        self._ws = worksheet

    @classmethod
    def from_settings(
        cls,
        *,
        spreadsheet_id: str,
        worksheet_name: str,
        credentials_path: str,
    ) -> SheetsRosterRepo:
        if not spreadsheet_id:
            raise ValueError("spreadsheet_id is required for sheets storage mode")
        ws = _open_worksheet(spreadsheet_id, worksheet_name, credentials_path)
        return cls(ws)

    def list_all(self) -> list[RosterEntry]:
        records = self._ws.get_all_records(expected_headers=list(FIELD_ORDER))
        return [RosterEntry.from_row({k: str(v) for k, v in row.items()}) for row in records]

    def get(self, entry_id: str) -> RosterEntry | None:
        for entry in self.list_all():
            if entry.id == entry_id:
                return entry
        return None

    def add(self, entry: RosterEntry) -> None:
        self._ws.append_row(entry.to_row(), value_input_option="USER_ENTERED")

    def add_many(self, entries: list[RosterEntry]) -> None:
        if not entries:
            return
        rows = [entry.to_row() for entry in entries]
        self._ws.append_rows(rows, value_input_option="USER_ENTERED")

    def update(self, entry: RosterEntry) -> bool:
        row_number = self._find_row_number(entry.id)
        if row_number is None:
            return False
        self._ws.update(
            f"A{row_number}",
            [entry.to_row()],
            value_input_option="USER_ENTERED",
        )
        return True

    def delete(self, entry_id: str) -> bool:
        row_number = self._find_row_number(entry_id)
        if row_number is None:
            return False
        self._ws.delete_rows(row_number)
        return True

    def _find_row_number(self, entry_id: str) -> int | None:
        """id 列（A 列）から一致する行番号（1 始まり、ヘッダ込み）を探す。"""
        id_column = self._ws.col_values(1)  # ヘッダ含む id 列
        for index, value in enumerate(id_column):
            if index == 0:
                continue  # ヘッダ行
            if value == entry_id:
                return index + 1
        return None


__all__ = ["SheetsRosterRepo"]
