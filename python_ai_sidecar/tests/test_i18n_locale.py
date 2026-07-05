"""i18n P4 — locale_directive: zh-TW/未知 locale 必須回空字串（prompt
byte-identical 保證），其餘語系注入 Response language 段。"""
from python_ai_sidecar.i18n_locale import current_locale, locale_directive


def test_default_and_zh_tw_inject_nothing():
    assert locale_directive("") == ""
    assert locale_directive("zh-TW") == ""
    assert locale_directive(None if False else "unknown-xx") == ""


def test_en_and_zh_cn_inject_language_line():
    en = locale_directive("en")
    assert "# Response language" in en and "English" in en
    cn = locale_directive("zh-CN")
    assert "Simplified Chinese" in cn
    # 專有名詞保留原文的指示必須在
    assert "OOC" in en and "tool_id" in en


def test_ja_adds_polite_style():
    ja = locale_directive("ja")
    assert "です・ます" in ja


def test_contextvar_fallback():
    token = current_locale.set("ja")
    try:
        assert "です・ます" in locale_directive()
    finally:
        current_locale.reset(token)
    assert locale_directive() == ""
