import json
import sys

import pytest

from video_understanding import speech
from video_understanding.transcript import Segment

from conftest import FakeWhisper

MODEL = "mlx-community/whisper-large-v3-turbo"


def test_load_audio_is_16k_mono_float32(video_with_audio):
    audio = speech.load_audio(video_with_audio)
    assert audio.dtype.name == "float32"
    assert abs(audio.size - 3 * speech.SAMPLE_RATE) < speech.SAMPLE_RATE * 0.1
    assert 0.1 < float(abs(audio).max()) <= 1.0


def test_load_audio_without_audio_track(sample_video):
    with pytest.raises(speech.SpeechUnavailable, match="音声がありません"):
        speech.load_audio(sample_video)


def test_transcribe_passes_options_and_caches(video_with_audio, tmp_path):
    fake = FakeWhisper()
    segs = speech.transcribe(video_with_audio, tmp_path, MODEL, "用語", "ja-JP", fake)
    assert segs == [Segment(0.0, 1.2, "左足に乗ってから回す")]
    call = fake.calls[0]
    assert call["path_or_hf_repo"] == MODEL
    assert call["language"] == "ja" and call["initial_prompt"] == "用語"
    assert call["condition_on_previous_text"] is False
    (cache_file,) = tmp_path.glob("whisper-ja-*.json")
    assert json.loads(cache_file.read_text())["model"] == MODEL
    # 2 回目はキャッシュ。モデルかヒントが変われば取り直す
    assert speech.transcribe(video_with_audio, tmp_path, MODEL, "用語", "ja", fake) == segs
    assert len(fake.calls) == 1
    speech.transcribe(video_with_audio, tmp_path, MODEL, "別の用語", "ja", fake)
    assert len(fake.calls) == 2


def test_empty_prompt_is_none_and_blank_segments_dropped(video_with_audio, tmp_path):
    fake = FakeWhisper(segments=[{"start": 0, "end": 1, "text": "  "}])
    assert speech.transcribe(video_with_audio, tmp_path, MODEL, "", "ja", fake) == []
    assert fake.calls[0]["initial_prompt"] is None


def test_silence_is_not_transcribed(video_silent_audio, tmp_path):
    fake = FakeWhisper()
    with pytest.raises(speech.SpeechUnavailable, match="無音"):
        speech.transcribe(video_silent_audio, tmp_path, MODEL, "", "ja", fake)
    assert fake.calls == []


def test_missing_extra_is_explained(monkeypatch):
    monkeypatch.undo()  # autouse の差し替えを外して、本物の _default_transcribe を見る
    monkeypatch.setitem(sys.modules, "mlx_whisper", None)  # import すると ImportError になる
    with pytest.raises(speech.SpeechUnavailable, match="--extra whisper"):
        speech._default_transcribe()


def test_whisper_lang():
    assert speech.whisper_lang("ja") == "ja"
    assert speech.whisper_lang("en-US") == "en"
