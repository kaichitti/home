from fractions import Fraction

import pytest

from detcut.common import DetCutError
from detcut.timeline.model import Clip, Timeline, make_params
from detcut.writers.alias import build_object
from detcut.writers.aup2 import Aup2Writer, escape_text, write_aup2
from detcut.writers.effects import AUP2_BUILTIN, diff_against_builtin, load_samples
from detcut.writers.exo import decode_exo_text, exo_text_hex, write_exo
from detcut.writers.ini import parse_ini
from detcut.writers.paths import output_path

FPS = Fraction(30000, 1001)
STYLE = {"font": "メイリオ", "size": 64, "color": "ffffff", "outline_color": "000000", "decoration": "outline",
         "align": "center_bottom", "x": 0, "y": 400, "bold": True, "italic": False, "spacing_x": 0, "spacing_y": 0,
         "extra_aup2": {}, "extra_exo": {}}


def sample_timeline() -> Timeline:
    tl = Timeline(fps=FPS, width=1920, height=1080, audio_rate=48000)
    tl.styles = {"telop": STYLE}
    seek = Fraction(15 * 1001, 30000)
    tl.clips = [
        Clip("v0001", "video", 1, 0, 59, file="/media/a.mp4", group=1,
             params=make_params(seek=seek, src_frame=15, source_fps=FPS, has_audio=True, scale=110, x=0, y=-20)),
        Clip("a0001", "audio", 2, 0, 59, file="/media/a.mp4", group=1,
             params=make_params(seek=seek, linked=True, volume=100)),
        Clip("t0001", "text", 4, 0, 40, params=make_params(text="一行目\n二行目\\x", style_id="telop", use_template=True)),
        Clip("s0001", "se", 6, 10, 27, file="/se/wow.wav", params=make_params(seek=Fraction(0), volume=80)),
        Clip("b0001", "bgm", 9, 0, 9, file="/bgm/x.wav",
             params=make_params(seek=Fraction(0), volume=Fraction(25), volume_end=Fraction(12))),
    ]
    return tl


def sections(text):
    return {s.name: s for s in parse_ini(text)}


def test_aup2_structure_and_encoding():
    data, warnings, ver = write_aup2(sample_timeline())
    assert not data.startswith(b"\xef\xbb\xbf")          # BOMなし
    text = data.decode("utf-8")
    assert "\r\n" in text and "\n" not in text.replace("\r\n", "")  # CRLFのみ
    s = sections(text)
    assert s["scene.0"].get("video.rate") == "30000" and s["scene.0"].get("video.scale") == "1001"
    assert s["project"].get("file") == ""
    # embedded モードでは連携音声は書かない（動画の「音声付き」で再生）
    names = [x for x in s if x.isdigit()]
    assert len(names) == 4
    v = s["0"]
    assert v.get("layer") == "0" and v.get("frame") == "0,59"
    assert s["0.0"].get("effect.name") == "動画ファイル"
    assert s["0.0"].get("音声付き") == "1"
    # 再生位置 = 開始秒（ミリ秒で切り上げ）, 終了秒, 再生範囲
    assert s["0.0"].get("再生位置") == "0.501,2.503,再生範囲,0"
    assert s["0.1"].get("effect.name") == "映像再生" and s["0.1"].get("拡大率") == "110.000"
    assert s["0.1"].get("Y") == "-20.00"
    assert ver == 2005200


def test_aup2_text_escape_and_style():
    assert escape_text("a\\b\nc") == "a\\\\b\\nc"
    text = write_aup2(sample_timeline())[0].decode("utf-8")
    s = sections(text)
    t = next(x for x in s.values() if x.get("effect.name") == "テキスト")
    assert t.get("テキスト") == "一行目\\n二行目\\\\x"
    assert t.get("文字装飾") == "縁取り文字"
    assert t.get("文字揃え") == "中央揃え[下]"
    assert t.get("B") == "1"


def test_aup2_separate_audio_mode_and_fade():
    text = write_aup2(sample_timeline(), audio_mode="separate")[0].decode("utf-8")
    s = sections(text)
    assert s["0.0"].get("音声付き") == "0"
    audio = [x for x in s.values() if x.get("effect.name") == "音声ファイル"]
    assert len(audio) == 3  # 本編音声・SE・BGM
    vols = [x.get("音量") for x in s.values() if x.get("effect.name") == "音声再生"]
    assert "25.00,12.00,直線移動,0" in vols


def test_aup2_template_preserved(tmp_path):
    tpl = ("[project]\r\nversion=2011500\r\nfile=C:\\old.aup2\r\ndisplay.scene=0\r\n"
           "[scene.0]\r\nscene=0\r\nname=Root\r\nvideo.width=1280\r\nvideo.height=720\r\nvideo.rate=60\r\n"
           "video.scale=1\r\naudio.rate=44100\r\nnew.key=keep\r\n"
           "[0]\r\nlayer=10\r\nframe=0,10\r\n[0.0]\r\neffect.name=図形\r\n"
           "[plugin.0]\r\nplugin.name=x\r\n")
    data, warnings, ver = write_aup2(sample_timeline(), template_text=tpl)
    text = data.decode("utf-8")
    names = [s.name for s in parse_ini(text)]
    assert names[:3] == ["project", "scene.0", "0"]
    assert names[-1] == "plugin.0"                 # プラグイン領域は末尾に残る
    s = sections(text)
    assert s["scene.0"].get("new.key") == "keep"    # 未知のキーも保持
    assert s["scene.0"].get("video.width") == "1920"
    assert s["1"].get("frame") == "0,59"            # 既存オブジェクトの後ろから採番
    assert ver == 2011500
    assert any("version" in w for w in warnings) and any("既存オブジェクト" in w for w in warnings)


def test_aup2_samples_override_key_layout(tmp_path):
    sample = tmp_path / "s.aup2"
    sample.write_text("[project]\nversion=2011500\n[scene.0]\nscene=0\n[0]\nlayer=0\nframe=0,9\n"
                      "[0.0]\neffect.name=動画ファイル\nファイル=x\n再生位置=0,1,再生範囲,0\n新しいキー=7\n"
                      "[0.1]\neffect.name=映像再生\nX=0.00\n", encoding="utf-8")
    samples = load_samples(str(sample))
    assert list(samples) == ["動画ファイル", "映像再生"]
    w = Aup2Writer(sample_timeline(), samples=samples)
    text = w.build()
    s = sections(text)
    keys = s["0.0"].keys()
    assert keys[:4] == ["effect.name", "ファイル", "再生位置", "新しいキー"]  # サンプルの順序を優先
    assert s["0.0"].get("新しいキー") == "7"
    assert any("音声付き" in x for x in w.warnings)  # サンプルにないキーは警告
    diff = diff_against_builtin(samples, AUP2_BUILTIN)
    assert any("新しいキー" in line for line in diff)


def test_aup2_style_template_object(tmp_path):
    obj = ("[Object]\r\n[Object.0]\r\neffect.name=テキスト\r\nサイズ=99.00\r\nテキスト=sample\r\n"
           "[Object.1]\r\neffect.name=グロー\r\n強さ=40\r\n[Object.2]\r\neffect.name=標準描画\r\nX=12.00\r\n")
    text = write_aup2(sample_timeline(), style_template_text=obj)[0].decode("utf-8")
    s = sections(text)
    t_idx = next(n for n, x in s.items() if x.get("effect.name") == "テキスト").split(".")[0]
    assert s[f"{t_idx}.0"].get("サイズ") == "99.00"
    assert s[f"{t_idx}.0"].get("テキスト") == "一行目\\n二行目\\\\x"
    assert s[f"{t_idx}.1"].get("effect.name") == "グロー"
    assert s[f"{t_idx}.2"].get("X") == "12.00"


def test_exo_structure():
    data, warnings = write_exo(sample_timeline())
    text = data.decode("cp932")
    s = sections(text)
    h = s["exedit"]
    assert (h.get("rate"), h.get("scale"), h.get("length")) == ("30000", "1001", "60")
    # (layer, start) 順: 動画→連携音声→テキスト→SE→BGM
    assert s["0.0"].get("_name") == "動画ファイル" and s["0.0"].get("再生位置") == "16"  # 1始まり
    assert s["0"].get("start") == "1" and s["0"].get("end") == "60" and s["0"].get("layer") == "1"
    assert s["1.0"].get("_name") == "音声ファイル" and s["1.0"].get("動画ファイルと連携") == "1"
    assert s["0"].get("group") == s["1"].get("group")          # 映像と音声は同じグループ
    assert s["1"].get("audio") == "1"
    assert s["2.0"].get("_name") == "テキスト" and s["2.0"].get("type") == "3" and s["2.0"].get("align") == "7"
    assert decode_exo_text(s["2.0"].get("text")) == "一行目\n二行目\\x"
    assert len(s["2.0"].get("text")) == 4096
    assert s["3"].get("group") != s["2"].get("group")
    assert s["4.1"].get("音量") == "25.0,12.0,1"


def test_exo_text_hex_handles_non_sjis():
    h = exo_text_hex("😀絵文字\nOK")
    assert decode_exo_text(h) == "😀絵文字\nOK"


def test_exo_rejects_non_sjis_path():
    tl = sample_timeline()
    tl.clips = [c for c in tl.clips if c.kind == "se"]
    tl.clips[0] = Clip("s0001", "se", 6, 0, 10, file="/se/😀.wav", params=make_params(volume=80))
    with pytest.raises(DetCutError, match="Shift-JIS"):
        write_exo(tl)


def test_exo_style_template():
    tpl_hex = exo_text_hex("x")
    tpl = ("[exedit]\r\nwidth=1920\r\n[0]\r\nstart=1\r\nend=30\r\nlayer=3\r\ngroup=1\r\noverlay=1\r\ncamera=0\r\n"
           f"[0.0]\r\n_name=テキスト\r\nサイズ=77\r\nfont=游ゴシック\r\ntext={tpl_hex}\r\n"
           "[0.1]\r\n_name=縁取り\r\nサイズ=3\r\n[0.2]\r\n_name=標準描画\r\nX=1.0\r\n")
    text = write_exo(sample_timeline(), style_template_text=tpl)[0].decode("cp932")
    s = sections(text)
    assert s["2.0"].get("サイズ") == "77" and s["2.1"].get("_name") == "縁取り"
    assert decode_exo_text(s["2.0"].get("text")) == "一行目\n二行目\\x"


def test_alias_object():
    tl = sample_timeline()
    w = Aup2Writer(tl)
    text = build_object(w, tl.clips[3])
    s = sections(text)
    assert s["Object"].get("frame") == "0,17"
    assert s["Object.0"].get("effect.name") == "音声ファイル"
    assert s["Object.1"].get("音量") == "80.00"


def test_output_path_map():
    p = output_path("/mnt/c/Users/me/a.mp4", [["/mnt/c/", "C:\\"]], "auto")
    assert p == "C:\\Users\\me\\a.mp4"
    assert output_path("/x/y.mp4", [], False) == "/x/y.mp4"
